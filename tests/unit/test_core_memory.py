"""核心记忆集成测试"""
import os
from types import SimpleNamespace

import pytest

from lighthermes.core import LightHermes, SkillLoader

class FakeAdapter:
    def create(self, **kwargs):
        raise AssertionError("测试不应调用真实模型")

class FakeChoice:
    def __init__(self, content):
        self.message = type("Message", (), {"content": content, "tool_calls": None})()

class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]
        self.usage = {"total_tokens": 3}

@pytest.mark.unit
class TestSkillLoaderFailureReports:
    """旧失败报告不得当作人工技能"""

    def test_failure_report_is_not_matched_as_skill(self):
        loader = SkillLoader([])
        loader.skills = {
            "bad_config": {
                "name": "bad_config",
                "description": "配置失败报告",
                "type": "failure_report",
                "trigger": "auto",
                "content": "不要忽略配置错误",
                "metadata": {"type": "failure_report", "task_type": "配置"}
            }
        }

        assert loader.match_skill("配置错误") is None
        assert loader.match_skill("/bad_config") is None

@pytest.mark.unit
class TestCoreMemoryIntegration:
    """测试核心流程中的记忆集成"""

    def test_from_config_uses_config_file_and_env_references(self, temp_memory_dir, tmp_path, monkeypatch):
        """测试 from_config 统一加载模型、记忆和运行配置"""
        captured_adapter_kwargs = {}
        memory_dir = temp_memory_dir.replace("\\", "/")
        config_path = tmp_path / "lighthermes.yaml"
        config_path.write_text(f"""
agent:
  name: ConfigAgent
  role: 配置驱动助手
model:
  provider: anthropic
  model_name: config-model
  api_key: ${{LIGHTHERMES_TEST_KEY}}
  base_url: https://example.test/anthropic
  fallback_models:
    - fallback-model
memory:
  enabled: true
  storage_dir: "{memory_dir}"
  hybrid_retrieval:
    enabled: false
evolution:
  enabled: false
skills:
  dirs: []
tools:
  builtin:
    enabled: false
context_compression:
  enabled: false
logging:
  level: DEBUG
cli:
  show_skill_usage: true
""", encoding="utf-8")

        def fake_get_adapter(**kwargs):
            captured_adapter_kwargs.update(kwargs)
            return FakeAdapter()

        monkeypatch.setenv("LIGHTHERMES_TEST_KEY", "env-api-key")
        monkeypatch.setattr("lighthermes.core.get_adapter", fake_get_adapter)

        agent = LightHermes.from_config(str(config_path))

        assert agent.name == "ConfigAgent"
        assert agent.role == "配置驱动助手"
        assert agent.model == "config-model"
        assert agent.provider == "anthropic"
        assert agent.fallback_models == ["fallback-model"]
        assert agent.memory_enabled is True
        assert str(agent.memory.memory_dir) == temp_memory_dir
        assert agent.evolution_enabled is False
        assert agent.compression_enabled is False
        assert agent.debug is True
        assert agent.tool_dispatcher.get_tool_schemas() == []
        assert captured_adapter_kwargs["api_key"] == "env-api-key"
        assert captured_adapter_kwargs["base_url"] == "https://example.test/anthropic"

    def test_from_config_resolves_model_name_and_base_url_from_env(self, temp_memory_dir, tmp_path, monkeypatch):
        config_path = tmp_path / "env-model.yaml"
        config_path.write_text(
            f"""
model:
  provider: openai
  model_name: ${{LIGHTHERMES_MODEL}}
  api_key: ${{LIGHTHERMES_API_KEY}}
  base_url: ${{LIGHTHERMES_BASE_URL}}
  fallback_models: []
memory:
  enabled: true
  storage_dir: "{temp_memory_dir.replace(chr(92), '/')}"
  hybrid_retrieval:
    enabled: false
evolution:
  enabled: false
context_compression:
  enabled: false
""",
            encoding="utf-8",
        )
        captured = {}

        def fake_get_adapter(**kwargs):
            captured.update(kwargs)
            return FakeAdapter()

        monkeypatch.setenv("LIGHTHERMES_MODEL", "my-gateway-model")
        monkeypatch.setenv("LIGHTHERMES_API_KEY", "env-key")
        monkeypatch.setenv("LIGHTHERMES_BASE_URL", "https://gateway.example/v1")
        monkeypatch.setattr("lighthermes.core.get_adapter", fake_get_adapter)

        agent = LightHermes.from_config(str(config_path))

        assert agent.model == "my-gateway-model"
        assert captured["model"] == "my-gateway-model"
        assert captured["api_key"] == "env-key"
        assert captured["base_url"] == "https://gateway.example/v1"

    def test_memory_enabled_registers_search_memory_builtin_tool(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=True,
            evolution_enabled=False
        )

        names = [schema["function"]["name"] for schema in agent.tool_dispatcher.get_tool_schemas()]
        assert "search_memory" in names
        assert "read_memory" in names

    def test_search_memory_builtin_does_not_affect_plain_response(self, temp_memory_dir, monkeypatch):
        captured = {}

        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: type("SkillLoader", (), {
            "match_skill": lambda self, query: None,
        })())

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=True,
            evolution_enabled=False
        )

        def fake_call_api(**kwargs):
            captured.update(kwargs)
            return FakeResponse("普通回复")

        agent._call_api_with_fallback = fake_call_api
        agent.tool_dispatcher.call_tool = lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("不应调用工具"))

        assert agent.run("你好", user_id="user_1", session_id="session_1") == "普通回复"
        assert captured["tool_choice"] == "auto"
        assert any(tool["function"]["name"] == "search_memory" for tool in captured["tools"])

    def test_file_tools_are_disabled_by_default(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=True,
            evolution_enabled=False
        )

        names = [schema["function"]["name"] for schema in agent.tool_dispatcher.get_tool_schemas()]
        assert "read_file" not in names
        assert "search_files" not in names

    def test_file_tools_register_when_enabled_in_config(self, temp_memory_dir, monkeypatch):
        original_exists = os.path.exists
        original_open = open

        def fake_exists(path):
            if path == "config.yaml":
                return True
            return original_exists(path)

        def fake_open(path, *args, **kwargs):
            if path == "config.yaml":
                from io import StringIO
                return StringIO(f"""
model:
  fallback_models: []
tools:
  builtin:
    enabled: true
    memory_search: true
    file_read: true
    file_search: true
    roots:
      - {temp_memory_dir}
context_compression:
  enabled: false
""")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("lighthermes.core.os.path.exists", fake_exists)
        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=True,
            evolution_enabled=False
        )

        names = [schema["function"]["name"] for schema in agent.tool_dispatcher.get_tool_schemas()]
        assert "search_memory" in names
        assert "read_file" in names
        assert "search_files" in names
        assert "write_file" not in names

    def test_write_file_registers_only_when_enabled_in_config(self, temp_memory_dir, monkeypatch):
        original_exists = os.path.exists
        original_open = open

        def fake_exists(path):
            if path == "config.yaml":
                return True
            return original_exists(path)

        def fake_open(path, *args, **kwargs):
            if path == "config.yaml":
                from io import StringIO
                return StringIO(f"""
model:
  fallback_models: []
tools:
  builtin:
    enabled: true
    file_write: true
    roots:
      - {temp_memory_dir}
context_compression:
  enabled: false
""")
            return original_open(path, *args, **kwargs)

        monkeypatch.setattr("lighthermes.core.os.path.exists", fake_exists)
        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=True,
            evolution_enabled=False
        )

        names = [schema["function"]["name"] for schema in agent.tool_dispatcher.get_tool_schemas()]
        assert "write_file" in names

    def test_memory_disabled_does_not_register_search_memory_builtin_tool(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=False,
            evolution_enabled=False
        )

        names = [schema["function"]["name"] for schema in agent.tool_dispatcher.get_tool_schemas()]
        assert "search_memory" not in names
        assert "read_memory" not in names

    def test_user_tool_overrides_builtin_search_memory(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)

        from lighthermes.tools import tool

        @tool("search_memory", "自定义记忆搜索", [])
        def custom_search_memory():
            return "custom"

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=True,
            evolution_enabled=False,
            tools=[custom_search_memory]
        )

        schemas = agent.tool_dispatcher.get_tool_schemas()
        matching = [schema for schema in schemas if schema["function"]["name"] == "search_memory"]
        assert len(matching) == 1
        assert matching[0]["function"]["description"] == "自定义记忆搜索"
        assert agent.tool_dispatcher.call_tool("search_memory", {}) == "custom"

    def test_non_stream_accepts_anthropic_dict_tool_calls(self):
        tool_message = type("Message", (), {
            "content": "",
            "tool_calls": [{
                "id": "call_1",
                "type": "function",
                "function": {"name": "lookup", "arguments": '{"query": "test"}'}
            }]
        })()
        final_message = type("Message", (), {
            "content": "完成",
            "tool_calls": None
        })()

        class Response:
            def __init__(self, message):
                self.choices = [type("Choice", (), {"message": message})()]
                self.usage = None

        calls = []
        agent = LightHermes.__new__(LightHermes)
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = False
        agent.memory = None
        agent.evolution_enabled = False
        agent.evolution = None
        agent.tool_dispatcher = type("ToolDispatcher", (), {
            "call_tool": lambda self, name, args: calls.append((name, args)) or "ok"
        })()
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.logger = type("Logger", (), {
            "warning": lambda *args, **kwargs: None,
            "info": lambda *args, **kwargs: None,
            "error": lambda *args, **kwargs: None,
        })()
        responses = iter([Response(tool_message), Response(final_message)])
        agent._call_api_with_fallback = lambda **kwargs: next(responses)

        reply = agent._run_non_stream(
            {"messages": [{"role": "user", "content": "问题"}], "stream": False},
            max_iterations=3,
            query="问题",
            user_id="user_1",
            session_id="session_1"
        )

        assert reply == "完成"
        assert calls == [("lookup", {"query": "test"})]

