"""
OpenAIAdapter - OpenAI API 适配器
"""

from typing import List, Dict, Any, Generator, Optional
from openai import OpenAI
from .base import BaseAdapter


class OpenAIAdapter(BaseAdapter):
    """OpenAI API 适配器"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        super().__init__(model, api_key, base_url, **kwargs)
        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1"
        )

    def create(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        **kwargs
    ) -> Any:
        """
        调用 OpenAI API

        Args:
            messages: 消息列表 (OpenAI 格式)
            tools: 工具列表 (OpenAI 格式)
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            流式: Generator[str]
            非流式: OpenAI response 对象
        """
        params = {
            "model": self.model,
            "messages": messages,
            "stream": stream,
            **kwargs
        }

        if tools:
            params["tools"] = tools

        response = self.client.chat.completions.create(**params)

        if stream:
            return self._handle_stream(response)
        else:
            return response

    def _handle_stream(self, response) -> Generator[str, None, None]:
        """处理流式响应"""
        for chunk in response:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
