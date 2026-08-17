# LightHermes 发展路线图

**版本**: v0.4.0 Active Memory 规划
**更新时间**: 2026-08-15
**设计理念**: 保持轻量，用可观测、按需、预算受控的主动召回把分级记忆真正用好，再小步扩展工具与生态

---

## 当前结论

- **记忆基础设施已经完成**：结构化召回、四级生命周期、蒸馏治理、反模式提示、内置 `search_memory`、安全边界和测试覆盖已经形成稳定基线。
- **记忆智能运行时已具备**：两轮搜索、来源展开、claim 写回、缺席状态和建议改写已落地；质量仍待 static / agentic A/B。
- **真实评测改变了优先级**：40 题 LoCoMo 分层抽样中，静态 Top-5 Evidence Hit 为 59.0%、Evidence Recall 为 49.2%、端到端 QA 为 50.0%；召回命中后 QA 为 70%，未命中时仅 19%。这些数字用于定位问题，不作为产品优化目标或唯一发布门槛。
- **v0.4.0 主线调整为 Active Memory**：先完成评测可信度、主动召回闭环、来源展开和双层记忆表征；插件/工具生态顺延到 v0.5.0。

### A/B 准入前定案的三项决策（2026-08-15）

讨论结论，作为 A/B 开跑前的既定方向，不反复推翻。

1. **确定性停答 trigger（瘦 A，不做 prompt 对照）**
   - 不选「模型自选搜不搜」来跑 A/B：模型搜索行为与召回质量纠缠，不可归因。
   - 不选「再加一条 prompt ablation」：实验矩阵乘 1.5，违反“先收敛再扩展”；prompt 对照留到同一套冻结数据后补跑。
   - 不放宽为「未解决 claim ∧ budget>0 → 强制搜」：seed 默认就是一条 unresolved claim，等于每题至少多搜一轮，会把 3.6 的「平均 ≤1.6 次调用」先打死。
   - **规则卡在停答点而非开场**：模型要结束回答 ∧ `can_search()` ∧ `absence ∈ {not_searched, evidence_conflict}` ∧ `coverage < 1` → 不判 `sufficient`，运行时用 `suggested_query` 自行执行一轮搜索（`trigger=forced`），结果交回模型。
   - 强制搜必须是**运行时检索**，不走「驳回再求模型发一次 tool call」：后者多一次模型调用，成本门槛先炸。
   - 与「自动 NLI」无关：trigger 只管“要不要再找”，`judge_claim` 仍由模型写 support/conflict；“相似度不当支持度”这条设计不改。
   - trace 至少新增 `trigger_reason`、`forced_rounds`、`would_have_stopped_early`；缺这三项，A/B 依旧分不清“没触发”与“召回差”。
   - 3.2 原「根据证据覆盖不足/冲突/可验证性不足触发主动搜索」勾掉是正确历史：P1 刻意做模型自选。现在它应从「P2 远景」改为「A/B 准入条件」，不再悬挂。

2. **3.3 只做最小闭环（瘦 A），完整表征排到 A/B 后**
   - 矛盾不在 ROADMAP 编号（3.3 写在 3.6 前），而在执行顺序：PROJECT_STATUS 与设计文档第 11 节下一步直接跳 A/B，3.3 整段空着。
   - 不选「先测现状」：不能拿半成品当 3.3 结论，文档还要改口径，后面补表征等于重跑。
   - 不选「表征与 A/B 骨架并行」：人来对齐，对这个体量是空转。
   - **做**：写入时 `abstract ≠ raw`（工作记忆已有摘要；情景/语义至少摘要/首句 vs 原文）；检索打 `abstract + cue_anchors`；回答/验证走已有点 `read_memory` 原文。
   - **不做（A/B 后再说）**：`supersedes` 版本链；联想线索、图谱关系；完整 status/event_time 治理。
   - **验收只有一条**：同一条记忆，检索命中所用文本 ≠ 回答展示的原文。当前 episodic/semantic 的 `abstract = content` 过不了这一条。A/B 测“分流后的运行时”，不是半成品字段。
   - 3.4/3.5 继续排在 A/B 之后，不挡归因。

