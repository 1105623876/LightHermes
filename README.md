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

### 嵌入模型配置

在 `config.yaml` 中配置记忆检索的嵌入模型:

```yaml
memory:
  embedding:
    provider: openai              # 使用 OpenAI API
    model: text-embedding-3-small
    
    # 或切换到本地模型:
    # provider: local
    # local_model: all-MiniLM-L6-v2
```

## 开发状态

当前版本: **0.1.0** (Phase 1 开发中)

- [x] 项目基础结构
- [ ] core.py 基础框架
- [ ] memory.py 四级记忆系统
- [ ] 基础技能加载
- [ ] cli.py 命令行界面
- [ ] Phase 2: 进化系统
- [ ] Phase 3: 增强功能

## 许可证

Apache 2.0

## 参考

- 设计文档: `docs/superpowers/specs/2026-04-25-lightherrmes-design.md`
- 参考项目: LightAgent, Hermes
