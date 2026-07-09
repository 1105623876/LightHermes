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
    MemoryQualityEvaluator,
)

__all__ = [
    "LightHermes",
    "tool",
    "MemoryEvalCase",
    "MemoryEvalReport",
    "MemoryEvalResult",
    "MemoryEvalSeed",
    "MemoryQualityEvaluator",
]