3. **防调参过线：冻结宣言先行（选 A）**
   - 不选「数据保管人模式」：单人/小团队，holdout 文件不进仓库、不进上下文即可。
   - 不选「只报告不设卡」：3.6 是 Phase 3 完成指标，改软等于改发布定义，须改 ROADMAP，不能口头放水。
   - 冻结宣言已落 `docs/FREEZE_COMMITMENT.md`（五条 + 执行纪律），优先于写评测脚本。
   - 3.6 门槛是「Active Memory 默认开启」的发布闸，不是“代码能否合入”的闸。跑输就默认关闭发版并如实披露，比改软门槛更干净。
   - 附加执行纪律：验证集连续看过 2 次仍未过线，只许出诊断报告，不许第三轮拧参。

### 落地顺序（现状 + 后续）

1. ✅ 停答点确定性 trigger + trace（决策 1）——已完成，含空结果/错误/覆盖/无 dispatcher 场景的 core 测试。
2. ✅ 冻结宣言（决策 3）——半页纸短文已落 `docs/FREEZE_COMMITMENT.md`；真正锁参见第 5 条。
3. ✅ abstract/cue 检索、原文回答最小闭环（决策 2，即 3.3a）——已完成。
4. ✅ 合成 case 单测（强制搜、冲突、无新证据）——`TestSyntheticScenario` 3 项端到端通过。
5. ⬜ 策略冻结 → static / agentic A/B → holdout 一次。冻结清单已落 `docs/FREEZE_LOCK.md`；开发集 A/B 入口为 `benchmarks/locomo_light.py --mode ab`。

静态臂测召回，主动臂测 trigger+召回；两侧表征相同，结果才拆得开。

这次调整不否定 Phase 2：Phase 2 完成的是“能存、能管、能搜”，v0.4.0 要解决的是“知道何时继续找、如何找全、何时可以回答”。

---

## 设计原则

1. **轻量优先**: 核心代码保持小而清晰，避免引入重框架
2. **渐进增强**: 高级功能可选，不增加基础依赖
3. **安全默认**: 文件写入、外部集成、多模态等能力默认关闭或按需开启
4. **实用为主**: 优先解决真实使用场景的问题
5. **科研探索**: 在稳定基础上实验创新想法，但避免过早复杂化
6. **评测驱动**: 优先用真实基准和阶段诊断决定优化方向，不用单一合成分数代替真实结论
7. **预算可控**: 高级召回按需触发，设置轮次、上下文、调用量和成本上限
8. **泛化优先**: 运行时不读取 benchmark 标签，不加入数据集专用规则；策略必须由通用证据状态驱动，并通过未见样本验证

---

## Phase 1: 可用性增强（v0.3.1）✅ 已完成

**目标**: 提升日常使用体验，修复已知问题

### 1.1 MiniMax 流式响应修复
**状态**: 已完成

- [x] 深度调试 MiniMax 流式响应格式
- [x] 实现更智能的增量文本提取算法
- [x] 添加流式响应单元测试

### 1.2 “记住”功能
**状态**: 已完成

- [x] 实现记忆提取功能（检测“记住”关键词）
- [x] 使用 LLM 提取关键信息
- [x] 创建 SOUL.md 和 USER.md 固定记忆文件
- [x] 直接注入到 system prompt，无需查询匹配

### 1.3 CLI 体验优化
**状态**: 已完成

- [x] `/stats` - 显示详细统计
- [x] `/export` - 导出对话历史
- [x] `/reset` - 重置会话但保留记忆
- [x] 改进错误提示和帮助信息

### 1.4 测试覆盖
**状态**: 已完成

- [x] 添加 pytest 配置和共享 fixtures
- [x] 完成记忆系统、Adapter、自进化、上下文压缩、CLI、性能测试
- [x] 当前测试基线：113/113 通过
- [x] 添加测试文档（tests/README.md）

