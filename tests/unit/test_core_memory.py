"""核心记忆集成测试"""
import os

import pytest

from lighthermes.core import LightHermes
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
class TestCoreMemoryIntegration:
    """测试核心流程中的记忆集成"""

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

    def test_hybrid_retrieval_config_passed_to_memory_manager(self, temp_memory_dir, monkeypatch):
        """测试混合检索配置传入记忆管理器"""
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
memory:
  hybrid_retrieval:
    enabled: true
    provider: local
    model: test-embedding
    api_key: test-key
context_compression:
  enabled: false
""")
            return original_open(path, *args, **kwargs)

        class FakeMemoryManager:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        monkeypatch.setattr("lighthermes.core.os.path.exists", fake_exists)
        monkeypatch.setattr("builtins.open", fake_open)
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
        assert agent.memory.kwargs["embedding_provider"] == "local"
        assert agent.memory.kwargs["embedding_model"] == "test-embedding"
        assert agent.memory.kwargs["api_key"] == "test-key"

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
