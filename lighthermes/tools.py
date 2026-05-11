"""
LightHermes 工具注册与调度边界
"""

from typing import Any, Callable, Dict, List, Optional


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
        self.tool_schemas = [
            schema for schema in self.tool_schemas
            if schema["function"]["name"] != tool_name
        ]

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

    def register_tools(self, funcs: List[Callable]) -> int:
        """批量注册工具"""
        return sum(1 for func in funcs if self.register_tool(func))

    def prepare_call(self, tool_name: str, args: Any) -> Optional[str]:
        """校验工具调用参数"""
        if tool_name not in self.tools:
            return f"Tool `{tool_name}` not found."

        if not isinstance(args, dict):
            return f"Tool `{tool_name}` arguments must be a JSON object."

        schema = next(
            (
                item for item in self.tool_schemas
                if item["function"]["name"] == tool_name
            ),
            None,
        )
        if not schema:
            return None

        parameters = schema["function"].get("parameters", {})
        required = parameters.get("required", [])
        properties = parameters.get("properties", {})

        for name in required:
            if name not in args:
                return f"Missing required argument `{name}` for tool `{tool_name}`."

        for name, value in args.items():
            if name not in properties:
                continue

            expected_type = properties[name].get("type")
            if expected_type == "string":
                if not isinstance(value, str):
                    return f"Argument `{name}` must be string."
            elif expected_type == "integer":
                if isinstance(value, bool) or not isinstance(value, int):
                    return f"Argument `{name}` must be integer."
            elif expected_type == "number":
                if isinstance(value, bool) or not isinstance(value, (int, float)):
                    return f"Argument `{name}` must be number."
            elif expected_type == "boolean":
                if not isinstance(value, bool):
                    return f"Argument `{name}` must be boolean."
            elif expected_type == "array":
                if not isinstance(value, list):
                    return f"Argument `{name}` must be array."
            elif expected_type == "object":
                if not isinstance(value, dict):
                    return f"Argument `{name}` must be object."

        return None

    def call_tool(self, tool_name: str, args: Dict[str, Any]) -> str:
        """调用工具"""
        error = self.prepare_call(tool_name, args)
        if error:
            return error

        try:
            result = self.tools[tool_name](**args)
            return str(result)
        except Exception as e:
            return f"Tool call error: {str(e)}"

    def get_tool_schemas(self) -> List[Dict[str, Any]]:
        """获取工具 schema"""
        return self.tool_schemas.copy()
