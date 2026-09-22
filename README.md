# LightHermes

本地优先的轻量记忆 Agent，正在按 [ROADMAP](docs/ROADMAP.md) 收敛为“行动、跨会话记忆、可验证自进化”一个闭环。

发布版本仍为 `0.3.4`；当前分支是 v0.4.0 重构开发版。**R0 基础收敛与 R1 bash 行动已实现；统一记忆存储与验证式自进化按 R2/R3 推进，不能把路线图当作已交付功能。**

## 当前可用能力

- OpenAI / Anthropic 及兼容端点，流式与非流式工具循环。
- 本地 bash：每次独立进程、会话授权、超时/取消清理进程组、有限输出和工具调用预算。
- `search_memory` / `read_memory`、关键词与可选 embedding 检索、上下文压缩。
- CLI 会话 ID 正确轮换，保存后重启可以按来源读取；不再自动跨层复制或按“命中条目数量”调参。
- 人工 Markdown 技能，支持指定目录、禁用技能和重新加载时移除已删除技能。
- 旧四级存储和实验模块尚未替换；旧自动技能激活已停止，生成技能目录不再默认加载。

当前仍有重要限制：会话保存主要发生在 CLI 结束/重置，保存内容来自当前短期窗口；不提供完整的崩溃恢复或全量事件日志。项目级隔离、可靠纠正/遗忘、统一容量治理在 R2 实现。旧进化引擎只有显式调用入口，其成功标签不代表经过任务验证。

## 安装与运行

需要 Python 3.10+。核心依赖只有 `openai`、`anthropic`、`pyyaml`；本地 embedding 和 CLI 颜色为可选项。

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
# 仅开发测试需要：
.venv/bin/python -m pip install -r requirements-dev.txt
```

复制 `.env.example` 为 `.env.local`，填写模型/端点/密钥；`config.yaml` 通过变量引用，不应包含真实密钥。需要 embedding 时配置独立端点；无需 embedding 可设 `memory.hybrid_retrieval.enabled: false`。

```python
from lighthermes import LightHermes

agent = LightHermes.from_config("config.yaml")
print(agent.run("解释这个项目的设计"))
```

```bash
.venv/bin/python -m lighthermes.cli
.venv/bin/python -m pytest tests
```

CLI：`/help`、`/skills`、`/memory`、`/stats`、`/config`、`/compress`、`/export`、`/reset`、`/exit`。同一次 CLI 会话保持相同 ID，`/reset` 保存成功后才分配新 ID；保存失败会显示错误、拒绝 `/reset` 或正常 `/exit` 并保留内存内容；强制结束进程仍不能保证恢复。

Python `run()` 未传 ID 时使用该 Agent 实例的稳定会话 ID。需要新的独立上下文应新建 Agent；显式 `session_id` 不会自动切换/加载历史。旧 `default` 用户名的数据保留，可显式传 `user_id="default"` 查询；默认统一为 `default_user`，不会偷偷改写旧数据库。

## bash 行动

CLI 启动时展示工作目录并询问本会话授权；同一会话内不重复逐条确认，`/reset` 后重新授权。非交互 CLI 保持未授权。Python 宿主显式开启：

```python
agent = LightHermes.from_config(
    "config.yaml",
    bash_authorized=True,
    bash_cwd="/absolute/path/to/project",
)
print(agent.run("检查项目中的计算函数，修复问题并运行已有测试"))
print(agent.last_turn["status"])
```

bash 在本机以当前账号权限执行，**不是沙箱**；工作目录不限制文件访问。每次命令默认 60 秒、最多 300 秒，输出最多 12,000 字符。`cd`/`export` 不跨调用保留，不支持后台任务；核心只继承基本环境，额外环境由宿主通过 `bash_env` 显式提供，模型不能修改执行授权。

`max_iterations` 同时限制模型迭代和工具调用总数；超出剩余预算的整批工具不会执行。取消立即停止后续命令，不自动重试副作用。`last_turn` 提供当前回合的会话 ID、状态和消息/工具观察；它仅保留在内存中，持久化事件日志属于 R2。`completed` 表示流程完成，不表示任务已外部验证。

## 配置变化

- `memory.retention.short_term_turns`、`working_memory_days` 已在构造时接通。
- `skills.dirs: []` 真的禁用加载，`skills.disabled` 真的排除指定技能。
- 不支持的 `plugins.dirs`、`skills.enabled/auto_load`、`episodic_auto_archive`、`evolution.sandbox.max_memory_mb` 会明确报错。
- `memory.adaptive.enabled: true`、`adapt_interval` 和 `auto_generate_skills: true` 已退出产品路径，旧配置需要移除这些项。
- `agent.load_config()` 不再只修改部分字段而留下旧模型连接；使用 `LightHermes.from_config()` 创建新实例。

完整消费关系与验证见 [PROJECT_STATUS](docs/PROJECT_STATUS.md)。

## 实验与历史

旧 Active Memory 默认关闭，当前保留代码和回归测试。原 LoCoMo 实验的复现应使用锁定版本、配置和历史结果，不能把当前重构版本冒充原冻结条件。有关数据划分、holdout 与调用预算的纪律仍由 [冻结宣言](docs/FREEZE_COMMITMENT.md) 和 [冻结清单](docs/FREEZE_LOCK.md) 约束。

- [当前路线与开发边界](docs/ROADMAP.md)
- [当前已实现状态](docs/PROJECT_STATUS.md)
- [离线测试说明](tests/README.md)
- [历史设计与清理清单](docs/archive/README.md)
- [版本历史](CHANGELOG.md)

Apache 2.0。
