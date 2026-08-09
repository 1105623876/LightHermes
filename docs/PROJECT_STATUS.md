# LightHermes 项目状态

**最后更新**: 2026-08-09
**发布版本**: v0.3.4
**开发主线**: v0.4.0 Active Memory
**状态**: Active Memory Runtime P0 + 最小 P1 已实现，默认关闭并等待真实 A/B

## 当前基线

- **测试**: 166/166 通过（`.\venv\Scripts\python.exe -m pytest tests`）
- **核心依赖**: `openai`、`anthropic`、`pyyaml`
- **可选增强**: `sentence-transformers`、`colorama`
- **模型端点**: 主模型与 embedding 可分别配置 provider、model、API key 和 base URL
- **记忆评测**: Memory Eval v2.1 合成回归 + LoCoMo 40 题分层开发基线
- **当前定位**: 面向单用户、本地或嵌入式场景的轻量记忆增强智能体运行时

## 已具备能力

### 记忆与召回

- 短期、工作、情景、语义四级记忆及生命周期钩子
- `MemoryManager.recall_items()` 结构化召回和兼容的字符串接口
- TF-IDF 初筛、独立 embedding 端点、跨层统一重排和显式降级边界
- 默认内置 `search_memory` 工具，支持层级与元数据过滤
- 记忆蒸馏、近重复合并、容量治理、状态过滤和来源元数据

### Agent 运行时

- OpenAI、Anthropic 与兼容端点适配
- 非流式/流式工具循环和统一回合收尾
- 上下文压缩、Markdown 技能、失败报告和轨迹记录
- 受控文件工具；读、搜索、写入均按配置显式开启

### 评测与稳定性

- 166 项单元、集成与性能测试
- Memory Eval v2.1：Recall@K、MRR、Precision@K、噪声率、延迟和质量门槛
- LoCoMo 轻量入口：固定分层样本、独立 embedding 缓存、token/成本记录和 strict 失败模式
- 当前 LoCoMo 静态开发基线：Evidence Hit@5 59.0%，QA 50.0%

## 当前判断

静态召回已经达到“可使用、可回归、可诊断”的阶段；Active Memory 的运行时基座也已落地：

1. `MemoryRecord`、`EvidenceLedger`、`RecallTrace` 和 `ActiveRecallSession` 已实现。
2. seed context 与结构化 item 来自同一次召回，不重复消耗 embedding。
3. 内置 `search_memory` 最多执行两轮，并按回答、无新增证据、预算耗尽、取消或错误停止。
4. trace 记录候选 ID/分数、来源增益、延迟、错误和公开 session 元数据，不记录隐藏推理。
5. 新路径默认关闭；用户自定义同名工具和原有静态路径保持兼容。

这仍不是完整的主动记忆质量闭环。当前 evidence ledger 主要聚合 candidate source，尚未让模型显式更新 claim 支持/冲突；query rewrite、来源全文/邻接展开和真实 static/agentic A/B 也尚未完成。

详细设计见 `docs/superpowers/specs/2026-08-09-active-memory-runtime-design.md`。

## 已知限制

1. **主动召回仍是 MVP**
   - 已有单回合状态、两轮预算和 trace，但默认关闭。
   - 尚无通用 query rewrite、来源全文/邻接展开和模型级 claim 判定。
   - 尚未通过真实 static / agentic A/B 证明质量收益与成本边界。

2. **长期记忆表征仍偏检索条目**
   - 已有来源与状态元数据，但缺少统一的 abstract、cue anchors 和版本链契约。
   - 回答阶段尚未把“检索摘要”和“可验证原始来源”明确分层。

3. **真实评测规模有限**
   - LoCoMo 40 题属于已见开发样本，不代表生产质量。
   - 仍需冻结验证集、最终 holdout、更新/冲突和隐私安全工作流回放。

4. **产品边界仍是本地单用户**
   - 尚无多用户命名空间、外部数据库后端、网络 Channel 或成熟插件系统。
   - 这些能力在 Active Memory 泛化验证前不进入主线。

## 下一步

### 已完成：P0 + 最小 P1

- 兼容现有结构化记忆的 `MemoryRecord`
- claim/candidate/support/conflict/coverage evidence ledger
- 候选分数、来源增益、延迟、错误和停止原因 trace
- 首轮 seed + 最多两轮内置记忆搜索
- 默认关闭，保留原有接口与自定义工具覆盖语义

### 下一步：P1 完整闭环

- 从未解决 claim 与 cue anchors 生成通用 query rewrite
- 按 source 读取完整记忆并展开可选邻接来源
- 让模型显式更新 support/conflict/unknown，而不是只聚合候选
- 区分“记忆中没有”和“当前尚未检索到”的稳定输出协议

### P2：泛化验证与经验记忆

- 建立 static / agentic A/B 和阶段错误诊断
- 冻结策略后运行验证集、holdout 与结构不同的工作流回放
- 将工具成功、失败、成本与延迟接入可追溯的经验记录，再决定是否固化为技能

## 参考文档

- 总览：`README.md`
- 路线图：`docs/ROADMAP.md`
- 设计规范：`docs/superpowers/specs/`
- 实施计划：`docs/superpowers/plans/`
- 测试说明：`tests/README.md`
- 变更记录：`CHANGELOG.md`
