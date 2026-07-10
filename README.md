# LightHermes

轻量级记忆增强智能体框架。在不引入 LangChain、LlamaIndex 或 LangGraph 的前提下，提供分级记忆、工具调用、上下文压缩和轻量自进化能力。

当前发布版本为 `v0.3.4`；`master` 开发基线包含 Memory Eval v2.1、批量 embedding、跨层统一重排和流式生命周期收口。

## 核心能力

| 能力 | 说明 |
|------|------|
| 四级记忆 | 短期、工作、情景、语义记忆分层存储和迁移 |
| 混合检索 | 关键词初筛、embedding 重排、跨层候选融合和噪声过滤 |
| 生命周期 | 回合开始/结束、压缩前、会话结束和记忆写入钩子 |
| 上下文压缩 | 接近窗口上限时保留设定、关键决策和最近消息 |
| 工具系统 | 默认提供 `search_memory`，文件工具按配置显式开启 |
| 自进化 | 记录轨迹，从高质量成功经验生成 Markdown 技能，并沉淀失败报告 |
| 多模型端点 | OpenAI、OpenAI 兼容端点、Anthropic 和 MiniMax Anthropic 兼容端点 |
| CLI | 交互对话、记忆统计、压缩、导出和会话重置 |

LightHermes 当前更适合单用户、本地运行或嵌入 Python 应用。多用户记忆隔离、网络 Channel 和插件生态仍属于后续阶段。

## 快速开始

### 安装

建议使用项目虚拟环境：

```powershell
python -m venv venv
.\venv\Scripts\python.exe -m pip install -r requirements.txt
```

核心依赖为 `openai`、`anthropic` 和 `pyyaml`。本地 embedding 的 `sentence-transformers` 属于可选依赖。

### 配置密钥

密钥可以只放在项目级 `.env.local`，不需要设置全局环境变量：

```env
OPENAI_API_KEY=your_main_model_key
SILICONFLOW_API_KEY=your_embedding_key
```

在 `config.yaml` 中引用变量：

```yaml
secrets:
  env_file: .env.local

model:
  provider: openai
  model_name: gpt-5.4-mini
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
```

支持 `${ENV_VAR}` 和 `$(ENV_VAR)` 两种形式。`.env`、`.env.local` 和 `*.env` 默认不会被 Git 跟踪。

### 运行

```python
from lighthermes import LightHermes

agent = LightHermes.from_config("config.yaml")
response = agent.run("帮我分析这段代码")
print(response)
```

流式调用：

```python
for chunk in agent.run("解释当前项目架构", stream=True):
    print(chunk, end="", flush=True)
```

流式和非流式路径共享同一套回合收尾逻辑。只有流被完整消费并正常结束时，最终回复才会写入完成态记忆和轨迹。

### CLI

```powershell
.\venv\Scripts\python.exe -m lighthermes.cli
```

| 命令 | 作用 |
|------|------|
| `/skills` | 列出技能 |
| `/memory` | 查看记忆概况 |
| `/stats` | 查看 API、token 和记忆统计 |
| `/config` | 查看当前配置 |
| `/compress` | 手动压缩上下文 |
| `/export` | 导出对话历史 |
| `/reset` | 重置会话并保留长期记忆 |
| `/exit` | 结束会话并触发会话收尾 |

## 模型端点

### OpenAI 兼容端点

```yaml
model:
  provider: openai
  model_name: gpt-5.4-mini
  api_key: ${SUB2API_KEY}
  base_url: https://your-gateway.example.com/v1
```

`base_url` 通常填写到 `/v1`，不要填写完整的 `/chat/completions` 路径。

### Anthropic / MiniMax

```python
from lighthermes import LightHermes

agent = LightHermes(
    name="MyAgent",
    role="编程助手",
    model="claude-sonnet-4-6",
    provider="anthropic",
    api_key="your_key",
    base_url="https://api.minimaxi.com/anthropic",
)
```

