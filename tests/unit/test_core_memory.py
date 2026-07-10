"""核心记忆集成测试"""
import os

import pytest

from lighthermes.core import LightHermes, SkillLoader
from lighthermes.memory import MemoryManager


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
    """测试失败报告召回"""

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

    def test_recall_failure_reports_by_task_type_and_query(self):
        loader = SkillLoader([])
        loader.skills = {
            "bad_config": {
                "name": "bad_config",
                "description": "配置失败报告",
                "type": "failure_report",
                "trigger": "auto",
                "content": "不要忽略 API key 配置错误，先验证配置",
                "metadata": {"type": "failure_report", "task_type": "配置"}
            },
            "bad_debug": {
                "name": "bad_debug",
                "description": "调试失败报告",
                "type": "failure_report",
                "trigger": "auto",
                "content": "不要盲目修复报错",
                "metadata": {"type": "failure_report", "task_type": "调试"}
            }
        }

        reports = loader.recall_failure_reports("配置 API key 报错", "配置")

        assert reports[0]["name"] == "bad_config"

    def test_unrelated_failure_report_is_not_recalled(self):
        loader = SkillLoader([])
        loader.skills = {
            "bad_config": {
                "name": "bad_config",
                "description": "配置失败报告",
                "type": "failure_report",
                "trigger": "auto",
                "content": "不要忽略 API key 配置错误",
                "metadata": {"type": "failure_report", "task_type": "配置"}
            }
        }

        assert loader.recall_failure_reports("解释 Python 生成器", "解释") == []


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

    def test_save_compression_summary_to_working_memory(self, temp_memory_dir):
        """测试压缩摘要写入工作记忆"""
        agent = LightHermes.__new__(LightHermes)
        agent.memory_enabled = True
        agent.extract_compression_to_memory = True
        agent.memory = MemoryManager(
            memory_dir=temp_memory_dir,
            use_hybrid_retrieval=False
        )

        messages = [
            {"role": "system", "content": "system"},
            {
                "role": "assistant",
                "content": "[CONTEXT COMPACTION — REFERENCE ONLY]\n\n保留关键设计决策"
            }
        ]

        agent._save_compression_summary_to_memory(
            messages,
            session_id="session_1",
            user_id="default"
        )

        sessions = agent.memory.working.get_recent_sessions("default", limit=1)
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "session_1"
        assert sessions[0]["summary"] == "保留关键设计决策"

    def test_compression_summary_respects_config_flag(self, temp_memory_dir):
        """测试关闭开关时不写入工作记忆"""
        agent = LightHermes.__new__(LightHermes)
        agent.memory_enabled = True
        agent.extract_compression_to_memory = False
        agent.memory = MemoryManager(
            memory_dir=temp_memory_dir,
            use_hybrid_retrieval=False
        )

        messages = [{
            "role": "assistant",
            "content": "[CONTEXT COMPACTION — REFERENCE ONLY]\n\n不应保存"
        }]

        agent._save_compression_summary_to_memory(
            messages,
            session_id="session_1",
            user_id="default"
        )

        sessions = agent.memory.working.get_recent_sessions("default", limit=1)
        assert sessions == []

    def test_embedding_config_passed_to_memory_manager(self, temp_memory_dir, monkeypatch):
        """测试独立 embedding 配置传入记忆管理器"""
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
model:
  fallback_models: []
embedding:
  provider: openai
  model_name: BAAI/bge-m3
  api_key: $(LIGHTHERMES_EMBEDDING_KEY)
  base_url: $(LIGHTHERMES_EMBEDDING_BASE_URL)
memory:
  hybrid_retrieval:
    enabled: true
    min_candidates: 3
    fallback_to_all: true
    semantic_threshold: 0.42
    score_margin: 0.11
    full_rerank_max_docs: 99
    tfidf_candidate_limit: 12
  retention:
    semantic_max_entries: 123
    semantic_max_chars: 4567
    semantic_similarity_threshold: 0.75
    distill_recent_limit: 8
context_compression:
  enabled: false