---

## Phase 2: 记忆蒸馏与轻量架构收敛（v0.3.x 主线）✅ 已完成

**目标**: 删除过重的记忆图谱方向，围绕“分级记忆如何真正被用好”继续增强；同时参考 Hermes 的记忆生命周期与 nanobot 的轻量 agent/tool/skill/channel 架构，保持 LightHermes 简洁可维护。

**参考项目取舍**:
- LightAgent：借鉴工具注册、轻量 `MemoryProtocol` 和候选工具过滤思路；不照搬 `la_core.py` 的大单文件混合架构。
- Hermes：优先借鉴记忆生命周期、召回上下文 fencing、压缩摘要“仅作参考而非当前指令”的安全措辞；不照搬外部 memory provider 插件体系。
- nanobot：优先借鉴 hook、tool registry、schema 校验和 skill frontmatter 解析；暂缓 cron、gateway 等生态能力。

### 2.1 记忆蒸馏与容量治理 ✅

- [x] 设计 `distill_memories()`：从工作/情景记忆中提炼高价值语义记忆
- [x] 增加记忆容量预算：对语义记忆设置字符/条目上限，避免无限追加
- [x] 增加重复与近重复检测：同类记忆优先合并而不是新增
- [x] 增加蒸馏元数据：`distilled_from`、`source_layer`、`confidence`、`last_verified`
- [x] 为归档、提升、蒸馏补边界测试，尤其是索引同步移除和幂等性

### 2.2 分级记忆生命周期 ✅

- [x] `on_turn_start(query)`：准备召回上下文，并用 `<memory-context>` 安全包装
- [x] `on_turn_end(user, assistant)`：同步助手回复到短期记忆
- [x] `on_pre_compress(messages)`：压缩前提取即将丢失的轻量线索
- [x] `on_session_end(messages)`：CLI `/exit`、`/reset`、KeyboardInterrupt/EOF 时生成短期摘要并触发迁移/归档/提升
- [x] `on_memory_write(...)`：固定记忆或用户偏好写入时进入统一生命周期入口

### 2.3 自进化与反模式学习 ✅

- [x] 成功质量评估：只从高质量成功轨迹生成技能
- [x] 失败轨迹生成 `failure_report`，不再包装成正向技能
- [x] 建立轻量反模式索引：让 `failure_report` 可以按任务类型/关键词召回
- [x] 在任务执行前召回相关失败报告，作为风险提示注入上下文
- [x] 为高危反模式生成简短 warning，而不是阻断执行
- [x] 将反模式学习结果优先存入情景记忆，稳定后再蒸馏到语义记忆

### 2.4 轻量 agent/tool/skill/channel 架构借鉴 ✅

- [x] tool：拆出 `lighthermes/tools.py`，统一工具装饰器、注册和调用边界
- [x] skill：拆出 `lighthermes/skills.py`，保留 Markdown skill 优先和失败报告召回能力
- [x] hook：新增 `lighthermes/hooks.py`，封装生命周期钩子的安全调用
- [x] channel：新增 `lighthermes/channels.py`，预留直接消息通道边界但不接入复杂 bus
- [x] `core.py` 保持主循环和兼容门面，不移动 `LightHermes`，不破坏现有导入路径

### 2.5 记忆工具计划 ✅

- [x] 结构化记忆召回：`recall_items()` 返回层级、来源、分数、优先级和元数据
- [x] 显式记忆搜索：`search_memory()` 支持指定层级和元数据返回
- [x] 内置 `search_memory` 工具：默认启用，支持用户同名工具覆盖
- [x] 受控只读文件工具：`read_file` / `search_files`，默认关闭
- [x] 受控写文件工具：`write_file` 单独显式开启，支持 `create`、`overwrite`、`append`
- [x] 安全边界：`roots` 白名单、排除目录、敏感文件保护、二进制文件拒绝、大小限制
- [x] 配置入口：`tools.builtin` 统一控制内置工具能力
- [x] 测试覆盖：结构化召回、工具注册、同名覆盖、文件安全边界和核心配置集成