MiniMax 累积式流文本会在 Adapter 层转换为增量文本。

### 独立 embedding 端点

主模型与 embedding 可以使用不同供应商：

```yaml
embedding:
  provider: openai
  model_name: BAAI/bge-m3
  api_key: ${SILICONFLOW_API_KEY}
  base_url: https://api.siliconflow.cn/v1

memory:
  hybrid_retrieval:
    enabled: true
    min_candidates: 5
    fallback_to_all: true
    semantic_threshold: 0.50
    score_margin: 0.08
    full_rerank_max_docs: 200
    tfidf_candidate_limit: 20
```

示例中的 `0.50` / `0.08` 是 BGE-M3 合成评测后的建议起点。不同 embedding 模型的分数分布不同，切换模型后应重新评估。

## 架构

```text
CLI / Python API
        |
   LightHermes core
        |
        +-- adapters/       模型供应商适配
        +-- tools.py        工具注册与调用
        +-- builtin_tools.py 记忆与受控文件工具
        +-- skills.py       Markdown 技能和失败报告召回
        +-- memory.py       四级记忆、迁移、蒸馏和跨层召回
        +-- retrieval.py    TF-IDF、批量 embedding 和混合重排
        +-- compressor.py   上下文压缩
        +-- evolution.py    轨迹分析和技能生成
        +-- evaluation.py   Memory Eval v2.1
```

核心边界：

- `LightHermes` 负责对话循环、记忆注入、工具迭代和统一回合收尾。
- `BaseAdapter` 隔离 OpenAI、Anthropic 和兼容端点差异。
- `MemoryManager` 统一管理保存、结构化召回、迁移、蒸馏和统计。
- `ToolDispatcher` 负责 schema、注册、同名覆盖和调用。
- `SkillLoader` 负责 Markdown 技能匹配以及 `failure_report` 风险提示。
- `ContextCompressor` 处理长上下文；`EvolutionEngine` 记录轨迹并生成可读技能。

## 记忆系统

| 层级 | 存储 | 典型内容 |
|------|------|----------|
| 短期记忆 | 进程内消息 | 当前对话窗口 |
| 工作记忆 | SQLite | 会话摘要、阶段任务 |
| 情景记忆 | Markdown | 调试经验、项目决策、任务事件 |
| 语义记忆 | Markdown + 索引 | 稳定事实、用户偏好、长期知识 |

关键行为：

- 召回内容通过 `<memory-context>` 包装，明确标记为背景信息而非新指令。
- `SOUL.md` 和 `USER.md` 用于稳定设定与固定用户偏好。
- hybrid 模式扩大各层候选池，再使用同一个 embedding 统一重排。
- 普通自动上下文默认排除 `historical`、`rejected` 和 `failure_report`；明确询问历史或失败经验时仍可召回。
- hybrid 工作记忆只保留最相关项，减少最近但无关的摘要占位。
- embedding 支持批量请求；缓存使用原子替换，缓存写失败不会让本次检索降级。
- 语义记忆支持容量预算、重复合并、访问统计、归档和蒸馏。

### 关键词还是 hybrid

关键词检索零额外成本，适合小规模记忆和直接词面查询。记忆数量增长，或出现跨语言、近义表达、冲突事实和硬负例时，应启用 hybrid。

同一组扩展合成评测结果：

| 指标 | 关键词 | BGE-M3 hybrid |
|------|------:|--------------:|
| 记忆条目 | 64 | 64 |
| 查询数 | 27 | 27 |
| 通过率 | 3.7% | **100%** |
| Recall@K | 55.6% | **100%** |
| MRR | 44.3% | **98.1%** |
| Precision@K | 11.0% | **96.3%** |
| 噪声率 | 89.0% | **3.7%** |
| 平均延迟 | 105ms | 314ms |

