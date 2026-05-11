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
