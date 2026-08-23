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
    # Active Memory 开启时，seed 召回后若证据不足（not_searched 且 coverage<1），
    # 停答点会强制执行一轮运行时自搜；关闭时保持单次召回。
    assert len(recall_calls) == (2 if active else 1)
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
def test_seen_sources_burn_rounds_then_budget_exhausted():
    # 返回了结果但全是已见来源：不触发 no_new_evidence，继续消耗轮次直到 budget。
    builtin = object()
    responses = [
        json.dumps({
            "query": "q1", "layer": "all", "limit": 5,
            "results": [{"source": "seed", "content": "same"}],
        }),
        json.dumps({
            "query": "q2", "layer": "all", "limit": 5,
            "results": [{"source": "seed", "content": "same again"}],
        }),
    ]
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(error=lambda *args, **kwargs: None)
    agent._builtin_search_memory = builtin
    agent.tool_dispatcher = FakeDispatcher(builtin, responses)
    session = ActiveRecallSession.from_seed(
        "question", [{"source": "seed", "content": "initial"}]
    )
    messages = []

    agent._append_tool_exchange(
        messages,
        [search_call("call-1", "q1"), search_call("call-2", "q2")],
        active_session=session,
    )

    assert len(agent.tool_dispatcher.calls) == 2
    assert session.trace.stop_reason == "budget_exhausted"
    assert len(session.trace.rounds) == 2
    blocked = json.loads(messages[-1]["content"])
    assert blocked["active_memory"]["stop_reason"] == "budget_exhausted"


class ThrowingDispatcher:
    """call_tool 抛错的调度器，用于验证强制搜错误路径不炸回答。"""

    def __init__(self, tool):
        self.tools = {"search_memory": tool}
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, args))
        raise RuntimeError("search exploded")


@pytest.mark.unit
class TestForcedActiveSearch:
    """停答点强制搜的 core 层运行时行为（空结果、错误、覆盖、无 dispatcher）。"""

    def _agent(self, tool):
        agent = LightHermes.__new__(LightHermes)
        agent.logger = SimpleNamespace(error=lambda *a, **k: None)
        agent._builtin_search_memory = tool
        agent.tool_dispatcher = FakeDispatcher(tool, [])
        return agent

    def test_empty_result_still_executes_and_returns_true(self):
        builtin = object()
        agent = self._agent(builtin)
        agent.tool_dispatcher.responses = iter([
            json.dumps({"query": "q", "layer": "all", "limit": 5, "results": []})
        ])
        session = ActiveRecallSession.from_seed("question", [])

        executed = agent._forced_active_search(session, "non_stream_answer")

        assert executed is True  # 搜空也算执行：必须交回模型，不能复用停答前答句
        assert len(agent.tool_dispatcher.calls) == 1
        assert session.ledger.absence_state() == "searched_no_evidence"
        assert len(session.trace.forced_search) == 1
        followup = agent._forced_search_followup(session)
        assert "本轮检索未返回新来源" in followup

    def test_search_error_records_skip_and_returns_false(self):
        builtin = object()
        agent = LightHermes.__new__(LightHermes)
        agent.logger = SimpleNamespace(error=lambda *a, **k: None)
        agent._builtin_search_memory = builtin
        agent.tool_dispatcher = ThrowingDispatcher(builtin)
        session = ActiveRecallSession.from_seed("question", [])

        executed = agent._forced_active_search(session, "non_stream_answer")

        assert executed is False
        skips = session.trace.metadata["forced_search_skip"]
        assert skips and skips[0]["skip_reason"].startswith("search_error:")
        assert session.trace.stop_reason == "error"
        assert session.trace.forced_search == []

    def test_custom_search_tool_is_skipped_not_called(self):
        builtin = object()
        custom = object()
        agent = LightHermes.__new__(LightHermes)
        agent.logger = SimpleNamespace(error=lambda *a, **k: None)
        agent._builtin_search_memory = builtin
        # tools 里注册的是 custom，不是 builtin 本身 → 视为用户覆盖
        agent.tool_dispatcher = FakeDispatcher(custom, [])
        session = ActiveRecallSession.from_seed("question", [])

        executed = agent._forced_active_search(session, "non_stream_answer")

        assert executed is False
        assert agent.tool_dispatcher.calls == []
        skips = session.trace.metadata["forced_search_skip"]
        assert skips[0]["skip_reason"] == "no_builtin_search"

    def test_no_dispatcher_is_skipped(self):
        agent = LightHermes.__new__(LightHermes)
        agent.logger = SimpleNamespace(error=lambda *a, **k: None)
        agent._builtin_search_memory = object()
        # 不带 tool_dispatcher 属性
        session = ActiveRecallSession.from_seed("question", [])

        executed = agent._forced_active_search(session, "non_stream_answer")

        assert executed is False
        assert session.trace.metadata["forced_search_skip"][0]["skip_reason"] == "no_dispatcher"


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