### 2.6 多模态支持（低优先级，移入想法池）

原 2.5 多模态支持暂不作为 Phase 2 主线。后续如推进，应保持轻量：优先复用模型原生图片能力，不引入重依赖。

---

### 2.7 发版准备与真实 API smoke test ✅ 已完成

**目标**: 在进入生态扩展前，确认当前稳定基线可发版。

- [x] 选择至少一条真实模型链路做 smoke test：MiniMax Anthropic 兼容端点
- [x] 验证非流式最小对话路径：`MiniMax-M2.7` 返回 `MiniMax smoke test OK`
- [x] 验证流式最小对话路径：原始流式和 Adapter 流式均返回 `MiniMax smoke test OK`
- [x] 验证 `search_memory` 工具注册不影响普通对话
- [x] 检查 `config.yaml` 示例和 README 配置一致
- [x] 统一更新 `lighthermes/__init__.py`、`setup.py`、README、CHANGELOG 版本号到 `0.3.3`
- [x] 创建发布说明，明确文件工具默认关闭和安全边界

---

### 2.8 v0.3.4 收口修复 ✅ 已完成

**目标**: 修复 v0.3.3 后发现的流式工具调用和记忆性能回归，并统一发布状态。

- [x] 修复 `_run_stream` 流式工具调用二次请求路径，统一使用 `_call_api_with_fallback`
- [x] 清理 Evolution 技能生成中的死代码 fallback
- [x] 修复语义记忆大批量召回性能回归
- [x] 统一 `lighthermes/__init__.py`、`setup.py`、CLI、README、PROJECT_STATUS、ROADMAP 和 CHANGELOG 到 `0.3.4`
- [x] 当前测试基线：113/113 通过

---

## Phase 3: Active Memory（v0.4.0 主线）

**目标**: 将一次性静态召回升级为可观测、按需、预算受控的主动记忆重建，同时保持黑盒模型兼容和最小依赖。

目标链路：

```text
初始 Top-K 召回
      ↓
证据充分性判断
      ├─ 充分：回答
      └─ 不充分：查询改写 → 多轮搜索 → 候选融合
                                    ↓
                              来源/相邻记忆展开
                                    ↓
                              证据账本与停止判断
```

### 3.0 评测可信度与可观测性（最高优先）

- [x] 增加 LightHermes 原生 LoCoMo 轻量评测入口
- [x] 建立类别均衡的 40 题开发基线，记录 Recall、MRR、QA、延迟、token 和成本
- [x] embedding 缓存路径可配置，benchmark 使用独立持久缓存
- [x] embedding 或 hybrid 失败时严格失败，禁止静默关键词降级污染评测
- [ ] 建立多轨评测矩阵：Memory Eval 回归、长对话、更新/冲突、真实工作流回放
- [ ] 将 LoCoMo 划分为已见开发样本、冻结验证样本和最终 holdout，禁止按 holdout 个例调规则
- [ ] 至少增加一种结构不同的未见评测集或隐私安全回放，验证跨数据集泛化
- [x] P0 记录每轮查询、候选 ID/分数、来源增益、工具错误、延迟和停止原因
- [x] P1 记录来源读取与邻接展开
- [x] P1 记录 query rewrite 和模型确认的最终证据（`judgments` / `rewrites`）
- [ ] 区分 Indexing、Retrieval、Reading、Answering 四阶段错误
- [ ] 固定数据划分、抽样清单和随机种子，保证 static / agentic A/B 可复现

### 3.1 可观测运行时基座（P0）

先建立与具体 benchmark、存储后端和模型供应商无关的数据契约。该层只描述证据与召回生命周期，不负责替代 `MemoryManager` 或另起一套 Agent 循环。

