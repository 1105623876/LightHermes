# 历史资料归档

这里保存重构前的设计、计划、状态分析与示例，**不作为当前开发指令**。文内版本、测试数字、功能完成状态和代码路径均是历史记录，可能已过时；不要执行其中旧实施计划或安装指令。

当前开发依据是 [ROADMAP](../ROADMAP.md)，已实现状态看 [PROJECT_STATUS](../PROJECT_STATUS.md)。冻结实验约束仍在 [FREEZE_COMMITMENT](../FREEZE_COMMITMENT.md) 与 [FREEZE_LOCK](../FREEZE_LOCK.md)。

## 2026-09-22 整理清单

| 内容 | 处理 | 原因 |
|---|---|---|
| `docs/superpowers/` 的 8 份旧设计/实施计划 | 原样移入 `pre-refactor/superpowers/` | 分层迁移、插件与旧 Active Memory 计划不再支配产品主线；保留实验背景 |
| `docs/design-decisions.md` | 移入 `pre-refactor/` | 部分轻量性/性能结论已无依据，保留历史取舍 |
| `docs/implementation-vs-design.md` | 移入 `pre-refactor/` | 行数、依赖、功能状态互相矛盾，不能继续充当当前状态 |
| `example_evolution.py` | 移入 `pre-refactor/example_evolution.py.txt` | 旧自动激活示例已不受支持；改为不可直接运行的历史文本 |
| 根目录 7 个跟踪的 `test_*.py` | 从工作树删除，Git 备份保留 | 打印/布尔值式检查、重复导入/功能验证、或导入时真实 API 调用；不属于正式 pytest 集合 |
| `tests/` 正式回归测试 | 保留并更新实际变化的契约 | Active Memory/旧存储仍在代码中，不能先删相应回归保护 |
| `.qoder/`、本地配置、真实记忆/日志、旧 worktree refs | 保留 | 用户既有内容与研究产物，不因清理文档而删除 |

删除的旧脚本：`test_adapter.py`、`test_complete.py`、`test_comprehensive.py`、`test_evolution.py`、`test_minimax_anthropic.py`、`test_stability_basic.py`、`test_tool_decorator.py`。基础覆盖分别由 `tests/unit/test_adapters.py`、`test_memory.py`、`test_core_memory.py`、`test_evolution.py`、`test_tools.py` 和流式测试保留；真实 API smoke 没有伪装成离线覆盖，后续必须单独授权运行。

恢复单个旧文件可先查看 `git show backup/pre-refactor-20260922:原路径`。完整原版本为 `04bb985`（包含新路线图），旧运行时代码为 `f470f11`。Git 历史是原路径索引，不维护重复的当前文档。

## R2 主循环整理

`6d0918d` 保存完整的切换前代码和测试。移除 `tests/unit/test_core_active_memory.py`，并从 `test_core_memory.py` 移除自动提炼、固定设定写入、四级配置转发与旧轨迹评分等已退役行为；合计 43 项。没有复制一套可误执行的旧测试目录。保留模型配置、fallback、文件工具、工具覆盖和供应商响应测试，新行为由 `integration/test_runtime_memory.py` 覆盖。旧独立存储/实验模块尚未整体删除，其独立测试继续保留。实际旧实验复现仍使用 `f470f11`。