""")
            return original_open(path, *args, **kwargs)

        class FakeMemoryManager:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        monkeypatch.setattr("lighthermes.core.os.path.exists", fake_exists)
        monkeypatch.setattr("builtins.open", fake_open)
        monkeypatch.setenv("LIGHTHERMES_EMBEDDING_KEY", "env-embedding-key")
        monkeypatch.setenv("LIGHTHERMES_EMBEDDING_BASE_URL", "https://embedding.example.test/v1")
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.MemoryManager", FakeMemoryManager)
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.ToolDispatcher", lambda *args, **kwargs: None)

        agent = LightHermes(
            model="gpt-4o-mini",
            provider="openai",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            evolution_enabled=False
        )

        assert agent.memory.kwargs["use_hybrid_retrieval"] is True
        assert agent.memory.kwargs["embedding_provider"] == "openai"
        assert agent.memory.kwargs["embedding_model"] == "BAAI/bge-m3"
        assert agent.memory.kwargs["api_key"] == "env-embedding-key"
        assert agent.memory.kwargs["embedding_base_url"] == "https://embedding.example.test/v1"
        assert agent.memory.kwargs["hybrid_min_candidates"] == 3
        assert agent.memory.kwargs["hybrid_fallback_to_all"] is True
        assert agent.memory.kwargs["hybrid_semantic_threshold"] == 0.42
        assert agent.memory.kwargs["hybrid_score_margin"] == 0.11
        assert agent.memory.kwargs["hybrid_full_rerank_max_docs"] == 99
        assert agent.memory.kwargs["hybrid_tfidf_candidate_limit"] == 12
        assert agent.memory.kwargs["semantic_max_entries"] == 123
        assert agent.memory.kwargs["semantic_max_chars"] == 4567
        assert agent.memory.kwargs["semantic_similarity_threshold"] == 0.75
        assert agent.memory.kwargs["distill_recent_limit"] == 8

    def test_from_config_loads_local_env_file_for_embedding(self, temp_memory_dir, tmp_path, monkeypatch):
        """测试项目级 env 文件可提供 embedding 密钥"""
        captured_memory_kwargs = {}
        memory_dir = temp_memory_dir.replace("\\", "/")
        config_path = tmp_path / "lighthermes.yaml"
        env_path = tmp_path / ".env.local"

        env_path.write_text(
            "LOCAL_EMBEDDING_KEY=local-embedding-key\n"
            "LOCAL_EMBEDDING_BASE_URL=https://local-embedding.example.test/v1\n",
            encoding="utf-8"
        )
        config_path.write_text(f"""
model:
  provider: openai
  model_name: gpt-5.4-mini
  api_key: test-main-key
embedding:
  provider: openai
  model_name: BAAI/bge-m3
  api_key: $(LOCAL_EMBEDDING_KEY)
  base_url: $(LOCAL_EMBEDDING_BASE_URL)
memory:
  enabled: true
  storage_dir: "{memory_dir}"
  hybrid_retrieval:
    enabled: true
secrets:
  env_file: .env.local
evolution:
  enabled: false
skills:
  dirs: []
tools:
  builtin:
    enabled: false
context_compression:
  enabled: false
