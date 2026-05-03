"""自进化系统单元测试"""
import json

import pytest

from lighthermes.evolution import EvolutionEngine, SkillGenerator, TrajectoryAnalyzer


GENERATED_SKILL = """---
name: generated_test_skill
description: 测试生成技能
type: skill
---

## 步骤
- 复用成功轨迹。
"""


class FakeAdapter:
    def __init__(self, content=GENERATED_SKILL):
        self.content = content
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return self.content


class FakeOpenAIResponse:
    def __init__(self, content):
        class Message:
            def __init__(self, text):
                self.content = text

        class Choice:
            def __init__(self, text):
                self.message = Message(text)

        self.choices = [Choice(content)]


class FakeOpenAIClient:
    def __init__(self, content=GENERATED_SKILL):
        class Completions:
            def __init__(self, text):
                self.text = text
                self.calls = []

            def create(self, **kwargs):
                self.calls.append(kwargs)
                return FakeOpenAIResponse(self.text)

        class Chat:
            def __init__(self, text):
                self.completions = Completions(text)

        self.chat = Chat(content)


@pytest.mark.unit
class TestTrajectoryQuality:
    """测试轨迹质量评估"""

    def test_high_quality_success_is_learning_worthy(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)
        trajectory = {
            "success": True,
            "tool_calls": [],
            "user_corrections": 0,
            "iterations": 0
        }

        quality = analyzer.evaluate_quality(trajectory)

        assert quality["quality_score"] == 100
        assert quality["quality_level"] == "high"
        assert quality["learning_worthy"] is True
        assert quality["quality_metrics"]["first_attempt_success"] is True

    def test_many_corrections_lower_quality(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)
        trajectory = {
            "success": True,
            "tool_calls": [{"tool": "search"}] * 8,
            "user_corrections": 3,
            "iterations": 8
        }

        quality = analyzer.evaluate_quality(trajectory)

        assert quality["quality_score"] < analyzer.quality_threshold
        assert quality["quality_level"] in ("medium", "low")
        assert quality["learning_worthy"] is False

    def test_failure_is_not_learning_worthy_success(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)
        trajectory = {
            "success": False,
            "tool_calls": [],
            "user_corrections": 0,
            "iterations": 0
        }

        quality = analyzer.evaluate_quality(trajectory)

        assert quality["quality_score"] == 0
        assert quality["learning_worthy"] is False
        assert analyzer.should_learn_from_success(trajectory) is False

    def test_legacy_trajectory_quality_can_be_computed(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)
        trajectory = {
            "success": True,
            "tool_calls": [{"tool": "read"}],
            "user_corrections": 0
        }

        assert "quality_score" not in trajectory
        assert analyzer.should_learn_from_success(trajectory) is True


@pytest.mark.unit
class TestAnalyzePatternsQualityFilter:
    """测试模式分析中的质量过滤"""

    def test_success_patterns_only_use_high_quality_trajectories(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)

        for i in range(3):
            analyzer.save_trajectory(
                session_id=f"high_{i}",
                messages=[{"role": "user", "content": "写代码"}],
                tool_calls=[],
                success=True,
                task_type="代码"
            )

        analyzer.save_trajectory(
            session_id="low_quality",
            messages=[{"role": "user", "content": "写代码"}],
            tool_calls=[{"tool": "search"}] * 8,
            success=True,
            task_type="代码",
            user_corrections=3,
            iterations=8
        )

        patterns = analyzer.analyze_patterns(min_success_count=3)

        assert len(patterns["success_patterns"]) == 1
        pattern = patterns["success_patterns"][0]
        assert pattern["count"] == 3
        assert pattern["filtered_count"] == 1
        assert all(t["learning_worthy"] for t in pattern["trajectories"])

    def test_low_quality_successes_do_not_form_pattern(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)

        for i in range(3):
            analyzer.save_trajectory(
                session_id=f"low_{i}",
                messages=[{"role": "user", "content": "调试"}],
                tool_calls=[{"tool": "search"}] * 8,
                success=True,
                task_type="调试",
                user_corrections=3,
                iterations=8
            )

        patterns = analyzer.analyze_patterns(min_success_count=3)

        assert patterns["success_patterns"] == []

    def test_failure_patterns_are_not_quality_filtered(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)

        for i in range(2):
            analyzer.save_trajectory(
                session_id=f"failure_{i}",
                messages=[{"role": "user", "content": "配置"}],
                tool_calls=[],
                success=False,
                task_type="配置"
            )

        patterns = analyzer.analyze_patterns(min_failure_count=2)

        assert len(patterns["failure_patterns"]) == 1
        assert patterns["failure_patterns"][0]["count"] == 2

    def test_legacy_files_are_supported(self, temp_memory_dir):
        analyzer = TrajectoryAnalyzer(temp_memory_dir)
        file_path = analyzer.trajectory_dir / "legacy.json"
        file_path.write_text(json.dumps({
            "session_id": "legacy",
            "timestamp": "2026-05-03T00:00:00",
            "task_type": "解释",
            "success": True,
            "messages": [],
            "tool_calls": [],
            "user_corrections": 0,
            "iterations": 0
        }), encoding="utf-8")

        patterns = analyzer.analyze_patterns(min_success_count=1)

        assert len(patterns["success_patterns"]) == 1
        trajectory = patterns["success_patterns"][0]["trajectories"][0]
        assert trajectory["quality_score"] == 100
        assert trajectory["learning_worthy"] is True