评测覆盖偏好、项目决策、故障经验、跨语言、冲突事实、硬负例、跨层召回和多领域干扰。数据全部为合成内容；这些结果证明当前配置在该基准上的表现，不等同于真实生产数据的最终结论。

### Memory Eval v2.1

```python
from lighthermes import (
    MemoryQualityEvaluator,
    build_memory_eval_v2_extended_suite,
)
from lighthermes.memory import MemoryManager

suite = build_memory_eval_v2_extended_suite()
memory = MemoryManager(memory_dir="eval-memory", use_hybrid_retrieval=False)
evaluator = MemoryQualityEvaluator(memory)

evaluator.seed(suite.seeds)
report = evaluator.run(suite.cases)

print(report.to_dict())
print(report.evaluate_quality_gates(suite.quality_gates))
```

Eval v2.1 提供来源级 Recall@K、MRR、Precision@K、噪声率、延迟、分类汇总和显式质量门槛。若需测试真实 embedding，请按上面的 `embedding` 配置构造启用 hybrid 的 `MemoryManager`。

## 工具与安全边界

默认只开启 `search_memory`。文件读、搜索和写入必须显式配置：

```yaml
tools:
  builtin:
    enabled: true
    memory_search: true
    file_read: false
    file_search: false
    file_write: false
    roots:
      - .
    max_read_chars: 20000
    max_write_chars: 20000
    max_search_results: 20
```

文件工具遵守以下边界：

- 只能访问 `roots` 内路径。
- 默认排除 `.git`、`.claude`、`venv`、`node_modules` 和 `memory` 等目录。
- 拒绝 `.env`、密钥、证书及 credentials/secrets 文件。
- 拒绝二进制文件并限制读写大小。
- `write_file` 必须单独开启，不会自动创建父目录。

## 自进化

自进化保持轻量，不实现复杂强化学习：

1. 保存消息、工具调用、任务类型和迭代次数。
2. 计算 `quality_score`、`quality_level` 和 `learning_worthy`。
3. 只从高质量完成轨迹生成 Markdown 技能。
4. 失败轨迹生成 `failure_report`，作为非阻断风险提示。
5. 失败报告先进入情景记忆，稳定后可蒸馏为语义记忆。

当前 `success=True` 表示流程正常完成，不等同于经过外部事实验证的任务成功。更严格的成功信号仍是后续改进项。

## 开发状态

- 发布版本：`v0.3.4`
- 当前开发基线：`144/144` 测试通过
- 测试层次：单元、集成、性能和离线记忆质量评估
- 真实 smoke：OpenAI 兼容主模型、MiniMax 流式路径、SiliconFlow BGE-M3 合成记忆评测

运行测试：

```powershell
.\venv\Scripts\python.exe -m pytest tests
```

当前限制：

- 关键词检索在规模化记忆中质量明显下降，高质量长期记忆建议启用 hybrid。
- Memory Eval v2.1 目前使用合成数据，仍需补充蒸馏污染和真实长期使用回放。
- 语义/情景记忆当前是本地文件存储，尚未提供多用户命名空间和外部数据库后端。
- 插件加载、网络 Channel、多模态和 Web UI 尚未进入稳定主线。

近期方向：

1. 多用户记忆隔离与隐私边界。
2. 蒸馏污染、反模式误召回和长期回放评测。
3. 更可靠的任务成功信号和用户反馈闭环。
4. 评审并移植轻量本地工具插件能力。

详细进度和历史版本请看 [ROADMAP](docs/ROADMAP.md)、[PROJECT_STATUS](docs/PROJECT_STATUS.md) 和 [CHANGELOG](CHANGELOG.md)。

## 许可证

Apache 2.0

## 参考

- [设计文档](docs/superpowers/specs/2026-04-25-lighthermes-design.md)
- LightAgent：轻量工具与 Agent 主循环参考
- Hermes：记忆生命周期与自进化参考
- nanobot：工具、技能、Hook 和 Channel 边界参考
