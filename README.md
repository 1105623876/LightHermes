# LightHermes

**极简自进化智能体框架** — 在 LightAgent 的轻量哲学上，加入记忆与自进化能力

## 设计理念

- **极简主义**: 核心 1500 行，零重依赖（无 LangChain/LlamaIndex）
- **开箱即用**: 默认关键词检索，可选语义增强
- **渐进增强**: 从最简实现开始，按需启用高级特性

## 核心特性

- **四级记忆系统**: 短期/工作/情景/语义分层管理
- **自进化能力**: 从对话中学习 + 自动生成技能
- **技能系统**: Markdown 技能 + Python 插件
- **多 API 支持**: OpenAI + Anthropic
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

### 使用

**Python API**:

```python
from lightherrmes import LightHermes

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
python -m lightherrmes.cli
```

## 项目结构

```
LightHermes/
├── lightherrmes/       # 核心代码
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

**可选**: 启用语义检索（`config.yaml`）

```yaml
memory:
  hybrid_retrieval:
    enabled: true
    provider: openai  # 或 local (需 sentence-transformers)
    model: text-embedding-3-small
```

**权衡**: 关键词快速零依赖，语义检索更精确但需 API/本地模型

## 开发状态

**v0.1.0** ✅ 核心完成

- 四级记忆系统
- 自进化能力（轨迹分析、技能生成）
- 混合检索（可选）
- 多 API 支持（OpenAI + Anthropic）

**改进方向**:
- 测试覆盖
- 性能优化（缓存、索引）
- 插件系统完善

## 对比

| 特性 | LightAgent | LightHermes |
|------|-----------|-------------|
| 核心代码 | ~1000 行 | ~1500 行 |
| 记忆系统 | mem0 外挂 | 内置四级记忆 |
| 自进化 | 自学习 | 轨迹分析 + 技能生成 |
| 依赖 | 零依赖 | 零依赖（可选增强）|
| 定位 | 极简基础 | 轻量 + 记忆增强 |

## 许可证

Apache 2.0

## 参考

- 设计文档: `docs/superpowers/specs/2026-04-25-lightherrmes-design.md`
- LightAgent: 极简智能体框架
- Hermes: 生产级记忆管理
