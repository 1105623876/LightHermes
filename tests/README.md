# 测试说明

使用项目 `.venv`，安装 `requirements-dev.txt` 后运行：

```bash
.venv/bin/python -m pytest tests
```

`tests/conftest.py` 会为每个测试切换到独立临时目录并拒绝 socket 连接，防止读取项目 `.env.local`、写入真实记忆或意外调用付费 API。配置测试显式构造临时配置；真实 API smoke 与 benchmark 不在离线测试中执行。

## 结构

- `unit/`：记忆、检索、工具、适配器、压缩、配置、旧进化与 Active Memory。
- `unit/test_migration.py`：临时新目录转换、源快照不变、幂等、失败不发布、未知字段/表/BLOB 保留。
- `unit/test_store.py`：R2 新存储的保存/重开、scope 隔离、候选、纠正、遗忘、索引重建与事务故障；另有主循环端到端回放。
- `integration/test_runtime_memory.py`：真实 Agent + SQLite 的保存/重启/纠正/遗忘、用户/项目隔离、流式取消、故障中止、预算、长记录尾部读取和旧库保护。
- `integration/test_cli.py`：CLI 命令和输入循环。
- `unit/test_bash.py`、`integration/test_bash_agent.py`：真实本地命令、输出上限、进程组清理、授权、预算、取消与读/改/测闭环。
- `integration/test_session_lifecycle.py`：真实 SQLite 保存、重置、重启、默认用户一致性、失败保留与自动机制停止。
- `performance/`：本地存储/检索性能回归。
- `test_stream_response.py`：供应商流式响应回归。

根目录的旧手动脚本已移除，清理理由与恢复出处见 [归档清单](../docs/archive/README.md)。旧独立模块对应测试仍保留。已退役主循环 Active Memory 与自动提炼等 43 项旧行为测试移除，原文件可从 `6d0918d` 恢复；模型配置、fallback、工具覆盖和供应商适配回归保留。不是通过删失败测试修复现行功能。

重构前离线基线在 2026-09-22 实测为 226 passed；重构后的成绩与环境记录见 [PROJECT_STATUS](../docs/PROJECT_STATUS.md)。测试通过不能替代真实模型质量或跨场景收益验证。

真实模型验收脚本为 `scripts/r2_acceptance.py --live --output <路径>`，不属于 pytest；只有当用户明确授权真实调用时运行。2026-09-22 的调用次数、失败和定向复验见 [R2 验收记录](../docs/validation/R2_ACCEPTANCE.md)。
