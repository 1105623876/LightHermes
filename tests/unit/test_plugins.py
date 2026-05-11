"""本地插件加载测试"""

import textwrap

import pytest

from lighthermes.channels import ChannelRegistry
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

    @pytest.mark.parametrize("plugin_name", ["../bad", "..\\bad", ".hidden", "bad/name"])
    def test_unsafe_enabled_plugin_name_is_rejected_in_strict_mode(self, tmp_path, plugin_name):
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        with pytest.raises(ValueError, match="Plugin name must be a safe file stem"):
            loader.load_tool_plugins(dispatcher, {"dirs": ["plugins/tools"], "enabled": [plugin_name]}, strict=True)

    def test_unsafe_enabled_plugin_name_is_skipped_in_non_strict_mode(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/hello.py", """
            from lighthermes import tool

            @tool("hello", "Say hello", [{"name": "name", "type": "string", "description": "Name", "required": True}])
            def hello(name):
                return f"Hello {name}"
        """)
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loaded = loader.load_tool_plugins(
            dispatcher,
            {"dirs": ["plugins/tools"], "enabled": ["../bad", "hello"]},
            strict=False,
        )

        assert loaded == ["hello"]
        assert dispatcher.call_tool("hello", {"name": "Hermes"}) == "Hello Hermes"

    def test_missing_enabled_plugin_is_skipped(self, tmp_path):
        write_plugin(tmp_path, "plugins/tools/hello.py", """
            from lighthermes import tool

            @tool("hello", "Say hello", [{"name": "name", "type": "string", "description": "Name", "required": True}])
            def hello(name):
                return f"Hello {name}"
        """)
        dispatcher = ToolDispatcher()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loaded = loader.load_tool_plugins(
            dispatcher,
            {"dirs": ["plugins/tools"], "enabled": ["missing", "hello"]},
            strict=False,
        )

        assert loaded == ["hello"]
        assert dispatcher.call_tool("hello", {"name": "Hermes"}) == "Hello Hermes"

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


@pytest.mark.unit
class TestChannelPluginLoader:
    def test_enabled_channel_plugin_registers_channel_object(self, tmp_path):
        write_plugin(tmp_path, "plugins/channels/local_debug.py", """
            from lighthermes.channels import DirectChannel

            channel = DirectChannel(name="local_debug")
        """)
        registry = ChannelRegistry()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_channel_plugins(registry, {"dirs": ["plugins/channels"], "enabled": ["local_debug"]}, strict=False)

        assert registry.get("local_debug") is not None
        assert registry.list_channels() == ["local_debug"]

    def test_register_channels_function_takes_precedence(self, tmp_path):
        write_plugin(tmp_path, "plugins/channels/mixed.py", """
            from lighthermes.channels import DirectChannel

            channel = DirectChannel(name="object_channel")

            def register_channels(registry):
                registry.register(DirectChannel(name="manual_channel"))
        """)
        registry = ChannelRegistry()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_channel_plugins(registry, {"dirs": ["plugins/channels"], "enabled": ["mixed"]}, strict=False)

        assert registry.list_channels() == ["manual_channel"]

    def test_disabled_channel_plugin_is_not_imported(self, tmp_path):
        write_plugin(tmp_path, "plugins/channels/bad.py", "raise RuntimeError('imported')")
        registry = ChannelRegistry()
        loader = PluginLoader(project_root=tmp_path, logger=None)

        loader.load_channel_plugins(registry, {"dirs": ["plugins/channels"], "enabled": []}, strict=False)

        assert registry.list_channels() == []
