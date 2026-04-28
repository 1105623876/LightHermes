# LightHermes

**极简自进化智能体框架** — 在 LightAgent 的轻量哲学上，加入记忆与自进化能力

## 设计理念

- **极简主义**: 核心 1808 行，零重依赖（无 LangChain/LlamaIndex）
- **开箱即用**: 默认关键词检索，可选语义增强
- **渐进增强**: 从最简实现开始，按需启用高级特性

## 核心特性

- **四级记忆系统**: 短期/工作/情景/语义分层管理
- **自适应记忆**: 根据命中率动态优化记忆层级
- **自进化能力**: 从对话中学习 + 自动生成技能
- **生产稳定性**: 轻量日志 + 模型降级 + 错误处理
- **技能系统**: Markdown 技能 + Python 插件
- **多 API 支持**: OpenAI + Anthropic + MiniMax (Anthropic 兼容)
- **交互式 CLI**: 简洁命令行界面

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

> **注意**: MiniMax 的流式响应实现存在问题（返回累积文本而非增量文本），建议在 `config.yaml` 中设置 `stream_output: false` 以避免重复输出。

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
/config     # 显示当前配置
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

**3. 模型降级** (生产环境推荐)
```yaml
model:
  fallback_models:
    - gpt-3.5-turbo  # API 失败时自动切换
```

**权衡**: 关键词快速零依赖，语义检索更精确但需 API/本地模型

## 开发状态

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

**测试覆盖**: 7/7 综合测试通过

**已知问题**:
- MiniMax 的 Anthropic 兼容端点流式响应存在重复输出问题，建议禁用流式输出
- Evolution 系统在非 OpenAI provider 时需要额外的 `OPENAI_API_KEY` 环境变量

**改进方向**:
- 性能优化（缓存、索引）
- 插件系统完善
- CLI 增强（彩色输出、更多命令）
- 修复 MiniMax 流式响应兼容性

## 对比

| 特性 | LightAgent | LightHermes |
|------|-----------|-------------|
| 核心代码 | ~1000 行 | ~1808 行 |
| 记忆系统 | mem0 外挂 | 内置四级记忆 + 自适应 |
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
