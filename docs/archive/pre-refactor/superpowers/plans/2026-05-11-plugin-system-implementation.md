# Lightweight Plugin System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build Phase 3.1 local tool and Channel plugin support with explicit enablement, safe defaults, runtime tool argument validation, and no new dependencies.

**Architecture:** Add a focused `lighthermes/plugins.py` loader that imports only explicitly enabled local plugin files and registers them into existing runtime registries. Extend `ToolDispatcher` with nanobot-inspired pre-call validation, extend `channels.py` with `BaseChannel` and `ChannelRegistry`, then integrate both registries into `LightHermes` initialization. Keep plugins local-directory only; do not add entry points, bus, gateway, network channels, or dependency installation.

**Tech Stack:** Python standard library (`importlib.util`, `inspect`, `pathlib`, `typing`), existing `pytest`, existing `pyyaml`, existing LightHermes modules.

---

## File Structure

- Modify: `lighthermes/tools.py`
  - Keep `@tool` and `ToolDispatcher` as the tool boundary.
  - Add `prepare_call()` and lightweight JSON-schema-based runtime validation.
  - Keep `call_tool()` returning strings instead of raising to the agent loop.
- Modify: `tests/unit/test_tools.py`
  - Add failing tests for non-object arguments, missing required parameters, simple type mismatch, unknown tools, and valid calls.
- Modify: `lighthermes/channels.py`
  - Add `BaseChannel` and `ChannelRegistry` while keeping existing `ChannelMessage` and `DirectChannel` compatible.
- Create: `tests/unit/test_channels.py`
  - Test channel registration, replacement, list, and get behavior.
- Create: `lighthermes/plugins.py`
  - Implement local plugin path validation, module import, tool plugin registration, channel plugin registration, and strict/default error handling.
- Create: `tests/unit/test_plugins.py`
  - Test disabled plugins do not import, enabled plugins load, unsafe paths are rejected, strict mode raises, default mode logs and skips, `register()` takes precedence over `@tool`, and channel plugins register.
- Modify: `lighthermes/core.py`
  - Instantiate `ChannelRegistry`.
  - Load tool and channel plugins from `config.yaml` after built-in and user-provided tool registration.
- Modify: `tests/unit/test_core_memory.py`
  - Add integration tests proving plugins are default-off and explicitly enabled plugins register.
- Modify: `config.yaml`
  - Replace legacy `plugins.dirs` with typed plugin config.
- Modify: `README.md`, `docs/ROADMAP.md`, `docs/PROJECT_STATUS.md`
  - Document the Phase 3.1 plugin plan and `self_state` future reservation.

---

### Task 1: Add ToolDispatcher Runtime Argument Validation

**Files:**
- Modify: `lighthermes/tools.py`
- Modify: `tests/unit/test_tools.py`

- [ ] **Step 1: Write failing tests for tool argument validation**

Append these tests to `tests/unit/test_tools.py` inside `TestToolDispatcher`:

```python
    def test_call_tool_rejects_non_object_args(self):
        dispatcher = ToolDispatcher()

        @tool("lookup", "查询工具", [{"name": "query", "type": "string", "description": "查询", "required": True}])
        def lookup(query):
            return query

        dispatcher.register_tool(lookup)

        result = dispatcher.call_tool("lookup", ["not", "object"])

        assert "Tool `lookup` arguments must be a JSON object" in result

    def test_call_tool_rejects_missing_required_arg(self):
        dispatcher = ToolDispatcher()

        @tool("lookup", "查询工具", [{"name": "query", "type": "string", "description": "查询", "required": True}])
        def lookup(query):
            return query

        dispatcher.register_tool(lookup)

        result = dispatcher.call_tool("lookup", {})

        assert "Missing required argument `query`" in result

    def test_call_tool_rejects_simple_type_mismatch(self):
        dispatcher = ToolDispatcher()

        @tool("repeat", "重复工具", [{"name": "count", "type": "integer", "description": "次数", "required": True}])
        def repeat(count):
            return "x" * count

        dispatcher.register_tool(repeat)

        result = dispatcher.call_tool("repeat", {"count": "3"})

        assert "Argument `count` must be integer" in result

    def test_prepare_call_accepts_valid_arguments(self):
        dispatcher = ToolDispatcher()

        @tool("repeat", "重复工具", [{"name": "count", "type": "integer", "description": "次数", "required": True}])
        def repeat(count):
            return "x" * count

        dispatcher.register_tool(repeat)

        assert dispatcher.call_tool("repeat", {"count": 3}) == "xxx"
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_tools.py -v
```

