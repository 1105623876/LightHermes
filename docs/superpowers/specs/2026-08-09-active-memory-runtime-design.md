# Active Memory Runtime 设计

**日期**: 2026-08-09
**目标版本**: v0.4.0
**状态**: P0 + 最小 P1 已实现（默认关闭）
**原则**: 通用证据状态、预算受控、可观察、默认兼容、不针对 benchmark 特判

**实现结果**: 新增 `lighthermes/active_memory.py`，接入单次 seed 召回、内置 `search_memory` 两轮预算、JSON trace 与流式取消/错误收尾；全量离线基线 166/166 通过。query rewrite、来源展开、模型级 claim 更新和真实 A/B 尚未实现。

## 1. 问题定义

LightHermes 当前已经具备四级记忆、结构化召回、hybrid 重排和 `search_memory` 工具，但运行时仍以一次性 Top-K 注入为主：

1. 回合开始时执行一次自动召回。
2. 模型获得固定记忆上下文。
3. 模型可以自行调用 `search_memory`，但系统不记录搜索轮次、证据增益或停止原因。
4. 最终轨迹无法区分“索引未写入、召回未命中、来源未展开、模型未正确使用证据”。

LoCoMo 开发基线说明，主要瓶颈已经从“有没有检索”转向“证据是否足够、是否需要继续找、何时停止”。因此 Active Memory 的第一步不是增加更多检索规则，而是给现有工具循环增加一个轻量、可回放的证据状态层。

## 2. 设计目标

### 2.1 必须做到

- 保留现有首轮自动 Top-K，维持低延迟路径。
- 复用现有模型调用，让模型直接选择回答或调用记忆工具。
- 每个回合建立独立的 evidence ledger 和 recall trace。
- 主动记忆搜索最多两轮；连续无新来源时提前停止。
- 记录查询、候选、来源、分数、增益、降级、错误和停止原因。
- 默认关闭新路径；关闭时行为与当前版本一致。
- 不改变 `MemoryManager.recall_items()`、`MemoryManager.search_memory()` 和内置工具返回的兼容字段。
- 只使用 Python 标准库与项目现有依赖。

### 2.2 暂不做到

- 不训练独立 Planner 或 MEMORY 模型。
- 不要求模型输出隐藏推理或 chain-of-thought。
- 不引入图数据库、向量数据库或后台服务。
- 不在首个切片中迁移所有历史 Markdown/SQLite 记录。
- 不自动判断任意自然语言 claim 的逻辑蕴含关系。
- 不根据 LoCoMo 类别、evidence 标注、样本 ID 或失败题型添加规则。
- 不在本阶段实现多 Agent 共享记忆。

## 3. 架构边界

```text
LightHermes.run()
    |
    +-- MemoryManager.on_turn_start() ----> seed memory items/context
    |
    +-- ActiveRecallSession
    |      +-- EvidenceLedger
    |      +-- RecallTrace
    |      +-- round budget / stop state
    |
    +-- existing model + tool loop
           |
           +-- search_memory
                  |
                  +-- MemoryManager.search_memory()
                  +-- ActiveRecallSession.observe_search()
```

职责保持单一：

- `MemoryManager`：存储、检索、排序、迁移和蒸馏。
- `ActiveRecallSession`：单回合证据状态、来源去重、轮次预算和停止判断。
- `LightHermes`：创建/结束会话，在工具调用边界转发可观察事件。
- `ToolDispatcher`：保持通用，不感知 Active Memory。
- `EvolutionEngine`：本切片不改；后续通过 trace ID 关联经验轨迹。

Active Memory 不应成为第二个 Agent 框架，也不应侵入具体 retrieval 算法。

## 4. 核心数据契约

首个实现放在 `lighthermes/active_memory.py`，使用 dataclass 与标准库 JSON。

### 4.1 MemoryRecord

`MemoryRecord` 是现有结构化记忆字典的兼容视图，不要求立即改变底层存储格式。

```python
@dataclass
class MemoryRecord:
    record_id: str
    abstract: str
    raw_source: str
    source_ids: list[str]
    cue_anchors: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    event_time: str | None = None
    status: str = "current"
    confidence: float = 1.0
    last_verified: str | None = None
    supersedes: list[str] = field(default_factory=list)
    layer: str = ""
    name: str = ""
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)
```

约束：

- `record_id` 优先使用已有 `source`；缺失时由 layer/name/content 的稳定摘要生成。
- `abstract` 用于检索与展示，默认兼容现有 `content`。
- `raw_source` 保存可验证来源标识或原始内容引用，不把摘要伪装成原文。
- `source_ids` 至少包含主来源 ID，去重时使用来源而不是自然语言文本。
- `status` 兼容 `current`、`historical`、`rejected`、`failure_report`。
- `from_memory_item()` 必须容忍字段缺失，不修改传入字典。

