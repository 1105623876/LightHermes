"""内置工具测试"""

import json

import pytest

from pathlib import Path

from lighthermes.builtin_tools import create_file_tools, create_memory_tools
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


@pytest.mark.unit
class TestBuiltinFileTools:
    def test_no_file_tools_registered_by_default(self, temp_memory_dir):
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({"roots": [temp_memory_dir]}))

        names = [schema["function"]["name"] for schema in dispatcher.get_tool_schemas()]
        assert "read_file" not in names
        assert "search_files" not in names

    def test_read_file_returns_numbered_lines_when_enabled(self, temp_memory_dir):
        root = Path(temp_memory_dir)
        (root / "note.txt").write_text("第一行\n第二行\n第三行", encoding="utf-8")
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({
            "file_read": True,
            "roots": [temp_memory_dir],
            "max_read_chars": 20000,
        }))

        result = dispatcher.call_tool("read_file", {
            "path": "note.txt",
            "start_line": 2,
            "max_lines": 1,
        })

        assert "2\t第二行" in result
        assert "第一行" not in result

    def test_read_file_rejects_root_escape_and_sensitive_files(self, temp_memory_dir):
        root = Path(temp_memory_dir)
        outside = root.parent / "outside-secret.txt"
        outside.write_text("secret", encoding="utf-8")
        (root / ".env").write_text("TOKEN=secret", encoding="utf-8")
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({"file_read": True, "roots": [temp_memory_dir]}))

        assert "拒绝" in dispatcher.call_tool("read_file", {"path": str(outside)})
        assert "拒绝" in dispatcher.call_tool("read_file", {"path": ".env"})

    def test_search_files_returns_content_matches_when_enabled(self, temp_memory_dir):
        root = Path(temp_memory_dir)
        (root / "a.txt").write_text("alpha\nneedle here", encoding="utf-8")
        (root / "b.md").write_text("needle too", encoding="utf-8")
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({
            "file_search": True,
            "roots": [temp_memory_dir],
            "max_search_results": 10,
        }))

        result = json.loads(dispatcher.call_tool("search_files", {
            "query": "needle",
            "directory": ".",
            "glob": "*.txt",
            "search_content": True,
            "limit": 5,
        }))

        assert len(result["results"]) == 1
        assert result["results"][0]["path"] == "a.txt"
        assert result["results"][0]["line"] == 2
        assert "needle here" in result["results"][0]["snippet"]

    def test_search_files_excludes_memory_directory(self, temp_memory_dir):
        root = Path(temp_memory_dir)
        (root / "memory").mkdir()
        (root / "memory" / "secret.txt").write_text("needle", encoding="utf-8")
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({"file_search": True, "roots": [temp_memory_dir]}))

        result = json.loads(dispatcher.call_tool("search_files", {
            "query": "needle",
            "search_content": True,
        }))

        assert result["results"] == []

    def test_write_file_is_not_registered_when_only_read_search_enabled(self, temp_memory_dir):
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({
            "file_read": True,
            "file_search": True,
            "roots": [temp_memory_dir],
        }))

        names = [schema["function"]["name"] for schema in dispatcher.get_tool_schemas()]
        assert "write_file" not in names

    def test_write_file_create_overwrite_and_append_modes(self, temp_memory_dir):
        root = Path(temp_memory_dir)
        existing = root / "existing.txt"
        existing.write_text("old", encoding="utf-8")
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({
            "file_write": True,
            "roots": [temp_memory_dir],
            "max_write_chars": 100,
        }))

        created = json.loads(dispatcher.call_tool("write_file", {
            "path": "new.txt",
            "content": "hello",
            "mode": "create",
        }))
        overwritten = json.loads(dispatcher.call_tool("write_file", {
            "path": "existing.txt",
            "content": "new",
            "mode": "overwrite",
        }))
        appended = json.loads(dispatcher.call_tool("write_file", {
            "path": "existing.txt",
            "content": "!",
            "mode": "append",
        }))

        assert created["written_chars"] == 5
        assert (root / "new.txt").read_text(encoding="utf-8") == "hello"
        assert overwritten["mode"] == "overwrite"
        assert appended["mode"] == "append"
        assert existing.read_text(encoding="utf-8") == "new!"

    def test_write_file_rejects_unsafe_modes_paths_and_sizes(self, temp_memory_dir):
        root = Path(temp_memory_dir)
        (root / "exists.txt").write_text("old", encoding="utf-8")
        dispatcher = ToolDispatcher()
        dispatcher.register_tools(create_file_tools({
            "file_write": True,
            "roots": [temp_memory_dir],
            "max_write_chars": 3,
        }))

        assert "拒绝" in dispatcher.call_tool("write_file", {"path": "exists.txt", "content": "x", "mode": "create"})
        assert "拒绝" in dispatcher.call_tool("write_file", {"path": "missing.txt", "content": "x", "mode": "overwrite"})
        assert "拒绝" in dispatcher.call_tool("write_file", {"path": ".env", "content": "x", "mode": "create"})
        assert "拒绝" in dispatcher.call_tool("write_file", {"path": "big.txt", "content": "toolong", "mode": "create"})
        assert "拒绝" in dispatcher.call_tool("write_file", {"path": "nested/new.txt", "content": "x", "mode": "create"})
