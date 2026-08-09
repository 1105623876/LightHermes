import json

import pytest

from lighthermes.active_memory import (
    ActiveRecallSession,
    EvidenceLedger,
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

    def test_no_new_evidence_and_answered_cancelled(self):
        session = ActiveRecallSession.from_seed("问题", [{"source": "s1"}])
        session.observe_search("问题", "all", 5, [{"source": "s1"}], 1)
        assert session.trace.stop_reason == "no_new_evidence"

        answered = ActiveRecallSession.from_seed("问题", [])
        answered.mark_answered()
        answered.mark_cancelled()
        assert answered.trace.stop_reason == "sufficient"

        cancelled = ActiveRecallSession.from_seed("问题", [])
        cancelled.mark_cancelled()
        assert cancelled.trace.stop_reason == "cancelled"

    def test_error_and_atomic_json_persistence(self, tmp_path):
        session = ActiveRecallSession.from_seed("问题", [], metadata={"session_id": "s1"})
        session.observe_search("问题", "all", 5, [], 2, error="bad response")
        assert session.trace.stop_reason == "error"

        target = session.persist(tmp_path)
        assert target is not None and target.exists()
        payload = json.loads(target.read_text(encoding="utf-8"))
        assert payload["trace_id"] == session.trace.trace_id
        assert payload["metadata"]["session_id"] == "s1"
        assert not list(tmp_path.glob("*.tmp"))
