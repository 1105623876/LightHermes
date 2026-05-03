"""
LightHermes 核心引擎

实现对话循环、工具调度、技能加载
"""

import json
import os
import yaml
import uuid
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, Generator, Union

from lighthermes.memory import MemoryManager
from lighthermes.evolution import EvolutionEngine
from lighthermes.adapters import get_adapter
from lighthermes.compressor import ContextCompressor


def tool(name: str, description: str, params: List[Dict]):
    """
    工具装饰器 - 简化工具注册流程

    Args:
        name: 工具名称
        description: 工具描述
        params: 参数列表，每个参数包含 name, type, description, required

    Example:
        @tool(
            name="get_weather",
            description="获取指定城市的天气",
            params=[
                {"name": "city", "type": "string", "description": "城市名称", "required": True}
            ]
        )
        def get_weather(city: str) -> str:
            return f"{city} 的天气是晴天"
    """
    def decorator(func):
        func.tool_info = {
            "tool_name": name,
            "tool_description": description,
            "tool_params": params,
        }
        return func
    return decorator


class SkillLoader:
    """技能加载器 - 加载和匹配 Markdown 技能"""

    def __init__(self, skill_dirs: List[str]):
        self.skill_dirs = skill_dirs
        self.skills: Dict[str, Dict[str, Any]] = {}
        self.load_all()

    def load_all(self):
        """加载所有技能"""
        for skill_dir in self.skill_dirs:
            if not os.path.exists(skill_dir):
                continue

            for file_path in Path(skill_dir).glob("*.md"):
                skill = self._parse_skill(file_path)
                if skill:
                    self.skills[skill["name"]] = skill

    def _parse_skill(self, file_path: Path) -> Optional[Dict[str, Any]]:
        """解析技能文件"""
        try:
            content = file_path.read_text(encoding="utf-8")
            if not content.startswith("---"):
                return None

            parts = content.split("---", 2)
            if len(parts) < 3:
                return None

            metadata = {}
            for line in parts[1].strip().split("\n"):
                if ":" in line:
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip()

            return {
                "name": metadata.get("name", file_path.stem),
                "description": metadata.get("description", ""),
                "type": metadata.get("type", "skill"),
                "category": metadata.get("category", "user"),
                "trigger": metadata.get("trigger", "auto"),
                "content": parts[2].strip(),
                "metadata": metadata
            }
        except Exception as e:
            print(f"Failed to parse skill {file_path}: {e}")
            return None

    def match_skill(self, query: str) -> Optional[Dict[str, Any]]:
        """匹配技能 - 简单的关键词匹配"""
        if query.startswith("/"):
            skill_name = query[1:]
            return self.skills.get(skill_name)

        query_lower = query.lower()
        query_words = set(query_lower.split())

        best_match = None
        best_score = 0

        for skill in self.skills.values():
            if skill["trigger"] != "auto":
                continue

            desc_lower = skill["description"].lower()
            content_lower = skill["content"].lower()

            desc_words = set(desc_lower.split())
            content_words = set(content_lower.split())

            score = len(query_words & desc_words) * 2 + len(query_words & content_words)

            if score > best_score:
                best_score = score
                best_match = skill

        return best_match if best_score > 2 else None

    def get_all_skills(self) -> List[Dict[str, Any]]:
        """获取所有技能"""
        return list(self.skills.values())


