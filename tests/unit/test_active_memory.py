import json

import pytest

from lighthermes.active_memory import (
    ActiveRecallSession,
    EvidenceLedger,
    JUDGMENT_VERDICTS,
    MemoryRecord,
)


@pytest.mark.unit
class TestMemoryRecord:
    def test_maps_legacy_item_and_stabilizes_missing_source(self):
        item = {"layer": "semantic", "name": "pref", "content": "中文回复", "score": "bad"}
        record = MemoryRecord.from_memory_item(item)

        assert record.abstract == "中文回复"
        assert record.record_id.startswith("memory:")
        assert record.source_ids == [record.record_id]
        assert record.score == 0.0
        assert record.record_id == MemoryRecord.from_memory_item(item).record_id

    def test_does_not_mutate_item_and_maps_source(self):
        item = {"layer": "semantic", "name": "pref", "content": "中文", "source": "semantic:pref"}
        before = dict(item)
        record = MemoryRecord.from_memory_item(item)

        assert item == before
        assert record.record_id == "semantic:pref"
        assert record.source_ids == ["semantic:pref"]


@pytest.mark.unit
class TestEvidenceLedger:
    def test_deduplicates_sources_and_only_support_resolves_claim(self):
        ledger = EvidenceLedger.for_query("问题")
        record = MemoryRecord.from_memory_item({"source": "s1", "content": "证据"})

        assert ledger.add_candidates([record, record]) == ["s1"]
        claim_id = next(iter(ledger.claims))
        ledger.mark_conflicting(claim_id, ["s1"])
        assert ledger.coverage == 0
        assert ledger.claims[claim_id].resolved is False
        ledger.mark_supporting(claim_id, ["s1"])
        assert ledger.coverage == 1


@pytest.mark.unit
class TestClaimJudgmentProtocol:
    def test_record_judgment_support_conflict_unknown_no_evidence(self):
        ledger = EvidenceLedger.for_query("部署服务器")

        assert ledger.record_judgment("部署服务器", "invalid") is False
        assert {c for c in ("support", "conflict", "unknown", "no_evidence")} == JUDGMENT_VERDICTS

        claim_id = next(iter(ledger.claims))
        assert ledger.record_judgment(claim_id, "support", ["s1"], 0.9)
        claim = ledger.claims[claim_id]
        assert claim.judgment == "support"
        assert claim.resolved is True
        assert claim.supporting_sources == ["s1"]
        assert claim.confidence == 0.9

        assert ledger.record_judgment(claim_id, "conflict", ["s2"])
        claim = ledger.claims[claim_id]
        assert claim.conflicting_sources == ["s2"]
        assert claim.supporting_sources == ["s1"]
        assert claim.resolved is False
        assert claim.judgment == "conflict"
        assert ledger.absence_state() == "evidence_conflict"

        assert ledger.record_judgment(claim_id, "unknown")
        assert ledger.claims[claim_id].resolved is False
        assert ledger.claims[claim_id].judgment == "unknown"

        ledger.mark_searched()
        assert ledger.record_judgment(claim_id, "no_evidence")
        assert ledger.claims[claim_id].resolved is True
        assert ledger.claims[claim_id].judgment == "no_evidence"

    def test_record_judgment_maps_paraphrase_and_id_to_single_seed(self):
        ledger = EvidenceLedger.for_query("A 项目的部署")
        claim_id = next(iter(ledger.claims))
        assert ledger.record_judgment("部署环境是哪台机器", "support", ["s1"]) is True
        assert len(ledger.claims) == 1
        claim = ledger.claims[claim_id]
        assert claim.claim == "A 项目的部署"
        assert claim.supporting_sources == ["s1"]
        assert ledger.record_judgment(claim_id, "unknown") is True
        assert claim.resolved is False

    def test_unresolved_claims_and_cue_anchors(self):
        ledger = EvidenceLedger.for_query("部署")
        ledger.add_candidates([
            MemoryRecord.from_memory_item({"source": "s1", "content": "x", "cue_anchors": ["服务器"]}),
        ])
        claim_id = next(iter(ledger.claims))
        assert ledger.unresolved_claims() == ["部署"]
        assert ledger.all_cue_anchors() == ["服务器"]
        ledger.record_judgment(claim_id, "support", ["s1"])
        assert ledger.unresolved_claims() == []

    def test_searched_flag_distinguishes_searched_vs_not(self):
        ledger = EvidenceLedger.for_query("q")
        claim_id = next(iter(ledger.claims))
        assert ledger.absence_state() == "not_searched"
        assert ledger.record_judgment(claim_id, "no_evidence") is False
        assert ledger.claims[claim_id].judgment is None
        ledger.mark_searched()
        assert ledger.record_judgment(claim_id, "no_evidence") is True
        assert ledger.claims[claim_id].searched is True
        assert ledger.absence_state() == "searched_no_evidence"

    def test_multiple_claims_do_not_create_on_unknown_text(self):
        ledger = EvidenceLedger.for_query("第一个问题")
        ledger.resolve_claim_id("第二个问题", create=True)
        assert len(ledger.claims) == 2
        assert ledger.record_judgment("完全无关的改写", "support", ["s1"]) is False