@pytest.mark.unit
class TestCallApiWithFallbackRestoresModel:
    """_call_api_with_fallback 在成功与失败路径都须恢复 adapter 原始模型。"""

    class TrackingAdapter:
        """create 会切换 model 到调用时的 model，并可对指定 model 抛异常。"""

        def __init__(self, fail_models):
            self.initial_model = "primary"
            self.model = "primary"
            self.fail_models = set(fail_models)
            self.invoked_models = []

        def create(self, **kwargs):
            self.invoked_models.append(self.model)
            if self.model in self.fail_models:
                raise RuntimeError(f"model {self.model} failed")
            response = SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="ok", tool_calls=None))]
            )
            return response

    def _make_agent(self, adapter, fallback_models):
        agent = LightHermes.__new__(LightHermes)
        agent.adapter = adapter
        agent.model = adapter.initial_model
        agent.fallback_models = fallback_models
        agent.logger = SimpleNamespace(
            warning=lambda *a, **k: None, error=lambda *a, **k: None, info=lambda *a, **k: None
        )
        return agent

    def test_primary_fails_fallback_succeeds_then_model_restored(self):
        adapter = self.TrackingAdapter(fail_models={"primary"})
        agent = self._make_agent(adapter, ["fallback-a", "fallback-b"])

        result = agent._call_api_with_fallback(messages=[{"role": "user", "content": "q"}])

        assert getattr(result, "choices", None)
        # 依次尝试 primary(失败)、fallback-a 成功
        assert adapter.invoked_models == ["primary", "fallback-a"]
        # 无论成功失败，最终都要恢复原始模型
        assert adapter.model == "primary"

    def test_all_models_fail_raises_and_still_restores_model(self):
        adapter = self.TrackingAdapter(fail_models={"primary", "fallback-a"})
        agent = self._make_agent(adapter, ["fallback-a"])

        with pytest.raises(RuntimeError, match="model fallback-a failed"):
            agent._call_api_with_fallback(messages=[{"role": "user", "content": "q"}])

        assert adapter.invoked_models == ["primary", "fallback-a"]
        # 全失败 raise 时也必须恢复原始模型，避免污染后续调用
        assert adapter.model == "primary"

