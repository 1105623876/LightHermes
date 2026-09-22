# LightHermes 设计文档

**日期**: 2026-04-25  
**版本**: 1.0  
**状态**: 待审阅

## 项目概述

LightHermes 是一个轻量级自进化智能体框架,参考 Hermes 的设计哲学(自进化、自动编排 skill、多级记忆管理),在 LightAgent 的基础上实现一个空间与代码量极小的自进化智能体框架。

**核心目标**:
- 代码量控制在 2000-5000 行
- 保留 Hermes 的核心创新(四级记忆、自进化、技能系统)
- 继承 LightAgent 的简洁性和易用性
- 最小化依赖,易于部署

## 整体架构

### 文件结构

```
LightHermes/
├── lighthermes/
│   ├── __init__.py (~50 行)
│   ├── core.py (~1800 行)
│   ├── memory.py (~900 行)
│   ├── evolution.py (~600 行)
│   └── cli.py (~250 行)
│
├── skills/
│   ├── core/           # 内置核心技能(Markdown)
│   ├── user/           # 用户自定义技能
│   └── generated/      # Agent自动生成的技能
│
├── plugins/
│   ├── tools/          # 工具插件(Python)
│   └── memory/         # 记忆提供者插件
│
├── memory/
│   ├── working.db              # 工作记忆(SQLite)
│   ├── episodic/               # 情景记忆(Markdown)
│   ├── semantic/               # 语义记忆(Markdown)
│   └── .embeddings/            # 嵌入缓存
│
├── logs/
│   └── lighthermes.log
│
├── trajectories/
│   └── (对话轨迹 JSONL 文件)
│
├── config.yaml                 # 配置文件
├── requirements.txt            # 依赖列表
├── setup.py                    # 安装脚本
└── README.md                   # 使用文档
```

### 核心模块职责

**core.py** (1500-2000 行):
- LightHermes 主类
- 对话循环(run 方法)
- 工具调度器(ToolDispatcher)
- 技能加载器(SkillLoader)

**memory.py** (800-1000 行):
- MemoryManager (四级记忆管理器)
- ShortTermMemory (会话内上下文)
- WorkingMemory (近期会话缓存)
- EpisodicMemory (项目/任务记忆)
- SemanticMemory (抽象知识库)

**evolution.py** (500-700 行):
- TrajectoryAnalyzer (轨迹分析器)
- SkillGenerator (技能生成器)
- SkillValidator (技能验证器)

**cli.py** (200-300 行):
- 交互式命令行界面
- 命令处理(/help, /skills, /memory 等)

### 设计理念

1. **单核心原则**: core.py 是唯一的入口点,提供简洁的 API
2. **职责分离**: 记忆系统和进化系统独立成模块,通过清晰的接口与核心交互
3. **插件扩展**: 工具和记忆提供者通过插件系统扩展,不增加核心复杂度
4. **轻量优先**: 核心代码控制在 3000-3700 行,无重型依赖

## 四级记忆系统

### 记忆层级

**1. ShortTermMemory (短期记忆)**
- **存储**: 内存中的 messages 数组
- **生命周期**: 当前会话
- **容量**: 最近 50 轮对话
- **用途**: API 调用的上下文窗口

**2. WorkingMemory (工作记忆)**
- **存储**: SQLite 数据库 `memory/working.db`
- **生命周期**: 最近 7 天的会话
- **容量**: 最近 20 次会话的摘要
- **用途**: 跨会话的临时信息,如"昨天讨论的那个 bug"

**3. EpisodicMemory (情景记忆)**
- **存储**: Markdown 文件 `memory/episodic/*.md`
- **生命周期**: 项目/任务周期
- **结构**:
  ```markdown
  ---
  name: auth_rewrite_project
  type: episodic
  status: active
  created: 2026-04-25
  ---
  
  # 认证系统重构项目
  
  **目标**: 将 JWT 迁移到 OAuth2
  **截止日期**: 2026-05-15
  **关键决策**: 使用 Auth0 而非自建
  ```
- **用途**: 项目上下文、任务进度、关键决策

**4. SemanticMemory (语义记忆)**
- **存储**: Markdown 文件 `memory/semantic/*.md`
- **生命周期**: 永久(除非用户删除)
- **结构**:
  ```markdown
  ---
  name: user_preferences_testing
  type: semantic
  ---
  
  用户偏好 TDD 开发流程
  
  **Why**: 之前因缺少测试导致生产事故
  **How to apply**: 实现新功能前先写测试
  ```
