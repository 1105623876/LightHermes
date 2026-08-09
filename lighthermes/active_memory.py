"""Per-turn active memory state and trace contracts."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


STOP_REASONS = {
    "sufficient", "no_new_evidence", "budget_exhausted", "disabled", "error", "cancelled"
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_id(layer: str, name: str, content: str) -> str:
    normalized = " ".join(f"{layer}:{name}:{content}".split()).lower()
    return "memory:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()[:16]


@dataclass
class MemoryRecord:
    record_id: str
    abstract: str
    raw_source: str
    source_ids: list[str]
    cue_anchors: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    event_time: str | None = None
    status: str = "current"
    confidence: float = 1.0
    last_verified: str | None = None
    supersedes: list[str] = field(default_factory=list)
    layer: str = ""
    name: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_memory_item(cls, item: dict[str, Any] | Any) -> "MemoryRecord":
        item = item if isinstance(item, dict) else {}
        metadata = item.get("metadata") or {}
        metadata = dict(metadata) if isinstance(metadata, dict) else {}
        layer = str(item.get("layer", ""))
        name = str(item.get("name", ""))
        abstract = str(item.get("abstract", item.get("content", "")) or "")
        source = str(item.get("source", "") or metadata.get("source", "") or "")
        record_id = str(item.get("record_id", "") or source or "") or _stable_id(layer, name, abstract)
        source_ids = item.get("source_ids") or metadata.get("source_ids") or []
        if isinstance(source_ids, str):
            source_ids = [source_ids]
        source_ids = [str(source_id) for source_id in source_ids if source_id]
        if source and source not in source_ids:
            source_ids.insert(0, source)
        if not source_ids:
            source_ids = [record_id]

        def list_value(key: str) -> list[str]:
            value = item.get(key, metadata.get(key, []))
            if isinstance(value, str):
                return [value] if value else []
            return [str(entry) for entry in (value or []) if entry]

        confidence = item.get("confidence", metadata.get("confidence", 1.0))
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 1.0

        score = item.get("score", 0)
        try:
            score = float(score or 0)
        except (TypeError, ValueError):
            score = 0.0

        return cls(
            record_id=record_id,
            abstract=abstract,
            raw_source=str(item.get("raw_source", source or abstract) or ""),
            source_ids=list(dict.fromkeys(source_ids)),
            cue_anchors=list_value("cue_anchors"),
            entities=list_value("entities"),
            event_time=item.get("event_time", metadata.get("event_time")),
            status=str(item.get("status", metadata.get("status", "current")) or "current"),
            confidence=confidence,
            last_verified=item.get("last_verified", metadata.get("last_verified")),
            supersedes=list_value("supersedes"),
            layer=layer,
            name=name,
            score=score,
            metadata=metadata,
        )


@dataclass
class ClaimEvidence:
    claim_id: str
    claim: str
    candidate_sources: list[str] = field(default_factory=list)
    supporting_sources: list[str] = field(default_factory=list)
    conflicting_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    resolved: bool = False


@dataclass
class EvidenceLedger:
    claims: dict[str, ClaimEvidence] = field(default_factory=dict)
    seen_sources: set[str] = field(default_factory=set)

    @classmethod
    def for_query(cls, query: str) -> "EvidenceLedger":
        claim_id = "claim:" + hashlib.sha256(query.strip().encode("utf-8")).hexdigest()[:16]
        return cls(claims={claim_id: ClaimEvidence(claim_id=claim_id, claim=query)})

    def add_candidates(self, records: Iterable[MemoryRecord]) -> list[str]:
        records = list(records)
        new_sources: list[str] = []
        for record in records:
            for source_id in record.source_ids or [record.record_id]:
                if source_id not in self.seen_sources:
                    self.seen_sources.add(source_id)
                    new_sources.append(source_id)
        source_ids = [source for record in records for source in record.source_ids]
        for claim in self.claims.values():
            claim.candidate_sources = list(dict.fromkeys(claim.candidate_sources + source_ids))
        return new_sources

    def mark_supporting(self, claim_id: str, source_ids: Iterable[str], confidence: float = 1.0):
        claim = self.claims[claim_id]
        claim.supporting_sources = list(dict.fromkeys(claim.supporting_sources + list(source_ids)))
        claim.confidence = float(confidence)
        claim.resolved = True

    def mark_conflicting(self, claim_id: str, source_ids: Iterable[str], confidence: float = 0.0):
        claim = self.claims[claim_id]
        claim.conflicting_sources = list(dict.fromkeys(claim.conflicting_sources + list(source_ids)))
        claim.confidence = float(confidence)
        claim.resolved = False

    @property
    def coverage(self) -> float:
        if not self.claims:
            return 0.0
        return sum(claim.resolved for claim in self.claims.values()) / len(self.claims)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": {claim_id: asdict(claim) for claim_id, claim in self.claims.items()},
            "seen_sources": sorted(self.seen_sources),
            "coverage": self.coverage,
        }


@dataclass
class RecallRoundTrace:
    round_index: int
    query: str
    layer: str
    limit: int
    candidate_ids: list[str]
    candidate_scores: dict[str, float]
    accepted_source_ids: list[str]
    new_source_count: int
    latency_ms: float
    degraded: bool = False
    error: str | None = None


@dataclass
class RecallTrace:
    trace_id: str
    initial_query: str
    max_rounds: int
    rounds: list[RecallRoundTrace]
    stop_reason: str | None
    started_at: str
    finished_at: str | None
    metadata: dict[str, Any]
    ledger: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class ActiveRecallSession:
    def __init__(self, trace: RecallTrace, ledger: EvidenceLedger):
        self.trace = trace
        self.ledger = ledger

    @classmethod
    def from_seed(
        cls,
        query: str,
        items: Iterable[dict[str, Any]] | None,
        max_rounds: int = 2,
        metadata: dict[str, Any] | None = None,
    ) -> "ActiveRecallSession":
        try:
            max_rounds = max(1, min(int(max_rounds), 2))
        except (TypeError, ValueError):
            max_rounds = 2
        ledger = EvidenceLedger.for_query(query)
        session = cls(RecallTrace(
            trace_id=uuid.uuid4().hex,
            initial_query=query,
            max_rounds=max_rounds,
            rounds=[],
            stop_reason=None,
            started_at=_now(),
            finished_at=None,
            metadata=dict(metadata or {}),
        ), ledger)
        session._ingest_seed(items or [])
        return session

    def _ingest_seed(self, items: Iterable[dict[str, Any]]):
        self.ledger.add_candidates(MemoryRecord.from_memory_item(item) for item in items)
        self.trace.ledger = self.ledger.to_dict()

    def can_search(self) -> bool:
        return self.trace.stop_reason is None and len(self.trace.rounds) < self.trace.max_rounds

    def observe_search(
        self,
        query: str,
        layer: str,
        limit: int,
        items: Iterable[dict[str, Any]] | None,
        latency_ms: float,
        degraded: bool = False,
        error: str | None = None,
    ) -> bool:
        if not self.can_search():
            return False
        records = [MemoryRecord.from_memory_item(item) for item in (items or [])]
        candidate_ids = [record.record_id for record in records]
        candidate_scores = {record.record_id: record.score for record in records}
        accepted_source_ids = self.ledger.add_candidates(records)
        try:
            safe_limit = int(limit)
        except (TypeError, ValueError):
            safe_limit = 5
        try:
            safe_latency_ms = float(latency_ms)
        except (TypeError, ValueError):
            safe_latency_ms = 0.0
        self.trace.rounds.append(RecallRoundTrace(
            round_index=len(self.trace.rounds) + 1,
            query=query,
            layer=layer,
            limit=safe_limit,
            candidate_ids=candidate_ids,
            candidate_scores=candidate_scores,
            accepted_source_ids=accepted_source_ids,
            new_source_count=len(accepted_source_ids),
            latency_ms=safe_latency_ms,
            degraded=bool(degraded),
            error=error,
        ))
        self.trace.ledger = self.ledger.to_dict()
        if error:
            self._stop("error")
        elif not accepted_source_ids:
            self._stop("no_new_evidence")
        elif len(self.trace.rounds) >= self.trace.max_rounds:
            self._stop("budget_exhausted")
        return True

    def mark_answered(self):
        if self.trace.stop_reason is None:
            self._stop("sufficient")

    def mark_cancelled(self):
        if self.trace.stop_reason is None:
            self._stop("cancelled")

    def mark_budget_exhausted(self):
        self._stop("budget_exhausted")

    def mark_error(self):
        self._stop("error")

    def _stop(self, reason: str):
        if reason not in STOP_REASONS or self.trace.stop_reason is not None:
            return
        self.trace.stop_reason = reason
        self.trace.finished_at = _now()
        self.trace.ledger = self.ledger.to_dict()

    def to_dict(self) -> dict[str, Any]:
        self.trace.ledger = self.ledger.to_dict()
        return self.trace.to_dict()

    def persist(self, trace_dir: str | Path) -> Path | None:
        try:
            directory = Path(trace_dir)
            directory.mkdir(parents=True, exist_ok=True)
            target = directory / f"{self.trace.trace_id}.json"
            fd, temp_name = tempfile.mkstemp(prefix=f".{self.trace.trace_id}.", suffix=".tmp", dir=directory)
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    json.dump(self.to_dict(), handle, ensure_ascii=False, indent=2)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_name, target)
            finally:
                if os.path.exists(temp_name):
                    os.unlink(temp_name)
            return target
        except Exception:
            return None
