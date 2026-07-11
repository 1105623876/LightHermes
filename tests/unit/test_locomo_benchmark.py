from benchmarks.locomo_light import (
    UsageTotals,
    build_session_documents,
    create_memory,
    parse_judge_label,
    retrieval_metrics,
    stratified_sample,
    token_f1,
)


def _sample(conversation_id: int):
    return {
        "conversation": {
            "speaker_a": "A",
            "speaker_b": "B",
            "session_1_date_time": "1 Jan 2024",
            "session_1": [
                {"speaker": "A", "text": "I like tea.", "dia_id": f"D{conversation_id}:1"},
                {"speaker": "B", "text": "Noted.", "dia_id": f"D{conversation_id}:2"},
            ],
        },
        "session_summary": {"session_1_summary": "A likes tea."},
        "qa": [
            {
                "question": f"Question {conversation_id}-{category}",
                "answer": "tea",
                "category": category,
                "evidence": [f"D{conversation_id}:1"],
            }
            for category in range(1, 6)
        ],
    }


def test_stratified_sample_balances_categories_and_conversations():
    selected = stratified_sample([_sample(index) for index in range(3)], per_category=2, seed=7)

    assert len(selected) == 8
    assert {case["category"] for case in selected} == {1, 2, 3, 4}
    for category in range(1, 5):
        category_cases = [case for case in selected if case["category"] == category]
        assert len(category_cases) == 2
        assert len({case["conversation_index"] for case in category_cases}) == 2


def test_build_session_documents_preserves_summary_and_evidence_ids():
    documents = build_session_documents(_sample(3))

    assert len(documents) == 1
    assert documents[0]["content"].startswith("Session date: 1 Jan 2024")
    assert "Session summary: A likes tea." in documents[0]["content"]
    assert documents[0]["metadata"]["dia_ids"] == "D3:1,D3:2"


def test_retrieval_metrics_uses_dialogue_evidence_rank():
    retrieved = [
        {"metadata": {"dia_ids": "D1:8,D1:9"}},
        {"metadata": {"dia_ids": "D1:1,D1:2"}},
    ]

    metrics = retrieval_metrics(retrieved, ["D1:1", "D1:2"])

    assert metrics == {
        "evidence_count": 2,
        "hit": True,
        "recall": 1.0,
        "rr": 0.5,
    }


def test_answer_metrics_and_usage_cost():
    assert token_f1("The green bicycle", "green bicycle") == 1.0
    assert parse_judge_label('{"label":"CORRECT"}') is True
    assert parse_judge_label("WRONG") is False
    assert parse_judge_label("unclear") is None

    usage = UsageTotals(prompt_tokens=1_000_000, completion_tokens=1_000_000)
    assert usage.estimated_cost(0.75, 4.50) == 5.25


def test_create_memory_uses_independent_embedding_cache(tmp_path, monkeypatch):
    captured_kwargs = {}

    class FakeMemoryManager:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr("benchmarks.locomo_light.MemoryManager", FakeMemoryManager)
    cache_file = tmp_path / "benchmark-cache" / "embeddings.json"

    create_memory(
        tmp_path / "memory",
        {"embedding": {"provider": "openai", "model_name": "test-model"}},
        cache_file,
    )

    assert captured_kwargs["embedding_cache_file"] == str(cache_file)
    assert captured_kwargs["strict_hybrid_retrieval"] is True
