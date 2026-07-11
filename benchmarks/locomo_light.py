"""Low-cost LoCoMo evaluation for LightHermes.

The benchmark stores each LoCoMo session as one semantic memory. The provided
session summary is placed first for retrieval, while the original dialogue is
kept as answer evidence. Categories 1-4 are sampled evenly; adversarial
category 5 is intentionally excluded from the lightweight run.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import re
import string
import sys
import tempfile
import time
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

        content_parts = [f"Session date: {timestamp}"]
        if summary:
            content_parts.append(f"Session summary: {summary}")
        content_parts.append("Dialogue:\n" + "\n".join(dialogue_lines))
        documents.append({
            "name": session_key,
            "content": "\n".join(content_parts),
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
        embedding_model=embedding.get("model_name", "text-embedding-3-small"),
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
        model=model.get("model_name", "gpt-5.4-mini"),
        api_key=resolved(model.get("api_key")),
        base_url=resolved(model.get("base_url")),
    )


def call_model(adapter: Any, messages: list[dict[str, str]], max_tokens: int) -> Any:
    return adapter.create(messages=messages, stream=False, max_tokens=max_tokens)


def answer_question(adapter: Any, question: str, context: str) -> Any:
    return call_model(
        adapter,
        [
            {
                "role": "system",
                "content": (
                    "Answer from the supplied conversation memories. Be concise and "
                    "specific. Resolve dates from timestamps. Do not invent unsupported facts."
                ),
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
        max_tokens=32,
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


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    config_path = Path(args.config).resolve()
    data_path = Path(args.data_path).resolve()
    output_path = Path(args.output).resolve()
    embedding_cache_file = Path(args.embedding_cache).resolve()
    config = load_config(config_path)
    dataset = load_dataset(data_path)
    cases = stratified_sample(dataset, args.per_category, args.seed)
    cases_by_conversation: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        cases_by_conversation[case["conversation_index"]].append(case)

    usage = UsageTotals()
    adapter = create_model_adapter(config) if args.mode == "qa" else None
    results: list[dict[str, Any]] = []
    started_at = time.time()
    consecutive_errors = 0

    with tempfile.TemporaryDirectory(prefix="lighthermes-locomo-") as temp_dir:
        original_cwd = Path.cwd()
        os.chdir(temp_dir)
        try:
            for conversation_index, conversation_cases in sorted(cases_by_conversation.items()):
                memory = create_memory(
                    Path(temp_dir) / f"conversation-{conversation_index}",
                    config,
                    embedding_cache_file,
                )
                for document in build_session_documents(dataset[conversation_index]):
                    memory.save_semantic(
                        document["name"],
                        document["content"],
                        document["metadata"],
                    )

                for case in conversation_cases:
                    case_started = time.perf_counter()
                    try:
                        retrieved = memory.recall_items(
                            case["question"],
                            layers=["semantic"],
                            limit=args.top_k,
                            max_chars=args.max_context_chars,
                        )
                        metrics = retrieval_metrics(retrieved, case["evidence"])
                        result = {
                            **case,
                            "category_name": CATEGORY_NAMES[case["category"]],
                            "retrieval": metrics,
                            "retrieved": [
                                {
                                    "rank": rank,
                                    "name": item.get("name"),
                                    "score": item.get("score"),
                                    "session_id": item.get("metadata", {}).get("session_id"),
                                }
                                for rank, item in enumerate(retrieved, 1)
                            ],
                        }

                        if adapter is not None:
                            context = "\n\n".join(item["content"] for item in retrieved)
                            answer_response = answer_question(adapter, case["question"], context)
                            usage.add_response(answer_response)
                            generated = response_text(answer_response)
                            judge_response = judge_answer(
                                adapter,
                                case["question"],
                                case["answer"],
                                generated,
                            )
                            usage.add_response(judge_response)
                            judge_text = response_text(judge_response)
                            result.update({
                                "generated_answer": generated,
                                "token_f1": token_f1(generated, case["answer"]),
                                "judge_correct": parse_judge_label(judge_text),
                                "judge_response": judge_text,
                            })

                        result["latency_ms"] = (time.perf_counter() - case_started) * 1000
                        results.append(result)
                        consecutive_errors = 0
                        print(
                            f"[{len(results)}/{len(cases)}] {result['category_name']} "
                            f"hit={metrics['hit']} judge={result.get('judge_correct')}"
                        )
                    except HybridRetrievalError as exc:
                        results.append({
                            **case,
                            "category_name": CATEGORY_NAMES[case["category"]],
                            "retrieval": {"evidence_count": 0, "hit": None, "recall": None, "rr": None},
                            "error": f"{type(exc).__name__}: {exc}",
                            "latency_ms": (time.perf_counter() - case_started) * 1000,
                        })
                        write_report(output_path, {
                            "status": "failed",
                            "settings": vars(args),
                            "error": f"{type(exc).__name__}: {exc}",
                            "summary": summarize_results(results),
                            "usage": asdict(usage),
                            "estimated_cost_usd": usage.estimated_cost(
                                args.input_price,
                                args.output_price,
                            ),
                            "elapsed_seconds": time.time() - started_at,
                            "results": results,
                        })
                        raise
                    except Exception as exc:
                        consecutive_errors += 1
                        results.append({
                            **case,
                            "category_name": CATEGORY_NAMES[case["category"]],
                            "retrieval": {"evidence_count": 0, "hit": None, "recall": None, "rr": None},
                            "error": f"{type(exc).__name__}: {exc}",
                            "latency_ms": (time.perf_counter() - case_started) * 1000,
                        })
                        if consecutive_errors >= 3:
                            raise RuntimeError("Stopped after 3 consecutive benchmark errors") from exc

                    report = {
                        "status": "completed",
                        "settings": vars(args),
                        "summary": summarize_results(results),
                        "usage": asdict(usage),
                        "estimated_cost_usd": usage.estimated_cost(
                            args.input_price,
                            args.output_price,
                        ),
                        "elapsed_seconds": time.time() - started_at,
                        "results": results,
                    }
                    write_report(output_path, report)
        finally:
            os.chdir(original_cwd)

    return report


def build_parser() -> argparse.ArgumentParser:
    default_data = Path(tempfile.gettempdir()) / "lighthermes-locomo" / "locomo10.json"
    default_cache = Path(tempfile.gettempdir()) / "lighthermes-locomo" / "embeddings.json"
    default_output = PROJECT_ROOT / "logs" / "locomo_light_report.json"
    parser = argparse.ArgumentParser(description="Low-cost stratified LoCoMo evaluation")
    parser.add_argument("--config", default=str(PROJECT_ROOT / "config.yaml"))
    parser.add_argument("--data-path", default=str(default_data))
    parser.add_argument("--embedding-cache", default=str(default_cache))
    parser.add_argument("--download", action="store_true")
    parser.add_argument("--mode", choices=["retrieval", "qa"], default="retrieval")
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
    print(json.dumps({
        "summary": report["summary"],
        "usage": report["usage"],
        "estimated_cost_usd": report["estimated_cost_usd"],
        "elapsed_seconds": report["elapsed_seconds"],
        "output": str(Path(args.output).resolve()),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
