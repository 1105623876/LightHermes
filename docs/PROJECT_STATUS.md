# LightHermes 项目状态

**最后更新**: 2026-05-04  
**版本**: v0.3.1（Phase 2 起步）  
**状态**: 稳定可用，测试基线通过

## 核心指标

- **测试通过率**: 67/67（`pytest tests/`）
- **核心依赖**: `openai` + `anthropic` + `pyyaml`
- **可选增强依赖**: `sentence-transformers`、`colorama`
- **分支状态**: `master`（当前有本地未提交改动）

## 最近进展（已在代码中）

### 1) 记忆系统增强
- 混合检索初始化修复并打通配置透传
- 工作记忆 → 情景记忆的幂等提升
- 压缩摘要可按配置写入工作记忆
- 失败轨迹与成功轨迹学习路径分离

### 2) 自进化质量控制
- 增加成功质量评估：`quality_score` / `quality_level` / `learning_worthy`
- 成功模式分析仅使用高质量成功轨迹
- 失败轨迹生成 `failure_report`，避免错误经验被当成正向技能

### 3) 测试体系
- 已形成单元/集成/性能测试分层
- 覆盖模块包括 memory / adapters / evolution / compressor / CLI
- 全量基线稳定（67 项）

## 当前开发现场（2026-05-04）

### 本地未提交改动
- `.claude/settings.local.json`
- `lighthermes/memory.py`
- `lighthermes/retrieval.py`

### 今日已定位并修复的高严重度问题
1. **`lighthermes/retrieval.py` 结构损坏**
   - 现象：`IndentationError: unexpected indent`
   - 根因：`TFIDFRetriever` 类定义被破坏（改到一半）
   - 修复：恢复类结构与初始化，并将 TF-IDF 流程统一使用 `_tokenize()`

2. **`lighthermes/memory.py` 参数回归**
   - 现象：`NameError: embedding_provider is not defined`
   - 根因：`MemoryManager.__init__` 参数列表误删 `embedding_provider` / `embedding_model`
   - 修复：恢复两个参数并保持向下游透传

### 修复后验证
- `tests/unit/test_memory.py` + `tests/unit/test_core_memory.py`：21/21 通过
- `pytest tests/`：67/67 通过

## 已知风险与限制

1. **混合检索默认关闭**
   - 启用 OpenAI embedding 需要 API key
   - 启用 local embedding 需要本地模型依赖

2. **记忆归档/提升策略仍偏规则化**
   - 当前阈值驱动，后续可继续做自适应优化

3. **真实 API 集成测试仍需外部凭据**
   - 当前 CI/本地主要依赖 mock 与离线测试路径

## 下一步建议（按优先级）

1. 完成本地改动的最小化收敛（本次修复 + 必要文档同步）
2. 在 `memory.py` 补充归档逻辑的小型边界测试（尤其是 index 同步移除）
3. 若准备发版，增加一轮真实 API smoke test（OpenAI/Anthropic 任一）

## 参考文档

- 总览说明：`README.md`
- 路线图：`docs/ROADMAP.md`
- 变更日志：`CHANGELOG.md`
- 测试说明：`tests/README.md`