- [x] 定义兼容现有记忆条目的 `MemoryRecord`
- [x] 定义 `EvidenceLedger`：claim、支持来源、冲突、覆盖度、置信度和待验证项
- [x] 定义 `RecallTrace`：轮次、查询、候选、来源、增益、延迟、降级和停止原因
- [x] 统一停止原因：`sufficient`、`no_new_evidence`、`budget_exhausted`、`disabled`、`error`
- [x] 新路径由配置开关控制且默认关闭，不改变现有 `recall_items()` / `search_memory` 接口
- [x] 轨迹只记录可观察的状态与动作，不保存模型隐藏推理
- [x] 为状态模型、候选去重、增益判断和轮次预算补齐离线单元测试

### 3.2 两轮主动召回 MVP（P1）

- [x] 保留首次自动 Top-K，作为低延迟种子上下文
- [x] 根据证据覆盖不足、检索不确定性、来源冲突、可验证性不足和检索增益触发主动搜索
  - 说明：P1 为模型自选（prompt 驱动）实现；定案后的确定性停答 trigger 为「A/B 准入条件」，规则见「当前结论」决策 1（`should_force_search` + forced round），不按字面「未解决 claim 就搜」。
- [x] 让首次模型调用直接选择“回答”或“调用记忆工具”，不额外引入独立 Planner
- [x] 查询改写来自未解决 claim 和新发现的 cue anchors，不读取 benchmark 类别或题目模板
- [ ] 合并 TF-IDF、embedding 和多轮候选，去重后统一重排
- [x] 建立通用 evidence ledger 数据契约，聚合 candidate/support/conflict/coverage
- [x] 将模型确认的 claim 支持、冲突、缺口和置信度写回 ledger
- [x] 按 `source` 读取完整记忆，并通过可选类型关系展开邻居；session 仅作为一种来源适配器
- [x] 最多两轮主动搜索；达到证据充分、连续无新增证据或预算上限时停止
- [x] 回答时区分“记忆中没有”与“当前检索尚未找到”

### 3.3 双层记忆表征与 Cue Anchors

> 拆分为「最小闭环（A/B 准入，先做）」与「完整表征（A/B 后）」。最小闭环的取舍见「当前结论」决策 2。

#### 3.3a 最小闭环（A/B 准入，先行）

借鉴 Primary Abstraction + Cue Anchors 思路，但不引入独立 MEMORY 模型或重型知识图谱。

- [x] 写入时 `abstract ≠ raw`：情景/语义「首句摘要」与原文分离（`derive_abstract`）
- [x] 检索打「abstract + cue_anchors」；TF-IDF + embedding + 层级关键词匹配都吃 abstract
- [x] 回答/验证走已有点 `read_memory` / `get_source` 原文
- [x] **验收**：同一条记忆，检索命中所用文本（abstract）≠ 回答展示原文（content）；`TestAbstractRawSeparation` 4 项覆盖

#### 3.3b 完整表征（A/B 之后）

- [ ] 增加 `entities`、`event_time`、`status`、`confidence` 和 `last_verified`
- [ ] 支持描述性线索和联想性线索，避免只依赖问题原词
- [ ] 为 current / historical / rejected / failure_report 保留明确状态边界
- [ ] 增加 `supersedes`，用版本链表达更新，不粗暴覆盖旧事实
- [ ] 继续使用 Markdown/SQLite 和现有依赖，不要求图数据库

### 3.4 轻量连接演化与选择性固化

- [ ] 增加轻量关系：`same_entity`、`same_event`、`adjacent_session`、`supports`、`conflicts_with`
- [ ] 根据共同召回、成功回答和用户反馈调整连接权重
- [ ] 重复出现且稳定的事实才从情景记忆固化到语义记忆
- [ ] 低价值、长期无用或被替代的连接逐步衰减
- [ ] 保留每次更新的前态、后态、原因和证据，支持追溯

### 3.5 经验记忆与选择性进化

工具使用经验与用户事实记忆分开建模。先记录可验证的成功、失败、成本和延迟，再由稳定证据决定是否生成技能或失败报告。

