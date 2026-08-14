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

# 模型显式给出的 claim/evidence 判定。`support` / `conflict` 表示模型基于已见
# 来源作出支持/冲突结论；`unknown` 表示证据不足、无法判定；`no_evidence` 表示
# 已检索但未找到相关证据（区别于“尚未检索”）。
JUDGMENT_VERDICTS = {"support", "conflict", "unknown", "no_evidence"}


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
    # 最近一次模型显式判定，取值见 JUDGMENT_VERDICTS。
    judgment: str | None = None
    # 判定时已检索、未检索来源是否覆盖，用于区分“记忆中没有”与“尚未找到”。
    searched: bool = False
    cue_anchors: list[str] = field(default_factory=list)


@dataclass
class EvidenceLedger:
    claims: dict[str, ClaimEvidence] = field(default_factory=dict)
    seen_sources: set[str] = field(default_factory=set)
    # 是否已至少执行过一次主动检索（seed 自动召回不算主动搜索）。
    searched: bool = False

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
            for record in records:
                for anchor in self._record_anchors(record):
                    if anchor not in claim.cue_anchors:
                        claim.cue_anchors.append(anchor)
        return new_sources

    @staticmethod
    def _record_anchors(record: MemoryRecord) -> list[str]:
        anchors: list[str] = []
        for value in list(record.cue_anchors or []) + list(record.entities or []) + [record.name]:
            text = str(value or "").strip()
            if text and text not in anchors:
                anchors.append(text)
        return anchors

    def mark_supporting(self, claim_id: str, source_ids: Iterable[str], confidence: float = 1.0):
        claim = self.claims[claim_id]
        claim.supporting_sources = list(dict.fromkeys(claim.supporting_sources + list(source_ids)))
        claim.confidence = float(confidence)
        claim.resolved = True
        claim.judgment = "support"

    def mark_conflicting(self, claim_id: str, source_ids: Iterable[str], confidence: float = 0.0):
        claim = self.claims[claim_id]
        claim.conflicting_sources = list(dict.fromkeys(claim.conflicting_sources + list(source_ids)))
        claim.confidence = float(confidence)
        claim.resolved = False
        claim.judgment = "conflict"

    def mark_searched(self):
        """标记已做过主动核对。seed 自动召回不算。"""
        self.searched = True

    @staticmethod
    def _claim_id_from_text(text: str) -> str:
        return "claim:" + hashlib.sha256(text.strip().encode("utf-8")).hexdigest()[:16]

    def resolve_claim_id(self, claim: str, create: bool = False) -> str:
        """解析已有 claim。顺序：精确 ID、精确文本、文本 hash。

        只有一条 claim 时，把改写文本当作对该 claim 的判定，不新建。
        多 claim 未命中时不静默 create。
        """
        text = str(claim or "")
        if text in self.claims:
            return text
        for cid, existing in self.claims.items():
            if existing.claim == text:
                return cid
        if text:
            probe = self._claim_id_from_text(text)
            if probe in self.claims:
                return probe
        if create and text:
            cid = self._claim_id_from_text(text)
            if cid not in self.claims:
                self.claims[cid] = ClaimEvidence(claim_id=cid, claim=text)
            return cid
        if len(self.claims) == 1:
            return next(iter(self.claims))
        return ""

    def record_judgment(
        self,
        claim_id_or_text: str,
        verdict: str,
        source_ids: Iterable[str] | None = None,
        confidence: float | None = None,
    ) -> bool:
        """记录模型显式判定。非法 verdict、未命中 claim、未检索的 no_evidence 返回 False。"""
        verdict = str(verdict or "").strip().lower()
        if verdict not in JUDGMENT_VERDICTS:
            return False
        if verdict == "no_evidence" and not self.searched:
            return False
        claim_text = str(claim_id_or_text or "")
        claim = self.claims.get(claim_text)
        if claim is None:
            claim_id = self.resolve_claim_id(claim_text, create=False)
            if not claim_id or claim_id not in self.claims:
                return False
            claim = self.claims[claim_id]

        source_ids_list = [str(s) for s in (source_ids or []) if str(s)]
        claim.judgment = verdict
        claim.searched = self.searched

        if verdict == "support":
            for source in source_ids_list:
                if source not in claim.supporting_sources:
                    claim.supporting_sources.append(source)
                claim.conflicting_sources = [
                    s for s in claim.conflicting_sources if s != source
                ]
            claim.resolved = True
        elif verdict == "conflict":
            for source in source_ids_list:
                if source not in claim.conflicting_sources:
                    claim.conflicting_sources.append(source)
            claim.resolved = False
        elif verdict == "unknown":
            claim.resolved = False
        else:
            claim.resolved = True

        if confidence is not None:
            try:
                claim.confidence = float(confidence)
            except (TypeError, ValueError):
                claim.confidence = 1.0 if verdict == "support" else 0.0
        else:
            claim.confidence = 1.0 if verdict == "support" else 0.0
        return True

    def absence_state(self) -> str:
        judgments = [claim.judgment for claim in self.claims.values()]
        if any(judgment == "conflict" for judgment in judgments):
            return "evidence_conflict"
        if any(
            claim.resolved and claim.judgment == "support"
            for claim in self.claims.values()
        ):
            return "evidence_support"
        if not self.searched:
            return "not_searched"
        if any(judgment == "no_evidence" for judgment in judgments) or not self.seen_sources:
            return "searched_no_evidence"
        return "unresolved"

    def unresolved_claims(self) -> list[str]:
        """返回尚未解决、需要更多证据或候选线索的 claim，用于驱动 query rewrite。"""
        unresolved = []
        for claim in self.claims.values():
            if not claim.resolved or claim.judgment in (None, "unknown"):
                unresolved.append(claim.claim)
        return unresolved

    def all_cue_anchors(self) -> list[str]:
        """收集所有 claim 的线索锚点，用于 query rewrite。"""
        anchors: list[str] = []
        for claim in self.claims.values():
            for anchor in claim.cue_anchors or []:
                if anchor and anchor not in anchors:
                    anchors.append(anchor)
        return anchors

    @property
    def coverage(self) -> float:
        if not self.claims:
            return 0.0
        return sum(claim.resolved for claim in self.claims.values()) / len(self.claims)

    def to_dict(self) -> dict[str, Any]:
        return {
            "claims": {claim_id: asdict(claim) for claim_id, claim in self.claims.items()},
            "seen_sources": sorted(self.seen_sources),
            "searched": self.searched,
            "absence": self.absence_state(),
            "coverage": self.coverage,
            "unresolved_claims": self.unresolved_claims(),
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
class RecallReadTrace:
    source: str
    found: bool
    reason: str
    adjacent_ids: list[str]
    latency_ms: float
    error: str | None = None


@dataclass
class RecallJudgmentTrace:
    claim_id: str
    claim: str
    verdict: str
    source_ids: list[str]
    searched: bool


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
    reads: list[RecallReadTrace] = field(default_factory=list)
    judgments: list[RecallJudgmentTrace] = field(default_factory=list)
    # query rewrite 若被触发，记录改写后的查询与来源 claim。
    rewrites: list[dict[str, Any]] = field(default_factory=list)

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
        self.ledger.mark_searched()
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
        unresolved = self.ledger.unresolved_claims()
        if unresolved and not error:
            rewritten = self.build_rewrite_query()
            if rewritten and not any(
                item.get("rewritten_query") == rewritten
                for item in self.trace.rewrites
            ):
                self.record_rewrite(rewritten, unresolved, round_index=len(self.trace.rounds))
        if error:
            self._stop("error")
        elif not accepted_source_ids:
            self._stop("no_new_evidence")
        elif len(self.trace.rounds) >= self.trace.max_rounds:
            self._stop("budget_exhausted")
        return True

    def observe_read(
        self,
        source: str,
        found: bool,
        adjacent_ids: Iterable[str] | None = None,
        latency_ms: float = 0.0,
        reason: str = "",
        error: str | None = None,
    ) -> bool:
        """记录来源读取。读取不消耗搜索预算；有效核对会标记 searched。"""
        try:
            safe_latency_ms = float(latency_ms)
        except (TypeError, ValueError):
            safe_latency_ms = 0.0
        if error is None and reason != "invalid_payload":
            self.ledger.mark_searched()
        self.trace.reads.append(RecallReadTrace(
            source=str(source or ""),
            found=bool(found),
            reason=str(reason or ""),
            adjacent_ids=[str(item) for item in (adjacent_ids or []) if item],
            latency_ms=safe_latency_ms,
            error=error,
        ))
        return True

    def observe_judgment(
        self,
        claim: str,
        verdict: str,
        source_ids: Iterable[str] | None = None,
        confidence: float | None = None,
    ) -> bool:
        """记录模型显式给出的 claim 判定，并写入 trace。judge_claim 工具路径。"""
        accepted = self.ledger.record_judgment(claim, verdict, source_ids, confidence)
        if not accepted:
            return False
        claim_id = self.ledger.resolve_claim_id(claim, create=False)
        stored = self.ledger.claims.get(claim_id)
        self.trace.judgments.append(RecallJudgmentTrace(
            claim_id=claim_id,
            claim=str(stored.claim if stored else claim or ""),
            verdict=str(verdict or "").strip().lower(),
            source_ids=[str(s) for s in (source_ids or []) if str(s)],
            searched=bool(self.ledger.searched),
        ))
        self.trace.ledger = self.ledger.to_dict()
        return True

    def record_rewrite(
        self,
        rewritten_query: str,
        source_claims: Iterable[str],
        round_index: int | None = None,
    ):
        entry = {
            "rewritten_query": str(rewritten_query or ""),
            "source_claims": [str(c) for c in source_claims if str(c)],
        }
        if round_index is not None:
            entry["round"] = round_index
        self.trace.rewrites.append(entry)
        self.trace.ledger = self.ledger.to_dict()

    def build_rewrite_query(self, max_len: int = 160) -> str:
        """从未解决 claim 与 cue anchors 生成确定性改写，供下一轮 search 参考。"""
        unresolved = self.ledger.unresolved_claims()
        anchors = self.ledger.all_cue_anchors()
        parts: list[str] = []
        for claim in unresolved:
            if claim not in parts:
                parts.append(claim)
        for anchor in anchors:
            if anchor not in parts:
                parts.append(anchor)
        if not parts:
            return ""
        rewritten = " ".join(parts)
        if len(rewritten) <= max_len:
            return rewritten
        return rewritten[:max_len].strip()

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