@pytest.mark.unit

@pytest.mark.unit
def test_adapter_create_is_single_model_call_exit(temp_memory_dir, monkeypatch):
    """走非流式 run 时，模型调用的唯一出口是 agent.adapter.create。

    benchmark 靠替换 agent.adapter.create 来统计 usage；此测试锁住该前提，
    防止未来多出一条绕过 adapter.create 的调用路径。
    """
    adapter_calls = {"n": 0}
    wrapper_calls = {"n": 0}

    class TrackingAdapter:
        def __init__(self):
            self.model = "gpt-4o-mini"

        def create(self, **kwargs):
            adapter_calls["n"] += 1
            return FakeResponse("计数回复")

    tracker = TrackingAdapter()
    monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: tracker)
    monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: type("SkillLoader", (), {
        "match_skill": lambda self, query: None,
    })())

    agent = LightHermes(
        model="gpt-4o-mini",
        provider="openai",
        api_key="test-key",
        memory_dir=temp_memory_dir,
        memory_enabled=True,
        evolution_enabled=False,
    )

    raw_create = agent.adapter.create

    def counted_create(**kwargs):
        wrapper_calls["n"] += 1
        return raw_create(**kwargs)

    agent.adapter.create = counted_create

    reply = agent.run("你好", user_id="u", session_id="s")

    assert reply == "计数回复"
    # 关键不变量：wrapper 与底层 adapter 一一对应，且模型确实被调用过。
    # 若存在绕过 wrapper 的第二条路径，adapter_calls 会大于 wrapper_calls。
    assert wrapper_calls["n"] == adapter_calls["n"]
    assert wrapper_calls["n"] >= 1
