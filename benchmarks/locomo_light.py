"""Low-cost LoCoMo evaluation for LightHermes.

The benchmark stores each LoCoMo session as one semantic memory. The provided
session summary is placed first for retrieval, while the original dialogue is
kept as answer evidence. Categories 1-4 are sampled evenly; adversarial
category 5 is intentionally excluded from the lightweight run.
"""

from __future__ import annotations

import argparse
import copy
import json
import os
import random
import re
import string
import sys
import tempfile
import time
import traceback
import urllib.request
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from lighthermes.adapters import get_adapter
from lighthermes.core import LightHermes
from lighthermes.memory import HybridRetrievalError, MemoryManager


DATASET_URL = (
    "https://raw.githubusercontent.com/snap-research/locomo/"
    "main/data/locomo10.json"
)
CATEGORY_NAMES = {
    1: "multi_hop",
    2: "temporal",
    3: "open_domain",
    4: "single_hop",
}


@dataclass
class UsageTotals:
    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def add_response(self, response: Any) -> None:
        self.calls += 1
        usage = getattr(response, "usage", None)
        if not usage:
            return
        self.prompt_tokens += _usage_value(usage, "prompt_tokens")
        self.completion_tokens += _usage_value(usage, "completion_tokens")
        self.total_tokens += _usage_value(usage, "total_tokens")
        details = getattr(usage, "completion_tokens_details", None)
        if details:
            self.reasoning_tokens += _usage_value(details, "reasoning_tokens")

    def estimated_cost(self, input_price: float, output_price: float) -> float:
        return (
            self.prompt_tokens * input_price
            + self.completion_tokens * output_price
        ) / 1_000_000


def _usage_value(usage: Any, key: str) -> int:
    if isinstance(usage, dict):
        return int(usage.get(key, 0) or 0)
    return int(getattr(usage, key, 0) or 0)


def download_dataset(path: Path, url: str = DATASET_URL) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return path
    temp_path = path.with_suffix(path.suffix + ".tmp")
    urllib.request.urlretrieve(url, temp_path)
    temp_path.replace(path)
    return path