- **用途**: 用户偏好、编码规范、抽象知识

### 记忆检索策略

**混合检索(TF-IDF + 嵌入)**:

```python
# 1. 快速过滤: TF-IDF 初筛(毫秒级)
candidates = tfidf_search(query, top_k=20)

# 2. 精确排序: 嵌入模型重排(秒级)
embeddings = embed_model.encode([query] + candidates)
scores = cosine_similarity(embeddings[0], embeddings[1:])
results = rerank(candidates, scores, top_k=5)
```

**嵌入模型配置**:
- **默认**: OpenAI `text-embedding-3-small` API (用户已有 API key)
- **可选**: 本地 `sentence-transformers/all-MiniLM-L6-v2` (80MB, 离线场景)

**配置位置** (`config.yaml`):
```yaml
memory:
  embedding:
    provider: openai              # openai 或 local
    model: text-embedding-3-small # OpenAI 模型
    api_key: ${OPENAI_API_KEY}
    
    # 切换到本地模型:
    # provider: local
    # local_model: all-MiniLM-L6-v2
    # cache_dir: .embeddings/
```

### 记忆写入时机

- **短期→工作**: 每次会话结束时,将摘要写入工作记忆
- **工作→情景**: 当检测到项目/任务相关对话时,提取到情景记忆
- **任意→语义**: 当用户明确表达偏好或 Agent 发现模式时,写入语义记忆

## 自进化系统

### 核心组件

**1. TrajectoryAnalyzer (轨迹分析器)**

**职责**: 分析对话轨迹,识别成功/失败模式

**触发时机**:
- 每次会话结束时自动分析
- 用户明确反馈时立即分析

**分析维度**:
```python
class TrajectoryAnalysis:
    success: bool              # 任务是否成功完成
    task_type: str            # 任务类型(debug/feature/refactor/explain)
    tool_usage: List[str]     # 使用的工具序列
    iterations: int           # 工具调用轮次
    user_corrections: int     # 用户纠正次数
    patterns: List[Pattern]   # 识别的模式
```

**模式识别**:
- **成功模式**: 连续3次相似任务成功 → 提取为技能候选
- **失败模式**: 连续2次相似任务失败 → 触发技能生成

**2. SkillGenerator (技能生成器)**

**职责**: 从轨迹中生成新技能

**生成流程**:
```
1. 提取任务模式 → 识别可复用的步骤序列
2. 生成技能草稿 → 使用 LLM 生成 Markdown 或 Python
3. 验证技能 → 沙箱测试(复杂技能)或直接启用(简单技能)
4. 保存技能 → 写入 skills/generated/
```

**技能类型判断**:
- **简单技能**(Markdown): 纯提示词模板,无工具调用
- **复杂技能**(Python 插件): 需要工具调用或复杂逻辑

**3. SkillValidator (技能验证器)**

**职责**: 验证生成的技能是否可用

**验证策略**:
- **简单技能**: 直接启用,无需验证
- **复杂技能**: 轻量级沙箱测试
  ```python
  # 使用 subprocess 隔离执行
  result = subprocess.run(
      ["python", "-c", skill_code],
      timeout=30,
      capture_output=True,
      text=True
  )
  
  # Agent 自评估结果
  is_valid = llm_evaluate(result.stdout, result.stderr)
  ```

**验证结果**:
- ✅ 通过 → 保存到 `skills/generated/`
- ❌ 失败 → 记录失败原因,不保存
- ⚠️ 不确定 → 询问用户是否启用

### 自进化循环

```
用户任务 → 执行 → 记录轨迹
              ↓
         轨迹分析
              ↓
    识别成功/失败模式
              ↓
         技能生成
              ↓
         技能验证
              ↓
    保存到技能库 → 下次任务自动使用
```

### 配置选项

```yaml
evolution:
  enabled: true                    # 是否启用自进化
  auto_generate_skills: true       # 是否自动生成技能
  skill_validation: "sandbox"      # 验证方式: none/sandbox/manual
  min_success_count: 3             # 成功模式阈值
  min_failure_count: 2             # 失败模式阈值
```

## 技能系统

