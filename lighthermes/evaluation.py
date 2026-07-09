"""
LightHermes 离线记忆质量评估

第一版只做确定性评估，避免引入模型成本。
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence


@dataclass
class MemoryEvalSeed:
    """一条待写入的测试记忆"""

    layer: str
    name: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)
    user_id: str = "default"


@dataclass
class MemoryEvalCase:
    """一个记忆召回评估用例"""

    name: str
    query: str
    expected_substrings: List[str] = field(default_factory=list)
    forbidden_substrings: List[str] = field(default_factory=list)
    expected_layers: List[str] = field(default_factory=list)
    min_expected_hits: int = 1
    limit: int = 8
    max_chars: int = 4000
    user_id: str = "default"


@dataclass
class MemoryEvalResult:
    """单个评估用例的结果"""

    name: str
    passed: bool
    score: float
    expected_hit_count: int
    forbidden_hit_count: int
    layer_hit_count: int
    retrieved_count: int
    missing_expected: List[str]
    forbidden_hits: List[str]
    missing_layers: List[str]
    retrieved_sources: List[str]


@dataclass
class MemoryEvalReport:
    """一组评估用例的汇总结果"""

    results: List[MemoryEvalResult]

    @property
    def passed(self) -> bool:
        return all(result.passed for result in self.results)

    @property
    def pass_rate(self) -> float:
        if not self.results:
            return 1.0
        return sum(1 for result in self.results if result.passed) / len(self.results)

    @property
    def average_score(self) -> float:
        if not self.results:
            return 1.0
        return sum(result.score for result in self.results) / len(self.results)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "average_score": self.average_score,
            "results": [result.__dict__ for result in self.results],
        }


class MemoryQualityEvaluator:
    """基于 MemoryManager 的确定性记忆质量评估器"""

    def __init__(self, memory_manager: Any):
        self.memory = memory_manager

    def seed(self, seeds: Sequence[MemoryEvalSeed]):
        """写入评估用测试记忆"""
        for seed in seeds:
            layer = seed.layer.lower()
            if layer == "working":
                self.memory.save_session(seed.name, seed.user_id, seed.content)
            elif layer == "episodic":
                self.memory.save_episodic(seed.name, seed.content, seed.metadata)
            elif layer == "semantic":
                self.memory.save_semantic(seed.name, seed.content, seed.metadata)
            else:
                raise ValueError("seed.layer must be one of: working, episodic, semantic")

    def run_case(self, case: MemoryEvalCase) -> MemoryEvalResult:
        """运行单个评估用例"""
        items = self.memory.recall_items(
            case.query,
            user_id=case.user_id,
            limit=case.limit,
            max_chars=case.max_chars
        )
        contents = [str(item.get("content", "")) for item in items]
        combined = "\n".join(contents)
        layers = {str(item.get("layer", "")) for item in items}

        missing_expected = [
            text for text in case.expected_substrings
            if text not in combined
        ]
        forbidden_hits = [
            text for text in case.forbidden_substrings
            if text in combined
        ]
        missing_layers = [
            layer for layer in case.expected_layers
            if layer not in layers
        ]

        expected_hit_count = len(case.expected_substrings) - len(missing_expected)
        forbidden_hit_count = len(forbidden_hits)
        layer_hit_count = len(case.expected_layers) - len(missing_layers)

        expected_total = max(len(case.expected_substrings), 1)
        layer_total = max(len(case.expected_layers), 1)
        expected_score = expected_hit_count / expected_total
        layer_score = layer_hit_count / layer_total
        noise_score = 1.0 if forbidden_hit_count == 0 else 0.0
        score = round((expected_score * 0.7) + (layer_score * 0.2) + (noise_score * 0.1), 4)

        passed = (
            expected_hit_count >= case.min_expected_hits and
            forbidden_hit_count == 0 and
            not missing_layers
        )

        return MemoryEvalResult(
            name=case.name,
            passed=passed,
            score=score,
            expected_hit_count=expected_hit_count,
            forbidden_hit_count=forbidden_hit_count,
            layer_hit_count=layer_hit_count,
            retrieved_count=len(items),
            missing_expected=missing_expected,
            forbidden_hits=forbidden_hits,
            missing_layers=missing_layers,
            retrieved_sources=[str(item.get("source", "")) for item in items],
        )

    def run(self, cases: Sequence[MemoryEvalCase]) -> MemoryEvalReport:
        """运行一组评估用例"""
        return MemoryEvalReport([self.run_case(case) for case in cases])