Expected: at least the new validation tests fail because `ToolDispatcher.call_tool()` currently passes args directly into the function.

- [ ] **Step 3: Implement minimal runtime validation**

Replace `ToolDispatcher` in `lighthermes/tools.py` with this implementation while keeping the module-level `tool()` decorator unchanged:

```python
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
        if tool_name not in self.tools:
            return f"Tool `{tool_name}` not found."

        if not isinstance(args, dict):
            return f"Tool `{tool_name}` arguments must be a JSON object."

        schema = next(
            schema for schema in self.tool_schemas
            if schema["function"]["name"] == tool_name
        )
        parameters = schema["function"]["parameters"]
        properties = parameters.get("properties", {})
        required = parameters.get("required", [])

        for name in required:
            if name not in args:
                return f"Missing required argument `{name}` for tool `{tool_name}`."

        for name, value in args.items():
            expected = properties.get(name, {}).get("type")
            error = self._validate_simple_type(name, value, expected)
            if error:
                return error

        return None

    def _validate_simple_type(self, name: str, value: Any, expected: Optional[str]) -> Optional[str]:
        if expected == "string" and not isinstance(value, str):
            return f"Argument `{name}` must be string."
        if expected == "integer" and not (isinstance(value, int) and not isinstance(value, bool)):
            return f"Argument `{name}` must be integer."
        if expected == "number" and not (isinstance(value, (int, float)) and not isinstance(value, bool)):
            return f"Argument `{name}` must be number."
        if expected == "boolean" and not isinstance(value, bool):
            return f"Argument `{name}` must be boolean."
        if expected == "array" and not isinstance(value, list):
            return f"Argument `{name}` must be array."
        if expected == "object" and not isinstance(value, dict):
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
```

- [ ] **Step 4: Run tests to verify Task 1 passes**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_tools.py -v
```

Expected: all tests in `tests/unit/test_tools.py` pass.

- [ ] **Step 5: Commit Task 1**

```bash
git add lighthermes/tools.py tests/unit/test_tools.py
git commit -m "feat: validate tool call arguments"
```

---

### Task 2: Add BaseChannel and ChannelRegistry

**Files:**
- Modify: `lighthermes/channels.py`
- Create: `tests/unit/test_channels.py`

- [ ] **Step 1: Write failing channel registry tests**

Create `tests/unit/test_channels.py`:

```python
"""轻量通道注册表测试"""

import pytest

from lighthermes.channels import ChannelMessage, ChannelRegistry, DirectChannel


