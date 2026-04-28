"""
AnthropicAdapter - Anthropic Messages API 适配器
"""

import json
from typing import List, Dict, Any, Generator, Optional
from .base import BaseAdapter


class AnthropicAdapter(BaseAdapter):
    """Anthropic Messages API 适配器"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(model, api_key, base_url, **kwargs)

        try:
            from anthropic import Anthropic
        except ImportError:
            raise ImportError(
                "需要安装 anthropic 库: pip install anthropic"
            )

        # 检测是否是 MiniMax 端点，需要 Bearer 认证
        is_minimax = (
            base_url and
            ("api.minimax.io/anthropic" in base_url.lower() or
             "api.minimaxi.com/anthropic" in base_url.lower())
        )

        if is_minimax:
            # MiniMax 需要 Bearer 认证，使用自定义 httpx client
            import httpx

            class BearerAuthClient(httpx.Client):
                def __init__(self, bearer_token, *args, **kwargs):
                    super().__init__(*args, **kwargs)
                    self.bearer_token = bearer_token

                def build_request(self, *args, **kwargs):
                    request = super().build_request(*args, **kwargs)
                    # 移除 X-Api-Key，使用 Bearer 认证
                    if 'X-Api-Key' in request.headers:
                        del request.headers['X-Api-Key']
                    request.headers['Authorization'] = f'Bearer {self.bearer_token}'
                    return request

            http_client = BearerAuthClient(bearer_token=api_key)
            self.client = Anthropic(
                api_key=api_key,
                base_url=base_url,
                http_client=http_client
            )
        else:
            # 标准 Anthropic API 使用 X-Api-Key
            self.client = Anthropic(
                api_key=api_key,
                base_url=base_url
            )

    def create(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        **kwargs
    ) -> Any:
        """
        调用 Anthropic API

        Args:
            messages: 消息列表 (OpenAI 格式)
            tools: 工具列表 (OpenAI 格式)
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            流式: Generator[str]
            非流式: Anthropic response 对象
        """
        # 转换消息格式
        system_prompt, anthropic_messages = self._convert_messages(messages)

        # 转换工具格式
        anthropic_tools = self._convert_tools(tools) if tools else None

        params = {
            "model": self.model,
            "messages": anthropic_messages,
            "max_tokens": kwargs.get("max_tokens", 4096),
            "stream": stream,
        }

        if system_prompt:
            params["system"] = system_prompt

        if anthropic_tools:
            params["tools"] = anthropic_tools

        # 移除 OpenAI 特有的参数
        for key in ["temperature", "top_p"]:
            if key in kwargs:
                params[key] = kwargs[key]

        response = self.client.messages.create(**params)

        if stream:
            return self._handle_stream(response)
        else:
            return self._convert_response(response)

    def _convert_messages(
        self, messages: List[Dict[str, Any]]
    ) -> tuple[Optional[str], List[Dict[str, Any]]]:
        """
        将 OpenAI 格式消息转换为 Anthropic 格式

        Returns:
            (system_prompt, anthropic_messages)
        """
        system_prompt = None
        anthropic_messages = []

        for msg in messages:
            role = msg["role"]
            content = msg["content"]

            if role == "system":
                # Anthropic 的 system 需要单独提取
                if system_prompt:
                    system_prompt += "\n\n" + content
                else:
                    system_prompt = content
            elif role in ["user", "assistant"]:
                # 处理 tool_calls (OpenAI) -> tool_use (Anthropic)
                if "tool_calls" in msg:
                    # assistant 消息带 tool_calls
                    content_blocks = []
                    if content:
                        content_blocks.append({"type": "text", "text": content})

                    for tool_call in msg["tool_calls"]:
                        content_blocks.append({
                            "type": "tool_use",
                            "id": tool_call["id"],
                            "name": tool_call["function"]["name"],
                            "input": json.loads(tool_call["function"]["arguments"])
                        })

                    anthropic_messages.append({
                        "role": "assistant",
                        "content": content_blocks
                    })
                elif "tool_call_id" in msg:
                    # tool 消息 -> tool_result
                    anthropic_messages.append({
                        "role": "user",
                        "content": [{
                            "type": "tool_result",
                            "tool_use_id": msg["tool_call_id"],
                            "content": content
                        }]
                    })
                else:
                    # 普通消息
                    anthropic_messages.append({
                        "role": role,
                        "content": content
                    })

        return system_prompt, anthropic_messages

    def _convert_tools(
        self, tools: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        将 OpenAI 格式工具转换为 Anthropic 格式
        """
        anthropic_tools = []

        for tool in tools:
            if tool["type"] == "function":
                func = tool["function"]
                anthropic_tools.append({
                    "name": func["name"],
                    "description": func.get("description", ""),
                    "input_schema": func.get("parameters", {})
                })

        return anthropic_tools

    def _convert_response(self, response) -> Any:
        """
        将 Anthropic 响应转换为类 OpenAI 格式
        """
        class Response:
            def __init__(self, anthropic_response):
                self.id = anthropic_response.id
                self.model = anthropic_response.model
                self.choices = [self._convert_choice(anthropic_response)]
                self.usage = {
                    "prompt_tokens": anthropic_response.usage.input_tokens,
                    "completion_tokens": anthropic_response.usage.output_tokens,
                    "total_tokens": (
                        anthropic_response.usage.input_tokens +
                        anthropic_response.usage.output_tokens
                    )
                }

            def _convert_choice(self, anthropic_response):
                class Choice:
                    def __init__(self, content_blocks):
                        self.message = self._convert_message(content_blocks)
                        self.finish_reason = "stop"

                    def _convert_message(self, content_blocks):
                        class Message:
                            def __init__(self, blocks):
                                self.role = "assistant"
                                self.content = ""
                                self.tool_calls = []

                                for block in blocks:
                                    if block.type == "text":
                                        self.content += block.text
                                    elif block.type == "tool_use":
                                        self.tool_calls.append({
                                            "id": block.id,
                                            "type": "function",
                                            "function": {
                                                "name": block.name,
                                                "arguments": json.dumps(block.input)
                                            }
                                        })

                        return Message(content_blocks)

                return Choice(anthropic_response.content)

        return Response(response)

    def _handle_stream(self, response) -> Generator[Any, None, None]:
        """处理流式响应，返回类 OpenAI 格式的 chunk"""
        for event in response:
            if event.type == "content_block_delta":
                if hasattr(event.delta, "text"):
                    # 构造类 OpenAI 格式的 chunk
                    class StreamChunk:
                        def __init__(self, text):
                            self.choices = [self._create_choice(text)]

                        def _create_choice(self, text):
                            class Choice:
                                def __init__(self, text):
                                    self.delta = self._create_delta(text)
                                    self.finish_reason = None

                                def _create_delta(self, text):
                                    class Delta:
                                        def __init__(self, text):
                                            self.content = text
                                            self.tool_calls = None
                                    return Delta(text)
                            return Choice(text)

                    yield StreamChunk(event.delta.text)