class ToolDispatcher:
    """工具调度器 - 管理和调用工具"""

    def __init__(self):
        self.tools: Dict[str, Callable] = {}
        self.tool_schemas: List[Dict[str, Any]] = []

    def register_tool(self, func: Callable) -> bool:
        """注册工具"""
        if not hasattr(func, "tool_info"):
            return False

        tool_info = func.tool_info
        tool_name = tool_info["tool_name"]

        self.tools[tool_name] = func

        tool_params = {}
        tool_required = []
        for param in tool_info["tool_params"]:
            tool_params[param["name"]] = {
                "type": param["type"],
                "description": param["description"],
            }
            if param["required"]:
                tool_required.append(param["name"])

        tool_schema = {
            "type": "function",
            "function": {
                "name": tool_name,
                "description": tool_info["tool_description"],
                "parameters": {
                    "type": "object",
                    "properties": tool_params,
                    "required": tool_required,
                },
            }
        }

        self.tool_schemas.append(tool_schema)
        return True

    def call_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """调用工具"""
        if tool_name not in self.tools:
            return f"Tool `{tool_name}` not found."

        try:
            result = self.tools[tool_name](**args)
            return str(result)
        except Exception as e:
            return f"Tool call error: {str(e)}"

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """获取工具 schema"""
        return self.tool_schemas.copy()