@pytest.mark.unit
class TestChannelRegistry:
    def test_register_and_get_channel(self):
        registry = ChannelRegistry()
        channel = DirectChannel(name="local_debug")

        registry.register(channel)

        assert registry.get("local_debug") is channel
        assert registry.list_channels() == ["local_debug"]

    def test_register_overwrites_same_name(self):
        registry = ChannelRegistry()
        old_channel = DirectChannel(name="local_debug")
        new_channel = DirectChannel(name="local_debug")

        registry.register(old_channel)
        registry.register(new_channel)

        assert registry.get("local_debug") is new_channel
        assert registry.list_channels() == ["local_debug"]

    def test_direct_channel_send_to_agent_uses_message_identity(self):
        class FakeAgent:
            def run(self, content, **kwargs):
                return {"content": content, "kwargs": kwargs}

        channel = DirectChannel(name="direct")
        message = ChannelMessage(content="hello", user_id="u1", session_id="s1")

        result = channel.send_to_agent(FakeAgent(), message, stream=False)

        assert result == {
            "content": "hello",
            "kwargs": {"user_id": "u1", "session_id": "s1", "stream": False},
        }
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_channels.py -v
```

Expected: import fails because `ChannelRegistry` does not exist and `DirectChannel` does not accept `name`.

- [ ] **Step 3: Implement channel registry**

Replace `lighthermes/channels.py` with:

```python
"""
LightHermes 轻量消息通道边界
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ChannelMessage:
    content: str
    user_id: str = "default_user"
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class BaseChannel:
    """轻量通道基类"""

    name: str

    def send(self, message: ChannelMessage) -> None:
        raise NotImplementedError

    def receive(self) -> Optional[ChannelMessage]:
        raise NotImplementedError


class DirectChannel(BaseChannel):
    """直接把通道消息交给 Agent 执行"""

    def __init__(self, name: str = "direct"):
        self.name = name

    def send(self, message: ChannelMessage) -> None:
        return None

    def receive(self) -> Optional[ChannelMessage]:
        return None

    def send_to_agent(self, agent: Any, message: ChannelMessage, **kwargs):
        return agent.run(
            message.content,
            user_id=message.user_id,
            session_id=message.session_id,
            **kwargs
        )


class ChannelRegistry:
    """轻量通道注册表"""

    def __init__(self):
        self.channels: Dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> bool:
        name = getattr(channel, "name", "")
        if not name:
            return False
        self.channels[name] = channel
        return True

    def get(self, name: str) -> Optional[BaseChannel]:
        return self.channels.get(name)

    def list_channels(self) -> list[str]:
        return sorted(self.channels.keys())
```

- [ ] **Step 4: Run tests to verify Task 2 passes**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_channels.py -v
```

Expected: all channel tests pass.

- [ ] **Step 5: Commit Task 2**

```bash
git add lighthermes/channels.py tests/unit/test_channels.py
git commit -m "feat: add channel registry"
```

---

### Task 3: Add PluginLoader for Safe Local Tool Plugins

**Files:**
- Create: `lighthermes/plugins.py`
- Create: `tests/unit/test_plugins.py`

- [ ] **Step 1: Write failing plugin loader tests for tool plugins**

Create `tests/unit/test_plugins.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_plugins.py -v
```

Expected: import fails because `lighthermes.plugins.PluginLoader` does not exist.

- [ ] **Step 3: Implement PluginLoader tool loading**

Create `lighthermes/plugins.py`:

```python
"""
LightHermes 本地插件加载器
"""

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any, Dict, Optional, Union


class PluginLoader:
    """加载显式启用的本地插件"""

    def __init__(self, project_root: Union[str, Path] = ".", logger: Any = None):
        self.project_root = Path(project_root).resolve()
        self.logger = logger

    def load_tool_plugins(self, dispatcher, config: Optional[Dict[str, Any]], strict: bool = False) -> list[str]:
        loaded = []
        for name, path in self._iter_enabled_plugin_paths(config):
            try:
                module = self._load_module("tool", name, path)
                self._register_tool_module(dispatcher, module)
                loaded.append(name)
            except Exception as exc:
                self._handle_error(f"加载工具插件 {name} 失败: {exc}", exc, strict)
        return loaded

    def _iter_enabled_plugin_paths(self, config: Optional[Dict[str, Any]]):
        config = config or {}
        enabled = list(config.get("enabled", []))
        if not enabled:
            return

        dirs = config.get("dirs", [])
        for directory in dirs:
            plugin_dir = self._resolve_plugin_dir(directory)
            for name in enabled:
                candidate = plugin_dir / f"{name}.py"
                if candidate.exists():
                    yield name, candidate
                    break

    def _resolve_plugin_dir(self, directory: str) -> Path:
        path = Path(directory)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("Plugin directory must stay inside project root")

        resolved = (self.project_root / path).resolve()
        if self.project_root not in resolved.parents and resolved != self.project_root:
            raise ValueError("Plugin directory must stay inside project root")
        return resolved

    def _load_module(self, kind: str, name: str, path: Path) -> ModuleType:
        module_name = f"lighthermes_plugin_{kind}_{name}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise ImportError(f"Cannot load plugin module {name}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def _register_tool_module(self, dispatcher, module: ModuleType) -> None:
        register = getattr(module, "register", None)
        if callable(register):
            register(dispatcher)
            return

        tools = []
        for value in vars(module).values():
            if callable(value) and hasattr(value, "tool_info"):
                tools.append(value)
        dispatcher.register_tools(tools)

    def _handle_error(self, message: str, exc: Exception, strict: bool) -> None:
        if strict:
            raise exc
        if self.logger:
            self.logger.warning(message)
```

- [ ] **Step 4: Run tests to verify Task 3 passes**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_plugins.py -v
```

Expected: all tool plugin loader tests pass.

- [ ] **Step 5: Commit Task 3**

```bash
git add lighthermes/plugins.py tests/unit/test_plugins.py
git commit -m "feat: load local tool plugins"
```

---

### Task 4: Extend PluginLoader for Channel Plugins

**Files:**
- Modify: `lighthermes/plugins.py`
- Modify: `tests/unit/test_plugins.py`

- [ ] **Step 1: Write failing channel plugin tests**

Append to `tests/unit/test_plugins.py`:

```python
from lighthermes.channels import ChannelRegistry


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
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_plugins.py -v
```

Expected: channel tests fail because `PluginLoader.load_channel_plugins()` does not exist.

- [ ] **Step 3: Implement channel plugin loading**

Add this method to `PluginLoader` in `lighthermes/plugins.py`:

```python
    def load_channel_plugins(self, registry, config: Optional[Dict[str, Any]], strict: bool = False) -> list[str]:
        loaded = []
        for name, path in self._iter_enabled_plugin_paths(config):
            try:
                module = self._load_module("channel", name, path)
                self._register_channel_module(registry, module)
                loaded.append(name)
            except Exception as exc:
                self._handle_error(f"加载 Channel 插件 {name} 失败: {exc}", exc, strict)
        return loaded
```

Add this helper to the same class:

```python
    def _register_channel_module(self, registry, module: ModuleType) -> None:
        register_channels = getattr(module, "register_channels", None)
        if callable(register_channels):
            register_channels(registry)
            return

        channel = getattr(module, "channel", None)
        if channel is not None:
            registry.register(channel)
```

- [ ] **Step 4: Run plugin and channel tests**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_plugins.py tests/unit/test_channels.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit Task 4**

```bash
git add lighthermes/plugins.py tests/unit/test_plugins.py
git commit -m "feat: load local channel plugins"
```

---

### Task 5: Integrate Plugin Loading into LightHermes Core

**Files:**
- Modify: `lighthermes/core.py`
- Modify: `tests/unit/test_core_memory.py`

- [ ] **Step 1: Write failing core integration tests**

Append these tests to `TestCoreMemoryIntegration` in `tests/unit/test_core_memory.py`:

```python
    def test_plugins_are_disabled_by_default(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            evolution_enabled=False
        )

        assert hasattr(agent, "channel_registry")
        assert agent.channel_registry.list_channels() == []

    def test_core_loads_enabled_tool_and_channel_plugins(self, tmp_path, temp_memory_dir, monkeypatch):
        plugin_root = tmp_path
        tools_dir = plugin_root / "plugins" / "tools"
        channels_dir = plugin_root / "plugins" / "channels"
        tools_dir.mkdir(parents=True)
        channels_dir.mkdir(parents=True)
        (tools_dir / "hello.py").write_text(
            "from lighthermes import tool\n"
            "@tool('hello_plugin', 'Hello plugin', [])\n"
            "def hello_plugin():\n"
            "    return 'hello'\n",
            encoding="utf-8"
        )
        (channels_dir / "local_debug.py").write_text(
            "from lighthermes.channels import DirectChannel\n"
            "channel = DirectChannel(name='local_debug')\n",
            encoding="utf-8"
        )

        original_exists = os.path.exists
        original_open = open

        def fake_exists(path):
            if path == "config.yaml":
                return True
            return original_exists(path)

        def fake_open(path, *args, **kwargs):
            if path == "config.yaml":
                from io import StringIO
                return StringIO("""
