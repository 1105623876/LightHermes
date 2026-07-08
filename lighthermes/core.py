"""
LightHermes 核心引擎

实现对话循环、工具调度、技能加载
"""

import json
import os
import yaml
import uuid
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Callable, Generator, Union

from lighthermes.memory import MemoryManager
from lighthermes.evolution import EvolutionEngine
from lighthermes.adapters import get_adapter
from lighthermes.compressor import ContextCompressor
from lighthermes.hooks import call_hook_safely
from lighthermes.skills import SkillLoader
from lighthermes.builtin_tools import create_file_tools, create_memory_tools
from lighthermes.tools import ToolDispatcher, tool

__all__ = ["LightHermes", "SkillLoader", "ToolDispatcher", "tool"]


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
        config_path: str = "config.yaml",
        config: Dict[str, Any] = None,
    ):
        # 读取配置文件
        if config is None:
            config = {}
        if not config and config_path and os.path.exists(config_path):
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
            retention_config = memory_config.get("retention", {})
            self.memory = MemoryManager(
                memory_dir=memory_dir,
                semantic_max_entries=retention_config.get("semantic_max_entries", 1000),
                semantic_max_chars=retention_config.get("semantic_max_chars", 200000),
                semantic_similarity_threshold=retention_config.get("semantic_similarity_threshold", 0.85),
                distill_recent_limit=retention_config.get("distill_recent_limit", 20),
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
        builtin_config = config.get("tools", {}).get("builtin", {})
        builtin_enabled = builtin_config.get("enabled", True)
        if builtin_enabled and memory_enabled and builtin_config.get("memory_search", True) and self.tool_dispatcher:
            self.tool_dispatcher.register_tools(create_memory_tools(self.memory))
        if builtin_enabled and self.tool_dispatcher:
            self.tool_dispatcher.register_tools(create_file_tools(builtin_config))
        if tools and self.tool_dispatcher:
            for tool in tools:
                self.tool_dispatcher.register_tool(tool)

        if evolution_enabled:
            self.evolution = EvolutionEngine(
                client=self.adapter,
                model=model,
                skill_validation=skill_validation,
                memory_manager=self.memory
            )
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

    @staticmethod
    def _resolve_config_value(value: Any) -> Any:
        """解析形如 ${ENV_VAR} 的配置值"""
        if isinstance(value, str) and value.startswith("${") and value.endswith("}"):
            return os.environ.get(value[2:-1])
        return value

    @classmethod
    def from_config(cls, config_path: str = "config.yaml", **overrides):
        """从配置文件创建 LightHermes 实例，参数覆盖配置文件"""
        config = {}
        if os.path.exists(config_path):
            with open(config_path, "r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}

        agent_config = config.get("agent", {})
        model_config = config.get("model", {})
        memory_config = config.get("memory", {})
        evolution_config = config.get("evolution", {})
        skills_config = config.get("skills", {})
        cli_config = config.get("cli", {})
        logging_config = config.get("logging", {})

        params = {
            "name": agent_config.get("name"),
            "role": agent_config.get("role"),
            "model": model_config.get("model_name", model_config.get("model", "gpt-4o-mini")),
            "provider": model_config.get("provider", "openai"),
            "api_key": cls._resolve_config_value(model_config.get("api_key")),
            "base_url": model_config.get("base_url"),
            "memory_enabled": memory_config.get("enabled", True),
            "memory_dir": memory_config.get("storage_dir", "memory"),
            "evolution_enabled": evolution_config.get("enabled", True),
            "auto_generate_skills": evolution_config.get("auto_generate_skills", True),
            "skill_validation": evolution_config.get("skill_validation", "sandbox"),
            "skill_dirs": skills_config.get("dirs", ["skills/core", "skills/user", "skills/generated"]),
            "disabled_skills": skills_config.get("disabled", []),
            "debug": cli_config.get("show_skill_usage", logging_config.get("debug", False)),
            "log_level": logging_config.get("level", "INFO"),
            "log_file": logging_config.get("file"),
            "fallback_models": model_config.get("fallback_models"),
            "config_path": config_path,
            "config": config,
        }
        params.update(overrides)
        return cls(**params)

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

    def _run_memory_hook(self, hook_name: str, *args, **kwargs):
        if not (self.memory_enabled and self.memory):
            return None
        return call_hook_safely(
            self.memory,
            hook_name,
            self.logger,
            "记忆生命周期钩子",
            *args,
            **kwargs
        )

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
        query_lower = query.lower().strip()
        memory_questions = [
            "记得什么", "还记得", "记得我", "记忆", "remember about", "what do you remember"
        ]
        if any(kw in query_lower for kw in memory_questions):
            return False

        memory_commands = [
            "记住", "记一下", "保存", "请记得", "帮我记", "remember that", "save that", "record that"
        ]
        return any(kw in query_lower for kw in memory_commands)

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

    def _build_failure_report_warning(self, query: str, task_type: str, limit: int = 2) -> str:
        """构建执行前失败风险提示"""
        if not hasattr(self.skill_loader, "recall_failure_reports"):
            return ""

        reports = self.skill_loader.recall_failure_reports(query, task_type, limit=limit)
        if not reports:
            return ""

        lines = ["## 执行前风险提示", "以下是相关失败经验，仅作为风险提示，不要阻断执行："]
        for report in reports:
            name = report.get("name", "failure_report")
            description = report.get("description", "")
            content = " ".join(report.get("content", "").split())[:200]
            warning = description or content
            lines.append(f"- {name}: {warning}")
        return "\n".join(lines)

    def _should_list_semantic_memories(self, query: str) -> bool:
        query_lower = query.lower()
        return "语义记忆" in query_lower or "semantic memory" in query_lower

    def _build_semantic_memory_list(self, limit: int = 20) -> str:
        if not (self.memory_enabled and self.memory and hasattr(self.memory, "search_memory")):
            return ""

        lines = []
        memories = self.memory.search_memory("", layer="semantic", limit=limit)
        for memory in memories:
            content = " ".join(memory.get("content", "").split())
            if content:
                lines.append(f"- {memory.get('name', 'unknown')}: {content[:300]}")

        if not lines:
            return ""
        return "## 语义记忆清单\n以下是当前语义记忆文件中的实际内容：\n" + "\n".join(lines)

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

        if self.memory_enabled:
            system_prompt += (
                "\n\n你具备 LightHermes 持久记忆能力。"
                "当用户询问你记得什么时，应基于智能体设定、用户偏好和相关记忆回答，"
                "不要声称每次对话都是完全独立且无法保留信息。"
            )

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

        task_type = self._classify_task(query)

        matched_skill = self.skill_loader.match_skill(query)
        if matched_skill:
            system_prompt += f"\n\n## 当前任务指导\n{matched_skill['content']}"
            if self.debug:
                print(f"[使用技能: {matched_skill['name']}]")

        failure_warning = self._build_failure_report_warning(query, task_type)
        if failure_warning:
            system_prompt += f"\n\n{failure_warning}"

        recalled_context = self._run_memory_hook(
            "on_turn_start",
            query,
            user_id=user_id,
            session_id=session_id
        )
        if recalled_context:
            system_prompt += f"\n\n## 相关记忆\n{recalled_context}"

        if self._should_list_semantic_memories(query):
            semantic_memory_list = self._build_semantic_memory_list()
            if semantic_memory_list:
                system_prompt += f"\n\n{semantic_memory_list}"

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
                pre_compress_note = self._run_memory_hook(
                    "on_pre_compress",
                    messages,
                    user_id=user_id,
                    session_id=session_id
                )
                if pre_compress_note:
                    messages.append({"role": "system", "content": pre_compress_note})
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

                self._run_memory_hook(
                    "on_turn_end",
                    params["messages"][-1]["content"],
                    reply,
                    user_id=user_id,
                    session_id=session_id
                )

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

            response_finished = False
            continue_next_iteration = False

            for chunk in response:
                response_finished = True
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

                    continue_next_iteration = True
                    break

            if response_finished:
                if continue_next_iteration:
                    continue
                return

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
