"""本地插件加载测试"""

import textwrap

import pytest

from lighthermes.plugins import PluginLoader
from lighthermes.tools import ToolDispatcher


def write_plugin(root, relative_path, content):
    path = root / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(textwrap.dedent(content), encoding="utf-8")
    return path


@pytest.mark.unit
class TestToolPluginLoader:
    def test_disabled_tool_plugin_is_not_imported(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/bad.py", "raise RuntimeError('imported')")
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_tool_plugins(dispatcher, {"dirs": ["plugins/tools"], "enabled": []}, strict=False)

        assert dispatcher.get_tool_schemas() == []

    def test_enabled_tool_plugin_registers_decorated_tool(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/hello.py", """
            from lighthermes import tool

            @tool("hello", "Say hello", [{"name": "name", "type": "string", "description": "Name", "required": True}])
            def hello(name):
                return f"Hello {name}"
        """)
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_tool_plugins(dispatcher, {"dirs": ["plugins/tools"], "enabled": ["hello"]}, strict=False)

        assert dispatcher.call_tool("hello", {"name": "Hermes"}) == "Hello Hermes"

    def test_register_function_takes_precedence_over_decorated_tools(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/mixed.py", """
            from lighthermes import tool

            @tool("decorated", "Decorated", [])
            def decorated():
                return "decorated"

            @tool("manual", "Manual", [])
            def manual():
                return "manual"

            def register(dispatcher):
                dispatcher.register_tool(manual)
        """)
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_tool_plugins(dispatcher, {"dirs": ["plugins/tools"], "enabled": ["mixed"]}, strict=False)

        names = [schema["function"]["name"] for schema in dispatcher.get_tool_schemas()]
        assert names == ["manual"]

    def test_unsafe_plugin_directory_is_rejected(self, tmp_path):
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        with pytest.raises(ValueError, match="Plugin directory must stay inside project root"):
            loader.load_tool_plugins(dispatcher, {"dirs": ["../outside"], "enabled": ["x"]}, strict=True)

    def test_load_error_is_skipped_by_default(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/bad.py", "raise RuntimeError('boom')")
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_tool_plugins(dispatcher, {"dirs": ["plugins/tools"], "enabled": ["bad"]}, strict=False)

        assert dispatcher.get_tool_schemas() == []

    def test_load_error_raises_in_strict_mode(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/bad.py", "raise RuntimeError('boom')")
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        with pytest.raises(RuntimeError, match="boom"):
            loader.load_tool_plugins(dispatcher, {"dirs": ["plugins/tools"], "enabled": ["bad"]}, strict=True)
