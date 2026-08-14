# Active Memory Runtime 实施计划

**Goal:** 在不改变默认行为和现有检索接口的前提下，交付 `MemoryRecord / EvidenceLedger / RecallTrace` 运行时基座，以及最多两轮的主动记忆搜索 MVP。

**Architecture:** 新增纯状态模块 `active_memory.py`；`MemoryManager` 一次召回同时提供上下文与结构化 seed；`LightHermes` 显式传递单回合 session，并在现有工具交换与统一收尾边界记录轨迹。

**Tech Stack:** Python 3.10、dataclasses、json、hashlib、pathlib、time、uuid；不增加依赖。

**Design:** `docs/superpowers/specs/2026-08-09-active-memory-runtime-design.md`

**Status:** 2026-08-09 已完成 P0 + 最小 P1；2026-08-13 完成来源读取与邻接展开。随后落地 P1 运行时协议（`judge_claim`、`absence`、`suggested_query`），并修正单 claim 回写、未检索 `no_evidence` 拒绝和 conflict 未决语义。全量 192/192。质量 A/B 不在本切片。

---

## 实施边界

本轮代码只实现 P0 + 最小 P1：

- 数据契约与纯状态机
- 单次 seed 召回的结构化结果
- 配置开关
- 内置 `search_memory` 的两轮预算、来源增益和停止原因
- 本地 JSON trace
- 离线单元/集成测试

本轮不实现：

- 自动 query rewrite
- source 文件全文读取或 session 邻接展开
- LLM claim entailment 判定
- 图关系、后台 dream/consolidation
- Evolution 经验固化
- LoCoMo 个例规则或真实 API benchmark

## Task 1: 纯状态模型

**Files:**
- Create: `lighthermes/active_memory.py`
- Create: `tests/unit/test_active_memory.py`

- [x] 定义停止原因常量或受控字符串集合。
- [x] 实现 `MemoryRecord.from_memory_item()`。
- [x] 稳定 ID 优先使用 source；无 source 时使用标准化 layer/name/content 的 SHA-256 短摘要。
- [x] 实现 `ClaimEvidence` 与 `EvidenceLedger`。
- [x] seed/search 只进入 candidate sources；支持/冲突必须显式标记。
- [x] 实现 `RecallRoundTrace`、`RecallTrace` 和可 JSON 序列化的 `to_dict()`。
- [x] 实现 `ActiveRecallSession.from_seed()`、`can_search()`、`observe_search()`、`mark_answered()`、`mark_cancelled()`。
- [x] seed 不消耗主动搜索预算。
- [x] 最新一轮没有新 source 时停止为 `no_new_evidence`。
- [x] 达到第二轮且仍有新 source 时停止为 `budget_exhausted`。
- [x] 已停止 session 的后续搜索不得改变已完成轮次或原停止原因。
- [x] 实现原子 JSON trace 持久化；临时文件与最终文件位于同一目录。
- [x] 测试兼容映射、稳定 ID、去重、coverage、两轮预算、各停止原因、序列化和持久化。

**Verify:**

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit/test_active_memory.py -v
```

## Task 2: 单次 seed 召回

**Files:**
- Modify: `lighthermes/memory.py`
- Modify: `tests/unit/test_memory.py`

当前 `on_turn_start()` 只返回安全包装后的字符串。Active Memory 需要同一次召回产生的结构化 item，不能为 trace 再执行一次 embedding 检索。

- [x] 从 `recall()` 提取私有格式化辅助方法，保持输出文本完全兼容。
- [x] 为 `on_turn_start()` 增加可选 `include_items: bool = False`。
- [x] `include_items=False` 时继续返回原字符串。
- [x] `include_items=True` 时返回 `(context: str, items: list[dict])`。
- [x] 两条路径均只调用一次 `recall_items()`。
- [x] 空召回仍返回有效的空 context 与空 list。
- [x] 补测试确认默认 hook 兼容、结构化返回和单次调用。

**Verify:**

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit/test_memory.py -v
```

## Task 3: 配置与单回合 Session

**Files:**
- Modify: `lighthermes/core.py`
- Modify: `config.yaml`
- Modify: `tests/unit/test_core_memory.py`

配置：

```yaml
memory:
  active_recall:
    enabled: false
    max_rounds: 2
    persist_traces: true
    trace_dir: memory/recall_traces
```

