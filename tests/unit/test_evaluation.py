"""记忆质量评估测试"""

import pytest

from lighthermes.evaluation import (
    MemoryEvalCase,
    MemoryEvalSeed,
    MemoryQualityEvaluator,
    build_memory_eval_v2_extended_suite,
    build_memory_eval_v2_suite,
)
from lighthermes.memory import MemoryManager


@pytest.mark.unit
class TestMemoryQualityEvaluator:
    def test_passes_when_expected_memory_is_recalled(self, temp_memory_dir):
        mm = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        evaluator = MemoryQualityEvaluator(mm)
        evaluator.seed([
            MemoryEvalSeed(
                layer="semantic",
                name="pref_style",
                content="用户偏好：回答要简洁清晰，避免过度解释。",
                metadata={"type": "user_preference"}
            )
        ])

        result = evaluator.run_case(MemoryEvalCase(
            name="preference_recall",
            query="用户回答风格偏好",
            expected_substrings=["简洁清晰"],
            expected_layers=["semantic"],
        ))

        assert result.passed is True
        assert result.score == 1.0
        assert result.retrieved_sources == ["semantic:pref_style"]

    def test_fails_when_forbidden_memory_is_recalled(self, temp_memory_dir):
        mm = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        evaluator = MemoryQualityEvaluator(mm)
        evaluator.seed([
            MemoryEvalSeed(
                layer="semantic",
                name="pref_python",
                content="用户偏好：主要使用 Python 编程。",
            ),
            MemoryEvalSeed(
                layer="semantic",
                name="pref_tea",
                content="用户偏好：喜欢红茶。",
            )
        ])

        result = evaluator.run_case(MemoryEvalCase(
            name="forbidden_noise",
            query="用户偏好",
            expected_substrings=["Python"],
            forbidden_substrings=["红茶"],
            expected_layers=["semantic"],
        ))

        assert result.passed is False
        assert result.forbidden_hits == ["红茶"]
        assert result.forbidden_hit_count == 1

    def test_report_summarizes_multiple_cases(self, temp_memory_dir):
        mm = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        evaluator = MemoryQualityEvaluator(mm)
        evaluator.seed([
            MemoryEvalSeed(
                layer="working",
                name="session_1",
                content="阶段总结：修复 config 加载 bug。",
            ),
            MemoryEvalSeed(
                layer="episodic",
                name="debug_case",
                content="调试经验：遇到完整错误日志时先读完日志再修改。",
            )
        ])

        report = evaluator.run([
            MemoryEvalCase(
                name="working_summary",
                query="config bug",
                expected_substrings=["config 加载 bug"],
                expected_layers=["working"],
            ),
            MemoryEvalCase(
                name="debug_experience",
                query="错误日志 修改",
                expected_substrings=["先读完日志"],
                expected_layers=["episodic"],
            ),
        ])

        assert report.passed is True
        assert report.pass_rate == 1.0
        assert report.average_score == 1.0
        assert report.to_dict()["results"][0]["name"] == "working_summary"

    def test_seed_rejects_unknown_layer(self, temp_memory_dir):
        mm = MemoryManager(memory_dir=temp_memory_dir, use_hybrid_retrieval=False)
        evaluator = MemoryQualityEvaluator(mm)

        with pytest.raises(ValueError, match="seed.layer"):
            evaluator.seed([
                MemoryEvalSeed(layer="unknown", name="bad", content="bad")
            ])

    def test_ranked_source_metrics_measure_recall_precision_and_mrr(self):
        class FakeMemory:
            def recall_items(self, *args, **kwargs):
                return [
                    {"source": "semantic:noise", "layer": "semantic", "content": "噪声"},
                    {"source": "semantic:target_b", "layer": "semantic", "content": "目标 B"},
                    {"source": "semantic:target_a", "layer": "semantic", "content": "目标 A"},
                ]

        result = MemoryQualityEvaluator(FakeMemory()).run_case(MemoryEvalCase(
            name="ranked_recall",
            category="ranking",
            query="目标",
            expected_sources=["semantic:target_a", "semantic:target_b"],
            max_noise_rate=0.34,
        ))

        assert result.passed is True
        assert result.category == "ranking"
        assert result.source_hit_count == 2
        assert result.recall_at_k == 1.0
        assert result.reciprocal_rank == 0.5
        assert result.precision_at_k == pytest.approx(2 / 3, abs=0.0001)
        assert result.noise_rate == pytest.approx(1 / 3, abs=0.0001)
        assert result.latency_ms >= 0

    def test_ranked_source_metrics_fail_on_missing_or_forbidden_source(self):
        class FakeMemory:
            def recall_items(self, *args, **kwargs):
                return [
                    {"source": "semantic:forbidden", "layer": "semantic", "content": "错误事实"},
                    {"source": "semantic:target_a", "layer": "semantic", "content": "目标 A"},
                ]

        result = MemoryQualityEvaluator(FakeMemory()).run_case(MemoryEvalCase(
            name="ranked_failure",
            query="目标",
            expected_sources=["semantic:target_a", "semantic:target_b"],
            forbidden_sources=["semantic:forbidden"],
        ))

        assert result.passed is False
        assert result.missing_sources == ["semantic:target_b"]
        assert result.forbidden_source_hits == ["semantic:forbidden"]
        assert result.recall_at_k == 0.5

    def test_report_aggregates_ranked_metrics_by_category(self):
        class FakeMemory:
            def recall_items(self, query, **kwargs):
                source = "semantic:a" if query == "hit" else "semantic:noise"
                return [{"source": source, "layer": "semantic", "content": source}]

        report = MemoryQualityEvaluator(FakeMemory()).run([
            MemoryEvalCase(
                name="hit",
                category="preference",
                query="hit",
                expected_sources=["semantic:a"],
            ),
            MemoryEvalCase(
                name="miss",
                category="decision",
                query="miss",
                expected_sources=["semantic:b"],
            ),
        ])

        payload = report.to_dict()
        assert report.average_recall_at_k == 0.5
        assert report.mean_reciprocal_rank == 0.5
        assert report.average_precision_at_k == 0.5
        assert payload["metric_version"] == "2.0"
        assert payload["categories"]["preference"]["pass_rate"] == 1.0
        assert payload["categories"]["decision"]["pass_rate"] == 0.0
        assert payload["average_latency_ms"] >= 0

    def test_default_v2_suite_covers_initial_quality_categories(self):
        suite = build_memory_eval_v2_suite()

        assert suite.version == "2.0"
        assert suite.seeds
        assert {case.category for case in suite.cases} == {
            "preference",
            "project_decision",
            "cross_lingual",
            "noise_control",
        }
        assert all(case.expected_sources for case in suite.cases)

    def test_v2_case_keeps_v1_positional_arguments_compatible(self):
        case = MemoryEvalCase(
            "legacy",
            "query",
            ["expected"],
            ["forbidden"],
            ["semantic"],
            1,
            5,
            1000,
            "user_1",
        )

        assert case.expected_substrings == ["expected"]
        assert case.limit == 5
        assert case.user_id == "user_1"
        assert case.category == "general"

    def test_case_can_limit_evaluated_memory_layers(self):
        class FakeMemory:
            def __init__(self):
                self.layers = None

            def recall_items(self, query, **kwargs):
                self.layers = kwargs.get("layers")
                return []

        memory = FakeMemory()
        evaluator = MemoryQualityEvaluator(memory)

        evaluator.run_case(MemoryEvalCase(
            name="semantic_only",
            query="query",
            layers=["semantic"],
        ))

        assert memory.layers == ["semantic"]

    def test_report_evaluates_explicit_quality_gates(self):
        class FakeMemory:
            def recall_items(self, query, **kwargs):
                if query == "hit":
                    return [{"source": "semantic:target", "content": "target", "layer": "semantic"}]
                return [{"source": "semantic:noise", "content": "noise", "layer": "semantic"}]

        report = MemoryQualityEvaluator(FakeMemory()).run([
            MemoryEvalCase(name="hit", query="hit", expected_sources=["semantic:target"]),
            MemoryEvalCase(name="miss", query="miss", expected_sources=["semantic:target"]),
        ])
        gate = report.evaluate_quality_gates({
            "min_pass_rate": 0.75,
            "min_recall_at_k": 0.75,
            "max_noise_rate": 0.4,
        })

        assert gate["passed"] is False
        assert gate["checks"]["min_pass_rate"]["actual"] == 0.5
        assert gate["checks"]["max_noise_rate"]["passed"] is False

    def test_extended_suite_has_scale_diversity_and_quality_gates(self):
        suite = build_memory_eval_v2_extended_suite()

        assert suite.version == "2.1"
        assert len(suite.seeds) == 64
        assert len(suite.cases) >= 24
        assert {seed.layer for seed in suite.seeds} == {
            "working",
            "episodic",
            "semantic",
        }
        assert {
            "preference",
            "project_decision",
            "incident",
            "cross_lingual",
            "conflict",
            "noise_control",
            "cross_layer",
        }.issubset({case.category for case in suite.cases})
        assert suite.quality_gates["min_recall_at_k"] >= 0.9
        assert suite.quality_gates["max_noise_rate"] <= 0.35
