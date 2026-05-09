# LightHermes

**极简自进化智能体框架** — 在 LightAgent 的轻量哲学上，加入记忆与自进化能力

## 设计理念

- **极简主义**: 核心约 3700 行，无重框架依赖（无 LangChain/LlamaIndex）
- **开箱即用**: 默认关键词检索，可选语义增强
- **渐进增强**: 从最简实现开始，按需启用高级特性

## 核心特性

- **四级记忆系统**: 短期/工作/情景/语义分层管理，对话上下文、会话摘要、项目经验和长期知识各自落在合适层级。
- **记忆生命周期钩子**: 在回合开始、回合结束、压缩前、会话结束和记忆写入时沉淀上下文，并用 `<memory-context>` 隔离召回内容。
- **记忆层级迁移**: 根据访问频率自动在层级间流动，低频归档、高频提升，避免长期记忆无限堆积。
- **自适应记忆**: 记录检索命中率、耗时和结果数，为后续动态调参和检索策略优化保留数据基础。
- **上下文压缩**: 智能压缩长对话，保留关键决策、待办和解决方案，防止 token 溢出。
- **自进化能力**: 记录任务轨迹、分析成功/失败模式，并从高质量成功轨迹中生成 Markdown 技能。
- **生产稳定性**: 轻量日志、模型降级、错误处理和测试基线，保持小框架的可维护性。
- **技能系统**: 支持 Markdown 技能和 Python 插件，默认优先生成无需执行代码的 Markdown 技能。
- **多 API 支持**: OpenAI + Anthropic + MiniMax (Anthropic 兼容)，通过统一 Adapter 隔离供应商差异。
- **交互式 CLI**: 支持记忆统计、配置查看、手动压缩、历史导出和会话重置。

## 快速开始

### 安装

```bash
pip install -r requirements.txt
```

### 配置

设置 API key（二选一）：

```bash
# 环境变量
export OPENAI_API_KEY=your_key

# 或编辑 config.yaml
model:
  api_key: your_key
```

**使用 Anthropic API**:

```python
agent = LightHermes(
    name="MyAgent",
    role="编程助手",
    model="claude-sonnet-4-6",
    provider="anthropic",
    api_key="your_anthropic_key"
)
```

**使用 MiniMax (Anthropic 兼容端点)**:

```python
agent = LightHermes(
    name="MyAgent",
    role="编程助手",
    model="claude-sonnet-4-6",
    provider="anthropic",
    api_key="your_minimax_key",
    base_url="https://api.minimaxi.com/anthropic"
)
```

> **注意**: MiniMax 的流式响应返回累积文本而非增量文本，但 LightHermes 已自动处理此差异，可正常使用流式输出。

### 使用

**Python API**:

```python
from lighthermes import LightHermes

agent = LightHermes(
    name="MyAgent",
    role="编程助手",
    model="gpt-4o-mini"
)

response = agent.run("帮我解释这段代码")
print(response)
```

**CLI**:

```bash
# 启动 CLI（需先在 config.yaml 中配置 API key）
python -m lighthermes.cli

# 可用命令
/help       # 显示帮助信息
/skills     # 列出所有可用技能
/memory     # 显示记忆系统统计
/stats      # 显示详细统计（API 调用、token 使用、记忆命中率）
/config     # 显示当前配置
/compress   # 压缩当前对话上下文
/export     # 导出对话历史到 JSON 文件
/reset      # 重置会话但保留长期记忆
/exit       # 退出
```

## 项目结构

```
LightHermes/
├── lighthermes/       # 核心代码
│   ├── core.py         # 主引擎
│   ├── memory.py       # 四级记忆系统
│   ├── evolution.py    # 自进化系统
│   └── cli.py          # 命令行界面
├── skills/             # 技能库
│   ├── core/           # 内置技能
│   ├── user/           # 用户自定义
│   └── generated/      # 自动生成
├── plugins/            # 插件
├── memory/             # 记忆存储
└── config.yaml         # 配置文件
```

## 系统架构

LightHermes 的核心设计是“少量模块 + 清晰边界”：

- `LightHermes` 主引擎负责对话循环、工具调度、记忆注入、上下文压缩和自进化触发。
- `MemoryManager` 管理四级记忆，并统一对外提供保存、召回、迁移、生命周期钩子和统计接口。
- `ContextCompressor` 在上下文接近窗口上限时压缩中间对话，保留开头设定和最近消息。
- `EvolutionEngine` 记录会话轨迹，分析高质量成功模式和失败模式，生成可复用技能。
- `BaseAdapter` 统一不同模型供应商的调用方式，核心逻辑不直接绑定 OpenAI/Anthropic SDK。
- `CLI` 提供本地交互入口，适合快速测试记忆、压缩、技能和模型配置。

## 记忆系统设计

LightHermes 内置四级记忆，默认先使用轻量关键词检索，按需启用语义增强：