### 4.2 ClaimEvidence 与 EvidenceLedger

```python
@dataclass
class ClaimEvidence:
    claim_id: str
    claim: str
    candidate_sources: list[str] = field(default_factory=list)
    supporting_sources: list[str] = field(default_factory=list)
    conflicting_sources: list[str] = field(default_factory=list)
    confidence: float = 0.0
    resolved: bool = False

@dataclass
class EvidenceLedger:
    claims: dict[str, ClaimEvidence]
    seen_sources: set[str]
```

首个切片只做显式状态管理，不尝试用启发式把检索结果自动判定为“支持”或“冲突”：

- seed/search 结果先进入 `candidate_sources`。
- 只有调用方显式标记时才进入 `supporting_sources` 或 `conflicting_sources`。
- `coverage` 是已解决 claim 数 / claim 总数；没有 claim 时为 0，而不是假定充分。
- `new_source_count` 只反映来源增益，不代表答案正确。
- 初始 query 可以作为默认 claim，但应标记为 unresolved。

这避免把 embedding 相似度错误解释成事实支持度。

### 4.3 RecallRoundTrace 与 RecallTrace

每次主动搜索形成一个轮次：

```python
@dataclass
class RecallRoundTrace:
    round_index: int
    query: str
    layer: str
    limit: int
    candidate_ids: list[str]
    candidate_scores: dict[str, float]
    accepted_source_ids: list[str]
    new_source_count: int
    latency_ms: float
    degraded: bool = False
    error: str | None = None

@dataclass
class RecallTrace:
    trace_id: str
    initial_query: str
    max_rounds: int
    rounds: list[RecallRoundTrace]
    stop_reason: str | None
    started_at: str
    finished_at: str | None
    metadata: dict[str, Any]
```

允许的停止原因：

- `sufficient`：模型在当前证据状态下选择回答。它表示行为选择，不等于事实已被外部验证。
- `no_new_evidence`：最新搜索没有引入新来源。
- `budget_exhausted`：已达到主动搜索轮次上限。
- `disabled`：Active Memory 未开启。
- `error`：Active Memory 状态或持久化失败；不得让主回答路径崩溃。
- `cancelled`：流式响应未完整消费或回合未正常结束。

轨迹不得记录模型隐藏推理，只记录输入查询、工具参数、工具返回摘要和系统状态转换。

### 4.4 ActiveRecallSession

`ActiveRecallSession` 是单回合状态机：

```text
created
  |
  +-- ingest seed sources
  |
  +-- model answers ----------------------> sufficient
  |
  +-- search requested
         |
         +-- already stopped ------------> return stop payload
         +-- budget reached -------------> budget_exhausted
         +-- execute search
                |
                +-- new sources ----------> continue if budget remains
                +-- no new sources -------> no_new_evidence
                +-- search error ----------> error
```

核心方法建议：

- `from_seed(query, items, max_rounds=2)`
- `can_search() -> bool`
- `observe_search(query, layer, limit, items, latency_ms, degraded=False)`
- `mark_answered()`
- `mark_cancelled()`
- `to_dict()`
- `persist(trace_dir) -> Path | None`

状态不跨回合共享。持久化失败仅记录 warning，不影响回答。

## 5. 运行时集成

### 5.1 配置

```yaml
memory:
  active_recall:
    enabled: false
    max_rounds: 2
    persist_traces: true
    trace_dir: memory/recall_traces
```

约束：

- 默认 `enabled: false`。
- `max_rounds` 在运行时夹紧到 1..2；v0.4.0 不开放更高预算。
- `trace_dir` 相对于项目运行目录解析，不包含 API key 或完整系统提示。
- 关闭时不新增提示、不拦截工具、不写 trace。

### 5.2 Core 集成点

1. `from_config()` 读取 `memory.active_recall`，传入构造器。
2. `run()` 在首轮记忆召回后创建 `ActiveRecallSession`。
3. 开启时追加短提示，说明：
   - 初始记忆是候选证据；
   - 证据不足时使用 `search_memory`；
   - 不得把“未检索到”表述为“确定不存在”；
   - 系统最多接受两轮主动搜索。
4. 非流式与流式工具循环在调用 `search_memory` 前检查预算，在调用后记录结果。
5. 回合正常回答时调用 `mark_answered()`；未完成流式响应调用 `mark_cancelled()`。
6. 统一收尾路径持久化 trace，避免流式与非流式行为分叉。

### 5.3 工具兼容

内置 `search_memory` 的成功 JSON 保持现有字段：

```json
{
  "query": "...",
  "layer": "all",
  "limit": 5,
  "results": []
}
```

预算或停止状态由 Core 在调用前返回兼容 JSON：

