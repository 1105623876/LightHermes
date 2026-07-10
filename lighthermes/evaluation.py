"""
LightHermes 离线记忆质量评估

使用确定性指标评估记忆召回，避免引入模型成本。
"""

import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence


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
    category: str = "general"
    expected_sources: List[str] = field(default_factory=list)
    forbidden_sources: List[str] = field(default_factory=list)
    min_source_recall: float = 1.0
    max_noise_rate: Optional[float] = None
    layers: Optional[List[str]] = None


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
    category: str = "general"
    source_expectation_count: int = 0
    source_hit_count: int = 0
    missing_sources: List[str] = field(default_factory=list)
    forbidden_source_hits: List[str] = field(default_factory=list)
    recall_at_k: float = 1.0
    reciprocal_rank: float = 1.0
    precision_at_k: float = 1.0
    noise_rate: float = 0.0
    latency_ms: float = 0.0


@dataclass
class MemoryEvalSuite:
    """一组可复用的评估种子和用例"""

    name: str
    version: str
    seeds: List[MemoryEvalSeed]
    cases: List[MemoryEvalCase]
    quality_gates: Dict[str, float] = field(default_factory=dict)


@dataclass
class MemoryEvalReport:
    """一组评估用例的汇总结果"""

    results: List[MemoryEvalResult]
    metric_version: str = "2.0"

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

    @property
    def ranked_results(self) -> List[MemoryEvalResult]:
        return [
            result for result in self.results
            if result.source_expectation_count > 0
        ]

    @staticmethod
    def _average(
        results: Sequence[MemoryEvalResult],
        attribute: str,
        default: float
    ) -> float:
        if not results:
            return default
        return sum(float(getattr(result, attribute)) for result in results) / len(results)

    @property
    def average_recall_at_k(self) -> float:
        return self._average(self.ranked_results, "recall_at_k", 1.0)

    @property
    def mean_reciprocal_rank(self) -> float:
        return self._average(self.ranked_results, "reciprocal_rank", 1.0)

    @property
    def average_precision_at_k(self) -> float:
        return self._average(self.ranked_results, "precision_at_k", 1.0)

    @property
    def average_noise_rate(self) -> float:
        return self._average(self.ranked_results, "noise_rate", 0.0)

    @property
    def average_latency_ms(self) -> float:
        return self._average(self.results, "latency_ms", 0.0)

    @property
    def category_metrics(self) -> Dict[str, Dict[str, Any]]:
        categories = {}
        for category in sorted({result.category for result in self.results}):
            results = [result for result in self.results if result.category == category]
            ranked = [result for result in results if result.source_expectation_count > 0]
            categories[category] = {
                "case_count": len(results),
                "pass_rate": sum(1 for result in results if result.passed) / len(results),
                "average_score": self._average(results, "score", 1.0),
                "recall_at_k": self._average(ranked, "recall_at_k", 1.0),
                "mean_reciprocal_rank": self._average(ranked, "reciprocal_rank", 1.0),
                "precision_at_k": self._average(ranked, "precision_at_k", 1.0),
                "noise_rate": self._average(ranked, "noise_rate", 0.0),
                "average_latency_ms": self._average(results, "latency_ms", 0.0),
            }
        return categories

    def evaluate_quality_gates(self, gates: Dict[str, float]) -> Dict[str, Any]:
        """根据显式门槛判断评估报告是否达到目标质量"""
        metrics = {
            "min_pass_rate": self.pass_rate,
            "min_recall_at_k": self.average_recall_at_k,
            "min_mean_reciprocal_rank": self.mean_reciprocal_rank,
            "min_precision_at_k": self.average_precision_at_k,
            "max_noise_rate": self.average_noise_rate,
            "max_average_latency_ms": self.average_latency_ms,
        }
        checks = {}
        for name, target in gates.items():
            if name not in metrics:
                raise ValueError(f"unsupported quality gate: {name}")
            actual = metrics[name]
            passed = actual >= target if name.startswith("min_") else actual <= target
            checks[name] = {
                "actual": actual,
                "target": target,
                "passed": passed,
            }
        return {
            "passed": all(check["passed"] for check in checks.values()),
            "checks": checks,
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "metric_version": self.metric_version,
            "passed": self.passed,
            "pass_rate": self.pass_rate,
            "average_score": self.average_score,
            "average_recall_at_k": self.average_recall_at_k,
            "mean_reciprocal_rank": self.mean_reciprocal_rank,
            "average_precision_at_k": self.average_precision_at_k,
            "average_noise_rate": self.average_noise_rate,
            "average_latency_ms": self.average_latency_ms,
            "categories": self.category_metrics,
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
        start_time = time.perf_counter()
        items = self.memory.recall_items(
            case.query,
            user_id=case.user_id,
            layers=case.layers,
            limit=case.limit,
            max_chars=case.max_chars
        )
        latency_ms = (time.perf_counter() - start_time) * 1000
        contents = [str(item.get("content", "")) for item in items]
        combined = "\n".join(contents)
        layers = {str(item.get("layer", "")) for item in items}
        retrieved_sources = [str(item.get("source", "")) for item in items]

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
        expected_source_set = set(case.expected_sources)
        forbidden_source_set = set(case.forbidden_sources)
        retrieved_source_set = set(retrieved_sources)
        missing_sources = [
            source for source in case.expected_sources
            if source not in retrieved_source_set
        ]
        forbidden_source_hits = [
            source for source in retrieved_sources
            if source in forbidden_source_set
        ]

        expected_hit_count = len(case.expected_substrings) - len(missing_expected)
        forbidden_hit_count = len(forbidden_hits)
        layer_hit_count = len(case.expected_layers) - len(missing_layers)
        source_hit_count = len(expected_source_set & retrieved_source_set)

        if expected_source_set:
            recall_at_k = source_hit_count / len(expected_source_set)
            precision_at_k = source_hit_count / len(retrieved_sources) if retrieved_sources else 0.0
            first_rank = next((
                index for index, source in enumerate(retrieved_sources, start=1)
                if source in expected_source_set
            ), None)
            reciprocal_rank = 1.0 / first_rank if first_rank else 0.0
            noise_rate = 1.0 - precision_at_k
        else:
            recall_at_k = 1.0
            reciprocal_rank = 1.0
            precision_at_k = 1.0
            noise_rate = 0.0

        score_components = []
        if case.expected_substrings:
            score_components.append(expected_hit_count / len(case.expected_substrings))
        if case.expected_layers:
            score_components.append(layer_hit_count / len(case.expected_layers))
        if case.expected_sources:
            score_components.extend([recall_at_k, reciprocal_rank, precision_at_k])
        score_components.append(
            1.0 if forbidden_hit_count == 0 and not forbidden_source_hits else 0.0
        )
        score = round(sum(score_components) / len(score_components), 4)

        passed = (
            (not case.expected_substrings or expected_hit_count >= case.min_expected_hits) and
            forbidden_hit_count == 0 and
            not missing_layers and
            not forbidden_source_hits and
            (not case.expected_sources or recall_at_k >= case.min_source_recall) and
            (case.max_noise_rate is None or noise_rate <= case.max_noise_rate)
        )

        return MemoryEvalResult(
            name=case.name,
            category=case.category,
            passed=passed,
            score=score,
            expected_hit_count=expected_hit_count,
            forbidden_hit_count=forbidden_hit_count,
            layer_hit_count=layer_hit_count,
            retrieved_count=len(items),
            missing_expected=missing_expected,
            forbidden_hits=forbidden_hits,
            missing_layers=missing_layers,
            retrieved_sources=retrieved_sources,
            source_expectation_count=len(case.expected_sources),
            source_hit_count=source_hit_count,
            missing_sources=missing_sources,
            forbidden_source_hits=forbidden_source_hits,
            recall_at_k=round(recall_at_k, 4),
            reciprocal_rank=round(reciprocal_rank, 4),
            precision_at_k=round(precision_at_k, 4),
            noise_rate=round(noise_rate, 4),
            latency_ms=round(latency_ms, 4),
        )

    def run(self, cases: Sequence[MemoryEvalCase]) -> MemoryEvalReport:
        """运行一组评估用例"""
        return MemoryEvalReport([self.run_case(case) for case in cases])


def build_memory_eval_v2_suite() -> MemoryEvalSuite:
    """构建不包含真实用户数据的 v2 合成评估集"""
    seeds = [
        MemoryEvalSeed(
            layer="semantic",
            name="pref_style",
            content="用户偏好：回答保持简洁清晰，避免过度解释。",
            metadata={"type": "user_preference"}
        ),
        MemoryEvalSeed(
            layer="semantic",
            name="pref_language",
            content="用户偏好：编程任务主要使用 Python。",
            metadata={"type": "user_preference"}
        ),
        MemoryEvalSeed(
            layer="semantic",
            name="pref_drink",
            content="用户偏好：日常饮品喜欢乌龙茶。",
            metadata={"type": "user_preference"}
        ),
        MemoryEvalSeed(
            layer="episodic",
            name="decision_storage",
            content="项目决定使用 SQLite 保存工作记忆，因为它轻量且无需外部服务。",
            metadata={"type": "decision"}
        ),
        MemoryEvalSeed(
            layer="episodic",
            name="incident_timeout",
            content="调试经验：HTTP timeout 后检查重试次数与退避策略。",
            metadata={"type": "incident"}
        ),
    ]
    cases = [
        MemoryEvalCase(
            name="preference_style",
            category="preference",
            query="回答风格要简洁清晰",
            expected_substrings=["简洁清晰"],
            expected_sources=["semantic:pref_style"],
            forbidden_sources=["semantic:pref_drink"],
            max_noise_rate=0.8,
        ),
        MemoryEvalCase(
            name="storage_decision",
            category="project_decision",
            query="项目为什么选择 SQLite 保存工作记忆",
            expected_substrings=["无需外部服务"],
            expected_sources=["episodic:decision_storage"],
            forbidden_sources=["episodic:incident_timeout"],
            max_noise_rate=0.8,
        ),
        MemoryEvalCase(
            name="cross_lingual_language_preference",
            category="cross_lingual",
            query="Which programming language does the user prefer?",
            expected_substrings=["Python"],
            expected_sources=["semantic:pref_language"],
            forbidden_sources=["semantic:pref_drink"],
            max_noise_rate=0.8,
        ),
        MemoryEvalCase(
            name="timeout_noise_control",
            category="noise_control",
            query="HTTP timeout retry backoff",
            expected_substrings=["退避策略"],
            expected_sources=["episodic:incident_timeout"],
            forbidden_sources=["semantic:pref_drink"],
            max_noise_rate=0.8,
        ),
    ]
    return MemoryEvalSuite(
        name="memory_quality_v2_synthetic",
        version="2.0",
        seeds=seeds,
        cases=cases,
    )


def build_memory_eval_v2_extended_suite() -> MemoryEvalSuite:
    """构建覆盖多层记忆、硬负例和冲突事实的扩展合成评估集"""
    semantic_targets = [
        ("pref_response_language", "用户当前要求所有技术回答使用简体中文，英文术语可以保留。", "user_preference"),
        ("pref_answer_style", "用户偏好先给结论再给必要依据，避免冗长背景。", "user_preference"),
        ("pref_python_version", "用户项目统一使用 Python 3.10，暂不升级到 Python 3.12。", "user_preference"),
        ("pref_secret_scope", "用户不希望设置全局环境变量，密钥只放项目 .env.local。", "user_preference"),
        ("pref_embedding_model", "记忆质量评测统一使用 BGE-M3 作为嵌入模型。", "user_preference"),
        ("current_semantic_threshold", "当前 BGE-M3 semantic_threshold 已调整为 0.50。", "config_fact"),
        ("current_score_margin", "当前 BGE-M3 score_margin 已调整为 0.08。", "config_fact"),
        ("current_release", "当前稳定分支是 master，发布版本为 v0.3.4。", "project_fact"),
        ("semantic_storage", "语义记忆的长期知识使用 Markdown 文件保存，便于人工检查。", "architecture"),
        ("file_write_policy", "文件写入工具默认关闭，必须在配置中显式开启。", "security_policy"),
    ]
    episodic_targets = [
        ("decision_working_storage", "项目决定使用 SQLite 保存工作记忆，因为轻量且无需外部服务。", "decision"),
        ("incident_stream_finalize", "流式响应修复：完整消费流后统一执行回合收尾并保存最终回复。", "incident"),
        ("incident_index_cleanup", "容量清理时必须同步删除倒排索引条目，避免召回已删除记忆。", "incident"),
        ("decision_skip_memory_graph", "项目决定暂缓记忆图谱，优先完成分级记忆与蒸馏治理。", "decision"),
        ("decision_adapter_boundary", "模型供应商差异统一放在 BaseAdapter 边界内处理。", "decision"),
        ("incident_local_env", "本地密钥读取问题通过项目级 .env.local 与 secrets.env_file 解决。", "incident"),
        ("decision_plugin_timing", "插件生态延后到核心生命周期和记忆质量稳定之后推进。", "decision"),
        ("incident_recall_performance", "500 条记忆召回通过复用 mtime 缓存减少重复文件 stat。", "incident"),
        ("incident_read_full_error", "调试失败经验：先阅读完整错误日志，再定位根因和修改代码。", "incident"),
        ("incident_minimax_stream", "MiniMax cumulative chunks must be converted into incremental stream text.", "incident"),
        ("incident_http_backoff", "HTTP timeout 后应限制重试次数并采用指数退避策略。", "incident"),
    ]
    working_memories = [
        ("work_eval", "当前会话正在扩展高质量记忆评测集。"),
        ("work_pending", "下一步待办是分析冲突记忆与多用户隔离。"),
        ("work_docs", "当前会话稍后需要同步 README 的测试数字。"),
        ("work_release", "当前会话不创建新版本标签。"),
    ]
    hard_negatives = [
        ("semantic", "old_response_english", "历史偏好：所有回答都使用英文。", "historical"),
        ("semantic", "old_python_312", "历史计划：项目立即升级到 Python 3.12。", "historical"),
        ("semantic", "old_global_env", "旧建议：把所有 API key 设置为全局环境变量。", "historical"),
        ("semantic", "old_threshold_035", "旧配置记录：BGE-M3 semantic_threshold 为 0.35。", "historical"),
        ("semantic", "old_margin_012", "旧配置记录：BGE-M3 score_margin 为 0.12。", "historical"),
        ("semantic", "old_release_033", "旧发布记录：稳定版本为 v0.3.3。", "historical"),
        ("episodic", "rejected_postgres", "被否决方案：工作记忆改用 PostgreSQL 服务。", "rejected"),
        ("episodic", "rejected_memory_graph", "被否决方案：立即实现完整记忆图谱作为主线。", "rejected"),
        ("semantic", "unsafe_file_write_default", "不安全旧方案：文件写入工具默认开启。", "rejected"),
        ("semantic", "old_embedding_model", "旧评测配置使用 text-embedding-3-small。", "historical"),
        ("episodic", "ignore_error_log", "错误做法：忽略完整日志并直接尝试随机修改。", "failure_report"),
        ("episodic", "retry_without_backoff", "错误做法：HTTP timeout 后无限立即重试。", "failure_report"),
    ]
    distractor_contents = [
        ("gardening", "园艺记录：番茄幼苗应根据土壤湿度控制浇水频率。"),
        ("baking", "烘焙笔记：高筋面粉适合制作需要筋度的面包。"),
        ("travel", "旅行计划：博物馆通常在周一闭馆，出发前需要确认。"),
        ("music", "音乐知识：爵士和声常使用七和弦与扩展音。"),
        ("photography", "摄影设置：低光环境需要平衡快门速度与 ISO。"),
        ("finance", "个人预算应区分固定支出、可变支出与应急储备。"),
        ("fitness", "训练安排：力量训练后需要保留恢复时间。"),
        ("astronomy", "天文知识：木星是太阳系体积最大的行星。"),
        ("history", "历史笔记：工业革命改变了生产组织与城市结构。"),
        ("architecture", "建筑设计：自然采光会影响空间朝向和开窗比例。"),
        ("frontend", "前端经验：表单提交前应显示明确的校验错误。"),
        ("connection_pool", "数据库连接池需要限制最大连接数并处理空闲回收。"),
        ("tls", "安全配置：TLS 证书到期前应自动告警和轮换。"),
        ("docker", "容器镜像应使用固定版本并减少不必要的构建层。"),
        ("git", "Git 协作中避免对共享分支执行 force push。"),
        ("unit_testing", "单元测试应覆盖正常路径、边界条件和错误处理。"),
        ("observability", "可观测性需要关联日志、指标和请求追踪。"),
        ("cache_eviction", "缓存淘汰策略应结合容量、访问频率和过期时间。"),
        ("message_queue", "消息队列消费者需要保证幂等并处理重复投递。"),
        ("search_index", "搜索索引更新应与原始数据变更保持一致。"),
        ("product_design", "产品设计应先验证核心工作流再增加次要功能。"),
        ("localization", "本地化界面需要处理不同语言的文本长度变化。"),
        ("accessibility", "无障碍设计要求交互控件具备键盘操作能力。"),
        ("documentation", "技术文档需要同步当前配置、示例和版本状态。"),
        ("analytics", "数据分析前需要确认指标口径与缺失值处理方式。"),
        ("backup", "备份策略必须定期验证恢复流程而不只是生成文件。"),
        ("timezone", "定时任务应显式保存时区，避免夏令时造成偏移。"),
    ]

    seeds = [
        MemoryEvalSeed("semantic", name, content, {"type": memory_type})
        for name, content, memory_type in semantic_targets
    ]
    seeds.extend(
        MemoryEvalSeed("episodic", name, content, {"type": memory_type})
        for name, content, memory_type in episodic_targets
    )
    seeds.extend(
        MemoryEvalSeed("working", name, content)
        for name, content in working_memories
    )
    seeds.extend(
        MemoryEvalSeed(layer, name, content, {"type": memory_type})
        for layer, name, content, memory_type in hard_negatives
    )
    seeds.extend(
        MemoryEvalSeed(
            "semantic" if index % 2 == 0 else "episodic",
            f"noise_{name}",
            content,
            {"type": "distractor"}
        )
        for index, (name, content) in enumerate(distractor_contents)
    )

    retrieval_layers = ["episodic", "semantic"]

    def eval_case(
        name: str,
        category: str,
        query: str,
        expected_source: str,
        expected_text: str,
        forbidden_sources: Optional[List[str]] = None,
        layers: Optional[List[str]] = retrieval_layers,
        max_noise_rate: float = 0.5,
    ) -> MemoryEvalCase:
        return MemoryEvalCase(
            name=name,
            query=query,
            category=category,
            expected_substrings=[expected_text],
            expected_layers=[expected_source.split(":", 1)[0]],
            expected_sources=[expected_source],
            forbidden_sources=forbidden_sources or [],
            max_noise_rate=max_noise_rate,
            limit=8,
            max_chars=5000,
            layers=layers,
        )

    cases = [
        eval_case("pref_language", "preference", "用户要求用什么语言回答技术问题", "semantic:pref_response_language", "简体中文", ["semantic:old_response_english"]),
        eval_case("pref_style", "preference", "回答应该先给结论还是先讲背景", "semantic:pref_answer_style", "先给结论"),
        eval_case("pref_python", "preference", "项目当前统一使用哪个 Python 版本", "semantic:pref_python_version", "Python 3.10", ["semantic:old_python_312"]),
        eval_case("pref_secret", "preference", "API key 应放在全局还是项目本地", "semantic:pref_secret_scope", ".env.local", ["semantic:old_global_env"]),
        eval_case("pref_file_write", "preference", "文件写入工具默认是否开启", "semantic:file_write_policy", "默认关闭", ["semantic:unsafe_file_write_default"]),
        eval_case("decision_storage", "project_decision", "工作记忆为什么选择 SQLite", "episodic:decision_working_storage", "无需外部服务", ["episodic:rejected_postgres"]),
        eval_case("decision_semantic_format", "project_decision", "长期语义知识保存成什么格式", "semantic:semantic_storage", "Markdown"),
        eval_case("decision_graph", "project_decision", "记忆图谱为什么没有成为当前主线", "episodic:decision_skip_memory_graph", "暂缓记忆图谱", ["episodic:rejected_memory_graph"]),
        eval_case("decision_adapter", "project_decision", "模型供应商差异放在哪个边界", "episodic:decision_adapter_boundary", "BaseAdapter"),
        eval_case("decision_plugin", "project_decision", "插件生态应该在什么时候推进", "episodic:decision_plugin_timing", "核心生命周期"),
        eval_case("incident_stream", "incident", "流式回复结束后如何保存最终回合", "episodic:incident_stream_finalize", "统一执行回合收尾"),
        eval_case("incident_index", "incident", "删除记忆时怎样避免索引残留", "episodic:incident_index_cleanup", "同步删除倒排索引"),
        eval_case("incident_env", "incident", "项目本地环境变量读取问题如何解决", "episodic:incident_local_env", "secrets.env_file"),
        eval_case("incident_performance", "incident", "500 条记忆召回性能如何修复", "episodic:incident_recall_performance", "mtime 缓存"),
        eval_case("incident_debug", "incident", "遇到报错后第一步该做什么", "episodic:incident_read_full_error", "完整错误日志", ["episodic:ignore_error_log"]),
        eval_case("cross_language_reply", "cross_lingual", "Which language should technical answers use?", "semantic:pref_response_language", "简体中文", ["semantic:old_response_english"]),
        eval_case("cross_threshold", "cross_lingual", "What is the current BGE-M3 semantic threshold?", "semantic:current_semantic_threshold", "0.50", ["semantic:old_threshold_035"]),
        eval_case("cross_minimax", "cross_lingual", "MiniMax 累积流式文本应该怎样处理", "episodic:incident_minimax_stream", "cumulative chunks"),
        eval_case("cross_semantic_storage", "cross_lingual", "Where is long-term semantic knowledge stored?", "semantic:semantic_storage", "Markdown"),
        eval_case("conflict_threshold", "conflict", "目前 BGE-M3 的语义阈值是多少", "semantic:current_semantic_threshold", "0.50", ["semantic:old_threshold_035"]),
        eval_case("conflict_margin", "conflict", "当前 BGE-M3 score margin 参数是多少", "semantic:current_score_margin", "0.08", ["semantic:old_margin_012"]),
        eval_case("conflict_release", "conflict", "现在稳定发布版本是多少", "semantic:current_release", "v0.3.4", ["semantic:old_release_033"]),
        eval_case("noise_timeout", "noise_control", "HTTP timeout retry backoff policy", "episodic:incident_http_backoff", "指数退避", ["episodic:retry_without_backoff"]),
        eval_case("noise_connection_pool", "noise_control", "数据库连接池的最大连接与空闲回收", "episodic:noise_connection_pool", "连接池"),
        eval_case("noise_gardening", "noise_control", "番茄幼苗应该根据什么决定浇水", "semantic:noise_gardening", "土壤湿度"),
        eval_case("working_current", "cross_layer", "当前会话正在做什么", "working:work_eval", "高质量记忆评测集", ["working:work_docs"], layers=None),
        eval_case("working_pending", "cross_layer", "当前会话的下一步待办是什么", "working:work_pending", "冲突记忆", ["working:work_release"], layers=None),
    ]

    return MemoryEvalSuite(
        name="memory_quality_v2_extended_synthetic",
        version="2.1",
        seeds=seeds,
        cases=cases,
        quality_gates={
            "min_pass_rate": 0.85,
            "min_recall_at_k": 0.95,
            "min_mean_reciprocal_rank": 0.90,
            "min_precision_at_k": 0.65,
            "max_noise_rate": 0.35,
            "max_average_latency_ms": 1000.0,
        },
    )