| 层级 | 作用 | 典型内容 |
|------|------|----------|
| 短期记忆 | 当前对话窗口 | 最近用户消息、助手回复、工具结果 |
| 工作记忆 | 当前会话摘要 | 压缩后的会话重点、阶段性任务上下文 |
| 情景记忆 | 项目/任务经验 | 某次调试、实现、设计讨论的沉淀 |
| 语义记忆 | 长期知识 | 稳定事实、用户明确要求记住的信息、可复用知识 |

关键机制：

- **中英文混合分词**: 关键词索引支持中文字符和英文 token，避免中文记忆无法命中。
- **召回上下文隔离**: 召回记忆通过 `<memory-context>` 注入，明确标记为背景信息而不是新的用户指令。
- **固定记忆注入**: `memory/SOUL.md` 和 `memory/USER.md` 可直接注入 system prompt，用于稳定保存智能体设定和用户偏好。
- **生命周期沉淀**: 回合结束同步短期记忆，压缩前提取轻量线索，CLI 退出或重置时生成会话摘要并触发迁移。
- **工作记忆提升**: 工作记忆可幂等迁移到情景记忆，避免重要会话摘要丢失。
- **压缩摘要入库**: 可配置将上下文压缩摘要写入工作记忆，让长对话压缩结果继续被后续召回。
- **可选混合检索**: 默认不开启 embedding；需要更精确召回时可启用 OpenAI 或 local embedding。

## 自进化系统设计

自进化模块目前保持轻量，不追求复杂强化学习，而是记录轨迹、筛选高质量经验、生成可读技能：

1. **轨迹记录**: 保存会话消息、工具调用、任务类型、成功状态、迭代次数和用户纠正次数。
2. **质量评估**: 为成功轨迹计算 `quality_score`、`quality_level`、`learning_worthy` 和 `quality_metrics`。
3. **选择性学习**: 只从高质量成功轨迹中学习，避免把多次试错后的“侥幸成功”固化为技能。
4. **技能生成**: 从成功模式生成 Markdown 技能，优先产出提示词模板而非可执行插件。
5. **失败报告**: 从失败模式生成 `failure_report` 文档，记录失败模式、不要这样做、可能原因、替代建议和识别信号。
6. **反模式提示**: 在任务执行前按任务类型和关键词召回相关 `failure_report`，生成简短非阻断风险提示。
7. **反模式记忆沉淀**: 失败报告会先写入情景记忆，再由 `distill_memories()` 蒸馏为稳定语义记忆。
8. **Adapter 解耦**: Evolution 复用主模型 Adapter，不再为非 OpenAI provider 额外要求 `OPENAI_API_KEY`。

当前 Evolution 已完成基础闭环；失败报告已可作为执行前轻量风险提示参与上下文，并进入记忆生命周期。

## 渐进增强

**默认**: 关键词检索，零额外依赖

**可选增强**:

**1. 语义检索** (`config.yaml`)
```yaml
memory:
  hybrid_retrieval:
    enabled: true
    provider: openai  # 或 local (需 sentence-transformers)
    model: text-embedding-3-small
```

**2. 自适应记忆** (默认启用)
```yaml
memory:
  adaptive:
    enabled: true
    adapt_interval: 100  # 每 100 次查询评估一次
    archive_days: 30     # 30 天未访问则归档
```

**3. 上下文压缩** (默认启用)
```yaml
context_compression:
  enabled: true
  trigger_threshold: 0.75  # 75% 上下文窗口时触发
  summary_model: gpt-4o-mini  # 使用便宜模型节省成本
```

**4. 模型降级** (生产环境推荐)
```yaml
model:
  fallback_models:
    - gpt-3.5-turbo  # API 失败时自动切换
```

**权衡**: 关键词快速零依赖，语义检索更精确但需 API/本地模型

## 开发状态

**v0.3.2 + Phase 2 起步** ✅ 记忆生命周期、蒸馏治理与自进化质量控制完成

- ✅ 上下文压缩系统（智能压缩长对话）
- ✅ 记忆层级迁移（访问追踪、自动归档、高频提升）
- ✅ 记忆生命周期钩子（回合开始/结束、压缩前、会话结束、记忆写入）
- ✅ 召回上下文安全包装（`<memory-context>`，避免记忆被误当作新用户输入）
- ✅ 记忆蒸馏与容量治理（`distill_memories()`、语义记忆预算、重复/近重复合并、蒸馏元数据）
- ✅ 失败报告反模式提示（按任务类型/关键词召回 `failure_report`，执行前生成非阻断 warning）
- ✅ 反模式记忆沉淀（`failure_report` 优先写入情景记忆，再通过蒸馏进入语义记忆）
- ✅ CLI 增强（/stats、/export、/reset 命令，退出/重置时沉淀会话摘要）
- ✅ MiniMax 流式响应修复（智能处理累积文本，添加单元测试）
- ✅ “记住”功能（SOUL.md/USER.md 固定记忆文件，自动注入上下文）
- ✅ **记忆系统检索修复**（中英文混合分词，索引搜索恢复正常）
- ✅ **pytest 测试框架**（单元测试、性能测试、完整测试套件）
- ✅ **自进化成功质量评估**（只从高质量成功轨迹中学习，避免侥幸成功污染技能生成）
- ✅ **记忆系统四项增强**（混合检索初始化修复、配置透传、工作记忆提升、压缩摘要入库）
- ✅ **Adapter 测试兼容性修复**（兼容新版 OpenAI SDK base_url 表示）

