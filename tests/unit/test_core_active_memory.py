import json
from types import SimpleNamespace

import pytest

from lighthermes.active_memory import ActiveRecallSession
from lighthermes.core import LightHermes


def judge_call(call_id, claim="问题", verdict="support", source_ids=None, confidence=None):
    args = {"claim": claim, "verdict": verdict}
    if source_ids is not None:
        args["source_ids"] = source_ids
    if confidence is not None:
        args["confidence"] = confidence
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": "judge_claim", "arguments": json.dumps(args, ensure_ascii=False)},
    }


class FakeAdapter:
    provider = "openai"

    def __init__(self):
        self.model = "test-model"
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        message = SimpleNamespace(content="done", tool_calls=None)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=message)],
            usage={"total_tokens": 3},
        )


class FakeSkillLoader:
    def __init__(self, *args, **kwargs):
        pass

    def match_skill(self, query):
        return None

    def recall_failure_reports(self, query, task_type, limit=2):
        return []

    def load_all(self):
        return None


class FakeDispatcher:
    def __init__(self, tool, responses):
        self.tools = {"search_memory": tool}
        self.responses = iter(responses)
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        return next(self.responses)


def make_agent(monkeypatch, tmp_path, *, active):
    adapter = FakeAdapter()
    monkeypatch.setattr("lighthermes.core.get_adapter", lambda **kwargs: adapter)
    monkeypatch.setattr("lighthermes.core.SkillLoader", FakeSkillLoader)
    config = {
        "memory": {
            "active_recall": {
                "enabled": active,
                "max_rounds": 99,
                "persist_traces": False,
                "trace_dir": str(tmp_path / "traces"),
            },
            "hybrid_retrieval": {"enabled": False},
        },
        "context_compression": {"enabled": False},
        "tools": {
            "builtin": {
                "enabled": True,
                "memory_search": True,
                "file_read": False,
                "file_search": False,
                "file_write": False,
            }
        },
    }
    agent = LightHermes(
        name="test-agent",
        role="test-role",
        model="test-model",
        provider="openai",
        api_key="test-key",
        memory_dir=str(tmp_path / "memory"),
        evolution_enabled=False,
        config=config,
    )
    return agent, adapter


def search_call(call_id, query="question", layer="all", limit=5):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "search_memory",
            "arguments": json.dumps(
                {"query": query, "layer": layer, "limit": limit},
                ensure_ascii=False,
            ),
        },
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("active", "expected_prompt"),
    [(False, False), (True, True)],
)
def test_active_recall_config_prompt_and_single_seed_recall(
    monkeypatch, tmp_path, active, expected_prompt
):
    agent, adapter = make_agent(monkeypatch, tmp_path, active=active)
    original_recall_items = agent.memory.recall_items
    recall_calls = []

    def counted_recall(*args, **kwargs):
        recall_calls.append((args, kwargs))
        return original_recall_items(*args, **kwargs)

    agent.memory.recall_items = counted_recall
    assert agent.run("ordinary question", session_id="session-1") == "done"

    system_prompt = adapter.calls[0]["messages"][0]["content"]
    assert ("Active Memory 规则" in system_prompt) is expected_prompt
    assert len(recall_calls) == 1
    assert agent.active_recall_max_rounds == 2
    assert not (tmp_path / "traces").exists()


@pytest.mark.unit
def test_active_seed_falls_back_for_legacy_memory_hook():
    calls = []

    class LegacyMemory:
        def on_turn_start(self, query, user_id="default", session_id=""):
            calls.append((query, user_id, session_id))
            return "legacy context"

    agent = LightHermes.__new__(LightHermes)
    agent.active_recall_enabled = True
    agent.memory_enabled = True
    agent.memory = LegacyMemory()
    agent.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    agent._run_memory_hook = lambda name, *args, **kwargs: getattr(
        agent.memory, name
    )(*args, **kwargs)

    context, items = agent._get_active_memory_seed("q", "u", "s")

    assert context == "legacy context"
    assert items == []
    assert calls == [("q", "u", "s")]


@pytest.mark.unit
def test_builtin_search_stops_after_two_rounds_without_third_dispatch():
    builtin = object()
    responses = [
        json.dumps({"query": "q1", "layer": "all", "limit": 5, "results": [
            {"source": "s1", "content": "one"}
        ]}),
        json.dumps({"query": "q2", "layer": "all", "limit": 5, "results": [
            {"source": "s2", "content": "two"}
        ]}),
    ]
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_search_memory = builtin
    agent.tool_dispatcher = FakeDispatcher(builtin, responses)
    session = ActiveRecallSession.from_seed("question", [], max_rounds=2)
    messages = []

    recorded = agent._append_tool_exchange(
        messages,
        [
            search_call("call-1", "q1"),
            search_call("call-2", "q2"),
            search_call("call-3", "q3", layer="invalid", limit="bad"),
        ],
        active_session=session,
    )

    assert len(recorded) == 3
    assert len(agent.tool_dispatcher.calls) == 2
    assert session.trace.stop_reason == "budget_exhausted"
    assert len(session.trace.rounds) == 2
    blocked = json.loads(messages[-1]["content"])
    assert blocked["results"] == []
    assert blocked["layer"] == "all"
    assert blocked["limit"] == 5
    assert blocked["active_memory"]["search_allowed"] is False
    assert blocked["active_memory"]["stop_reason"] == "budget_exhausted"
    assert "suggested_query" in blocked["active_memory"]
    assert "absence" in blocked["active_memory"]