@pytest.mark.unit
class TestSkillGeneratorAdapter:
    """测试技能生成器的 adapter 兼容路径"""

    def test_generate_skill_uses_adapter_create(self):
        adapter = FakeAdapter()
        generator = SkillGenerator(adapter, model="test-model")
        pattern = {
            "task_type": "代码",
            "trajectories": [{"tool_calls": [{"tool": "read"}]}]
        }

        skill = generator.generate_skill_from_pattern(pattern, "success")

        assert skill["name"] == "generated_test_skill"
        assert adapter.calls[0]["messages"][0]["role"] == "user"
        assert adapter.calls[0]["temperature"] == 0.7

    def test_generate_skill_supports_openai_like_client(self):
        client = FakeOpenAIClient()
        generator = SkillGenerator(client, model="test-model")
        pattern = {
            "task_type": "配置",
            "trajectories": [{"tool_calls": []}]
        }

        skill = generator.generate_skill_from_pattern(pattern, "failure")

        assert skill["name"] == "generated_test_skill"
        call = client.chat.completions.calls[0]
        assert call["model"] == "test-model"
        assert call["temperature"] == 0.7


@pytest.mark.unit
class TestEvolutionEngineRecordSession:
    """测试进化引擎会话记录"""

    def test_record_session_writes_quality_fields(self, temp_memory_dir):
        engine = EvolutionEngine(
            client=None,
            trajectory_dir=temp_memory_dir,
            skill_output_dir=f"{temp_memory_dir}/skills"
        )

        engine.record_session(
            session_id="session_1",
            messages=[{"role": "user", "content": "写一个函数"}],
            tool_calls=[{"tool": "python", "name": "python", "arguments": "{}"}],
            success=True,
            task_type="代码",
            iterations=1
        )

        trajectory = engine.analyzer.load_trajectory("session_1")

        assert trajectory["quality_score"] == 100
        assert trajectory["quality_level"] == "high"
        assert trajectory["learning_worthy"] is True
        assert trajectory["quality_version"] == "1.0"
        assert trajectory["tool_calls"][0]["tool"] == "python"

    def test_evolve_generates_skill_with_adapter(self, temp_memory_dir):
        engine = EvolutionEngine(
            client=FakeAdapter(),
            trajectory_dir=temp_memory_dir,
            skill_output_dir=f"{temp_memory_dir}/skills",
            min_success_count=1,
            skill_validation="none"
        )
        engine.record_session(
            session_id="session_1",
            messages=[{"role": "user", "content": "写一个函数"}],
            tool_calls=[],
            success=True,
            task_type="代码",
            iterations=0
        )

        result = engine.evolve()

        assert result["success_skills"] == ["generated_test_skill"]
        assert result["errors"] == []
