# LightHermes 开发日志

## 2026-05-04 - 修复进行中的回归问题（未发布）

### 修复
- ✅ 修复 `lighthermes/retrieval.py` 结构损坏导致的 `IndentationError`
  - 恢复 `TFIDFRetriever` 类定义与 `__init__`
  - 将 TF-IDF 分词与检索统一切换为 `_tokenize()`（支持中英文混合）
- ✅ 修复 `lighthermes/memory.py` 的 `MemoryManager.__init__` 参数回归
  - 恢复 `embedding_provider` / `embedding_model` 构造参数
  - 消除初始化阶段 `NameError: embedding_provider is not defined`

### 验证
- ✅ 记忆相关回归测试：`tests/unit/test_memory.py` + `tests/unit/test_core_memory.py`（21/21）
- ✅ 全量 pytest：`tests/`（67/67）

---

## 2026-05-03 - v0.3.1 + Phase 2 起步

### 自进化系统
- ✅ 新增成功质量评估字段：`quality_score`、`quality_level`、`learning_worthy`、`quality_metrics`、`quality_version`
- ✅ 成功模式分析仅使用高质量成功轨迹，避免侥幸成功污染技能生成
- ✅ 失败轨迹生成 `failure_report`，避免将失败经验固化为正向技能

### 记忆系统增强
- ✅ 修复 `SemanticMemory` 混合检索初始化不可达问题
- ✅ 打通 `config.yaml` 的 `memory.hybrid_retrieval` 到 `MemoryManager`
- ✅ 实现工作记忆到情景记忆的幂等迁移
- ✅ 支持将上下文压缩摘要按配置写入工作记忆

### 适配器与测试
- ✅ Evolution 复用主模型 Adapter，不再为非 OpenAI provider 额外要求 `OPENAI_API_KEY`
- ✅ 修复 Adapter 对新版 OpenAI SDK 的兼容性
- ✅ 补充压缩与 CLI 测试
- ✅ 全量 pytest：67/67 通过

---

## 2026-04-29 - v0.3.0 可用性增强完成

### 记忆层级迁移（最新）
- ✅ 访问追踪系统
  - 为情景记忆和语义记忆添加 `last_accessed` 和 `access_count` 字段
  - 每次访问自动更新访问记录
- ✅ 自动归档机制
  - 30 天未访问的记忆自动归档到 `archived` 子目录
  - 在 `adapt_weights` 中自动执行归档
- ✅ 自动提升机制
  - 高频访问（>10次）的情景记忆自动提升为语义记忆
  - 会话结束时短期记忆迁移到工作记忆
- ✅ 迁移方法
  - `archive_inactive_memories()` - 归档低频记忆
  - `promote_memories()` - 提升高频记忆
  - `migrate_short_to_working()` - 短期→工作记忆迁移
  - `auto_migrate()` - 自动执行所有迁移操作

### CLI 增强功能
- ✅ `/stats` 命令 - 显示详细统计
  - API 调用次数、token 使用量、查询次数
  - 记忆统计（短期/情景/语义记忆数量）
  - 压缩统计（压缩次数、节省 tokens）
- ✅ `/export` 命令 - 导出对话历史
  - 导出到带时间戳的 JSON 文件
  - 包含消息列表和统计信息
- ✅ `/reset` 命令 - 重置会话
  - 清空短期记忆和统计信息
  - 保留长期记忆（情景记忆、语义记忆）
- ✅ 统计跟踪
  - 在 `core.py` 中添加 `api_call_count` 和 `total_tokens_used`
  - 在 `_run_non_stream` 中自动统计

### 上下文压缩系统

### 新增功能
- ✅ 上下文压缩系统（`compressor.py`，246 行）
  - Token 估算函数（`len(text) // 4`）
  - 工具输出预剪枝（保留调用信息，删除详细输出）
  - 头尾保护（保护系统提示 + 前 3 条消息 + 最近 20K tokens）
  - 中间内容总结（使用便宜模型 gpt-4o-mini）
  - 压缩统计功能
- ✅ 自动触发机制（token 使用达到 75% 上下文窗口时触发）
- ✅ 手动触发命令（`/compress`）
- ✅ 压缩统计命令（`/compress stats`）
- ✅ CLI 用户体验改进
  - 修复 Windows 终端中文乱码
  - 改进错误提示信息
  - 优化命令提示和彩色输出

### 集成
- ✅ 集成到 `LightHermes` 核心引擎
- ✅ 上下文窗口自动检测（支持 GPT-4、Claude 等多种模型）
- ✅ 配置文件支持（`context_compression` 配置段）

### 测试
- ✅ 单元测试通过（5/5）
  - Token 估算测试
  - 工具输出预剪枝测试
  - 头尾消息保护测试
  - 压缩统计测试
  - 压缩触发判断测试

### 文档
- ✅ 更新 README 添加上下文压缩功能说明
- ✅ 更新 CHANGELOG
- ✅ 完成设计文档（`docs/superpowers/plans/2026-04-28-context-compression-design.md`）

### 设计特点
- 参考 hermes-agent 核心算法
- 保持轻量（< 300 行代码）
- 默认使用便宜模型（gpt-4o-mini）节省成本
- 可配置触发阈值、摘要模型、保护策略等

### 代码统计
- 新增代码：367 行
- `compressor.py`: 246 行
- `core.py`: +68 行
- `cli.py`: +53 行

## 2026-04-27 - v0.2.0 稳定性增强完成

### 新增功能
- ✅ 自适应记忆调整（根据命中率动态优化记忆层级）
- ✅ 记忆归档功能（30天未访问自动归档）
- ✅ 记忆统计系统（MemoryStats）
- ✅ 轻量日志系统（logger.py）
- ✅ 模型降级机制（API 失败自动切换）
- ✅ 记忆系统错误处理
- ✅ 配置集成（config.yaml）

### 安全修复
- ✅ 修复 eval() 安全漏洞（替换为 json.loads）

### 测试
- ✅ 添加综合测试（test_comprehensive.py）
- ✅ 添加基础稳定性测试（test_stability_basic.py）
- ✅ 测试通过率：7/7（100%）

### 文档
- ✅ 更新 README（突出自适应记忆和生产稳定性）
- ✅ 添加项目状态文档（docs/PROJECT_STATUS.md）

### 代码统计
- 核心代码：1808 行
- 模块分布：
  - `memory.py`: 539 行（四级记忆 + 自适应）
  - `core.py`: 482 行（对话循环 + 工具调度）
  - `evolution.py`: 349 行（自进化系统）
  - `cli.py`: 210 行（命令行界面）
  - `retrieval.py`: 169 行（混合检索）
  - `logger.py`: 50 行（日志系统）