@pytest.mark.unit
def test_no_new_evidence_stops_and_blocks_next_search():
    builtin = object()
    response = json.dumps({
        "query": "q1",
        "layer": "all",
        "limit": 5,
        "results": [{"source": "seed", "content": "same"}],
    })
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_search_memory = builtin
    agent.tool_dispatcher = FakeDispatcher(builtin, [response])
    session = ActiveRecallSession.from_seed(
        "question", [{"source": "seed", "content": "initial"}]
    )
    messages = []

    agent._append_tool_exchange(
        messages,
        [search_call("call-1", "q1"), search_call("call-2", "q2")],
        active_session=session,
    )

    assert len(agent.tool_dispatcher.calls) == 1
    assert session.trace.stop_reason == "no_new_evidence"
    assert len(session.trace.rounds) == 1
    blocked = json.loads(messages[-1]["content"])
    assert blocked["active_memory"]["stop_reason"] == "no_new_evidence"


@pytest.mark.unit
def test_custom_search_memory_is_not_observed_or_blocked():
    builtin = object()
    custom = object()
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_search_memory = builtin
    agent.tool_dispatcher = FakeDispatcher(custom, ["custom response"])
    session = ActiveRecallSession.from_seed("question", [])
    session.mark_budget_exhausted()
    messages = []

    agent._append_tool_exchange(
        messages,
        [search_call("call-1")],
        active_session=session,
    )

    assert len(agent.tool_dispatcher.calls) == 1
    assert messages[-1]["content"] == "custom response"
    assert session.trace.rounds == []
    assert session.trace.stop_reason == "budget_exhausted"


def read_call(call_id, source="working:s1", expand_adjacent=True):
    return {
        "id": call_id,
        "type": "function",
        "function": {
            "name": "read_memory",
            "arguments": json.dumps(
                {"source": source, "expand_adjacent": expand_adjacent},
                ensure_ascii=False,
            ),
        },
    }


@pytest.mark.unit
def test_builtin_read_is_observed_without_consuming_search_budget():
    builtin_search = object()
    builtin_read = object()
    response = json.dumps({
        "source": "working:s1",
        "found": True,
        "reason": "",
        "adjacent": [{"source": "working:s0"}],
    })
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_search_memory = builtin_search
    agent._builtin_read_memory = builtin_read
    agent.tool_dispatcher = FakeDispatcher(builtin_read, [response])
    agent.tool_dispatcher.tools["read_memory"] = builtin_read
    session = ActiveRecallSession.from_seed("question", [])
    messages = []

    agent._append_tool_exchange(
        messages,
        [read_call("call-read")],
        active_session=session,
    )

    assert session.can_search()
    assert session.trace.stop_reason is None
    assert session.trace.rounds == []
    assert session.trace.reads[0].source == "working:s1"
    assert session.trace.reads[0].adjacent_ids == ["working:s0"]


@pytest.mark.unit
def test_active_prompt_mentions_read_memory_when_builtin_registered(
    monkeypatch, tmp_path
):
    agent, adapter = make_agent(monkeypatch, tmp_path, active=True)
    assert agent.run("ordinary question", session_id="session-1") == "done"
    system_prompt = adapter.calls[0]["messages"][0]["content"]
    assert "read_memory" in system_prompt
    assert "不计入搜索轮次" in system_prompt


@pytest.mark.unit
def test_stream_close_persists_cancelled_trace(tmp_path):
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    agent.active_recall_persist_traces = True
    agent.active_recall_trace_dir = str(tmp_path)

    def fake_stream_impl(*args):
        yield "first"
        yield "second"

    agent._run_stream_impl = fake_stream_impl
    session = ActiveRecallSession.from_seed("question", [])
    stream = agent._run_stream({}, 1, "question", "user", "session", session)

    assert next(stream) == "first"
    stream.close()

    assert session.trace.stop_reason == "cancelled"
    traces = list(tmp_path.glob("*.json"))
    assert len(traces) == 1
    assert json.loads(traces[0].read_text(encoding="utf-8"))["stop_reason"] == "cancelled"


