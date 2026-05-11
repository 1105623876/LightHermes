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
        assert agent.memory.kwargs["semantic_max_entries"] == 123
        assert agent.memory.kwargs["semantic_max_chars"] == 4567
        assert agent.memory.kwargs["semantic_similarity_threshold"] == 0.75
        assert agent.memory.kwargs["distill_recent_limit"] == 8

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
        calls = []

        def fake_call_api(**kwargs):
            calls.append(kwargs)
            return iter([Chunk()])

        agent._call_api_with_fallback = fake_call_api

        chunks = list(agent._run_stream({"messages": [], "stream": True}, max_iterations=10))

        assert chunks == ["测试回复"]
        assert len(calls) == 1

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