### Skill vs Tool

**Tool (工具)**:
- **是什么**: 可执行的函数,完成具体操作
- **例子**: `read_file()`, `run_test()`, `search_web()`
- **特点**: 输入→输出,无状态,原子操作

**Skill (技能)**:
- **是什么**: 工作流程或思维模板,指导 Agent 如何组合使用工具
- **例子**: "调试测试失败的标准流程"、"代码审查检查清单"
- **特点**: 包含多步骤,可能调用多个工具,有上下文

### 执行流程

```
用户请求
    ↓
1. 匹配 Skill (工作流程层)
    ↓
2. Skill 指导下调用 Tool (执行层)
    ↓
3. 返回结果
```

**具体流程**:
```python
def handle_user_query(query: str):
    # 1. 先尝试匹配 Skill
    matched_skill = skill_loader.match_skill(query)
    
    if matched_skill:
        # 2. 将 Skill 内容注入到 system prompt
        system_prompt += f"\n\n## 当前任务指导\n{matched_skill.content}"
        
        # 3. Agent 在 Skill 指导下,自主决定调用哪些 Tool
        response = agent.run(query, system_prompt=system_prompt, tools=available_tools)
    else:
        # 4. 没有匹配的 Skill,直接使用 Tool
        response = agent.run(query, tools=available_tools)
    
    return response
```

### 技能文件格式

**Markdown 技能** (简单技能):
```markdown
---
name: explain_architecture
description: 解释代码架构的标准流程
type: skill
category: core
trigger: auto
platforms: [all]
---

当用户询问代码架构时,按以下结构解释:

1. **整体架构**: 用一句话概括系统设计理念
2. **核心组件**: 列出 3-5 个关键模块及其职责
3. **数据流**: 描述请求如何在组件间流转
4. **关键设计决策**: 说明为什么这样设计(权衡)

保持简洁,避免过度细节。
```

**Python 插件** (复杂技能):
```python
"""
---
name: auto_debug_test
description: 自动调试失败的测试用例
type: plugin
category: generated
trigger: manual
---
"""

def auto_debug_test(test_name: str, error_log: str) -> str:
    """自动调试测试失败"""
    pass

auto_debug_test.plugin_info = {
    "name": "auto_debug_test",
    "description": "自动调试失败的测试用例",
    "params": [
        {"name": "test_name", "type": "string", "required": True},
        {"name": "error_log", "type": "string", "required": True}
    ]
}
```

### 技能优先级

当多个技能匹配时,按以下优先级选择:
1. **用户自定义技能** (`skills/user/`) - 最高优先级
2. **自动生成技能** (`skills/generated/`) - 经过验证的成功模式
3. **核心技能** (`skills/core/`) - 内置通用技能

### 技能触发方式

- **自动触发** (`trigger: auto`): Agent 根据任务类型自动选择
- **手动触发** (`trigger: manual`): 用户明确调用(如 `/explain_architecture`)
- **条件触发**: 满足特定条件时触发(如连续失败 2 次)

## 核心 API

### LightHermes 类

```python
class LightHermes:
    def __init__(
        self,
        *,
        name: str = None,
        role: str = None,
        model: str,
        api_key: str = None,
        base_url: str = None,
        
        # 记忆配置
        memory_enabled: bool = True,
        memory_dir: str = "memory",
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-small",
        
        # 进化配置
        evolution_enabled: bool = True,
        auto_generate_skills: bool = True,
        skill_validation: str = "sandbox",
        
        # 技能配置
        skill_dirs: List[str] = None,
        plugin_dirs: List[str] = None,
        disabled_skills: List[str] = None,
        
        # 工具配置
        tools: List[Callable] = None,
        
        # 调试配置
        debug: bool = False,
        log_level: str = "INFO",
        log_file: str = None,
    ):
        """初始化 LightHermes"""
        pass
    
    def run(
        self,
        query: str,
        *,
        stream: bool = False,
        user_id: str = "default_user",
        session_id: str = None,
        history: List[Dict] = None,
        max_iterations: int = 10,
    ) -> Union[str, Generator]:
        """运行 Agent,处理用户输入"""
        pass
```

### 使用示例

**基础使用**:
```python
from lighthermes import LightHermes

agent = LightHermes(
    name="MyAgent",
    role="你是一个有用的编程助手",
    model="gpt-4o-mini",
    api_key="your_api_key"
)

response = agent.run("帮我重构这个函数")
print(response)
```

