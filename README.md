# LightHermes

轻量级自进化智能体框架

## 特性

- **四级记忆系统**: 短期、工作、情景、语义四层记忆管理
- **混合自进化**: 从对话中学习 + 自动生成技能
- **轻量级设计**: 核心代码 ~3600 行,最小依赖
- **技能系统**: Markdown 技能 + Python 插件
- **交互式 CLI**: 简洁的命令行界面

## 快速开始

### 安装

```bash
pip install -r requirements.txt
```

### 配置

1. 复制 `config.yaml` 并设置你的 API key:

```yaml
model:
  api_key: your_openai_api_key
```

2. 设置环境变量(可选):

```bash
export OPENAI_API_KEY=your_api_key
```

### 使用

**Python API**:

```python
from lightherrmes import LightHermes

agent = LightHermes(
    name="MyAgent",
    role="你是一个有用的编程助手",
    model="gpt-4o-mini",
    api_key="your_api_key"
)

response = agent.run("帮我解释这段代码")
print(response)
```

**命令行界面**:

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

## 配置说明

### 混合检索配置 (可选)

**默认行为**: LightHermes 使用简单的关键词匹配进行记忆检索,**无需任何额外依赖**。

**可选增强**: 如果需要更精确的语义检索,可以启用混合检索:

```yaml
memory:
  hybrid_retrieval:
    enabled: true                 # 启用混合检索
    provider: openai              # 使用 OpenAI API (推荐)
    model: text-embedding-3-small
    
    # 或使用本地模型 (需要: pip install sentence-transformers)
    # provider: local
    # model: all-MiniLM-L6-v2
```

**权衡**:
- 关键词匹配: 快速、零依赖、适合大多数场景
- 混合检索: 更精确、需要 API 调用或本地模型(~80MB)

## 开发状态

当前版本: **0.1.0** (Phase 1+2+3 完成)

**Phase 1 - 核心功能** ✅
- [x] 项目基础结构
- [x] core.py 基础框架
- [x] memory.py 四级记忆系统
- [x] 基础技能加载
- [x] cli.py 命令行界面

**Phase 2 - 自进化系统** ✅
- [x] evolution.py (轨迹分析、技能生成、验证)
- [x] 集成到 core.py

**Phase 3 - 增强功能** ✅
- [x] 混合检索 (TF-IDF + 嵌入)
- [x] 集成到记忆系统

## 许可证

Apache 2.0

## 参考

- 设计文档: `docs/superpowers/specs/2026-04-25-lightherrmes-design.md`
- 参考项目: LightAgent, Hermes