**v0.2.0** ✅ 稳定性增强完成

- ✅ 四级记忆系统（短期/工作/情景/语义）
- ✅ 自适应记忆调整（根据命中率动态优化）
- ✅ 记忆归档功能（低频记忆自动归档）
- ✅ 自进化能力（轨迹分析、技能生成）
- ✅ 混合检索（可选）
- ✅ 多 API 支持（OpenAI + Anthropic + MiniMax）
- ✅ 轻量日志系统
- ✅ 模型降级机制
- ✅ 配置集成（config.yaml）

**测试覆盖**:
- pytest 测试：84/84 通过 (100%)
- 覆盖模块：记忆系统、Adapter、MiniMax 流式响应、自进化质量评估、失败报告、反模式提示、记忆生命周期、记忆蒸馏、上下文压缩、CLI、性能基准
- 新增 Memory 生命周期单元测试：召回包装、回合结束同步、钩子失败隔离、上下文 fencing 清理
- 新增记忆蒸馏与容量治理测试：蒸馏幂等、低价值过滤、近重复合并、索引同步移除、配置透传
- 新增 failure_report 风险提示测试：反模式召回、正向技能隔离、执行前 warning 注入
- 新增反模式记忆沉淀测试：失败报告写入情景记忆、情景反模式蒸馏到语义记忆
- 新增 Core/CLI 集成测试：主循环接入生命周期钩子，退出和重置时触发会话结束沉淀

**已知问题**:
- 混合检索默认关闭；启用 OpenAI/local embedding 时需要对应 API key 或本地模型依赖
- 记忆蒸馏当前使用轻量启发式规则，后续可继续优化稳定事实筛选和反模式检索

**最近更新** (2026-05-08):
- ✅ **记忆生命周期钩子**
  - `on_turn_start()` 召回记忆并用 `<memory-context>` 安全包装
  - `on_turn_end()` 同步助手回复到短期记忆
  - `on_pre_compress()` 在压缩前提取即将丢失的轻量线索
  - `on_session_end()` 在 CLI 退出、重置、KeyboardInterrupt/EOF 时保存摘要并触发迁移
  - `on_memory_write()` 作为固定记忆与用户偏好写入后的统一入口
- ✅ **记忆蒸馏与容量治理**
  - `distill_memories()` 从工作/情景记忆提炼高价值语义记忆
  - 语义记忆支持条目数/字符预算，清理时同步索引并优先保留用户偏好
  - 重复/近重复蒸馏记忆自动合并，保留 `distilled_from`、`source_layer`、`confidence`、`last_verified` 等元数据
- ✅ **失败报告反模式提示**
  - `failure_report` 不再被当作正向技能匹配
  - 执行前按任务类型和关键词召回相关失败报告，生成简短非阻断 warning
  - 生成后的失败报告优先沉淀到情景记忆，后续由蒸馏机制进入语义记忆
- ✅ **Phase 2 路线重排**
  - 删除过重的记忆图谱主线，优先推进记忆蒸馏、合并和容量治理
  - 借鉴 Hermes 的记忆生命周期与上下文安全包装
  - 借鉴 nanobot 的轻量 agent/tool/skill/channel 边界，但不直接整体集成
- ✅ **测试更新**
  - 全量测试从 67 项扩展到 84 项，并保持全部通过

**改进方向**:
- 优化 `distill_memories()` 的稳定事实筛选策略，减少启发式误判
- 后续再收敛 tool/skill/channel 边界，避免过早引入重框架
- 若准备发版，增加一轮真实 API smoke test

## 对比

| 特性 | LightAgent | LightHermes |
|------|-----------|-------------|
| 核心代码 | ~1000 行 | ~3700 行 |
| 记忆系统 | mem0 外挂 | 内置四级记忆 + 生命周期钩子 + 自适应 |
| 自进化 | 自学习 | 轨迹分析 + 技能生成 |
| 稳定性 | 基础 | 日志 + 降级 + 错误处理 |
| 依赖 | 零依赖 | 2 个核心依赖（可选增强）|
| 定位 | 极简基础 | 轻量 + 生产就绪 |

## 许可证

Apache 2.0

## 参考

- 设计文档: `docs/superpowers/specs/2026-04-25-lighthermes-design.md`
- LightAgent: 极简智能体框架
- Hermes: 生产级记忆管理