def load_dataset(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("LoCoMo dataset must be a JSON list")
    return data


def stratified_sample(
    dataset: list[dict[str, Any]],
    per_category: int = 10,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Sample each answerable category while spreading cases across conversations."""
    rng = random.Random(seed)
    grouped: dict[int, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for conversation_index, sample in enumerate(dataset):
        for qa_index, qa in enumerate(sample.get("qa", [])):
            category = int(qa.get("category", 0))
            if category not in CATEGORY_NAMES:
                continue
            grouped[category][conversation_index].append({
                "conversation_index": conversation_index,
                "qa_index": qa_index,
                "category": category,
                "question": qa.get("question", ""),
                "answer": qa.get("answer", ""),
                "evidence": list(qa.get("evidence") or []),
            })

    selected: list[dict[str, Any]] = []
    for category in CATEGORY_NAMES:
        buckets = grouped.get(category, {})
        for values in buckets.values():
            rng.shuffle(values)
        conversation_order = list(buckets)
        rng.shuffle(conversation_order)

        category_cases: list[dict[str, Any]] = []
        while len(category_cases) < per_category:
            added = False
            for conversation_index in conversation_order:
                values = buckets[conversation_index]
                if values:
                    category_cases.append(values.pop())
                    added = True
                    if len(category_cases) >= per_category:
                        break
            if not added:
                break
        if len(category_cases) != per_category:
            raise ValueError(
                f"Category {category} only has {len(category_cases)} usable cases; "
                f"requested {per_category}"
            )
        selected.extend(category_cases)

    rng.shuffle(selected)
    return selected


def build_session_documents(sample: dict[str, Any]) -> list[dict[str, Any]]:
    conversation = sample["conversation"]
    session_numbers = sorted(
        int(match.group(1))
        for key in conversation
        if (match := re.fullmatch(r"session_(\d+)", key))
    )
    summaries = sample.get("session_summary", {})
    documents = []

    for session_number in session_numbers:
        session_key = f"session_{session_number}"
        turns = conversation[session_key]
        timestamp = conversation.get(f"{session_key}_date_time", "")
        summary = summaries.get(f"{session_key}_summary", "")
        if isinstance(summary, list):
            summary = " ".join(str(item) for item in summary)

        dialogue_lines = []
        dia_ids = []
        for turn in turns:
            dia_id = str(turn.get("dia_id", ""))
            if dia_id:
                dia_ids.append(dia_id)
            text = str(turn.get("text", ""))
            caption = str(turn.get("blip_caption", ""))
            if caption and caption not in text:
                text = f"{text} [Image: {caption}]".strip()
            dialogue_lines.append(f"{turn.get('speaker', 'unknown')}: {text}")

        # 检索打整段 session summary；回答/验证走日期+原文对话，不回退全文混检索。
        content_parts = []
        if timestamp:
            content_parts.append(f"Session date: {timestamp}")
        content_parts.append("Dialogue:\n" + "\n".join(dialogue_lines))
        documents.append({
            "name": session_key,
            "content": "\n".join(content_parts),
            "abstract": str(summary or "").strip(),
            "metadata": {
                "type": "locomo_session",
                "session_id": session_key,
                "timestamp": timestamp,
                "dia_ids": ",".join(dia_ids),
            },
        })
    return documents


def retrieval_metrics(
    retrieved: Iterable[dict[str, Any]],
    evidence_ids: Iterable[str],
) -> dict[str, Any]:
    evidence = {str(item) for item in evidence_ids if str(item)}
    if not evidence:
        return {"evidence_count": 0, "hit": None, "recall": None, "rr": None}

    found: set[str] = set()
    first_rank = None
    for rank, item in enumerate(retrieved, 1):
        metadata = item.get("metadata", {})
        item_ids = {
            value.strip()
            for value in str(metadata.get("dia_ids", "")).split(",")
            if value.strip()
        }
        overlap = evidence & item_ids
        if overlap and first_rank is None:
            first_rank = rank
        found.update(overlap)

    return {
        "evidence_count": len(evidence),
        "hit": bool(found),
        "recall": len(found) / len(evidence),
        "rr": 1 / first_rank if first_rank else 0.0,
    }


def normalize_answer(text: str) -> list[str]:
    text = str(text).lower().translate(str.maketrans("", "", string.punctuation))
    return [token for token in text.split() if token not in {"a", "an", "the"}]


def token_f1(prediction: str, gold: str) -> float:
    predicted_tokens = normalize_answer(prediction)
    gold_tokens = normalize_answer(gold)
    if not predicted_tokens or not gold_tokens:
        return float(predicted_tokens == gold_tokens)
    overlap = sum((Counter(predicted_tokens) & Counter(gold_tokens)).values())
    if overlap == 0:
        return 0.0
    precision = overlap / len(predicted_tokens)
    recall = overlap / len(gold_tokens)
    return 2 * precision * recall / (precision + recall)


def parse_judge_label(text: str) -> bool | None:
    upper = str(text).upper()
    labels = re.findall(r"\b(CORRECT|WRONG)\b", upper)
    if not labels:
        return None
    return labels[-1] == "CORRECT"


def response_text(response: Any) -> str:
    return str(response.choices[0].message.content or "").strip()


def load_config(config_path: Path) -> dict[str, Any]:
    with config_path.open("r", encoding="utf-8") as handle:
        config = yaml.safe_load(handle) or {}
    LightHermes._load_local_env_files(str(config_path), config)
    return config


def resolved(value: Any) -> Any:
    return LightHermes._resolve_config_value(value)


def create_memory(
    memory_dir: Path,
    config: dict[str, Any],
    embedding_cache_file: Path | None = None,
) -> MemoryManager:
    memory_config = config.get("memory", {})
    hybrid = memory_config.get("hybrid_retrieval", {})
    embedding = config.get("embedding", {})
    return MemoryManager(
        memory_dir=str(memory_dir),
        semantic_max_entries=1000,
        semantic_max_chars=2_000_000,
        use_hybrid_retrieval=True,
        embedding_provider=embedding.get("provider", "openai"),
        embedding_model=resolved(embedding.get("model_name", "text-embedding-3-small")),
        api_key=resolved(embedding.get("api_key")),
        embedding_base_url=resolved(embedding.get("base_url")),
        embedding_cache_file=(
            str(embedding_cache_file) if embedding_cache_file else None
        ),
        strict_hybrid_retrieval=True,
        hybrid_min_candidates=int(hybrid.get("min_candidates", 5)),
        hybrid_fallback_to_all=True,
        hybrid_semantic_threshold=hybrid.get("semantic_threshold"),
        hybrid_score_margin=float(hybrid.get("score_margin", 0.08)),
        hybrid_full_rerank_max_docs=1000,
        hybrid_tfidf_candidate_limit=int(hybrid.get("tfidf_candidate_limit", 20)),
    )


def create_model_adapter(config: dict[str, Any]):
    model = config.get("model", {})
    return get_adapter(
        provider=model.get("provider", "openai"),
        model=resolved(model.get("model_name", "gpt-4o-mini")),
        api_key=resolved(model.get("api_key")),
        base_url=resolved(model.get("base_url")),
    )


def call_model(adapter: Any, messages: list[dict[str, str]], max_tokens: int) -> Any:
    response = adapter.create(messages=messages, stream=False, max_tokens=max_tokens)
    if isinstance(response, str):
        raise RuntimeError(f"模型接口返回了非 ChatCompletion：{response[:180]!r}")
    return response


def answer_question(adapter: Any, question: str, context: str) -> Any:
    return call_model(
        adapter,
        [
            {
                "role": "system",
                "content": STATIC_ANSWER_INSTRUCTION,
            },
            {
                "role": "user",
                "content": f"Conversation memories:\n{context}\n\nQuestion: {question}",
            },
        ],
        max_tokens=256,
    )


def judge_answer(adapter: Any, question: str, gold: str, generated: str) -> Any:
    return call_model(
        adapter,
        [
            {
                "role": "system",
                "content": (
                    "Grade whether the generated answer matches the gold answer. Be generous "
                    "about wording and equivalent dates. Return exactly CORRECT or WRONG."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\nGold answer: {gold}\n"
                    f"Generated answer: {generated}"
                ),
            },
        ],
        max_tokens=128,
    )


def average(values: Iterable[float | int | bool | None]) -> float | None:
    usable = [float(value) for value in values if value is not None]
    return sum(usable) / len(usable) if usable else None


def summarize_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    def summarize(items: list[dict[str, Any]]) -> dict[str, Any]:
        return {
            "count": len(items),
            "retrieval_hit_rate": average(item["retrieval"]["hit"] for item in items),
            "evidence_recall": average(item["retrieval"]["recall"] for item in items),
            "mrr": average(item["retrieval"]["rr"] for item in items),
            "token_f1": average(item.get("token_f1") for item in items),
            "judge_accuracy": average(item.get("judge_correct") for item in items),
            "avg_latency_ms": average(item.get("latency_ms") for item in items),
        }

    per_category = {}
    for category, name in CATEGORY_NAMES.items():
        category_items = [item for item in results if item["category"] == category]
        per_category[name] = summarize(category_items)
    return {"overall": summarize(results), "per_category": per_category}


def write_report(path: Path, report: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    temp_path.replace(path)


STATIC_ANSWER_INSTRUCTION = (
    "Answer from the supplied conversation memories. Be concise and "
    "specific. Resolve dates from timestamps. Do not invent unsupported facts."
)


def freeze_snapshot(config: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    """A/B 冻结清单：只记可复现设置，不写密钥。"""
    model = config.get("model", {})
    embedding = config.get("embedding", {})
    hybrid = config.get("memory", {}).get("hybrid_retrieval", {})
    return {
        "date": "2026-08-15",
        "split": "locomo_dev_stratified",
        "holdout": False,
        "stream": False,
        "seed": int(args.seed),
        "per_category": int(args.per_category),
        "categories": list(CATEGORY_NAMES.values()),
        "top_k": int(args.top_k),
        "max_context_chars": int(args.max_context_chars),
        "model": resolved(model.get("model_name")),
        "model_provider": model.get("provider", "openai"),
        "base_url": resolved(model.get("base_url")),
        "embedding_model": resolved(embedding.get("model_name")),
        "embedding_base_url": resolved(embedding.get("base_url")),
        "hybrid_semantic_threshold": hybrid.get("semantic_threshold"),
        "hybrid_score_margin": hybrid.get("score_margin"),
        "trigger": (
            "should_force_search: can_search and coverage<1 "
            "and absence in {not_searched, evidence_conflict}"
        ),
        "static_arm": "recall_items Top-K + dedicated QA prompt; no active_recall",
        "agentic_arm": (
            "LightHermes.run non-stream, active_recall=true, runtime forced search; "
            "same answering instruction as static"
        ),
        "judge": "CORRECT/WRONG, wording-generous, one shot",
    }


def compare_arm_summaries(
    static_summary: dict[str, Any],
    agentic_summary: dict[str, Any],
) -> dict[str, Any]:
    def delta(metric: str) -> dict[str, Any]:
        left = static_summary.get("overall", {}).get(metric)
        right = agentic_summary.get("overall", {}).get(metric)
        change = None
        if left is not None and right is not None:
            change = (float(right) - float(left)) * 100
        return {"static": left, "agentic": right, "delta_pp": change}

    return {
        "judge_accuracy": delta("judge_accuracy"),
        "retrieval_hit_rate": delta("retrieval_hit_rate"),
        "evidence_recall": delta("evidence_recall"),
        "token_f1": delta("token_f1"),
        "avg_latency_ms": {
            "static": static_summary.get("overall", {}).get("avg_latency_ms"),
            "agentic": agentic_summary.get("overall", {}).get("avg_latency_ms"),
        },
    }


def latest_trace(trace_dir: Path) -> dict[str, Any] | None:
    files = sorted(trace_dir.glob("*.json"), key=lambda path: path.stat().st_mtime)
    if not files:
        return None
    return json.loads(files[-1].read_text(encoding="utf-8"))


def items_from_sources(memory: MemoryManager, source_ids: Iterable[str]) -> list[dict[str, Any]]:
    items = []
    for source in source_ids:
        record = memory.get_source(str(source or ""))
        if record.get("found"):
            items.append({"metadata": record.get("metadata") or {}})
    return items


def create_runtime_agent(
    config_path: Path,
    config: dict[str, Any],
    memory_dir: Path,
    embedding_cache_file: Path,
    trace_dir: Path,
) -> LightHermes:
    cfg = copy.deepcopy(config)
    memory_cfg = cfg.setdefault("memory", {})
    active = memory_cfg.setdefault("active_recall", {})
    active["enabled"] = True
    active["persist_traces"] = True
    active["trace_dir"] = str(trace_dir)
    hybrid = memory_cfg.setdefault("hybrid_retrieval", {})
    hybrid["enabled"] = True
    hybrid["strict_hybrid_retrieval"] = True
    hybrid["full_rerank_max_docs"] = 1000
    memory_cfg.setdefault("retention", {})["semantic_max_chars"] = 2_000_000
    cfg["evolution"] = {"enabled": False}
    cfg["context_compression"] = {"enabled": False}
    cfg.setdefault("skills", {})["dirs"] = []
    cfg["logging"] = {"level": "ERROR", "file": None, "debug": False}
    return LightHermes.from_config(
        str(config_path),
        config=cfg,
        name="locomo-ab",
        role=STATIC_ANSWER_INSTRUCTION,
        memory_dir=str(memory_dir),
        evolution_enabled=False,
        skill_dirs=[],
        embedding_cache_file=str(embedding_cache_file),
    )


def populate_memory(
    memory: MemoryManager,
    documents: list[dict[str, Any]],
) -> None:
    for document in documents:
        metadata = dict(document.get("metadata") or {})
        abstract = " ".join(str(document.get("abstract") or "").split())
        if abstract:
            metadata["abstract"] = abstract
        memory.save_semantic(
            document["name"],
            document["content"],
            metadata,
        )


def retrieved_preview(retrieved: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "rank": rank,
            "name": item.get("name"),
            "score": item.get("score"),
            "session_id": item.get("metadata", {}).get("session_id"),
        }
        for rank, item in enumerate(retrieved, 1)
    ]


def grade_answer(
    adapter: Any,
    usage: UsageTotals,
    question: str,
    gold: str,
    generated: str,
) -> dict[str, Any]:
    judge_response = judge_answer(adapter, question, gold, generated)
    usage.add_response(judge_response)
    judge_text = response_text(judge_response)
    return {
        "generated_answer": generated,
        "token_f1": token_f1(generated, gold),
        "judge_correct": parse_judge_label(judge_text),
        "judge_response": judge_text,
    }


def run_static_case(
    memory: MemoryManager,
    adapter: Any | None,
    usage: UsageTotals,
    case: dict[str, Any],
    args: argparse.Namespace,
) -> dict[str, Any]:
    retrieved = memory.recall_items(
        case["question"],
        layers=["semantic"],
        limit=args.top_k,
        max_chars=args.max_context_chars,
    )
    result = {
        **case,
        "arm": "static",
        "category_name": CATEGORY_NAMES[case["category"]],
        "retrieval": retrieval_metrics(retrieved, case["evidence"]),
        "retrieved": retrieved_preview(retrieved),
    }
    if adapter is not None:
        context = "\n\n".join(item["content"] for item in retrieved)
        answer_response = answer_question(adapter, case["question"], context)
        usage.add_response(answer_response)
        result.update(grade_answer(
            adapter, usage, case["question"], case["answer"],
            response_text(answer_response),
        ))
        result["model_calls"] = 1
    return result


def run_agentic_case(
    config_path: Path,
    config: dict[str, Any],
    documents: list[dict[str, Any]],
    adapter: Any,
    usage: UsageTotals,
    case: dict[str, Any],
    args: argparse.Namespace,
    memory_dir: Path,
    embedding_cache_file: Path,
    trace_dir: Path,
) -> dict[str, Any]:
    agent = create_runtime_agent(
        config_path, config, memory_dir, embedding_cache_file, trace_dir,
    )
    populate_memory(agent.memory, documents)
    # agent.run 内部走 agent.adapter.create，包装计数，让模型调用与 token 进 UsageTotals。
    raw_create = agent.adapter.create

    def counted_create(**kwargs):
        response = raw_create(**kwargs)
        usage.add_response(response)
        return response

    agent.adapter.create = counted_create
    seed = agent.memory.recall_items(
        case["question"],
        layers=["semantic"],
        limit=args.top_k,
        max_chars=args.max_context_chars,
    )
    generated = agent.run(
        case["question"],
        stream=False,
        session_id=f"ab-{case['conversation_index']}-{case['qa_index']}",
        max_iterations=6,
    )
    if not isinstance(generated, str):
        generated = "".join(generated)
    trace = latest_trace(trace_dir) or {}
    seen_sources = list(trace.get("ledger", {}).get("seen_sources") or [])
    # 主比对指标必须和 static 同口径：都用 seed Top-K 算，不再用 ledger 反推。
    seed_retrieval = retrieval_metrics(seed, case["evidence"])
    # ledger 覆盖仅作诊断，展示主动搜索最终把哪些来源纳入账本，不参与 A/B 对比。
    covered = items_from_sources(agent.memory, seen_sources) if seen_sources else seed
    result = {
        **case,
        "arm": "agentic",
        "category_name": CATEGORY_NAMES[case["category"]],
        "retrieval": seed_retrieval,
        "seed_retrieval": seed_retrieval,
        "ledger_retrieval": retrieval_metrics(covered, case["evidence"]),
        "ledger_sources": seen_sources,
        "retrieved": retrieved_preview(seed),
        "model_calls": int(getattr(agent, "api_call_count", 0) or 0),
        "agent_tokens": int(getattr(agent, "total_tokens_used", 0) or 0),
        "stop_reason": trace.get("stop_reason"),
        "forced_search": trace.get("forced_search") or [],
        "forced_search_skip": (trace.get("metadata") or {}).get("forced_search_skip") or [],
        "absence": (trace.get("ledger") or {}).get("absence"),
    }
    result.update(grade_answer(
        adapter, usage, case["question"], case["answer"], generated,
    ))
    return result


def empty_error_result(case: dict[str, Any], arm: str, exc: Exception, started: float) -> dict[str, Any]:
    return {
        **case,
        "arm": arm,
        "category_name": CATEGORY_NAMES[case["category"]],
        "retrieval": {"evidence_count": 0, "hit": None, "recall": None, "rr": None},
        "error": f"{type(exc).__name__}: {exc}",
        "latency_ms": (time.perf_counter() - started) * 1000,
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).resolve()
    data_path = Path(args.data_path).resolve()
    output_path = Path(args.output).resolve()
    embedding_cache_file = Path(args.embedding_cache).resolve()
    config = load_config(config_path)
    if args.mode in {"qa", "ab"}:
        if not resolved(config.get("model", {}).get("api_key")):
            raise ValueError("缺少 LIGHTHERMES_API_KEY（或 config model.api_key）")
        if not resolved(config.get("model", {}).get("model_name")):
            raise ValueError("缺少 LIGHTHERMES_MODEL")
        if not resolved(config.get("model", {}).get("base_url")):
            raise ValueError("缺少 LIGHTHERMES_BASE_URL")
    dataset = load_dataset(data_path)
    cases = stratified_sample(dataset, args.per_category, args.seed)
    cases_by_conversation: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        cases_by_conversation[case["conversation_index"]].append(case)

    static_usage = UsageTotals()
    agentic_usage = UsageTotals()
    adapter = create_model_adapter(config) if args.mode in {"qa", "ab"} else None
    static_results: list[dict[str, Any]] = []
    agentic_results: list[dict[str, Any]] = []
    started_at = time.time()
    consecutive_errors = 0
    freeze = freeze_snapshot(config, args)

    def persist(status: str = "completed", error: str | None = None) -> dict[str, Any]:
        if args.mode == "ab":
            report = {
                "status": status,
                "freeze": freeze,
                "settings": vars(args),
                "arms": {
                    "static": {
                        "summary": summarize_results(static_results),
                        "usage": asdict(static_usage),
                        "estimated_cost_usd": static_usage.estimated_cost(
                            args.input_price, args.output_price
                        ),
                        "results": static_results,
                    },
                    "agentic": {
                        "summary": summarize_results(agentic_results),
                        "usage": asdict(agentic_usage),
                        "estimated_cost_usd": agentic_usage.estimated_cost(
                            args.input_price, args.output_price
                        ),
                        "results": agentic_results,
                    },
                },
                "comparison": compare_arm_summaries(
                    summarize_results(static_results),
                    summarize_results(agentic_results),
                ),
                "elapsed_seconds": time.time() - started_at,
            }
        else:
            results = static_results
            usage = static_usage
            report = {
                "status": status,
                "settings": vars(args),
                "summary": summarize_results(results),
                "usage": asdict(usage),
                "estimated_cost_usd": usage.estimated_cost(
                    args.input_price, args.output_price
                ),
                "elapsed_seconds": time.time() - started_at,
                "results": results,
            }
        if error:
            report["error"] = error
        write_report(output_path, report)
        return report

    with tempfile.TemporaryDirectory(prefix="lighthermes-locomo-") as temp_dir:
        original_cwd = Path.cwd()
        os.chdir(temp_dir)
        try:
            for conversation_index, conversation_cases in sorted(cases_by_conversation.items()):
                try:
                    documents = build_session_documents(dataset[conversation_index])
                    static_memory = create_memory(
                        Path(temp_dir) / f"conversation-{conversation_index}",
                        config,
                        embedding_cache_file,
                    )
                    populate_memory(static_memory, documents)
                except Exception as exc:
                    traceback.print_exc()
                    persist("failed", f"setup conversation {conversation_index}: {type(exc).__name__}: {exc}")
                    raise

                for case in conversation_cases:
                    if args.mode in {"retrieval", "qa"}:
                        case_started = time.perf_counter()
                        try:
                            result = run_static_case(
                                static_memory, adapter, static_usage, case, args
                            )
                            result["latency_ms"] = (time.perf_counter() - case_started) * 1000
                            static_results.append(result)
                            consecutive_errors = 0
                            print(
                                f"[{len(static_results)}/{len(cases)}] "
                                f"{result['category_name']} hit={result['retrieval']['hit']} "
                                f"judge={result.get('judge_correct')}",
                                flush=True,
                            )
                        except HybridRetrievalError as exc:
                            static_results.append(
                                empty_error_result(case, "static", exc, case_started)
                            )
                            persist("failed", f"{type(exc).__name__}: {exc}")
                            raise
                        except Exception as exc:
                            consecutive_errors += 1
                            static_results.append(
                                empty_error_result(case, "static", exc, case_started)
                            )
                            print(f"ERROR {type(exc).__name__}: {exc}")
                            if consecutive_errors >= 3:
                                persist("failed", f"{type(exc).__name__}: {exc}")
                                raise RuntimeError(
                                    "Stopped after 3 consecutive benchmark errors"
                                ) from exc
                    else:
                        static_started = time.perf_counter()
                        try:
                            static_result = run_static_case(
                                static_memory, adapter, static_usage, case, args
                            )
                            static_result["latency_ms"] = (
                                time.perf_counter() - static_started
                            ) * 1000
                        except HybridRetrievalError as exc:
                            persist("failed", f"{type(exc).__name__}: {exc}")
                            raise
                        except Exception as exc:
                            consecutive_errors += 1
                            static_result = empty_error_result(
                                case, "static", exc, static_started
                            )
                            traceback.print_exc()
                            print(f"STATIC ERROR {type(exc).__name__}: {exc}", flush=True)
                        static_results.append(static_result)

                        agentic_started = time.perf_counter()
                        try:
                            agentic_dir = Path(temp_dir) / (
                                f"agentic-{conversation_index}-{case['qa_index']}"
                            )
                            agentic_result = run_agentic_case(
                                config_path,
                                config,
                                documents,
                                adapter,
                                agentic_usage,
                                case,
                                args,
                                agentic_dir,
                                embedding_cache_file,
                                agentic_dir / "traces",
                            )
                            agentic_result["latency_ms"] = (
                                time.perf_counter() - agentic_started
                            ) * 1000
                            consecutive_errors = 0
                        except HybridRetrievalError as exc:
                            persist("failed", f"{type(exc).__name__}: {exc}")
                            raise
                        except Exception as exc:
                            consecutive_errors += 1
                            agentic_result = empty_error_result(
                                case, "agentic", exc, agentic_started
                            )
                            traceback.print_exc()
                            print(f"AGENTIC ERROR {type(exc).__name__}: {exc}", flush=True)
                        agentic_results.append(agentic_result)
                        print(
                            f"[{len(static_results)}/{len(cases)}] "
                            f"{static_result['category_name']} "
                            f"static_hit={static_result.get('retrieval', {}).get('hit')} "
                            f"static_judge={static_result.get('judge_correct')} "
                            f"agentic_hit={agentic_result.get('retrieval', {}).get('hit')} "
                            f"agentic_judge={agentic_result.get('judge_correct')} "
                            f"force={len(agentic_result.get('forced_search') or [])} "
                            f"stop={agentic_result.get('stop_reason')}",
                            flush=True,
                        )
                        if consecutive_errors >= 3:
                            persist("failed", "Stopped after 3 consecutive benchmark errors")
                            raise RuntimeError("Stopped after 3 consecutive benchmark errors")

                    persist("completed")
        finally:
            os.chdir(original_cwd)

    return persist("completed")


def build_parser() -> argparse.ArgumentParser:
    default_data = Path(tempfile.gettempdir()) / "lighthermes-locomo" / "locomo10.json"
    default_cache = Path(tempfile.gettempdir()) / "lighthermes-locomo" / "embeddings.json"
    default_output = PROJECT_ROOT / "logs" / "locomo_light_report.json"
    parser = argparse.ArgumentParser(description="Low-cost stratified LoCoMo evaluation")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--data-path", default=str(default_data))
    parser.add_argument("--embedding-cache", default=str(default_cache))
    parser.add_argument("--download", action="store_true")
    parser.add_argument(
        "--mode",
        choices=["retrieval", "qa", "ab"],
        default="retrieval",
        help="retrieval=召回; qa=静态问答; ab=同一开发集 static vs agentic",
    )
    parser.add_argument("--per-category", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--max-context-chars", type=int, default=30000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(default_output))
    parser.add_argument("--input-price", type=float, default=0.75)
    parser.add_argument("--output-price", type=float, default=4.50)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    data_path = Path(args.data_path).resolve()
    if args.download:
        print(f"Downloading LoCoMo to {data_path}")
        download_dataset(data_path)
    if not data_path.exists():
        raise FileNotFoundError(
            f"Dataset not found: {data_path}. Run again with --download."
        )

    report = run_benchmark(args)
    payload = {
        "status": report.get("status"),
        "elapsed_seconds": report.get("elapsed_seconds"),
        "output": str(Path(args.output).resolve()),
    }
    if "comparison" in report:
        payload["comparison"] = report["comparison"]
    else:
        payload["summary"] = report.get("summary")
        payload["usage"] = report.get("usage")
        payload["estimated_cost_usd"] = report.get("estimated_cost_usd")
    print(json.dumps(payload, ensure_ascii=False, indent=2), flush=True)
    return 0 if report.get("status") == "completed" else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        traceback.print_exc()
        raise
