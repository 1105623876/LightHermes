# 测试说明

使用项目 `.venv`，安装 `requirements-dev.txt` 后运行：

```bash
.venv/bin/python -m pytest tests
```

`tests/conftest.py` 会为每个测试切换到独立临时目录并拒绝 socket 连接，防止读取项目 `.env.local`、写入真实记忆或意外调用付费 API。配置测试显式构造临时配置；真实 API smoke 与 benchmark 不在离线测试中执行。

## 结构

- `unit/`：记忆、检索、工具、适配器、压缩、配置、旧进化与 Active Memory。
- `integration/test_cli.py`：CLI 命令和输入循环。
- `unit/test_bash.py`、`integration/test_bash_agent.py`：真实本地命令、输出上限、进程组清理、授权、预算、取消与读/改/测闭环。
- `integration/test_session_lifecycle.py`：真实 SQLite 保存、重置、重启、默认用户一致性、失败保留与自动机制停止。
- `performance/`：本地存储/检索性能回归。
- `test_stream_response.py`：供应商流式响应回归。

根目录的旧手动脚本已移除，清理理由与恢复出处见 [归档清单](../docs/archive/README.md)。旧模块尚在，因此对应有效测试仍保留；删除实现时再同步删除仅保护旧行为的测试，不按测试数量清理。

重构前离线基线在 2026-09-22 实测为 226 passed；重构后的成绩与环境记录见 [PROJECT_STATUS](../docs/PROJECT_STATUS.md)。测试通过不能替代真实模型质量或跨场景收益验证。
