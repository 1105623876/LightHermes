# LightHermes 当前状态

更新时间：2026-09-22。开发依据：[ROADMAP](ROADMAP.md)。发布版本仍为 0.3.4；当前是 v0.4.0 收敛开发分支。

## R0：基础收敛

- Git 备份分支：`backup/pre-refactor-20260922`，提交 `04bb985`。工作分支：`refactor/memory-core-20260922`。
- 原发布开发基线：`f470f11`；本地 Git bundle 与工作状态归档已验证。R0/R1 工作分支已推送至 origin（`b838ff0`），备份分支与本地状态归档未上传。
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

## R2：第一切片——统一存储基础

- 新增 `lighthermes/store.py:MemoryStore`，只接受显式数据库路径；尚未接入 `LightHermes`、CLI 或默认配置，没有自动迁移、双写或新旧后端开关。
- 同一 SQLite 保存增量事件与长期条目；每条记录有精确 scope，事件关联 session/turn。长期条目必须有同 scope 的事件来源；默认 candidate，只有宿主明确激活后才进入检索。
- FTS5 复用中英文分词，索引完整正文；最多返回 50 条，只查 active 和指定 scope。不是语义检索：同义词/跨语言、中文单字误匹配和上下文污染阈值还需后续验证，当前不能宣称无关请求必然零注入。
- 精确 ID 纠正在事务中产生新条目、保留历史、失效旧索引；未批准候选不能覆盖 active。归档退出召回；重建索引不会恢复历史状态。
- 遗忘删除整条纠正链及索引，来源 ID 留无正文排除标记，拒绝再次提取。可明确清除来源原文；若原文还支撑链外条目则整次拒绝，不隐式扩大删除范围。保留来源模式仍可显式读取原文并看到 excluded 标记。
- SQLite 写入和索引同事务，错误直接抛出。默认 256 MiB 应用容量保护，计入该库及 SQLite sidecar，并限制数据库页数；不是操作系统硬配额，也尚不覆盖未来外部日志/缓存。容量失败保留已提交事实，不删除旧原文腾空间。
- 不引入运行依赖、embedding 缓存或后台维护。原文 payload 的限长/脱敏、任务完成状态、项目稳定 ID 绑定、全回合预算和主循环接入仍待下一切片；当前 API 由宿主负责提供可信 scope 和已处理 payload，不能直接作为模型工具暴露。
- 旧实现仍有实际调用者，其行为测试保留；这次不额外复制历史文档，不删除尚在运行的旧测试。真实记忆未读取内容或迁移。

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
- R2 存储切片：新增 11 项行为测试，全套离线回归 278 passed / 2.86s；通过公开写入 API 保存事件/条目后关闭重开验证，不宣称已通过 Agent 端到端记忆验收。包含故障回滚、容量不足和错误不伪装为空结果。
- 112 个备份中的本地配置/资料/运行数据文件逐一校验未改动；活动文档链接与 Git 差异格式检查通过。
- 本轮没有运行真实模型、LoCoMo 或 holdout，也没有迁移真实记忆。

## 下一阶段与当前限制

下一步将 R2 存储接入现有主循环与三个记忆工具，补充事件脱敏/限长、任务状态、项目绑定、seed 与总上下文预算，验证流式/非流式完整保存回放；再提供只读迁移清单与幂等转换工具，真实数据转换单独核对范围。完成后才进入 R3 验证式经验闭环。

当前四级存储、窗口截断、历史保留期、按词触发固定设定写入仍为旧实现；R0 没有解决全部记忆质量问题。已有记忆与日志没有被清理或迁移，旧 worktree 引用也未删除。