**高级配置**:
```python
agent = LightHermes(
    name="AdvancedAgent",
    model="gpt-4o-mini",
    api_key="your_api_key",
    
    # 自定义记忆配置
    memory_enabled=True,
    embedding_provider="local",  # 使用本地嵌入模型
    
    # 自定义进化配置
    evolution_enabled=True,
    auto_generate_skills=True,
    skill_validation="sandbox",
    
    # 自定义技能目录
    skill_dirs=["skills/core", "skills/custom"],
    
    # 调试模式
    debug=True,
    log_level="DEBUG"
)

for chunk in agent.run("解释这段代码", stream=True):
    print(chunk, end="", flush=True)
```

## 交互式 CLI

### 界面示例

```bash
$ python -m lighthermes

╭─────────────────────────────────────╮
│  LightHermes v0.1.0                │
│  轻量级自进化智能体框架              │
╰─────────────────────────────────────╯

[MyAgent] 你好!我是 MyAgent,有什么可以帮你的?

> 帮我解释这段代码

[MyAgent] 正在分析代码...
[使用技能: explain_code_pattern]

这段代码实现了...

> /skills

可用技能:
  ✓ explain_code_pattern - 解释代码模式
  ✓ debug_test_failure - 调试测试失败
  ✓ refactor_suggestion - 重构建议

> exit

再见!
```

### 支持的命令

```
/help       - 显示帮助信息
/skills     - 列出所有可用技能
/memory     - 显示记忆系统统计
/evolution  - 显示自进化统计
/config     - 显示当前配置
/clear      - 清屏
/exit       - 退出
```

### 启动方式

```bash
# 方式 1: 作为模块运行
python -m lighthermes

# 方式 2: 直接运行脚本
python cli.py

# 方式 3: 安装后全局命令
pip install lighthermes
lighthermes
```

## 配置文件

### config.yaml

```yaml
# 模型配置
model:
  provider: openai
  model_name: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1

# 记忆配置
memory:
  enabled: true
  storage_dir: memory
  embedding:
    provider: openai              # openai 或 local
    model: text-embedding-3-small
  retention:
    short_term_turns: 50
    working_memory_days: 7
    episodic_auto_archive: true
    semantic_max_entries: 1000

# 进化配置
evolution:
  enabled: true
  auto_generate_skills: true
  skill_validation: sandbox
  triggers:
    min_success_count: 3
    min_failure_count: 2
  sandbox:
    timeout: 30
    max_memory_mb: 512

# 技能配置
skills:
  enabled: true
  auto_load: true
  dirs:
    - skills/core
    - skills/user
    - skills/generated
  disabled: []

# 插件配置
plugins:
  dirs:
    - plugins/tools
    - plugins/memory

# CLI 配置
cli:
  prompt_symbol: ">"
  show_banner: true
  stream_output: true
  show_skill_usage: true
  color_enabled: true

# 日志配置
logging:
  level: INFO
  file: logs/lighthermes.log
  debug: false
```

## 依赖管理

### 核心依赖 (必需)

```
openai>=1.0.0           # OpenAI API 客户端
pyyaml>=6.0            # 配置文件解析
```

### 可选依赖

```
sentence-transformers>=2.0.0  # 本地嵌入模型
colorama>=0.4.0              # CLI 彩色输出
```

### 开发依赖

```
pytest>=7.0.0          # 测试框架
black>=22.0.0          # 代码格式化
```

## 实现路线图

### Phase 1: 核心功能 (MVP)

1. `core.py` - 基础对话循环和工具调度
2. `memory.py` - 四级记忆系统(先实现存储,检索用简单的关键词匹配)
3. 基础技能加载(Markdown 技能)
4. `cli.py` - 基础命令行界面

### Phase 2: 进化系统

1. `evolution.py` - 轨迹分析器
2. 技能生成器(先支持 Markdown 技能)
3. 沙箱验证器

### Phase 3: 增强功能

1. 混合检索(TF-IDF + 嵌入)
2. Python 插件支持
3. 复杂技能的沙箱验证
4. CLI 增强(彩色输出、更多命令)

## 代码量估算