def stream_stop_chunk(content="final"):
    delta = SimpleNamespace(content=content, tool_calls=None)
    choice = SimpleNamespace(delta=delta, finish_reason="stop")
    return SimpleNamespace(choices=[choice])


def _make_stream_fake_adapter(chunks):
    class StreamResponse:
        def __init__(self, chunks):
            self.chunks = chunks
        def __iter__(self):
            return iter(self.chunks)

    class Adapter:
        provider = "openai"
        def __init__(self):
            self.model = "test-model"
            self.calls = []
        def create(self, **kwargs):
            self.calls.append(kwargs)
            if isinstance(chunks, Exception):
                raise chunks
            return StreamResponse(chunks)

    return Adapter()


def _run_stream_once(agent, active_session, max_iterations=3):
    params = {
        "messages": [{"role": "system", "content": "sys"}, {"role": "user", "content": "q"}],
        "stream": True,
    }
    collected = list(
        agent._run_stream(
            params, max_iterations, "q", "user", "session", active_session
        )
    )
    return params, collected


class ScriptedAdapter:
    """按脚本顺序返回响应，并记录每次 create 的 messages，用于端到端合成场景。"""

    provider = "openai"

    def __init__(self, responses):
        self.model = "test-model"
        self.responses = list(responses)
        self.calls = []

    def create(self, messages=None, **kwargs):
        self.calls.append(messages)
        if not self.responses:
            return answer_response("")
        return self.responses.pop(0)


def answer_response(content):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content, tool_calls=None))],
        usage={"total_tokens": 3},
    )


def tool_call_response(tool_calls):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=tool_calls))],
        usage={"total_tokens": 3},
    )


def _install_scripted_adapter(agent, responses):
    adapter = ScriptedAdapter(responses)
    agent.adapter = adapter
    return adapter


