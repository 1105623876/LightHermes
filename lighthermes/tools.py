"""
LightHermes 工具注册与调度边界
"""

from typing import Any, Callable, Dict, List


def tool(name: str, description: str, params: List[Dict]):
    """
    工具装饰器 - 简化工具注册流程
    """
    def decorator(func):
        func.tool_info = {
            "tool_name": name,
            "tool_description": description,
            "tool_params": params,
        }
        return func
    return decorator


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