@pytest.mark.unit
class TestQueryRewrite:
    def test_rewrite_built_from_unresolved_claims_and_anchors(self, tmp_path):
        session = ActiveRecallSession.from_seed(
            "项目部署到哪台服务器",
            [{"source": "s0", "content": "部署主题", "cue_anchors": ["服务器"]}],
        )
        session.observe_search(
            "服务器部署", "all", 5,
            [{"source": "s1", "content": "候选证据", "cue_anchors": ["部署", "环境"]}],
            1.0,
        )
        rewritten = session.build_rewrite_query()
        assert rewritten
        assert "部署" in rewritten
        assert "服务器" in rewritten
        # rewrite 也被记录进 trace
        assert session.trace.rewrites
        assert session.trace.rewrites[0]["rewritten_query"] == rewritten

    def test_rewrite_empty_when_no_unresolved(self):
        session = ActiveRecallSession.from_seed("q", [{"source": "s1"}])
        session.observe_judgment("q", "support", ["s1"])
        assert session.build_rewrite_query() == ""
        assert session.trace.rewrites == []


@pytest.mark.unit
class TestForceSearchTrigger:
    """停答点确定性 trigger：absence ∈ {not_searched, evidence_conflict} ∧ coverage < 1。"""

    def test_not_searched_and_unresolved_forces(self):
        ledger = EvidenceLedger.for_query("问题")
        assert ledger.coverage == 0
        assert ledger.absence_state() == "not_searched"
        assert ledger.should_force_search(can_search=True) == (True, "absence_not_searched")

    def test_searched_no_evidence_does_not_force(self):
        ledger = EvidenceLedger.for_query("问题")
        ledger.mark_searched()
        assert ledger.absence_state() == "searched_no_evidence"
        assert ledger.should_force_search(can_search=True)[0] is False

    def test_conflict_forces(self):
        ledger = EvidenceLedger.for_query("问题")
        claim_id = next(iter(ledger.claims))
        ledger.mark_conflicting(claim_id, ["s1"])
        assert ledger.absence_state() == "evidence_conflict"
        assert ledger.coverage == 0
        assert ledger.should_force_search(can_search=True) == (True, "absence_evidence_conflict")

    def test_coverage_complete_does_not_force_even_unknown_absence(self):
        ledger = EvidenceLedger.for_query("问题")
        claim_id = next(iter(ledger.claims))
        ledger.mark_supporting(claim_id, ["s1"])
        assert ledger.coverage == 1
        assert ledger.should_force_search(can_search=True) == (False, "coverage_complete")

    def test_no_budget_does_not_force(self):
        ledger = EvidenceLedger.for_query("问题")
        assert ledger.should_force_search(can_search=False) == (False, None)

    def test_seed_unresolved_alone_does_not_force_when_searched(self):
        # 反例：seed 默认 unresolved，但已检索无证据时禁止强制搜（避免“每题多搜一轮”）。
        ledger = EvidenceLedger.for_query("问题")
        ledger.mark_searched()
        ledger.record_judgment(next(iter(ledger.claims)), "no_evidence")
        assert ledger.absence_state() == "searched_no_evidence"
        assert ledger.coverage == 1  # no_evidence resolves the claim
        assert ledger.should_force_search(can_search=True)[0] is False