@pytest.mark.unit
class TestSyntheticScenario:
    """端到端合成 case：强制搜、冲突、无新证据（假模型 + 假记忆走完整 run()）。"""

    def test_not_searched_stop_forces_search_then_model_reanswers(
        self, monkeypatch, tmp_path
    ):
        agent, _ = make_agent(monkeypatch, tmp_path, active=True)
        adapter = _install_scripted_adapter(
            agent,
            [answer_response("第一版答案"), answer_response("补充后的答案")],
        )

        result = agent.run("ordinary question", session_id="s1")

        assert result == "补充后的答案"
        assert len(adapter.calls) == 2
        # 强制搜跟进必须是 system 消息（不是伪 user），模型必须看到并改口
        followup_messages = [
            msg for msg in adapter.calls[1]
            if isinstance(msg, dict)
            and msg.get("role") == "system"
            and "本轮检索未返回新来源" in str(msg.get("content", ""))
        ]
        assert followup_messages, "强制搜跟进应以 system 角色注入"

    def test_conflict_stop_forces_search_and_hands_back_to_model(
        self, monkeypatch, tmp_path
    ):
        agent, _ = make_agent(monkeypatch, tmp_path, active=True)
        # 落盘 trace，才能断言「冲突」确实是本次强制搜的触发原因
        agent.active_recall_persist_traces = True
        agent.active_recall_trace_dir = str(tmp_path / "traces")
        adapter = _install_scripted_adapter(
            agent,
            [
                # ① 模型主动写 conflict（claim 与 seed 的初 query 一致，命中 seed claim）
                tool_call_response([judge_call("call-judge", claim="ordinary question", verdict="conflict")]),
                # ② 模型第一次回答，停答点因 conflict 被强制再搜
                answer_response("第一次回答"),
                # ③ 模型拿到强制搜结果后的最终回答
                answer_response("冲突澄清后的最终回答"),
            ],
        )

        result = agent.run("ordinary question", session_id="s1")

        assert result == "冲突澄清后的最终回答"
        # ① judge_claim 写 conflict，② 答句触发强制搜，③ 才允许收尾
        assert len(adapter.calls) == 3
        # 强制搜跟进以 system 角色出现在第二次 model 调用（③）的输入里
        followup_messages = [
            msg for msg in adapter.calls[2]
            if isinstance(msg, dict)
            and msg.get("role") == "system"
            and "本轮检索未返回新来源" in str(msg.get("content", ""))
        ]
        assert followup_messages, "强制搜跟进应以 system 角色注入"

        # 钉死触发原因：账本真是 conflict，且强制搜的 trigger_reason 来自冲突
        traces = list((tmp_path / "traces").glob("*.json"))
        assert len(traces) == 1
        trace = json.loads(traces[0].read_text(encoding="utf-8"))
        claims = trace["ledger"]["claims"]
        assert any(c["judgment"] == "conflict" for c in claims.values())
        assert trace["ledger"]["absence"] == "evidence_conflict"
        assert trace["forced_search"][0]["trigger_reason"] == "absence_evidence_conflict"

    def test_seen_sources_do_not_infinite_force(
        self, monkeypatch, tmp_path
    ):
        agent, _ = make_agent(monkeypatch, tmp_path, active=True)
        agent.active_recall_persist_traces = True
        agent.active_recall_trace_dir = str(tmp_path / "traces")
        # 记忆库里有一条和 seed 同源的语义记忆 → 强制搜返回已见来源 → 不触发 no_new_evidence
        agent.memory.save_semantic("fact", "项目采用分级记忆架构。这是关键结论。", {"type": "fact"})
        adapter = _install_scripted_adapter(
            agent,
            [answer_response("第一次回答"), answer_response("最终回答")],
        )

        result = agent.run("分级记忆架构", session_id="s1")

        # 第一轮触发强制搜（已见来源）→ 第二轮停答点 absence=unresolved 放行 → 正常收尾
        assert result == "最终回答"
        assert len(adapter.calls) == 2

        traces = list((tmp_path / "traces").glob("*.json"))
        assert len(traces) == 1
        trace = json.loads(traces[0].read_text(encoding="utf-8"))
        assert trace["stop_reason"] == "sufficient"
        assert trace["rounds"], "强制搜应记录一轮"
        assert trace["rounds"][0]["new_source_count"] == 0
        assert trace["forced_search"][0]["trigger_reason"] == "absence_not_searched"


@pytest.mark.unit
def test_stream_normal_stop_marks_active_session_sufficient(monkeypatch, tmp_path):
    """流式正常结束（finish_reason=stop，无工具调用）应把 trace 标记为 sufficient 而非 cancelled。"""
    stream_adapter = _make_stream_fake_adapter([stream_stop_chunk("done")])
    agent = LightHermes.__new__(LightHermes)
    agent.logger = SimpleNamespace(
        warning=lambda *a, **k: None, info=lambda *a, **k: None, error=lambda *a, **k: None
    )
    agent.adapter = stream_adapter
    agent.model = "test-model"
    agent.fallback_models = []
    agent.api_call_count = 0
    agent.memory_enabled = False
    agent.memory = None
    agent.evolution_enabled = False
    agent.evolution = None
    agent.query_count = 0
    agent.auto_generate_skills = False
    agent._run_memory_hook = lambda *a, **k: None
    agent._classify_task = lambda q: "通用"
    agent.active_recall_persist_traces = True
    agent.active_recall_trace_dir = str(tmp_path)
    agent._finish_turn = LightHermes._finish_turn.__get__(agent)

    session = ActiveRecallSession.from_seed("q", [])
    params, collected = _run_stream_once(agent, session)

    assert collected == ["done"]
    assert session.trace.stop_reason == "sufficient"
    # 流式结束后 finally 不应把 sufficient 覆盖成 cancelled
    assert session.trace.stop_reason == "sufficient"