""", encoding="utf-8")

        class FakeMemoryManager:
            def __init__(self, **kwargs):
                captured_memory_kwargs.update(kwargs)

        monkeypatch.delenv("LOCAL_EMBEDDING_KEY", raising=False)
        monkeypatch.delenv("LOCAL_EMBEDDING_BASE_URL", raising=False)
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.MemoryManager", FakeMemoryManager)
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.ToolDispatcher", lambda *args, **kwargs: None)

        LightHermes.from_config(str(config_path))

        assert captured_memory_kwargs["use_hybrid_retrieval"] is True
        assert captured_memory_kwargs["embedding_model"] == "BAAI/bge-m3"
        assert captured_memory_kwargs["api_key"] == "local-embedding-key"
        assert captured_memory_kwargs["embedding_base_url"] == "https://local-embedding.example.test/v1"

    def test_memory_enabled_registers_search_memory_builtin_tool(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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

    def test_search_memory_builtin_does_not_affect_plain_response(self, temp_memory_dir, monkeypatch):
        captured = {}

        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: type("SkillLoader", (), {
            "match_skill": lambda self, query: None,
            "recall_failure_reports": lambda self, query, task_type, limit=2: []
        })())
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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

    def test_user_tool_overrides_builtin_search_memory(self, temp_memory_dir, monkeypatch):
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", lambda *args, **kwargs: None)

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

    def test_non_openai_provider_reuses_adapter_for_evolution(self, temp_memory_dir, monkeypatch):
        """测试非 OpenAI provider 不再要求额外 OPENAI_API_KEY"""
        class FakeEvolutionEngine:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: FakeAdapter())
        monkeypatch.setattr("lighthermes.core.SkillLoader", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.ToolDispatcher", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.MemoryManager", lambda *args, **kwargs: None)
        monkeypatch.setattr("lighthermes.core.EvolutionEngine", FakeEvolutionEngine)

        agent = LightHermes(
            model="claude-sonnet-4-6",
            provider="anthropic",
            api_key="test-key",
            memory_dir=temp_memory_dir,
            memory_enabled=False,
            evolution_enabled=True
        )

        assert agent.evolution_enabled is True
        assert isinstance(agent.evolution.kwargs["client"], FakeAdapter)
        assert agent.evolution.kwargs["model"] == "claude-sonnet-4-6"

    def test_should_extract_memory_detects_save_intent(self):
        agent = LightHermes.__new__(LightHermes)

        assert agent._should_extract_memory("请记住我的名字是张三") is True
        assert agent._should_extract_memory("记一下我喜欢 Python") is True
        assert agent._should_extract_memory("remember that I prefer concise answers") is True

    def test_should_extract_memory_ignores_memory_queries(self):
        agent = LightHermes.__new__(LightHermes)

        assert agent._should_extract_memory("你还记得什么吗") is False
        assert agent._should_extract_memory("你记得我是谁吗") is False
        assert agent._should_extract_memory("查看记忆") is False
        assert agent._should_extract_memory("what do you remember about me?") is False

    def test_run_does_not_extract_memory_for_memory_query(self, temp_memory_dir):
        captured = {}

        class FakeMemory:
            memory_dir = temp_memory_dir

            def on_turn_start(self, query, user_id="default", session_id=""):
                return "<memory-context>用户喜欢简洁回答</memory-context>"

            def on_turn_end(self, user_content, assistant_content, user_id="default", session_id=""):
                pass

            def get_context(self):
                return []

            def add_message(self, role, content):
                pass

        agent = LightHermes.__new__(LightHermes)
        agent.name = "test-agent"
        agent.role = "你是测试助手"
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = True
        agent.memory = FakeMemory()
        agent.skill_loader = type("SkillLoader", (), {
            "match_skill": lambda self, query: None,
            "recall_failure_reports": lambda self, query, task_type, limit=2: []
        })()
        agent.compression_enabled = False
        agent.compressor = None
        agent.context_window = 128000
        agent.tool_dispatcher = type("ToolDispatcher", (), {"get_tool_schemas": lambda self: []})()
        agent.evolution_enabled = False
        agent.evolution = None
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.debug = False
        agent.logger = type("Logger", (), {"warning": lambda *args, **kwargs: None, "info": lambda *args, **kwargs: None})()

        def fake_call_api(**kwargs):
            captured["system_prompt"] = kwargs["messages"][0]["content"]
            return FakeResponse("测试回复")

        agent._call_api_with_fallback = fake_call_api
        agent._extract_and_save_memory = lambda query: (_ for _ in ()).throw(AssertionError("不应提取记忆"))

        assert agent.run("你还记得什么吗", user_id="user_1", session_id="session_1") == "测试回复"
        assert "你具备 LightHermes 持久记忆能力" in captured["system_prompt"]
        assert "用户喜欢简洁回答" in captured["system_prompt"]

    def test_run_stream_stops_after_response_without_finish_reason(self):
        class Delta:
            content = "测试回复"
            tool_calls = None

        class Choice:
            delta = Delta()
            finish_reason = None

        class Chunk:
            choices = [Choice()]

        agent = LightHermes.__new__(LightHermes)
        agent.tool_dispatcher = type("ToolDispatcher", (), {"get_tool_schemas": lambda self: []})()
        agent.logger = type("Logger", (), {"error": lambda *args, **kwargs: None})()
        agent.api_call_count = 0
        agent.query_count = 0
        agent.memory_enabled = False
        agent.evolution_enabled = False
        agent.evolution = None
        calls = []

        def fake_call_api(**kwargs):
            calls.append(kwargs)
            return iter([Chunk()])

        agent._call_api_with_fallback = fake_call_api

        chunks = list(agent._run_stream(
            {"messages": [], "stream": True},
            max_iterations=10,
            query="测试",
            user_id="user_1",
            session_id="session_1"
        ))

        assert chunks == ["测试回复"]
        assert len(calls) == 1
        assert agent.api_call_count == 1
        assert agent.query_count == 1

    def test_run_stream_completes_memory_lifecycle(self, temp_memory_dir):
        class FakeMemory:
            memory_dir = temp_memory_dir

            def __init__(self):
                self.calls = []

            def on_turn_start(self, query, user_id="default", session_id=""):
                self.calls.append(("start", query, user_id, session_id))
                return ""

            def on_turn_end(self, user_content, assistant_content, user_id="default", session_id=""):
                self.calls.append(("end", user_content, assistant_content, user_id, session_id))

            def get_context(self):
                return []

            def add_message(self, role, content):
                self.calls.append(("message", role, content))

        class Delta:
            content = "流式回复"
            tool_calls = None

        class Choice:
            delta = Delta()
            finish_reason = "stop"

        class Chunk:
            choices = [Choice()]

        agent = LightHermes.__new__(LightHermes)
        agent.name = "test-agent"
        agent.role = "你是测试助手"
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = True
        agent.memory = FakeMemory()
        agent.skill_loader = type("SkillLoader", (), {
            "match_skill": lambda self, query: None,
            "recall_failure_reports": lambda self, query, task_type, limit=2: []
        })()
        agent.compression_enabled = False
        agent.compressor = None
        agent.context_window = 128000
        agent.tool_dispatcher = type("ToolDispatcher", (), {"get_tool_schemas": lambda self: []})()
        agent.evolution_enabled = False
        agent.evolution = None
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.debug = False
        agent.logger = type("Logger", (), {
            "warning": lambda *args, **kwargs: None,
            "info": lambda *args, **kwargs: None,
            "error": lambda *args, **kwargs: None,
        })()
        agent._call_api_with_fallback = lambda **kwargs: iter([Chunk()])
        agent._should_extract_memory = lambda query: False

        chunks = list(agent.run(
            "原始问题",
            stream=True,
            user_id="user_1",
            session_id="session_1"
        ))

        assert chunks == ["流式回复"]
        assert ("start", "原始问题", "user_1", "session_1") in agent.memory.calls
        assert ("message", "user", "原始问题") in agent.memory.calls
        assert ("end", "原始问题", "流式回复", "user_1", "session_1") in agent.memory.calls
        assert agent.query_count == 1
        assert agent.api_call_count == 1

    def test_run_stream_records_trajectory_only_after_completion(self):
        class Delta:
            content = "完整回复"
            tool_calls = None

        class Choice:
            delta = Delta()
            finish_reason = "stop"

        class Chunk:
            choices = [Choice()]

        class FakeEvolution:
            def __init__(self):
                self.recorded = None

            def record_session(self, **kwargs):
                self.recorded = kwargs

        def make_agent():
            agent = LightHermes.__new__(LightHermes)
            agent.model = "gpt-4o-mini"
            agent.memory_enabled = False
            agent.memory = None
            agent.evolution_enabled = True
            agent.evolution = FakeEvolution()
            agent.auto_generate_skills = False
            agent.tool_dispatcher = type("ToolDispatcher", (), {})()
            agent.query_count = 0
            agent.api_call_count = 0
            agent.logger = type("Logger", (), {
                "warning": lambda *args, **kwargs: None,
                "info": lambda *args, **kwargs: None,
                "error": lambda *args, **kwargs: None,
            })()
            agent._call_api_with_fallback = lambda **kwargs: iter([Chunk()])
            return agent

        interrupted_agent = make_agent()
        interrupted = interrupted_agent._run_stream(
            {"messages": [{"role": "user", "content": "原始问题"}], "stream": True},
            max_iterations=1,
            query="原始问题",
            user_id="user_1",
            session_id="session_1"
        )
        assert next(interrupted) == "完整回复"
        interrupted.close()
        assert interrupted_agent.evolution.recorded is None
        assert interrupted_agent.query_count == 0

        completed_agent = make_agent()
        chunks = list(completed_agent._run_stream(
            {"messages": [{"role": "user", "content": "原始问题"}], "stream": True},
            max_iterations=1,
            query="原始问题",
            user_id="user_1",
            session_id="session_1"
        ))

        assert chunks == ["完整回复"]
        recorded = completed_agent.evolution.recorded
        assert recorded["task_type"] == completed_agent._classify_task("原始问题")
        assert recorded["messages"][-1] == {"role": "assistant", "content": "完整回复"}
        assert recorded["tool_calls"] == []
        assert completed_agent.query_count == 1

    def test_non_stream_tool_trajectory_keeps_query_reply_and_tool_call(self):
        class ToolFunction:
            name = "lookup"
            arguments = '{"query": "LightHermes"}'

        class ToolCall:
            id = "call_1"
            function = ToolFunction()

        class ToolMessage:
            content = ""
            tool_calls = [ToolCall()]

        class FinalMessage:
            content = "最终答案"
            tool_calls = None

        class Response:
            def __init__(self, message):
                self.choices = [type("Choice", (), {"message": message})()]
                self.usage = {"total_tokens": 3}

        class FakeEvolution:
            def __init__(self):
                self.recorded = None

            def record_session(self, **kwargs):
                self.recorded = kwargs

        agent = LightHermes.__new__(LightHermes)
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = False
        agent.memory = None
        agent.evolution_enabled = True
        agent.evolution = FakeEvolution()
        agent.auto_generate_skills = False
        agent.skill_loader = type("SkillLoader", (), {"load_all": lambda self: None})()
        agent.tool_dispatcher = type("ToolDispatcher", (), {
            "call_tool": lambda self, name, args: "工具结果"
        })()
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.logger = type("Logger", (), {
            "warning": lambda *args, **kwargs: None,
            "info": lambda *args, **kwargs: None,
            "error": lambda *args, **kwargs: None,
        })()

        responses = iter([Response(ToolMessage()), Response(FinalMessage())])
        agent._call_api_with_fallback = lambda **kwargs: next(responses)

        reply = agent._run_non_stream(
            {"messages": [{"role": "user", "content": "原始问题"}], "stream": False},
            max_iterations=3,
            query="原始问题",
            user_id="user_1",
            session_id="session_1"
        )

        assert reply == "最终答案"
        recorded = agent.evolution.recorded
        assert recorded["task_type"] == agent._classify_task("原始问题")
        assert recorded["tool_calls"] == [{
            "tool": "lookup",
            "name": "lookup",
            "arguments": '{"query": "LightHermes"}'
        }]
        assert recorded["messages"][-1] == {"role": "assistant", "content": "最终答案"}
        assert recorded["messages"][0] == {"role": "user", "content": "原始问题"}

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

    def test_build_semantic_memory_list_uses_search_memory(self, temp_memory_dir):
        class FakeMemory:
            def __init__(self):
                self.calls = []

            def search_memory(self, query, layer="all", limit=5, include_metadata=False):
                self.calls.append({
                    "query": query,
                    "layer": layer,
                    "limit": limit,
                    "include_metadata": include_metadata,
                })
                return [{"layer": "semantic", "name": "pref", "content": "用户偏好中文"}]

        agent = LightHermes.__new__(LightHermes)
        agent.memory_enabled = True
        agent.memory = FakeMemory()

        result = agent._build_semantic_memory_list()

        assert agent.memory.calls == [{
            "query": "",
            "layer": "semantic",
            "limit": 20,
            "include_metadata": False,
        }]
        assert "- pref: 用户偏好中文" in result

    def test_run_injects_all_semantic_memories_for_memory_list_query(self, temp_memory_dir):
        captured = {}
        memory = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        memory.save_user_preference("- 助手名字", "糖糖")

        agent = LightHermes.__new__(LightHermes)
        agent.name = "test-agent"
        agent.role = "你是测试助手"
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = True
        agent.memory = memory
        agent.skill_loader = type("SkillLoader", (), {
            "match_skill": lambda self, query: None,
            "recall_failure_reports": lambda self, query, task_type, limit=2: []
        })()
        agent.compression_enabled = False
        agent.compressor = None
        agent.context_window = 128000
        agent.tool_dispatcher = type("ToolDispatcher", (), {"get_tool_schemas": lambda self: []})()
        agent.evolution_enabled = False
        agent.evolution = None
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.debug = False
        agent.logger = type("Logger", (), {"warning": lambda *args, **kwargs: None, "info": lambda *args, **kwargs: None})()

        def fake_call_api(**kwargs):
            captured["system_prompt"] = kwargs["messages"][0]["content"]
            return FakeResponse("测试回复")

        agent._call_api_with_fallback = fake_call_api
        agent._extract_and_save_memory = lambda query: (_ for _ in ()).throw(AssertionError("不应提取记忆"))

        assert agent.run("你的语义记忆里有1条，是什么", user_id="user_1", session_id="session_1") == "测试回复"
        assert "## 语义记忆清单" in captured["system_prompt"]
        assert "- 助手名字: 糖糖" in captured["system_prompt"]

    def test_run_injects_failure_report_warning(self, temp_memory_dir):
        """测试 run 注入失败报告风险提示"""
        captured = {}

        class FakeMemory:
            memory_dir = temp_memory_dir

            def on_turn_start(self, query, user_id="default", session_id=""):
                return ""

            def on_turn_end(self, user_content, assistant_content, user_id="default", session_id=""):
                pass

            def get_context(self):
                return []

            def add_message(self, role, content):
                pass

        class FakeSkillLoader:
            def match_skill(self, query):
                return None

            def recall_failure_reports(self, query, task_type, limit=2):
                return [{
                    "name": "bad_config",
                    "description": "不要忽略 API key 配置错误",
                    "content": "先验证配置再继续"
                }]

        def fake_call_api(**kwargs):
            captured["messages"] = kwargs["messages"]
            return FakeResponse("测试回复")

        agent = LightHermes.__new__(LightHermes)
        agent.name = "test-agent"
        agent.role = "你是测试助手"
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = True
        agent.memory = FakeMemory()
        agent.skill_loader = FakeSkillLoader()
        agent.compression_enabled = False
        agent.compressor = None
        agent.context_window = 128000
        agent.tool_dispatcher = type("ToolDispatcher", (), {"get_tool_schemas": lambda self: []})()
        agent.evolution_enabled = False
        agent.evolution = None
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.debug = False
        agent.logger = type("Logger", (), {"warning": lambda *args, **kwargs: None, "info": lambda *args, **kwargs: None})()
        agent._call_api_with_fallback = fake_call_api
        agent._should_extract_memory = lambda query: False

        reply = agent.run("配置 API key 报错", user_id="user_1", session_id="session_1")

        system_prompt = captured["messages"][0]["content"]
        assert reply == "测试回复"
        assert "执行前风险提示" in system_prompt
        assert "不要忽略 API key 配置错误" in system_prompt

    def test_run_uses_memory_lifecycle_hooks(self, temp_memory_dir):
        """测试 run 接入记忆生命周期钩子"""
        class FakeMemory:
            memory_dir = temp_memory_dir

            def __init__(self):
                self.calls = []

            def on_turn_start(self, query, user_id="default", session_id=""):
                self.calls.append(("start", query, user_id, session_id))
                return "<memory-context>测试记忆</memory-context>"

            def on_turn_end(self, user_content, assistant_content, user_id="default", session_id=""):
                self.calls.append(("end", user_content, assistant_content, user_id, session_id))

            def get_context(self):
                return []

            def add_message(self, role, content):
                self.calls.append(("message", role, content))

        agent = LightHermes.__new__(LightHermes)
        agent.name = "test-agent"
        agent.role = "你是测试助手"
        agent.model = "gpt-4o-mini"
        agent.memory_enabled = True
        agent.memory = FakeMemory()
        agent.skill_loader = type("SkillLoader", (), {"match_skill": lambda self, query: None})()
        agent.compression_enabled = False
        agent.compressor = None
        agent.context_window = 128000
        agent.tool_dispatcher = type("ToolDispatcher", (), {"get_tool_schemas": lambda self: []})()
        agent.evolution_enabled = False
        agent.evolution = None
        agent.query_count = 0
        agent.total_tokens_used = 0
        agent.api_call_count = 0
        agent.debug = False
        agent.logger = type("Logger", (), {"warning": lambda *args, **kwargs: None, "info": lambda *args, **kwargs: None})()
        agent._call_api_with_fallback = lambda **kwargs: FakeResponse("测试回复")
        agent._should_extract_memory = lambda query: False

        reply = agent.run("你好", user_id="user_1", session_id="session_1")

        assert reply == "测试回复"
        assert ("start", "你好", "user_1", "session_1") in agent.memory.calls
        assert ("message", "user", "你好") in agent.memory.calls
        assert ("end", "你好", "测试回复", "user_1", "session_1") in agent.memory.calls

    def test_run_stream_with_tool_calls_uses_fallback(self):
        class ToolCallFunction:
            name = "my_tool"
            arguments = '{"arg": "val"}'

        class ToolCallDelta:
            id = "call_1"
            index = 0
            function = ToolCallFunction()

        class DeltaWithTool:
            content = None
            tool_calls = [ToolCallDelta()]

        class ChoiceWithTool:
            delta = DeltaWithTool()
            finish_reason = "tool_calls"

        class ChunkWithTool:
            choices = [ChoiceWithTool()]

        class DeltaNormal:
            content = "最终回复"
            tool_calls = None

        class ChoiceNormal:
            delta = DeltaNormal()
            finish_reason = "stop"

        class ChunkNormal:
            choices = [ChoiceNormal()]

        agent = LightHermes.__new__(LightHermes)

        class FakeToolDispatcher:
            def get_tool_schemas(self):
                return []
            def call_tool(self, name, args):
                return "tool_result"
        agent.tool_dispatcher = FakeToolDispatcher()

        agent.logger = type("Logger", (), {"error": lambda *args, **kwargs: None})()
        agent.api_call_count = 0
        agent.query_count = 0
        agent.memory_enabled = False
        agent.evolution_enabled = False
        agent.evolution = None

        calls = []
        def fake_call_api(**kwargs):
            calls.append(kwargs)
            if len(calls) == 1:
                return iter([ChunkWithTool()])
            else:
                return iter([ChunkNormal()])

        agent._call_api_with_fallback = fake_call_api

        chunks = list(agent._run_stream(
            {
                "messages": [{"role": "user", "content": "hello"}],
                "stream": True,
                "tools": [],
                "tool_choice": "auto"
            },
            max_iterations=10,
            query="hello",
            user_id="user_1",
            session_id="session_1"
        ))

        assert "最终回复" in chunks
        assert len(calls) == 2
        messages = calls[1]["messages"]
        assert len(messages) == 4
        assert messages[1]["role"] == "assistant"
        assert messages[1]["tool_calls"][0]["function"]["name"] == "my_tool"
        assert messages[2]["role"] == "tool"
        assert messages[2]["content"] == "tool_result"
        assert messages[3] == {"role": "assistant", "content": "最终回复"}
        assert agent.api_call_count == 2
        assert agent.query_count == 1
