"""内置工具测试"""

import json

import pytest

from lighthermes.builtin_tools import create_memory_tools
from lighthermes.memory import MemoryManager
from lighthermes.tools import ToolDispatcher


@pytest.mark.unit
class TestBuiltinMemoryTools:
    def test_search_memory_tool_returns_json_results(self, temp_memory_dir):
        memory = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        memory.save_semantic("pref", "用户偏好中文回复", {"type": "user_preference"})
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_memory_tools(memory))

        result = json.loads(dispatcher.call_tool("search_memory", {
            "query": "中文",
            "layer": "semantic",
            "limit": 20,
        }))

        assert result["query"] == "中文"
        assert result["layer"] == "semantic"
        assert len(result["results"]) == 1
        assert result["results"][0]["name"] == "pref"
        assert "metadata" in result["results"][0]

    def test_search_memory_tool_clamps_limit(self, temp_memory_dir):
        memory = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        captured = {}

        def fake_search_memory(query, layer="all", limit=5, include_metadata=False):
            captured["limit"] = limit
            return []

        memory.search_memory = fake_search_memory
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_memory_tools(memory))

        dispatcher.call_tool("search_memory", {"query": "x", "limit": 99})

        assert captured["limit"] == 10
