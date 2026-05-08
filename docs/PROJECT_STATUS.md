# LightHermes 项目状态

**最后更新**: 2026-05-09
**版本**: v0.3.1（Phase 2 起步）
**状态**: 稳定可用，测试基线通过

## 核心指标

- **测试通过率**: 84/84（`pytest tests/`）
- **核心依赖**: `openai` + `anthropic` + `pyyaml`
- **可选增强依赖**: `sentence-transformers`、`colorama`
- **分支状态**: `master`（仅 `.claude/settings.local.json` 为本地 Claude 配置改动）

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

### 3) 自进化与反模式提示
- 增加成功质量评估：`quality_score` / `quality_level` / `learning_worthy`
- 成功模式分析仅使用高质量成功轨迹
- 失败轨迹生成 `failure_report`，避免错误经验被当成正向技能
- `failure_report` 会按任务类型和关键词召回，并在执行前注入简短非阻断风险提示
- 生成后的 `failure_report` 会优先沉淀到情景记忆，后续可由蒸馏机制进入语义记忆

### 4) 测试体系
- 已形成单元/集成/性能测试分层
- 覆盖模块包括 memory / adapters / evolution / compressor / CLI / performance
- 全量基线稳定（84 项）

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

4. **真实 API 集成测试仍需外部凭据**
   - 当前 CI/本地主要依赖 mock 与离线测试路径

## 下一步建议（按优先级）

1. 继续优化 `distill_memories()` 的稳定事实筛选策略
2. 借鉴 nanobot 的轻量 agent/tool/skill/channel 架构，先收敛边界，不直接整体集成
3. 若准备发版，增加一轮真实 API smoke test（OpenAI/Anthropic 任一）

## 参考文档

- 总览说明：`README.md`
- 路线图：`docs/ROADMAP.md`
- 变更日志：`CHANGELOG.md`
- 测试说明：`tests/README.md`