- [ ] 定义 `ExperienceRecord`：任务类型、工具序列、结果、外部反馈、成本、延迟和来源轨迹
- [ ] 将 `EvolutionEngine` 的完成态轨迹与 recall/tool trace 关联
- [ ] 区分流程正常完成、用户确认成功和外部验证成功
- [ ] 失败经验默认作为风险证据，不直接升级为正向技能
- [ ] 只有跨任务重复出现且收益稳定的经验才固化为技能

### 3.6 跨场景泛化验收门槛

LoCoMo 40 题只作为已见开发基线，不作为 v0.4.0 的单一优化目标。策略和提示冻结后，再运行验证集、最终 holdout 和结构不同的评测轨道。

- [ ] 运行时不读取 benchmark 标签、evidence 标注或样本 ID，不包含数据集专用关键词规则
- [ ] static / agentic A/B 至少覆盖合成回归、长对话、更新/冲突、真实工作流中的三条轨道
- [ ] Active Memory 至少在两条独立轨道上稳定提升，且任一轨道不得出现超过 2 个百分点的显著回归
- [ ] 同时报告 evidence coverage、最终 QA、拒答/未知判断和阶段错误，禁止只优化单一总分
- [ ] 报告开发集、验证集和最终 holdout 的泛化差距；holdout 只在策略冻结后运行
- [ ] 主动搜索最多 2 轮，平均生产模型调用不超过 1.6 次/问题
- [ ] 平均成本不超过静态方案 2 倍，并报告每个正确答案的成本
- [ ] embedding/hybrid 降级必须显式记录，禁止将降级结果计入正式指标
- [ ] LoCoMo 开发基线 59.0% Hit / 50.0% QA 仅用于回归参考，不因个例失败添加特判

### 3.7 v0.4.0 明确不做

- 不训练独立 MEMORY 模型
- 不做 RL、在线 LoRA 或参数化蒸馏
- 不引入 Neo4j 等重型图数据库
- 不追求让记忆架构自动重写自身
- 不在主动召回验证前扩展多 agent 共享记忆
- 不按 benchmark 类别、样本 ID、答案或个例失败硬编码召回规则

---

## Phase 4: 生态扩展（v0.5.0 候选）

**目标**: 构建轻量级工具生态，但不牺牲默认安全和最小依赖。

### 4.1 插件系统完善（中优先）

- [ ] Python 插件加载机制
- [ ] 插件目录扫描和显式启停配置
- [ ] 插件依赖管理（轻量级，避免自动安装重依赖）
- [ ] 插件错误隔离和测试样例
- [ ] 插件市场（GitHub-based，可后置）

### 4.2 工具集成（按需）

- [ ] Docker 镜像
- [ ] GitHub Actions 集成
- [ ] VS Code 插件（基础版）
- [ ] Web UI（可选，倾向后置）

---

## Phase 5: 性能优化（持续）

**目标**: 保持轻量的同时提升性能。

### 5.1 记忆系统优化
- [ ] 记忆检索缓存（LRU）
- [ ] 索引优化（可评估 SQLite FTS5，但不作为默认复杂依赖）
- [ ] 批量操作优化
- [ ] 异步 I/O（可选）

### 5.2 API 调用优化
- [ ] 请求缓存（相同查询）
- [ ] 批量请求支持
- [ ] 连接池管理
- [ ] 重试策略优化

---

## 科研实验想法池

以下方向保留为想法池，不进入近期主线：

1. **多模态支持**
   - 支持图片输入（Claude / GPT 系列原生能力）
   - 支持代码截图理解
   - 支持架构图生成（优先 mermaid 文本）
   - 不引入额外重依赖

2. **元学习与迁移学习**
   - 从一个项目学到的技能迁移到另一个项目
   - 跨项目的知识共享机制
   - 个性化的智能体人格

3. **协作智能体**
   - 多个 LightHermes 实例协作完成任务
   - 任务分解与分配策略
   - 协作通信协议（轻量级）

