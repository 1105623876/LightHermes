# LightHermes 项目状态

**最后更新**: 2026-05-11
**版本**: v0.3.2（记忆工具计划完成，待发版时再统一提升版本号）
**状态**: 稳定可用，测试基线通过

## 核心指标

- **测试通过率**: 112/112（`pytest tests/`）
- **核心依赖**: `openai` + `anthropic` + `pyyaml`
- **可选增强依赖**: `sentence-transformers`、`colorama`
- **分支状态**: `master` 已推送；仅 `.claude/settings.local.json` 为本地 Claude 配置改动
- **当前定位**: 轻量智能体框架，围绕四级记忆、生命周期钩子、自进化和受控工具形成闭环

## 最近进展（已在代码中）

### 1) 记忆生命周期
- `on_turn_start()` 召回记忆并用 `<memory-context>` 安全包装
- `on_turn_end()` 同步助手回复到短期记忆
- `on_pre_compress()` 在压缩前提取即将丢失的轻量线索
- `on_session_end()` 在 CLI 退出、重置、KeyboardInterrupt/EOF 时保存摘要并触发迁移
- `on_memory_write()` 作为固定记忆与用户偏好写入后的统一入口

### 2) 记忆蒸馏与容量治理
- 新增 `distill_memories()`，从工作/情景记忆提炼高价值语义记忆
- 语义记忆支持条目数与字符预算，避免长期无限追加
- 重复/近重复蒸馏记忆自动合并，避免同类语义记忆膨胀
- 蒸馏元数据包含 `distilled_from`、`source_layer`、`confidence`、`last_verified`、`source_count`
- 语义记忆清理时同步移除索引，并优先保留用户偏好

### 3) 结构化记忆召回与记忆搜索工具
- `MemoryManager.recall_items()` 返回层级、来源、分数、优先级和元数据
- `MemoryManager.search_memory()` 支持按 `working`、`episodic`、`semantic` 或 `all` 搜索
- `recall()` 保留旧字符串接口，内部复用结构化召回
- 默认注册内置 `search_memory` 工具，显式记忆查询可以走工具调用
- 用户自定义同名工具会覆盖内置工具，避免重复 schema

### 4) 受控文件工具
- 新增 `lighthermes/builtin_tools.py`，集中管理内置工具
- `read_file`、`search_files`、`write_file` 均由 `tools.builtin` 配置显式开启
- 文件工具默认关闭；`write_file` 必须单独开启，不会被读/搜索能力隐式启用
- 文件访问受 `roots` 白名单、排除目录、敏感文件名、二进制文件和大小限制保护
- `write_file` 支持 `create`、`overwrite`、`append`，不会自动创建父目录

### 5) 自进化与反模式提示
- 增加成功质量评估：`quality_score` / `quality_level` / `learning_worthy`
- 成功模式分析仅使用高质量成功轨迹
- 失败轨迹生成 `failure_report`，避免错误经验被当成正向技能
- `failure_report` 会按任务类型和关键词召回，并在执行前注入简短非阻断风险提示
- 生成后的 `failure_report` 会优先沉淀到情景记忆，后续可由蒸馏机制进入语义记忆

### 6) 轻量架构边界收敛
- `tool` 装饰器与 `ToolDispatcher` 已拆到 `lighthermes/tools.py`
- `SkillLoader` 已拆到 `lighthermes/skills.py`，继续支持 Markdown 技能和 `failure_report` 召回
- 生命周期钩子的安全调用已收敛到 `lighthermes/hooks.py`
- `lighthermes/channels.py` 预留 `ChannelMessage` / `DirectChannel`，暂不引入复杂 channel bus
- `core.py` 保持 `LightHermes` 主循环和兼容门面，避免破坏既有导入与测试 monkeypatch

### 7) 测试体系
- 已形成单元/集成/性能测试分层
- 覆盖模块包括 memory / builtin_tools / tools / adapters / evolution / compressor / CLI / performance
- 全量基线稳定（112 项）

## 已完成计划判断

**记忆工具计划已完成。** 当前已完成结构化记忆召回、内置 `search_memory`、受控只读文件工具、默认关闭的 `write_file`、配置入口、安全边界和测试覆盖。

## 已知风险与限制

1. **混合检索默认关闭**
   - 启用 OpenAI embedding 需要 API key
   - 启用 local embedding 需要本地模型依赖

2. **记忆蒸馏仍是轻量启发式**
   - 当前不调用 LLM、不引入新依赖
   - 后续可继续优化稳定事实筛选和误判控制

3. **反模式提示是轻量召回**
   - 当前只按任务类型和关键词匹配
   - 后续可继续优化反模式稳定性筛选和去重策略

4. **文件工具需要谨慎开启**
   - 默认关闭是正确安全边界
   - 开启时应尽量缩小 `roots`，写入能力只在可信环境中启用

5. **真实 API 集成测试仍需外部凭据**
   - 当前 CI/本地主要依赖 mock 与离线测试路径
   - MiniMax Anthropic 兼容端点已完成一次真实非流式与流式 smoke test

## 下一步建议（按优先级）

1. **发版准备**
   - MiniMax 真实 smoke test 已通过；发版前可再补 OpenAI/Anthropic 任一路径
   - 若发版，再统一更新 `__version__`、`setup.py` 和文档版本号

2. **插件系统完善（Phase 3.1）**
   - Python 插件加载机制
   - 插件目录扫描和启停配置
   - 保持插件依赖管理轻量，不默认安装重依赖

3. **工具生态扩展（Phase 3.2）**
   - Docker 镜像、GitHub Actions、VS Code 插件或 Web UI 按需推进
   - 优先选对当前开发/测试最有帮助的集成

4. **记忆系统优化（Phase 4.1）**
   - 记忆检索缓存（LRU）
   - 批量操作优化
   - 评估 SQLite FTS5，但不作为默认复杂依赖

5. **多模态支持（低优先级）**
   - 图片输入、代码截图理解、架构图生成
   - 原则是不引入重依赖，优先复用模型原生能力

## 参考文档

- 总览说明：`README.md`
- 路线图：`docs/ROADMAP.md`
- 变更日志：`CHANGELOG.md`
- 测试说明：`tests/README.md`
