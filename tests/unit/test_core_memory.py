"""核心记忆集成测试"""
import os

import pytest

from lighthermes.core import LightHermes
from lighthermes.memory import MemoryManager


class FakeAdapter:
    def create(self, **kwargs):
        raise AssertionError("测试不应调用真实模型")


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