@pytest.mark.unit
class TestObserveJudgment:
    def test_observe_judgment_writes_trace_judgments(self, tmp_path):
        session = ActiveRecallSession.from_seed("部署", [])
        assert session.observe_judgment("部署", "unknown") is True
        assert len(session.trace.judgments) == 1
        assert session.trace.judgments[0].verdict == "unknown"
        assert session.trace.judgments[0].searched is False

        target = session.persist(tmp_path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["judgments"][0]["verdict"] == "unknown"


@pytest.mark.unit
class TestActiveRecallSession:
    def test_seed_does_not_consume_round_budget_and_two_searches_stop(self, tmp_path):
        session = ActiveRecallSession.from_seed(
            "问题", [{"source": "seed", "content": "初始"}], max_rounds=2
        )
        assert session.can_search()
        assert len(session.trace.rounds) == 0

        assert session.observe_search(
            "问题", "all", 5, [{"source": "s1", "content": "一"}], 1.2
        )
        assert session.can_search()
        assert session.observe_search(
            "问题", "all", 5, [{"source": "s2", "content": "二"}], 1.3
        )
        assert session.trace.stop_reason == "budget_exhausted"
        assert session.trace.rounds[0].candidate_scores == {"s1": 0.0}
        snapshot = session.to_dict()
        assert len(snapshot["rounds"]) == 2
        assert session.observe_search("问题", "all", 5, [{"source": "s3"}], 1) is False
        assert len(session.trace.rounds) == 2

    def test_zero_results_stops_and_answered_cancelled(self):
        session = ActiveRecallSession.from_seed("问题", [{"source": "s1"}])
        session.observe_search("问题", "all", 5, [], 1)
        assert session.trace.stop_reason == "no_new_evidence"

        answered = ActiveRecallSession.from_seed("问题", [])
        answered.mark_answered()
        answered.mark_cancelled()
        assert answered.trace.stop_reason == "sufficient"

        cancelled = ActiveRecallSession.from_seed("问题", [])
        cancelled.mark_cancelled()
        assert cancelled.trace.stop_reason == "cancelled"

    def test_seen_sources_do_not_stop_no_new_evidence(self):
        # 返回了结果但全是已见来源：不算「无证据」，不应停止，让 max_rounds 自然收口。
        session = ActiveRecallSession.from_seed("问题", [{"source": "s1"}], max_rounds=2)
        session.observe_search("问题", "all", 5, [{"source": "s1", "content": "已见"}], 1)
        assert session.trace.stop_reason is None
        assert session.can_search() is True

    def test_error_and_atomic_json_persistence(self, tmp_path):
        session = ActiveRecallSession.from_seed("问题", [], metadata={"session_id": "s1"})
        session.observe_search("问题", "all", 5, [], 2, error="bad response")
        assert session.trace.stop_reason == "error"

        target = session.persist(tmp_path)
        assert target is not None and target.exists()
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["trace_id"] == session.trace.trace_id
        assert payload["metadata"]["session_id"] == "s1"
        assert payload["reads"] == []
        assert not list(tmp_path.glob("*.tmp"))

    def test_observe_read_does_not_consume_search_budget(self):
        session = ActiveRecallSession.from_seed("问题", [])
        assert session.observe_read("working:s1", found=True, adjacent_ids=["working:s0"], latency_ms=3)
        assert session.can_search()
        assert session.trace.stop_reason is None
        assert session.ledger.searched is True
        assert session.trace.reads[0].source == "working:s1"
        assert session.trace.reads[0].adjacent_ids == ["working:s0"]
        assert len(session.trace.rounds) == 0
