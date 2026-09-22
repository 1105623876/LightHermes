# LightHermes 当前状态

更新时间：2026-09-22。开发依据：[ROADMAP](ROADMAP.md)。发布版本仍为 0.3.4；当前是 v0.4.0 收敛开发分支。

## R0：基础收敛

- Git 备份分支：`backup/pre-refactor-20260922`，提交 `04bb985`。工作分支：`refactor/memory-core-20260922`。
- 原发布开发基线：`f470f11`；本地 Git bundle 与工作状态归档已验证，未 push。
- 新路线图已单独提交。文档与测试整理清单：[archive/README.md](archive/README.md)。
- CLI 会话 ID 按新会话生成，重置前保存；连续关闭幂等，保存失败不清空当前会话。
- `LightHermes.run()` 默认沿用实例会话 ID；Memory/CLI 默认用户统一为 `default_user`。旧 `default` 数据未迁移，仍可显式查询。
- 会话结束不再自动提升/蒸馏/归档；回合结束不再按命中数量自适应。旧手动方法暂保留到替代存储完成。
- 旧 Evolution 默认关闭，自动技能激活明确拒绝；人工技能继续可用。生成目录不默认加载，加载器尊重空目录/禁用项并在重载时移除已删技能。
- 测试使用临时目录并禁网；核心/测试依赖分开，本地模型包不再随默认 requirements 安装。

## R1：bash 行动

- 默认内置 `bash`，模型可见但未授权不执行；CLI 按会话授权，Python 使用 `bash_authorized=True`。工作目录与额外环境由 `bash_cwd/bash_env` 提供。
- 支持 macOS/Linux bash；独立进程、有限首尾输出、UTF-8 增量解码、超时/取消清理进程组，不支持后台任务。
- 流式与非流式共用工具分发，整批工具不能突破剩余调用预算；取消、错误、预算耗尽不会记为完成回合。
- `last_turn` 关联会话 ID 与内存消息/观察，明确区分完成、取消、错误与预算耗尽；持久化和验证结果仍由 R2/R3 接入。
- 脚本化模型 + 真实 bash 在临时项目完成读取、修改计算函数与断言验证，两种响应路径都通过。没有运行真实 LLM，不宣称模型任务成功率。

## 配置消费审计

| 配置 | 消费入口与现状 |
|---|---|
| `secrets.env_file`、`model.*` | `from_config` / 环境加载 / Adapter；支持主模型与 fallback，密钥不入示例配置 |
| `embedding.*`、`memory.hybrid_retrieval.*` | MemoryManager → SemanticMemory / HybridRetriever；保留实验 strict 模式 |
| `memory.retention.short_term_turns/working_memory_days` | 已补接构造参数；限制短期窗口与旧会话保留期 |
| 其他现有 `memory.retention.*`、`memory.recall.*` | 容量、手动蒸馏上限、seed/search 截断，旧存储仍有对应消费者 |
| `memory.active_recall.*` | 旧实验会话及 trace；默认关闭，冻结复现使用旧提交 |
| `memory.adaptive.enabled: true` / `adapt_interval` | 已拒绝；`archive_days` 仅供显式旧归档方法，默认配置不再暴露 |
| `evolution.enabled`、`triggers`、`sandbox.timeout` | 显式旧引擎入口；默认关闭，不作为验证式自进化交付 |
| `auto_generate_skills: true` | 已拒绝；不再每 50 回合生成并热加载 |
| `evolution.sandbox.max_memory_mb` | 从未实际限制内存，现明确拒绝，不能宣称沙箱配额 |
| `skills.dirs/disabled` | SkillLoader；空目录与排除名单生效 |
| `plugins.dirs`、`plugin_dirs` | 未实现，非空时拒绝 |
| `skills.enabled/auto_load`、`episodic_auto_archive` | 曾无真实消费者，现拒绝并从示例移除 |
| `tools.builtin.*` | 现有记忆/文件工具与 R1 bash；文件工具仍默认关闭，bash 另需显式宿主授权 |
| `context_compression.*` | ContextCompressor / 压缩收尾；原有 token 估算待 R2 改进 |
| `cli.*`、`logging.*` | CLI 展示/流式与 logger；用 `from_config` 获取完整配置 |
| `agent.load_config()` | 原为不一致的部分热更新，现拒绝；应新建实例 |

## 验证记录

- Python 3.12.14；SQLite 3.53.1 的 FTS5 可用；`/bin/bash` 可用。
- 项目 `.venv`：openai 3.17.0、anthropic 1.7.0、PyYAML 6.0.3、pytest 9.1.1。安装均来自项目既有声明，无新运行依赖。
- 重构前：在临时工作目录且拒绝网络的条件下，226 passed / 3.61s。
- R0 重构后：242 passed / 1.57s；新增会话持久化与失败路径、配置拒绝和技能失效验证。
- R1 最终离线回归：267 passed；包含真实 bash 执行、文件修复与断言验证、输出上限、超时/取消和批量调用预算。
- 112 个备份中的本地配置/资料/运行数据文件逐一校验未改动；活动文档链接与 Git 差异格式检查通过。
- 本轮没有运行真实模型、LoCoMo 或 holdout，也没有迁移真实记忆。

## 下一阶段与当前限制

下一步 R2 统一存储、原始事件增量保存、作用域/纠正/遗忘和预算，再到 R3 验证式经验闭环。

当前四级存储、窗口截断、历史保留期、按词触发固定设定写入仍为旧实现；R0 没有解决全部记忆质量问题。已有记忆与日志没有被清理或迁移，旧 worktree 引用也未删除。