```
core.py          ~1800 行  (对话循环、工具调度、技能加载)
memory.py        ~900 行   (四级记忆系统)
evolution.py     ~600 行   (轨迹分析、技能生成、验证)
cli.py           ~250 行   (交互式命令行界面)
__init__.py      ~50 行    (包初始化、版本信息)
─────────────────────────
总计             ~3600 行  (在目标范围 2000-5000 行内)
```

## 与 LightAgent 和 Hermes 的对比

| 特性 | LightAgent | Hermes | LightHermes |
|------|-----------|--------|-------------|
| 代码量 | ~1600 行 | ~50k+ 行 | ~3600 行 |
| 记忆系统 | 可插拔 mem0 | 双层(内置+外部) | 四级记忆 |
| 技能系统 | 无 | 完整 skill 系统 | 轻量级 skill+plugin |
| 自进化 | self_learning | 轨迹训练 | 混合自进化 |
| 工具系统 | 自适应过滤 | 完整工具注册表 | 继承 LightAgent |
| CLI | 无 | 完整 TUI | 简洁 CLI |
| 依赖 | openai | 20+ 依赖 | openai + yaml |

## 关键技术决策

### 1. 记忆存储格式

- **短期记忆**: Python list (内存)
- **工作记忆**: SQLite (轻量级,无需额外依赖)
- **情景/语义记忆**: Markdown 文件 (人类可读,易于编辑)

### 2. 技能匹配策略

```python
def match_skill(query: str) -> Optional[Skill]:
    # 1. 精确匹配:用户明确调用
    if query.startswith("/"):
        return get_skill_by_name(query[1:])
    
    # 2. 语义匹配:使用嵌入模型
    query_embedding = embed(query)
    skill_embeddings = load_cached_skill_embeddings()
    scores = cosine_similarity(query_embedding, skill_embeddings)
    
    # 3. 阈值过滤:相似度 > 0.7 才匹配
    if max(scores) > 0.7:
        return skills[argmax(scores)]
    
    return None
```

### 3. 轨迹存储格式

```json
{
  "session_id": "abc123",
  "timestamp": "2026-04-25T10:30:00",
  "task_type": "debug",
  "success": true,
  "messages": [...],
  "tool_calls": [
    {"tool": "read_file", "args": {...}, "result": "..."},
    {"tool": "run_test", "args": {...}, "result": "..."}
  ],
  "user_corrections": 0,
  "iterations": 3
}
```

## 设计原则

1. **YAGNI (You Aren't Gonna Need It)**: 只实现当前需要的功能,不为未来可能的需求过度设计
2. **简洁优于复杂**: 在功能完整性和代码简洁性之间,优先选择简洁
3. **可读性优先**: Markdown 技能、清晰的配置文件、人类可读的记忆存储
4. **渐进式增强**: 核心功能先行,高级功能可选,允许用户按需启用
5. **最小依赖**: 核心功能只依赖 openai 和 pyyaml,其他功能通过可选依赖实现

## 成功标准

1. **代码量**: 核心代码 < 5000 行
2. **依赖**: 核心依赖 ≤ 2 个
3. **启动速度**: 首次启动 < 3 秒
4. **记忆检索**: 平均响应时间 < 500ms
5. **技能生成**: 成功率 > 70%
6. **易用性**: 新用户 10 分钟内完成首次对话

## 风险与缓解

### 风险 1: 嵌入模型性能不足

**风险**: TF-IDF + 嵌入的混合检索可能在大量记忆时性能下降

**缓解**:
- Phase 1 使用简单的关键词匹配
- Phase 3 引入混合检索,并进行性能测试
- 提供配置选项允许用户禁用嵌入检索

### 风险 2: 技能生成质量不稳定

**风险**: LLM 生成的技能可能不可用或质量低

**缓解**:
- 实现沙箱验证机制
- 提供人工审核选项
- 记录失败案例,持续优化生成提示词

### 风险 3: 代码量超出目标

**风险**: 实现过程中代码量可能超过 5000 行

**缓解**:
- 严格遵循 YAGNI 原则
- 定期代码审查,删除冗余代码
- 将非核心功能移至插件系统

## 下一步

1. 用户审阅设计文档
2. 创建实现计划(调用 writing-plans skill)
3. Phase 1 实现(核心功能 MVP)
4. 测试与迭代
5. Phase 2/3 增量开发