```json
{
  "query": "...",
  "layer": "all",
  "limit": 5,
  "results": [],
  "active_memory": {
    "search_allowed": false,
    "stop_reason": "budget_exhausted"
  }
}
```

不修改用户自定义同名工具的语义。只有内置 `search_memory` 被 Active Memory 观察和限额；用户覆盖工具继续按现有覆盖规则运行。

## 6. 失败与降级

- 记忆检索自身抛错：沿用现有错误边界，并在 trace 标记 `error`。
- JSON 解析失败：保留原工具结果，trace 记录解析错误，不中断主循环。
- trace 写盘失败：warning + 内存态保留，不让回答失败。
- Active Memory 内部异常：禁用本回合状态层，现有工具循环继续工作。
- embedding/product fallback：从现有检索结果或异常显式传入 `degraded`；不得把降级结果计入正式 benchmark。
- 流未完整消费：trace 标记 `cancelled`，不记为 `sufficient`。

## 7. 可观察性与隐私

默认 trace 内容：

- trace/session ID
- 查询和工具参数
- 来源 ID、层级、分数和截断后的候选摘要
- 轮次、延迟、增益、错误与停止原因
- ledger 的公开状态快照

默认不保存：

- API key、请求头、完整系统提示
- 模型隐藏推理
- 未经现有记忆系统允许持久化的临时工具输出
- benchmark evidence 标签、标准答案或样本内部元数据

后续可增加摘要脱敏，但首个切片沿用现有本地单用户信任边界。

## 8. 测试策略

### 8.1 纯单元测试

- `MemoryRecord.from_memory_item()` 的兼容映射与稳定 ID
- ledger 来源去重、显式支持/冲突、coverage
- seed 不消耗主动轮次
- 第 1/2 次搜索记录正确，第 3 次被拒绝
- 无新来源触发 `no_new_evidence`
- 回答、预算、错误和取消停止原因
- JSON 序列化与 trace 持久化失败容错

### 8.2 Core 集成测试

- 配置默认关闭，现有行为不变
- 配置开启后创建会话并添加提示
- 两次内置 `search_memory` 可执行，第三次返回预算停止 payload
- 用户自定义同名工具不受内置限额误伤
- 非流式与流式完成态均持久化 trace
- 未完整消费流时不标记 sufficient

### 8.3 回归与评测

- 聚焦：`test_active_memory.py`、`test_core_memory.py`、`test_builtin_tools.py`
- 全量：`.\venv\Scripts\python.exe -m pytest tests`
- 首个代码切片只做离线能力验证，不立即消耗真实 API。
- 策略冻结后再做 LoCoMo static / agentic A/B；不按当前 40 题逐题调规则。

## 9. 验收标准

首个实现切片完成需同时满足：

1. 新状态模块无第三方依赖。
2. 配置默认关闭时原测试全部通过；实现后全量基线为 166/166。
3. 开启时 seed 召回不计入主动轮次，额外搜索最多两轮。
4. 无新来源和预算耗尽均有稳定、可序列化的停止原因。
5. trace 可回放每轮查询、候选来源和增益，不包含隐藏推理。
6. 内置 `search_memory` 兼容；用户覆盖工具不被误拦截。
7. 不包含 benchmark 专用判断。
8. 聚焦测试与全量回归通过。

## 10. 实际交付边界

已完成：

- 运行时数据契约、来源去重、候选分数和 JSON trace
- seed context 与 structured item 单次召回
- 内置记忆工具 callable identity 检测
- 最多两轮搜索，以及 sufficient / no_new_evidence / budget_exhausted / cancelled / error
- 非流式、流式、自定义同名工具和旧 hook 兼容测试

仍保留为下一阶段：

- `degraded` 字段已有契约，但现有检索返回尚未提供统一降级信号
- ledger 支持显式 support/conflict API，但模型尚未写回 claim 判定
- 关闭状态不创建 trace，因此 `disabled` 仅保留为状态契约
- 尚未运行真实模型 static / agentic A/B，不能据此宣称召回或 QA 提升

## 11. 后续演进

首个切片稳定后，按以下顺序推进：

1. 来源读取与邻接 session 展开。
2. 模型可见的结构化 claim/evidence 更新协议。
3. query rewrite 与 cue anchors。
4. static / agentic 多轨 A/B 和阶段错误归因。
5. recall trace、tool trace 与 `EvolutionEngine` 的 `ExperienceRecord` 关联。
6. 背景 consolidation/dream 只处理已保留原始来源的记录。

Pi 的会话事件与回放边界、ReMe 的 source-first 和记忆精炼、ExpG 的工具成功/失败/成本记录可作为设计参考，但 LightHermes 保持单进程、黑盒模型兼容和最小依赖。
