"""
LightHermes 核心引擎

实现对话循环、工具调度、技能加载
"""

import os
import yaml
import uuid
from pathlib import Path
from typing import List, Dict, Any, Callable, Optional, Generator, Union
from openai import OpenAI

from lightherrmes.memory import MemoryManager
from lightherrmes.evolution import EvolutionEngine


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
    ):
        self.name = name or f"LightHermes-{uuid.uuid4().hex[:8]}"
        self.role = role or "你是一个有用的AI助手"
        self.model = model
        self.debug = debug

        if api_key is None:
            api_key = os.environ.get("OPENAI_API_KEY")
        if api_key is None:
            raise ValueError("API key is required")

        self.client = OpenAI(
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1"
        )

        self.memory_enabled = memory_enabled
        if memory_enabled:
            self.memory = MemoryManager(memory_dir=memory_dir)
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
            self.evolution = EvolutionEngine(
                client=self.client,
                model=model,
                skill_validation=skill_validation
            )
        else:
            self.evolution = None

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
            response = self.client.chat.completions.create(**params)
            message = response.choices[0].message

            if message.tool_calls:
                params["messages"].append(message)

                for tool_call in message.tool_calls:
                    function_call = tool_call.function
                    function_args = eval(function_call.arguments)

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

                return reply

        return "达到最大迭代次数"

    def _run_stream(self, params: Dict[str, Any], max_iterations: int) -> Generator:
        """流式运行"""
        for _ in range(max_iterations):
            response = self.client.chat.completions.create(**params)

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
                            function_args = eval(tool_call["arguments"])
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