@pytest.mark.unit
def test_stream_error_persists_error_trace(tmp_path):
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(warning=lambda *args, **kwargs: None)
    agent.active_recall_persist_traces = True
    agent.active_recall_trace_dir = str(tmp_path)

    def failing_stream_impl(*args):
        if False:
            yield ""
        raise RuntimeError("stream failed")

    agent._run_stream_impl = failing_stream_impl
    session = ActiveRecallSession.from_seed("question", [])

    with pytest.raises(RuntimeError, match="stream failed"):
        list(agent._run_stream({}, 1, "question", "user", "session", session))

    assert session.trace.stop_reason == "error"
    traces = list(tmp_path.glob("*.json"))
    assert len(traces) == 1
    assert json.loads(traces[0].read_text(encoding="utf-8"))["stop_reason"] == "error"


def make_judge_dispatcher(judge_tool):
    dispatcher = SimpleNamespace(tools={"judge_claim": judge_tool})
    return dispatcher


@pytest.mark.unit
def test_judge_claim_intercepted_writes_ledger_and_trace():
    judge_tool = object()
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_judge_claim = judge_tool
    agent.tool_dispatcher = make_judge_dispatcher(judge_tool)
    session = ActiveRecallSession.from_seed("部署服务器", [])
    messages = []

    # 先检索一次，让 searched=True，验证读取后 judgment 区分“已检索”
    session.observe_search("部署", "all", 5, [{"source": "s1", "content": "证据"}], 1.0)

    agent._append_tool_exchange(
        messages,
        [judge_call("call-judge", claim="部署服务器", verdict="no_evidence", source_ids=["s1"], confidence=0.4)],
        active_session=session,
    )

    assert len(messages) == 2  # assistant tool_call 帧 + tool 结果
    payload = json.loads(messages[-1]["content"])
    assert payload["accepted"] is True
    assert payload["verdict"] == "no_evidence"
    assert payload["active_memory"]["judged"] is True
    assert payload["active_memory"]["searched"] is True
    assert len(session.trace.judgments) == 1
    assert session.trace.judgments[0].verdict == "no_evidence"
    assert session.trace.judgments[0].searched is True
    claim = next(iter(session.ledger.claims.values()))
    assert claim.judgment == "no_evidence"


@pytest.mark.unit
def test_judge_claim_no_evidence_before_search_is_rejected():
    judge_tool = object()
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_judge_claim = judge_tool
    agent.tool_dispatcher = make_judge_dispatcher(judge_tool)
    session = ActiveRecallSession.from_seed("部署服务器", [])
    messages = []

    agent._append_tool_exchange(
        messages,
        [judge_call("call-judge", claim="部署服务器", verdict="no_evidence")],
        active_session=session,
    )

    payload = json.loads(messages[-1]["content"])
    assert payload["accepted"] is False
    assert payload["reason"] == "not_searched"
    assert payload["active_memory"]["absence"] == "not_searched"
    assert session.trace.judgments == []


def test_judge_claim_invalid_verdict_is_rejected():
    judge_tool = object()
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_judge_claim = judge_tool
    agent.tool_dispatcher = make_judge_dispatcher(judge_tool)
    session = ActiveRecallSession.from_seed("部署服务器", [])
    messages = []

    agent._append_tool_exchange(
        messages,
        [judge_call("call-judge", claim="部署服务器", verdict="bogus")],
        active_session=session,
    )

    payload = json.loads(messages[-1]["content"])
    assert payload["accepted"] is False
    assert payload["verdict"] == "bogus"
    assert payload["reason"] == "invalid_verdict"
    assert session.trace.judgments == []
    assert next(iter(session.ledger.claims.values())).judgment is None


@pytest.mark.unit
def test_judge_claim_not_registered_when_active_memory_off(monkeypatch, tmp_path):
    agent, adapter = make_agent(monkeypatch, tmp_path, active=False)
    assert agent.run("question", session_id="s") == "done"
    schemas = agent.tool_dispatcher.get_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "judge_claim" not in names
    assert getattr(agent, "_builtin_judge_claim", None) is None
    system_prompt = adapter.calls[0]["messages"][0]["content"]
    assert "judge_claim" not in system_prompt


@pytest.mark.unit
def test_judge_claim_registered_and_prompted_when_active_memory_on(monkeypatch, tmp_path):
    agent, adapter = make_agent(monkeypatch, tmp_path, active=True)
    assert agent.run("question", session_id="s") == "done"
    schemas = agent.tool_dispatcher.get_tool_schemas()
    names = [s["function"]["name"] for s in schemas]
    assert "judge_claim" in names
    system_prompt = adapter.calls[0]["messages"][0]["content"]
    assert "judge_claim" in system_prompt
    assert "尚未检索到" in system_prompt