plugins:
  strict: false
  tools:
    dirs:
      - plugins/tools
    enabled:
      - hello
  channels:
    dirs:
      - plugins/channels
    enabled:
      - local_debug
context_compression:
  enabled: false
""")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("lighthermes.core.os.path.exists", fake_exists)
        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setattr("lighthermes.core.Path.cwd", lambda: plugin_root)
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            evolution_enabled=False
        )

        assert agent.tool_dispatcher.call_tool("hello_plugin", {}) == "hello"
        assert agent.channel_registry.get("local_debug") is not None
```

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_core_memory.py::TestCoreMemoryIntegration::test_plugins_are_disabled_by_default tests/unit/test_core_memory.py::TestCoreMemoryIntegration::test_core_loads_enabled_tool_and_channel_plugins -v
```

Expected: first test fails because `channel_registry` is missing; second test fails because core does not load plugins.

- [ ] **Step 3: Modify imports in `lighthermes/core.py`**

Add these imports near the existing LightHermes imports:

```python
from lighthermes.channels import ChannelRegistry
from lighthermes.plugins import PluginLoader
```

- [ ] **Step 4: Initialize ChannelRegistry and PluginLoader in core**

In `LightHermes.__init__`, immediately after user-provided tools are registered, add:

```python
        self.channel_registry = ChannelRegistry()
        plugin_config = config.get("plugins", {})
        plugin_strict = plugin_config.get("strict", False)
        plugin_loader = PluginLoader(project_root=Path.cwd(), logger=self.logger)
        plugin_loader.load_tool_plugins(
            self.tool_dispatcher,
            plugin_config.get("tools", {}),
            strict=plugin_strict
        )
        plugin_loader.load_channel_plugins(
            self.channel_registry,
            plugin_config.get("channels", {}),
            strict=plugin_strict
        )
```

Place it before EvolutionEngine initialization so plugin tools are available before the agent runs.

- [ ] **Step 5: Run targeted core integration tests**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_core_memory.py::TestCoreMemoryIntegration::test_plugins_are_disabled_by_default tests/unit/test_core_memory.py::TestCoreMemoryIntegration::test_core_loads_enabled_tool_and_channel_plugins -v
```

Expected: both tests pass.

- [ ] **Step 6: Commit Task 5**

```bash
git add lighthermes/core.py tests/unit/test_core_memory.py
git commit -m "feat: integrate plugin loading into core"
```

---

### Task 6: Update Default Config and Documentation

**Files:**
- Modify: `config.yaml`
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`
- Modify: `docs/PROJECT_STATUS.md`
- Modify: `docs/superpowers/specs/2026-05-11-plugin-system-design.md` only if implementation names differ from the spec

- [ ] **Step 1: Update `config.yaml` plugin section**

Replace the current section:

```yaml
# 插件配置
plugins:
  dirs:
    - plugins/tools
    - plugins/memory
```

with:

```yaml
# 插件配置
# 本地插件默认关闭；只有 enabled 中显式列出的插件会被加载
plugins:
  strict: false
  tools:
    dirs:
      - plugins/tools
    enabled: []
  channels:
    dirs:
      - plugins/channels
    enabled: []
```

- [ ] **Step 2: Update README architecture bullets**

In `README.md`, update the architecture list so it includes these bullets:

```md
- `ToolDispatcher` 与 `tool` 位于 `lighthermes/tools.py`，统一工具装饰、注册、调用边界和运行时参数校验，支持同名工具覆盖。
- `PluginLoader` 位于 `lighthermes/plugins.py`，按配置显式加载本地工具插件和轻量 Channel 插件，默认关闭并隔离加载失败。
- `ChannelMessage` / `DirectChannel` / `ChannelRegistry` 位于 `lighthermes/channels.py`，预留 CLI/API/消息平台的轻量通道边界，不引入复杂 bus。
```

- [ ] **Step 3: Add README plugin configuration section**

After the built-in tools configuration block in `README.md`, add:

```md
**5. 本地插件系统** (`config.yaml`)
```yaml
plugins:
  strict: false
  tools:
    dirs:
      - plugins/tools
    enabled: []
  channels:
    dirs:
      - plugins/channels
    enabled: []
```

插件默认关闭，只有 `enabled` 中显式列出的本地插件会被加载。工具插件可使用 `@tool` 自动收集或 `register(dispatcher)` 手动注册；Channel 插件可暴露 `channel` 对象或 `register_channels(registry)`。第一版只支持项目内相对路径，不自动安装依赖，不提供网络 channel 或插件市场。后续可独立评估只读 `self_state` 自省工具。
```

When inserting this markdown, close and reopen code fences correctly so the README remains valid.

- [ ] **Step 4: Update ROADMAP Phase 3.1**

In `docs/ROADMAP.md`, replace Phase 3.1 checklist with:

```md
### 3.1 插件系统完善（中优先）

- [x] 设计轻量工具与 Channel 插件系统，明确 nanobot 借鉴边界
- [ ] 本地 Python 工具插件加载机制
- [ ] 本地 Channel 插件注册机制（DirectChannel 风格，不引入 bus/gateway）
- [ ] 插件目录扫描和显式启停配置
- [ ] 插件依赖管理（轻量级，避免自动安装重依赖）
- [ ] 插件错误隔离和 strict 模式
- [ ] 工具调用前运行时参数校验
- [ ] 插件测试样例
- [ ] `self_state` 自省工具（后续预留，不纳入 Phase 3.1 首轮实现）
- [ ] 插件市场（GitHub-based，可后置）
```

- [ ] **Step 5: Update PROJECT_STATUS next steps**

In `docs/PROJECT_STATUS.md`, update the Phase 3.1 next-step bullets to mention:

```md
2. **插件系统完善（Phase 3.1）**
   - 已完成轻量工具与 Channel 插件系统设计
   - 下一步实现本地工具插件加载、DirectChannel 风格 Channel 插件注册和 strict 错误模式
   - 保持插件默认关闭，不自动安装重依赖
```

- [ ] **Step 6: Run documentation grep checks**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests/unit/test_tools.py tests/unit/test_channels.py tests/unit/test_plugins.py -v
```

Expected: all targeted tests pass.

- [ ] **Step 7: Commit Task 6**

```bash
git add config.yaml README.md docs/ROADMAP.md docs/PROJECT_STATUS.md docs/superpowers/specs/2026-05-11-plugin-system-design.md
git commit -m "docs: document local plugin configuration"
```

---

### Task 7: Full Verification and Release-State Check

**Files:**
- No production file changes expected unless verification reveals a defect.

- [ ] **Step 1: Run full test suite**

Run:

```bash
.\venv\Scripts\python.exe -m pytest tests -v
```

Expected: all tests pass. The count will be higher than 113 because this plan adds new tests.

- [ ] **Step 2: Check git status**

Run:

```bash
git status --short
```

Expected: no uncommitted implementation files. `.claude/settings.local.json` may remain modified from local Claude settings and must not be committed.

- [ ] **Step 3: Inspect recent commits**

Run:

```bash
git log -5 --oneline
```

Expected: Task commits appear in order after `docs: 设计轻量插件系统`.

- [ ] **Step 4: If tests pass, leave branch ready for final review**

Do not create a tag during this implementation. This is post-v0.3.3 Phase 3.1 work and should be reviewed separately before a future release.

---

## Self-Review Checklist

- Spec coverage: PluginLoader, explicit enablement, safe defaults, strict mode, tool plugin APIs, channel plugin APIs, runtime argument validation, core integration, docs, and `self_state` reservation are covered by tasks.
- Scope control: No entry points, plugin market, network channels, bus, gateway, new dependencies, provider plugins, skill plugins, or `self_state` implementation are included.
- Type consistency: `PluginLoader`, `ToolDispatcher.prepare_call`, `ChannelRegistry`, `BaseChannel`, `DirectChannel(name=...)`, `load_tool_plugins`, and `load_channel_plugins` names are used consistently across tests and implementation steps.
- Verification: Every production change has a failing-test step before implementation and a passing-test step after implementation.