4. **主动学习**
   - 智能体主动提问以获取更多信息
   - 不确定性估计与查询策略
   - 人机协作的最优策略

5. **可解释性**
   - 解释智能体的决策过程
   - 可视化记忆检索和技能选择
   - 生成决策报告

6. **安全与隐私**
   - 本地模型支持（Ollama 集成）
   - 敏感信息检测与过滤
   - 记忆加密存储

7. **代码理解增强**
   - AST 分析与代码图谱
   - 依赖关系可视化
   - 代码变更影响分析

---

## 实施策略

### 开发节奏
- **先能力单测再 benchmark**: 先用合成 case 验证证据充分性、停止条件和冲突处理，再运行 LoCoMo 开发样本
- **先冻结再 holdout**: 开发样本只用于诊断；策略冻结后才运行验证集和最终 holdout
- **跨场景再发版**: 至少两类结构不同的记忆任务获得稳定提升，才将 Active Memory 视为可发布能力
- **先收敛再扩展**: 每次只推进一个边界清晰的小功能
- **文档同步**: 计划、状态和测试说明随代码同步更新
- **阶段诊断优先**: 分开评估写入、召回、阅读和回答，避免用最终准确率掩盖根因
- **参考不照搬**: 借鉴 MRAgent、MEMORA、T-Mem、MemTrace 等思路，但保持 LightHermes 极简、黑盒兼容

### 质量保证
- **测试先行**: 主动召回状态机、预算停止、候选融合、来源展开和降级检测先补测试
- **边界验证**: 重点覆盖索引同步、幂等性、容量限制、显式失败、调用预算和敏感信息边界
- **基线稳定**: 当前测试基线为 220/220；每个功能完成后跑 `pytest tests/`
- **真实评测隔离**: benchmark 使用独立记忆、独立缓存和合成/公开数据，不读取真实用户记忆

---

## 成功指标

### 可用性指标
- CLI 启动时间 < 1s
- API 响应时间 < 2s（非流式）
- 关键词记忆检索时间 < 100ms；远程 hybrid 单独报告延迟与可用性
- 测试覆盖率 > 80%

### 轻量性指标
- 核心代码尽量保持在小规模、易读范围内
- 核心依赖 < 5 个
- 安装包大小 < 10MB
- 内存占用 < 100MB

### Phase 2 完成指标
- [x] 工作记忆、情景记忆、语义记忆迁移路径清晰且幂等
- [x] 语义记忆具备容量治理和合并策略
- [x] 失败报告可被检索并用于执行前风险提示
- [x] agent/tool/skill/channel 边界更清晰，但不引入重框架
- [x] 记忆可通过内置工具显式搜索
- [x] 文件工具可按配置受控开启，默认安全关闭

### Phase 3 完成指标
- [ ] 首次模型调用可以根据证据充分性选择回答或继续检索
- [ ] 主动召回具备查询改写、候选融合、来源展开和预算停止
- [ ] MemoryRecord 同时保留抽象、线索锚点和可验证原始来源
- [x] benchmark strict 模式能区分 hybrid 成功和显式失败，不将降级结果混入正式指标
- [ ] 多轨 static / agentic A/B 达到 3.6 的泛化、质量与成本门槛
- [ ] 运行时策略不依赖 benchmark 标签、样本 ID 或数据集专用规则
- [ ] 不增加必选重依赖，不破坏现有静态召回和 `search_memory` 兼容接口

---

## 参考资源

- **设计文档**: `docs/superpowers/specs/`
- **项目状态**: `docs/PROJECT_STATUS.md`
- **变更日志**: `CHANGELOG.md`
- **本地参考**: `hermes-agent/`、`nanobot/`（均不纳入 LightHermes 提交）
- **研究分类参考**: `D:\11056\Documents\Obsidian Vault\LLM WIKI\comparisons\agent-memory-taxonomy.md`

---

**最后更新**: 2026-08-15
**维护者**: @wyw  
**反馈**: 欢迎通过 GitHub Issues 提供反馈
