"""工具调度器测试"""

import pytest

from lighthermes.tools import ToolDispatcher, tool


@pytest.mark.unit
class TestToolDispatcher:
    def test_register_tool_overwrites_schema_with_same_name(self):
        dispatcher = ToolDispatcher()

        @tool("lookup", "旧工具", [{"name": "query", "type": "string", "description": "查询", "required": True}])
        def old_lookup(query):
            return f"old:{query}"

        @tool("lookup", "新工具", [{"name": "text", "type": "string", "description": "文本", "required": True}])
        def new_lookup(text):
            return f"new:{text}"

        assert dispatcher.register_tool(old_lookup) is True
        assert dispatcher.register_tool(new_lookup) is True

        schemas = dispatcher.get_tool_schemas()
        assert len([schema for schema in schemas if schema["function"]["name"] == "lookup"]) == 1
        assert schemas[0]["function"]["description"] == "新工具"
        assert dispatcher.call_tool("lookup", {"text": "x"}) == "new:x"

    def test_register_tools_registers_each_function(self):
        dispatcher = ToolDispatcher()

        @tool("one", "工具一", [])
        def one():
            return "1"

        @tool("two", "工具二", [])
        def two():
            return "2"

        assert dispatcher.register_tools([one, two]) == 2
        assert dispatcher.call_tool("one", {}) == "1"
        assert dispatcher.call_tool("two", {}) == "2"

    def test_array_param_gets_default_items_string(self):
        dispatcher = ToolDispatcher()

        @tool("tag", "打标签", [
            {"name": "labels", "type": "array", "description": "标签列表", "required": True},
        ])
        def tag(labels):
            return "ok"

        assert dispatcher.register_tool(tag) is True
        schema = dispatcher.get_tool_schemas()[0]
        prop = schema["function"]["parameters"]["properties"]["labels"]
        assert prop["type"] == "array"
        assert prop["items"] == {"type": "string"}  # 默认补 items，兼容 OpenAI strict

    def test_array_param_respects_explicit_items(self):
        dispatcher = ToolDispatcher()

        @tool("count", "计数", [
            {
                "name": "nums",
                "type": "array",
                "description": "数字列表",
                "required": False,
                "items": {"type": "integer"},
            },
        ])
        def count(nums):
            return "ok"

        assert dispatcher.register_tool(count) is True
        schema = dispatcher.get_tool_schemas()[0]
        prop = schema["function"]["parameters"]["properties"]["nums"]
        assert prop["items"] == {"type": "integer"}  # 显式 items 不被覆盖