- [x] 构造器读取 `memory.active_recall`。
- [x] `max_rounds` 夹紧到 1..2，非法值回退 2。
- [x] 保存 `enabled`、`persist_traces`、`trace_dir`，不得解析或写入任何 API key。
- [x] 内置记忆工具注册时保存 callable identity。
- [x] 用户自定义 `search_memory` 覆盖后，identity 检查必须返回 false。
- [x] `run()` 开启 Active Memory 时调用 `on_turn_start(include_items=True)`，否则保持现有调用。
- [x] hook 若只返回字符串，兼容降级为空 seed items。
- [x] 从结构化 seed 创建局部 `ActiveRecallSession`，不得挂到共享的 `self.current_session`。
- [x] 通过函数参数把 session 传给非流式、流式、工具交换和统一收尾路径，避免并发回合互相污染。
- [x] 开启时添加简短系统提示；关闭时 system prompt 必须不变。
- [x] 测试默认关闭、配置开启、max_rounds 边界、seed 透传和用户工具覆盖。

**Verify:**

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit/test_core_memory.py -v
```

## Task 4: 工具观察、预算与收尾

**Files:**
- Modify: `lighthermes/core.py`
- Modify: `tests/unit/test_core_memory.py`
- Optionally modify: `tests/unit/test_builtin_tools.py` only if compatibility coverage needs it

在 `_append_tool_exchange()` 的现有通用调用边界处理，不修改 `ToolDispatcher`。

- [x] 仅当 tool name 为 `search_memory` 且当前 callable identity 等于内置工具时启用 Active Memory 观察。
- [x] 调用前检查 `session.can_search()`。
- [x] 已停止时不调用底层记忆检索，返回包含 `active_memory.stop_reason` 的兼容 JSON。
- [x] 允许调用时记录 monotonic 延迟。
- [x] 解析内置工具 JSON 的 `results`，转换为 `MemoryRecord` 并调用 `observe_search()`。
- [x] JSON 解析失败或工具错误不得破坏原工具响应；trace 记录 error。
- [x] 正常回答时仅在 session 尚未停止时标记 `sufficient`。
- [x] 达到迭代上限时用 `budget_exhausted` 或 `error` 结束 trace，不伪装为回答充分。
- [x] 流式完成和非流式完成都走同一个 trace finalize helper。
- [x] 流式生成器未完整消费时标记 `cancelled`；使用 `try/finally`，但不得重复执行现有记忆/evolution 完成钩子。
- [x] 持久化失败只 warning，不影响用户回复。
- [x] 测试两次搜索成功、第三次拦截、无新来源提前停止、用户覆盖不被拦截、完成/取消 trace。

**Verify:**

```powershell
.\venv\Scripts\python.exe -m pytest tests/unit/test_active_memory.py tests/unit/test_core_memory.py tests/unit/test_builtin_tools.py -v
```

## Task 5: 兼容与回归审查

**Files to review:**
- `lighthermes/active_memory.py`
- `lighthermes/memory.py`
- `lighthermes/core.py`
- `config.yaml`
- 所有新增/修改测试

- [x] 检查关闭开关时参数、提示、工具返回、hook 次数和持久化行为不变。
- [x] 检查没有 LoCoMo、benchmark 类别、样本 ID 或答案特判。
- [x] 检查没有新依赖、明文 key 或完整系统提示写入 trace。
- [x] 检查 active session 是 run-local，不会跨并发回合共享。
- [x] 运行 `git diff --check`。
- [x] 运行全量测试。

**Verify:**

```powershell
git diff --check
.\venv\Scripts\python.exe -m pytest tests
```

## Task 6: 文档收尾

**Owner:** 主代理，不与实现子代理并行编辑文档。

- [x] README 架构图加入 `active_memory.py`。
- [x] README 说明配置开关、两轮上限和 trace 位置。
- [x] PROJECT_STATUS 与 ROADMAP 只在实际能力完成后勾选对应项。
- [x] tests/README 更新新的测试文件与最终测试总数。
- [x] 不提交、不推送，等待用户明确指令。

## 子代理交付要求

子代理只改代码、配置和测试，不改以下主代理正在维护的文件：

- `README.md`
- `docs/PROJECT_STATUS.md`
- `docs/ROADMAP.md`
- `docs/superpowers/specs/2026-08-09-active-memory-runtime-design.md`
- `docs/superpowers/plans/2026-08-09-active-memory-runtime.md`
- `tests/README.md`

交付时报告：

1. 修改文件清单。
2. 关键设计偏差及原因。
3. 聚焦测试结果。
4. 尚未覆盖的风险。
5. 不执行 commit 或 push。