class LightHermes:
    """LightHermes 主类"""

    def __init__(
        self,
        *,
        name: str = None,
        role: str = None,
        model: str = "gpt-4o-mini",
        provider: str = "openai",
        api_key: str = None,
        base_url: str = None,
        memory_enabled: bool = True,
        memory_dir: str = "memory",
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-small",
        evolution_enabled: bool = True,
        auto_generate_skills: bool = True,
        skill_validation: str = "sandbox",
        skill_dirs: List[str] = None,
        plugin_dirs: List[str] = None,
        disabled_skills: List[str] = None,
        tools: List[Callable] = None,
        debug: bool = False,
        log_level: str = "INFO",
        log_file: str = None,
        fallback_models: List[str] = None,
    ):
        # 读取配置文件
        config = {}
        config_path = "config.yaml"
        if os.path.exists(config_path):
            try:
                with open(config_path, 'r', encoding='utf-8') as f:
                    config = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"警告: 读取配置文件失败: {e}")

        # 应用配置（参数优先级高于配置文件）
        if not fallback_models and config.get("model", {}).get("fallback_models"):
            fallback_models = config["model"]["fallback_models"]

        if not log_level and config.get("logging", {}).get("level"):
            log_level = config["logging"]["level"]

        if not log_file and config.get("logging", {}).get("file"):
            log_file = config["logging"]["file"]

        self.name = name or f"LightHermes-{uuid.uuid4().hex[:8]}"
        self.role = role or "你是一个有用的AI助手"
        self.model = model
        self.provider = provider
        self.debug = debug

        from lighthermes.logger import setup_logger
        self.logger = setup_logger(
            name="lighthermes",
            level=log_level,
            log_file=log_file
        )

        self.fallback_models = fallback_models or []
        self.query_count = 0
        self.total_tokens_used = 0
        self.api_call_count = 0

        # 自动检测 API key
        if api_key is None:
            if provider == "openai":
                api_key = os.environ.get("OPENAI_API_KEY")
            elif provider == "anthropic":
                api_key = os.environ.get("ANTHROPIC_API_KEY")

        if api_key is None:
            raise ValueError(f"API key is required for provider: {provider}")

        # 使用 adapter 替代直接创建 client
        self.adapter = get_adapter(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=base_url
        )

        self.memory_enabled = memory_enabled
        if memory_enabled:
            memory_config = config.get("memory", {})
            hybrid_config = memory_config.get("hybrid_retrieval", {})
            self.memory = MemoryManager(
                memory_dir=memory_dir,
                use_hybrid_retrieval=hybrid_config.get("enabled", False),
                embedding_provider=hybrid_config.get("provider", embedding_provider),
                embedding_model=hybrid_config.get("model", embedding_model),
                api_key=hybrid_config.get("api_key")
            )
        else:
            self.memory = None

        self.evolution_enabled = evolution_enabled
        self.auto_generate_skills = auto_generate_skills

        skill_dirs = skill_dirs or ["skills/core", "skills/user", "skills/generated"]
        self.skill_loader = SkillLoader(skill_dirs)

        self.tool_dispatcher = ToolDispatcher()
        if tools:
            for tool in tools:
                self.tool_dispatcher.register_tool(tool)

        if evolution_enabled:
            # Evolution 系统需要 OpenAI client
            # 如果主 provider 不是 openai，为 evolution 创建单独的 client
            evolution_client = None
            if provider == "openai":
                evolution_client = self.adapter.client
            else:
                from openai import OpenAI
                evolution_api_key = os.environ.get("OPENAI_API_KEY")
                if not evolution_api_key:
                    self.logger.warning(
                        "Evolution 系统需要 OPENAI_API_KEY，已禁用"
                    )
                    self.evolution_enabled = False
                else:
                    evolution_client = OpenAI(api_key=evolution_api_key)

            if self.evolution_enabled and evolution_client:
                self.evolution = EvolutionEngine(
                    client=evolution_client,
                    model=model,
                    skill_validation=skill_validation
                )
            else:
                self.evolution = None
        else:
            self.evolution = None

        # 初始化上下文压缩器
        compression_config = config.get("context_compression", {})
        self.compression_enabled = compression_config.get("enabled", True)
        self.extract_compression_to_memory = compression_config.get("extract_to_memory", False)
        if self.compression_enabled:
            self.compressor = ContextCompressor(
                llm_adapter=self.adapter,
                config=compression_config
            )
            # 获取上下文窗口大小（根据模型）
            self.context_window = self._get_context_window(model)
        else:
            self.compressor = None
            self.context_window = 128000  # 默认值

    def _get_context_window(self, model: str) -> int:
        """获取模型的上下文窗口大小"""
        context_windows = {
            "gpt-4o": 128000,
            "gpt-4o-mini": 128000,
            "gpt-4-turbo": 128000,
            "gpt-3.5-turbo": 16385,
            "claude-opus-4": 200000,
            "claude-sonnet-4": 200000,
            "claude-haiku-4": 200000,
        }
        # 模糊匹配
        for key, value in context_windows.items():
            if key in model.lower():
                return value
        return 128000  # 默认值

    def _save_compression_summary_to_memory(
        self,
        messages: List[Dict[str, Any]],
        session_id: str,
        user_id: str
    ):
        """按配置将上下文压缩摘要保存到工作记忆"""
        if not (self.memory_enabled and self.memory and self.extract_compression_to_memory):
            return

        marker = "[CONTEXT COMPACTION — REFERENCE ONLY]"
        for message in messages:
            content = message.get("content", "") if isinstance(message, dict) else ""
            if marker in content:
                summary = content.replace(marker, "").strip()
                if summary:
                    self.memory.save_session(session_id, user_id, summary)
                return

    def _call_api_with_fallback(
        self,
        messages: List[Dict],
        **kwargs
    ) -> Any:
        """
        带降级机制的 API 调用
        """
        models = [self.model] + self.fallback_models
        last_error = None

        for i, model in enumerate(models):
            try:
                # 临时切换 adapter 的模型
                original_model = self.adapter.model
                self.adapter.model = model

                response = self.adapter.create(
                    messages=messages,
                    **kwargs
                )

                # 恢复原始模型
                self.adapter.model = original_model

                if i > 0:
                    self.logger.warning(f"降级到模型 {model}")
                return response
            except Exception as e:
                last_error = e
                if i == len(models) - 1:
                    self.logger.error(f"所有模型失败: {e}")
                    raise
                self.logger.warning(f"模型 {model} 失败，尝试降级: {e}")

        raise last_error

    def _should_extract_memory(self, query: str) -> bool:
        """检测用户是否要求记住某些信息"""
        query_lower = query.lower()
        memory_keywords = ["记住", "记得", "记一下", "保存", "remember", "save", "记录"]
        return any(kw in query_lower for kw in memory_keywords)

    def _extract_and_save_memory(self, query: str):
        """提取并保存用户要求记住的信息到 SOUL.md 或 USER.md"""
        try:
            extraction_prompt = f"""请从以下用户输入中提取关键信息。

用户输入："{query}"

请分析用户想要记住什么信息：
1. 如果是关于智能体的设定（名字、人格、角色等），返回：SOUL: <内容>
2. 如果是关于用户的偏好或信息，返回：USER: <内容>

示例：
- "记住我的名字是张三" → USER: 用户名字是张三
- "请记住我喜欢Python" → USER: 用户喜欢Python编程
- "记住你的名字是希儿" → SOUL: 智能体名字是希儿
- "记住你的名字是糖糖，是一个可爱的小萝莉" → SOUL: 智能体名字是糖糖，人格特征：可爱、乐于助人的小萝莉

请提取关键信息："""

            self.logger.info(f"检测到记忆提取请求: {query}")

            response = self.adapter.create(
                messages=[{"role": "user", "content": extraction_prompt}],
                stream=False,
                max_tokens=200
            )

            extracted = response.choices[0].message.content.strip()
            self.logger.info(f"LLM 提取结果: {extracted}")

            # 使用正则表达式提取 SOUL: 或 USER: 格式
            import re
            soul_match = re.search(r'SOUL:\s*(.+?)(?:\n|$)', extracted, re.IGNORECASE)
            user_match = re.search(r'USER:\s*(.+?)(?:\n|$)', extracted, re.IGNORECASE)

            if soul_match:
                content = soul_match.group(1).strip()
                self._update_soul_file(content)
                self.logger.info(f"已更新 SOUL.md: {content}")
            elif user_match:
                content = user_match.group(1).strip()
                self._update_user_file(content)
                self.logger.info(f"已更新 USER.md: {content}")
            else:
                self.logger.warning(f"无法从回复中提取 SOUL/USER 信息: {extracted}")
        except Exception as e:
            import traceback
            self.logger.error(f"提取记忆失败: {e}")
            self.logger.error(f"详细错误: {traceback.format_exc()}")

    def _update_soul_file(self, content: str):
        """更新 SOUL.md 文件"""
        soul_path = Path(self.memory.memory_dir) / "SOUL.md"

        # 读取现有内容
        if soul_path.exists():
            existing = soul_path.read_text(encoding="utf-8")
        else:
            existing = "# 智能体灵魂设定\n\n"

        # 添加新内容
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = f"\n## 更新 ({timestamp})\n{content}\n"

        soul_path.write_text(existing + new_entry, encoding="utf-8")

    def _update_user_file(self, content: str):
        """更新 USER.md 文件"""
        user_path = Path(self.memory.memory_dir) / "USER.md"

        # 读取现有内容
        if user_path.exists():
            existing = user_path.read_text(encoding="utf-8")
        else:
            existing = "# 用户偏好设定\n\n"

        # 添加新内容
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        new_entry = f"\n## 更新 ({timestamp})\n{content}\n"

        user_path.write_text(existing + new_entry, encoding="utf-8")

    def _classify_task(self, query: str) -> str:
        """
        简单的任务分类 - 基于关键词识别任务类型
        """
        query_lower = query.lower()

        # 代码相关
        code_keywords = ["代码", "函数", "class", "def", "实现", "编写", "写一个", "code", "function", "implement"]
        if any(kw in query_lower for kw in code_keywords):
            return "代码"

        # 调试相关
        debug_keywords = ["调试", "bug", "错误", "报错", "修复", "fix", "debug", "error"]
        if any(kw in query_lower for kw in debug_keywords):
            return "调试"

        # 解释相关
        explain_keywords = ["解释", "说明", "什么是", "如何", "为什么", "explain", "what", "how", "why"]
        if any(kw in query_lower for kw in explain_keywords):
            return "解释"

        # 配置相关
        config_keywords = ["配置", "设置", "安装", "部署", "config", "setup", "install", "deploy"]
        if any(kw in query_lower for kw in config_keywords):
            return "配置"

        return "通用"

    def run(
        self,
        query: str,
        *,
        stream: bool = False,
        user_id: str = "default_user",
        session_id: str = None,
        history: List[Dict] = None,
        max_iterations: int = 10,
    ) -> Union[str, Generator]:
        """运行 Agent"""
        session_id = session_id or uuid.uuid4().hex

        system_prompt = f"{self.role}\n\n你的名字是 {self.name}。"

        # 注入 SOUL.md 和 USER.md（固定记忆文件）
        if self.memory_enabled:
            soul_path = Path(self.memory.memory_dir) / "SOUL.md"
            user_path = Path(self.memory.memory_dir) / "USER.md"

            if soul_path.exists():
                soul_content = soul_path.read_text(encoding="utf-8")
                system_prompt += f"\n\n## 智能体设定\n{soul_content}"

            if user_path.exists():
                user_content = user_path.read_text(encoding="utf-8")
                system_prompt += f"\n\n## 用户偏好\n{user_content}"

        matched_skill = self.skill_loader.match_skill(query)
        if matched_skill:
            system_prompt += f"\n\n## 当前任务指导\n{matched_skill['content']}"
            if self.debug:
                print(f"[使用技能: {matched_skill['name']}]")

        if self.memory_enabled:
            recalled_context = self.memory.recall(query, user_id)
            if recalled_context:
                system_prompt += f"\n\n## 相关记忆\n{recalled_context}"

        messages = [{"role": "system", "content": system_prompt}]

        if history:
            messages.extend(history)

        if self.memory_enabled:
            messages.extend(self.memory.get_context())

        messages.append({"role": "user", "content": query})

        if self.memory_enabled:
            self.memory.add_message("user", query)

            # 检测"记住"指令并提取信息
            if self._should_extract_memory(query):
                self._extract_and_save_memory(query)

        # 检查是否需要压缩上下文
        if self.compression_enabled and self.compressor:
            if self.compressor.should_compress(messages, self.context_window):
                self.logger.info("触发上下文压缩")
                messages = self.compressor.compress(messages)
                self._save_compression_summary_to_memory(messages, session_id, user_id)

        tools = self.tool_dispatcher.get_tool_schemas()

        params = {
            "model": self.model,
            "messages": messages,
            "stream": stream
        }

        if tools:
            params["tools"] = tools
            params["tool_choice"] = "auto"

        if stream:
            return self._run_stream(params, max_iterations)
        else:
            return self._run_non_stream(params, max_iterations, user_id, session_id)

    def _run_non_stream(
        self,
        params: Dict[str, Any],
        max_iterations: int,
        user_id: str,
        session_id: str
    ) -> str:
        """非流式运行"""
        for _ in range(max_iterations):
            self.api_call_count += 1
            response = self._call_api_with_fallback(
                messages=params["messages"],
                stream=params.get("stream", False),
                tools=params.get("tools"),
                tool_choice=params.get("tool_choice")
            )
            message = response.choices[0].message

            # 统计 token 使用
            if hasattr(response, 'usage') and response.usage:
                usage = response.usage
                if isinstance(usage, dict):
                    self.total_tokens_used += usage.get('total_tokens', 0)
                else:
                    self.total_tokens_used += usage.total_tokens

            if message.tool_calls:
                params["messages"].append(message)

                for tool_call in message.tool_calls:
                    function_call = tool_call.function
                    try:
                        function_args = json.loads(function_call.arguments)
                    except json.JSONDecodeError:
                        self.logger.error(f"工具参数解析失败: {function_call.arguments}")
                        continue

                    tool_response = self.tool_dispatcher.call_tool(
                        function_call.name,
                        function_args
                    )

                    params["messages"].append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": tool_response
                    })
            else:
                reply = message.content

                if self.memory_enabled:
                    self.memory.add_message("assistant", reply)

                # 自适应记忆调整
                self.query_count += 1
                if self.memory_enabled and self.query_count % 100 == 0:
                    self.memory.adapt_weights()
                    self.logger.info(f"已完成 {self.query_count} 次查询，执行记忆自适应调整")

                # 自动记录轨迹并触发进化
                if self.evolution_enabled and self.evolution:
                    task_type = self._classify_task(params["messages"][-1]["content"])
                    tool_calls_list = []

                    # 收集本次对话的工具调用
                    for msg in params["messages"]:
                        if isinstance(msg, dict) and msg.get("role") == "assistant" and msg.get("tool_calls"):
                            for tc in msg["tool_calls"]:
                                tool_calls_list.append({
                                    "tool": tc["function"]["name"],
                                    "name": tc["function"]["name"],
                                    "arguments": tc["function"]["arguments"]
                                })

                    # 记录轨迹
                    self.evolution.record_session(
                        session_id=session_id,
                        messages=params["messages"],
                        tool_calls=tool_calls_list,
                        success=True,
                        task_type=task_type,
                        iterations=len(tool_calls_list)
                    )

                    # 每 50 次对话触发一次进化
                    if self.query_count % 50 == 0:
                        self.logger.info(f"触发自动进化（已完成 {self.query_count} 次对话）")
                        result = self.evolution.evolve()
                        if result.get("success_skills"):
                            self.skill_loader.load_all()
                            self.logger.info(f"热加载了 {len(result['success_skills'])} 个新技能")

                return reply

        return "达到最大迭代次数"

    def _run_stream(self, params: Dict[str, Any], max_iterations: int) -> Generator:
        """流式运行"""
        for _ in range(max_iterations):
            response = self._call_api_with_fallback(
                messages=params["messages"],
                stream=params.get("stream", True),
                tools=params.get("tools"),
                tool_choice=params.get("tool_choice")
            )

            output = ""
            tool_calls = []

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    content = chunk.choices[0].delta.content
                    output += content
                    yield content

                if chunk.choices and chunk.choices[0].delta.tool_calls:
                    tool_call_delta = chunk.choices[0].delta.tool_calls[0]
                    tool_call_index = tool_call_delta.index or 0

                    if len(tool_calls) <= tool_call_index:
                        tool_calls.append({"name": "", "arguments": "", "id": ""})

                    if tool_call_delta.id:
                        tool_calls[tool_call_index]["id"] = tool_call_delta.id
                    if tool_call_delta.function.name:
                        tool_calls[tool_call_index]["name"] = tool_call_delta.function.name
                    if tool_call_delta.function.arguments:
                        tool_calls[tool_call_index]["arguments"] += tool_call_delta.function.arguments

                finish_reason = chunk.choices[0].finish_reason if chunk.choices else None
                if finish_reason == "stop" and not any(tc["name"] for tc in tool_calls):
                    return

                elif finish_reason in ("tool_calls", "stop") and any(tc["name"] for tc in tool_calls):
                    for tool_call in tool_calls:
                        if tool_call["name"]:
                            try:
                                function_args = json.loads(tool_call["arguments"])
                            except json.JSONDecodeError:
                                self.logger.error(f"工具参数解析失败: {tool_call['arguments']}")
                                continue

                            tool_response = self.tool_dispatcher.call_tool(
                                tool_call["name"],
                                function_args
                            )

                            params["messages"].append({
                                "role": "assistant",
                                "content": "",
                                "tool_calls": [{
                                    "id": tool_call["id"],
                                    "type": "function",
                                    "function": {
                                        "name": tool_call["name"],
                                        "arguments": tool_call["arguments"]
                                    }
                                }]
                            })

                            params["messages"].append({
                                "role": "tool",
                                "tool_call_id": tool_call["id"],
                                "content": tool_response
                            })

                    response = self.client.chat.completions.create(**params)
                    break

    def load_config(self, config_path: str = "config.yaml"):
        """从配置文件加载配置"""
        if not os.path.exists(config_path):
            return

        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if "model" in config:
            self.model = config["model"].get("model_name", self.model)

        if "memory" in config and self.memory_enabled:
            memory_config = config["memory"]
            if "retention" in memory_config:
                retention = memory_config["retention"]
                self.memory.short_term.max_turns = retention.get("short_term_turns", 50)
