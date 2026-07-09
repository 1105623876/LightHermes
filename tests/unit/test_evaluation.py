"""记忆质量评估测试"""

import pytest

from lighthermes.evaluation import (
    MemoryEvalCase,
    MemoryEvalSeed,
    MemoryQualityEvaluator,
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
