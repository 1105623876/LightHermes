"""
LightHermes - 轻量级自进化智能体框架
"""

__version__ = "0.3.4"

from lighthermes.core import LightHermes, tool
from lighthermes.evaluation import (
    MemoryEvalCase,
    MemoryEvalReport,
    MemoryEvalResult,
    MemoryEvalSeed,
    MemoryEvalSuite,
    MemoryQualityEvaluator,
    build_memory_eval_v2_extended_suite,
    build_memory_eval_v2_suite,
)

__all__ = [
    "LightHermes",
    "tool",
    "MemoryEvalCase",
    "MemoryEvalReport",
    "MemoryEvalResult",
    "MemoryEvalSeed",
    "MemoryEvalSuite",
    "MemoryQualityEvaluator",
    "build_memory_eval_v2_extended_suite",
    "build_memory_eval_v2_suite",
]
