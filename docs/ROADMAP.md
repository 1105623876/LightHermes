# LightHermes 发展路线图

**版本**: v0.3.1 完成 + Phase 2 起步  
**更新时间**: 2026-05-03  
**设计理念**: 保持轻量，增强可用性，实验科研想法

---

## 设计原则

1. **轻量优先**: 核心代码保持在 3000 行以内
2. **渐进增强**: 高级功能可选，不增加基础依赖
3. **实用为主**: 优先解决真实使用场景的问题
4. **科研探索**: 在稳定基础上实验创新想法

---

## Phase 1: 可用性增强（v0.3.1）

**目标**: 提升日常使用体验，修复已知问题

### 1.1 MiniMax 流式响应修复 ✅
**优先级**: 高  
**工作量**: 2-3 小时

- [x] 深度调试 MiniMax 流式响应格式
- [x] 实现更智能的增量文本提取算法
- [x] 添加流式响应单元测试

**完成情况**: 
- 验证了现有的累积文本处理逻辑正确性
- 添加了 5 个单元测试覆盖标准/累积/混合/空增量/Unicode 场景
- 所有测试通过，MiniMax 流式响应已正常工作

**科研价值**: 探索不同 API 提供商的流式实现差异

### 1.2 "记住"功能 ✅
**优先级**: 高  
**工作量**: 4-5 小时

- [x] 实现记忆提取功能（检测"记住"关键词）
- [x] 使用 LLM 提取关键信息
- [x] 创建 SOUL.md 和 USER.md 固定记忆文件
- [x] 直接注入到 system prompt，无需查询匹配

**完成情况**:
- 用户说"记住"时，LLM 自动提取信息并分类保存
- SOUL.md 存储智能体设定（名字、人格等）
- USER.md 存储用户偏好和信息
- 每次对话自动注入，无需复杂检索逻辑

**今日提交**: 10 个提交
- 代码精简优化（减少 131 行）
- MiniMax 流式响应测试
- token 统计 bug 修复
- "记住"功能完整实现
- SOUL.md/USER.md 固定记忆文件

### 1.3 CLI 体验优化 ✅
**优先级**: 中  
**工作量**: 已完成

- [x] `/stats` - 显示详细统计
- [x] `/export` - 导出对话历史
- [x] `/reset` - 重置会话但保留记忆
- [x] 改进错误提示和帮助信息

### 1.4 测试覆盖 ✅
**优先级**: 中  
**工作量**: 4-5 小时

- [x] 添加流式响应单元测试（5 个测试）
- [x] 添加 pytest 框架
- [x] Adapter 单元测试（OpenAI, Anthropic, MiniMax）
- [x] 记忆系统单元测试
- [x] 性能基准测试（记忆检索、API 调用）
- [x] CLI 集成测试（可选）

**完成情况** (2026-05-03):
- 添加 pytest 配置和共享 fixtures
- 完成记忆系统单元测试（分词、索引、统计、管理器）
- 完成 Adapter 单元测试（工厂、OpenAI、Anthropic、MiniMax 流式响应）
- 完成自进化质量评估单元测试
- 完成上下文压缩单元测试和 CLI 集成测试
- 完成性能基准测试（索引性能、搜索性能、召回性能、可扩展性）
- 当前测试基线：63/63 通过
- 添加测试文档（tests/README.md）

---

## Phase 2: 科研实验（v0.4.0）

**目标**: 探索创新想法，保持轻量设计

**已完成起步项** (2026-05-03):
- [x] 自进化成功质量评估：新增 `quality_score`、`quality_level`、`learning_worthy`、`quality_metrics`、`quality_version`
- [x] 成功模式分析只从高质量成功轨迹中学习，避免侥幸成功污染技能生成
- [x] 记忆系统四项增强：混合检索初始化修复、配置透传、工作记忆提升、压缩摘要入库

### 2.1 记忆系统增强 🧠
**优先级**: 高  
**工作量**: 5-6 小时

**实验 1: 记忆压缩与蒸馏**
- 使用 LLM 自动总结和压缩长期记忆
- 保留关键信息，减少存储空间
- 实验不同的压缩策略（时间衰减、重要性评分）

**实验 2: 记忆图谱**
- 将记忆组织为知识图谱（实体-关系）
- 支持更复杂的记忆查询（"找出所有与 X 相关的讨论"）
- 轻量实现：使用 JSON 存储，避免引入图数据库

**实验 3: 自适应检索策略**
- 根据查询类型动态选择检索策略
- 实验混合检索的权重自适应调整
- 记录检索效果，持续优化

**科研价值**: 探索轻量级记忆管理的边界

### 2.2 自进化系统增强 🔄
**优先级**: 高  
**工作量**: 8-10 小时

#### 实验 1: 反模式学习系统 (Anti-Pattern Learning)
**目标**: 从失败中学习"不要做什么"

**核心概念**:
- 传统学习只关注成功案例，但失败案例同样重要
- 反模式 = 看似合理但实际导致失败的做法
- 主动警告 > 被动记录

**实现方案**:
```
新增模块: lighthermes/anti_pattern.py (~200 行)

1. 失败案例分析器 (FailureAnalyzer)
   - 记录失败原因分类：
     * 工具使用错误（参数错误、顺序错误）
     * 逻辑错误（条件判断、循环逻辑）
     * 资源问题（超时、内存溢出）
     * 依赖问题（版本冲突、缺失依赖）
   - 提取失败模式特征：
     * 触发条件（什么情况下会失败）
     * 错误症状（如何识别这个问题）
     * 影响范围（失败的后果）

2. 反模式技能生成器 (AntiPatternGenerator)
   - 生成"不要做什么"的技能
   - 格式：
     ---
     name: antipattern_xxx
     type: anti-pattern
     severity: high/medium/low
     ---
     
     ## 反模式：[名称]
     
     ### 不要这样做
     [错误的做法]
     
     ### 为什么会失败
     [失败原因]
     
     ### 正确的做法
     [替代方案]
     
     ### 识别信号
     [如何识别这个问题即将发生]

3. 主动警告系统 (WarningSystem)
   - 在执行前检查是否匹配已知反模式
   - 警告级别：
     * 🔴 高危：立即阻止并警告
     * 🟡 中危：警告但允许继续
     * 🟢 低危：记录日志
   - 集成到 core.py 的工具调用前
```

**数据结构**:
```python
{
  "anti_pattern_id": "ap_001",
  "name": "recursive_api_call_without_limit",
  "severity": "high",
  "trigger_conditions": {
    "tool": "api_call",
    "pattern": "recursive without max_depth"
  },
  "failure_cases": [
    {
      "session_id": "xxx",
      "error": "RecursionError: maximum recursion depth exceeded",
      "context": "..."
    }
  ],
  "warning_message": "检测到无限制递归调用，可能导致栈溢出",
  "correct_approach": "添加 max_depth 参数限制递归深度"
}
```

**科研价值**: 探索"负向学习"在 AI 系统中的应用

---

#### 实验 2: 成功质量评估系统 (Success Quality Assessment) ✅
**目标**: 区分"侥幸成功"和"高效成功"，只从高质量成功中学习

**核心概念**:
- 不是所有成功都值得学习
- 侥幸成功 = 多次重试、用户多次纠正、执行时间过长
- 高效成功 = 一次成功、无需纠正、执行时间合理

**质量评估指标**:
```python
SuccessQuality = {
  "efficiency_score": 0-100,  # 综合评分
  "metrics": {
    "retry_count": 0,           # 重试次数（越少越好）
    "user_corrections": 0,      # 用户纠正次数（越少越好）
    "execution_time": 1.5,      # 执行时间（秒）
    "tool_call_count": 3,       # 工具调用次数
    "token_usage": 1500,        # Token 使用量
    "first_attempt_success": True  # 是否一次成功
  },
  "quality_level": "high",  # high/medium/low
  "learning_worthy": True   # 是否值得学习
}
```

**评分算法**:
```python
def calculate_quality_score(metrics):
    score = 100
    
    # 重试惩罚：每次重试 -20 分
    score -= metrics["retry_count"] * 20
    
    # 用户纠正惩罚：每次纠正 -15 分
    score -= metrics["user_corrections"] * 15
    
    # 执行时间惩罚：超过基准时间每秒 -5 分
    baseline_time = estimate_baseline_time(task_type)
    if metrics["execution_time"] > baseline_time:
        score -= (metrics["execution_time"] - baseline_time) * 5
    
    # 一次成功奖励：+20 分
    if metrics["first_attempt_success"]:
        score += 20
    
    return max(0, min(100, score))
```

**学习策略**:
- 高质量成功（score >= 80）：立即学习，生成技能
- 中等质量成功（50 <= score < 80）：记录但不立即学习
- 低质量成功（score < 50）：标记为"侥幸成功"，不学习

**已实现**:
```
扩展 evolution.py 中的 TrajectoryAnalyzer:

1. 添加质量评估方法
   - calculate_quality_score()
   - classify_success_quality()
   - should_learn_from_success()

2. 修改 save_trajectory()
   - 记录详细的执行指标
   - 计算质量评分
   - 标记学习价值

3. 修改 analyze_patterns()
   - 只分析高质量成功案例
   - 过滤低质量成功
   - 生成质量报告
```

**科研价值**: 探索"选择性学习"提升 AI 系统学习效率

---

#### 实验 3: 元学习机制 (Meta-Learning)
**目标**: 从学习过程本身中学习，识别知识缺口

**核心概念**:
- 元学习 = 学习如何学习
- 识别"我不知道什么"比"我知道什么"更重要
- 知识缺口 = 反复失败的领域

**知识缺口识别**:
```python
KnowledgeGap = {
  "gap_id": "kg_001",
  "domain": "database_optimization",  # 缺口领域
  "failure_count": 5,                 # 失败次数
  "failure_rate": 0.83,               # 失败率（5/6）
  "recent_failures": [                # 最近失败案例
    {"session_id": "xxx", "error": "..."},
    {"session_id": "yyy", "error": "..."}
  ],
  "missing_knowledge": [              # 缺失的知识点
    "索引优化策略",
    "查询计划分析",
    "慢查询诊断"
  ],
  "learning_priority": "high",        # 学习优先级
  "suggested_resources": [            # 建议学习资源
    "PostgreSQL 性能优化文档",
    "数据库索引设计最佳实践"
  ]
}
```

**元学习循环**:
```
1. 执行任务 → 记录结果
2. 分析失败模式 → 识别知识缺口
3. 生成学习目标 → 优先级排序
4. 主动学习 → 填补知识缺口
5. 验证学习效果 → 重新评估
```

**实现方案**:
```
新增模块: lighthermes/meta_learning.py (~250 行)

1. 知识缺口分析器 (KnowledgeGapAnalyzer)
   - 统计失败模式频率
   - 识别反复失败的领域
   - 计算知识缺口优先级

2. 学习目标生成器 (LearningGoalGenerator)
   - 根据知识缺口生成学习目标
   - 推荐学习资源
   - 制定学习计划

3. 学习进度追踪器 (LearningProgressTracker)
   - 追踪每个知识缺口的学习进度
   - 验证学习效果（失败率是否下降）
   - 生成学习报告

4. CLI 命令
   - /gaps - 显示当前知识缺口
   - /learn <domain> - 针对特定领域学习
   - /progress - 显示学习进度
```

**学习效果验证**:
```python
def validate_learning_effect(gap_id):
    gap = load_knowledge_gap(gap_id)
    
    # 学习前失败率
    before_rate = gap["failure_rate"]
    
    # 学习后执行相同类型任务
    recent_tasks = get_recent_tasks(gap["domain"], limit=10)
    after_rate = calculate_failure_rate(recent_tasks)
    
    # 计算改进幅度
    improvement = (before_rate - after_rate) / before_rate
    
    if improvement > 0.5:
        return "学习有效，知识缺口已填补"
    elif improvement > 0.2:
        return "学习有一定效果，需要继续学习"
    else:
        return "学习效果不明显，需要调整学习策略"
```

**科研价值**: 探索 AI 系统的"自我认知"和"主动学习"能力

---

#### 实验 4: 反事实推理系统 (Counterfactual Reasoning)
**目标**: "如果当时做了 X，结果会怎样？"

**核心概念**:
- 反事实推理 = 事后分析备选方案
- 决策点 = 有多个选择的关键时刻
- 学习最优决策策略

**决策点记录**:
```python
DecisionPoint = {
  "decision_id": "dp_001",
  "timestamp": "2026-04-29T20:00:00",
  "context": "需要查询数据库中的用户信息",
  "options": [
    {
      "option_id": "opt_1",
      "description": "使用 ORM 查询",
      "estimated_cost": {"time": 2, "complexity": "low"},
      "chosen": True
    },
    {
      "option_id": "opt_2",
      "description": "使用原生 SQL",
      "estimated_cost": {"time": 1, "complexity": "medium"},
      "chosen": False
    },
    {
      "option_id": "opt_3",
      "description": "使用缓存",
      "estimated_cost": {"time": 0.5, "complexity": "high"},
      "chosen": False
    }
  ],
  "actual_outcome": {
    "success": True,
    "actual_time": 2.5,
    "quality_score": 75
  }
}
```

**反事实分析**:
```python
def counterfactual_analysis(decision_id):
    decision = load_decision(decision_id)
    chosen = get_chosen_option(decision)
    alternatives = get_unchosen_options(decision)
    
    analysis = {
        "chosen_option": chosen["description"],
        "actual_outcome": decision["actual_outcome"],
        "counterfactuals": []
    }
    
    for alt in alternatives:
        # 基于历史数据估算备选方案的结果
        estimated_outcome = estimate_outcome(alt, decision["context"])
        
        # 比较实际结果和估算结果
        comparison = compare_outcomes(
            decision["actual_outcome"],
            estimated_outcome
        )
        
        analysis["counterfactuals"].append({
            "option": alt["description"],
            "estimated_outcome": estimated_outcome,
            "comparison": comparison,
            "lesson": generate_lesson(comparison)
        })
    
    return analysis
```

**学习策略优化**:
```python
# 如果反事实分析显示备选方案更好
if counterfactual_better_than_actual:
    # 更新决策策略
    update_decision_strategy(
        context=decision["context"],
        preferred_option=better_alternative,
        reason="反事实分析显示此方案更优"
    )
    
    # 生成学习记录
    save_lesson({
        "context": decision["context"],
        "wrong_choice": chosen_option,
        "better_choice": better_alternative,
        "reason": comparison["reason"]
    })
```

**实现方案**:
```
扩展 evolution.py:

1. 决策点记录器 (DecisionPointRecorder)
   - 在关键决策点记录所有选项
   - 记录选择理由
   - 记录实际结果

2. 反事实分析器 (CounterfactualAnalyzer)
   - 事后分析备选方案
   - 估算"如果选择 X"的结果
   - 生成对比报告

3. 决策策略优化器 (DecisionStrategyOptimizer)
   - 根据反事实分析更新决策策略
   - 学习最优决策模式
   - 避免重复错误决策

4. CLI 命令
   - /decisions - 显示最近的决策点
   - /whatif <decision_id> <option_id> - 分析"如果选择 X"
   - /lessons - 显示从反事实分析中学到的经验
```

**科研价值**: 探索 AI 系统的"反思能力"和"决策优化"

---

#### 集成方案

**统一架构**:
```
lighthermes/
├── evolution.py          # 现有自进化系统（扩展）
├── anti_pattern.py       # 反模式学习系统（新增）
├── meta_learning.py      # 元学习机制（新增）
└── advanced_learning.py  # 统一管理高级学习功能（新增）

advanced_learning.py 职责：
- 协调四个学习系统
- 提供统一的 API
- 管理学习优先级
- 生成综合学习报告
```

**配置项**:
```yaml
# config.yaml
advanced_learning:
  enabled: true
  
  # 反模式学习
  anti_pattern:
    enabled: true
    warning_level: medium  # high/medium/low
    auto_block_high_risk: true
  
  # 成功质量评估
  quality_assessment:
    enabled: true
    min_quality_score: 80  # 只从高质量成功中学习
    track_metrics: true
  
  # 元学习
  meta_learning:
    enabled: true
    gap_detection_threshold: 3  # 失败 3 次后识别为知识缺口
    auto_generate_goals: true
  
  # 反事实推理
  counterfactual:
    enabled: true
    record_decision_points: true
    auto_analyze: true  # 自动分析决策点
```

**CLI 命令**:
```bash
# 反模式相关
/antipatterns              # 显示已识别的反模式
/antipattern <id>          # 查看特定反模式详情
/warnings                  # 显示最近的警告

# 质量评估相关
/quality                   # 显示成功质量统计
/quality <session_id>      # 查看特定会话的质量评分

# 元学习相关
/gaps                      # 显示知识缺口
/learn <domain>            # 针对特定领域学习
/progress                  # 显示学习进度

# 反事实推理相关
/decisions                 # 显示决策点
/whatif <decision_id> <option_id>  # 反事实分析
/lessons                   # 显示学到的经验

# 综合报告
/learning-report           # 生成综合学习报告
```

**实施优先级**:
1. **Phase 1** (3-4 小时): 反模式学习 + 成功质量评估
   - 这两个功能相对独立，可以先实现
   - 立即产生价值（避免重复错误、提升学习质量）

2. **Phase 2** (2-3 小时): 元学习机制
   - 依赖 Phase 1 的数据积累
   - 需要一定量的失败案例才能识别知识缺口

3. **Phase 3** (3-4 小时): 反事实推理
   - 最复杂，需要决策点记录和结果估算
   - 可以作为长期优化项

**总工作量**: 8-10 小时

**科研价值**: 探索智能体的自我改进机制

### 2.3 多模态支持 🖼️
**优先级**: 低  
**工作量**: 3-4 小时

- [ ] 支持图片输入（Claude 4.x 原生支持）
- [ ] 支持代码截图理解
- [ ] 支持架构图生成（使用 mermaid）
- [ ] 轻量实现：不引入额外依赖

**科研价值**: 探索多模态在代码助手中的应用

---

## Phase 3: 生态扩展（v0.5.0）

**目标**: 构建轻量级工具生态

### 3.1 插件系统完善
**优先级**: 中  
**工作量**: 5-6 小时

- [ ] Python 插件加载机制
- [ ] 插件热重载
- [ ] 插件依赖管理（轻量级）
- [ ] 插件市场（GitHub-based）

### 3.2 工具集成
**优先级**: 低  
**工作量**: 按需

- [ ] VS Code 插件（基础版）
- [ ] Web UI（可选，使用 Streamlit）
- [ ] Docker 镜像
- [ ] GitHub Actions 集成

---

## Phase 4: 性能优化（持续）

**目标**: 保持轻量的同时提升性能

### 4.1 记忆系统优化
- [ ] 记忆检索缓存（LRU）
- [ ] 索引优化（使用 SQLite FTS5）
- [ ] 批量操作优化
- [ ] 异步 I/O（可选）

### 4.2 API 调用优化
- [ ] 请求缓存（相同查询）
- [ ] 批量请求支持
- [ ] 连接池管理
- [ ] 重试策略优化

---

## 科研实验想法池 💡

以下是一些有趣的科研想法，可以在未来探索：

### 1. 元学习与迁移学习
- 从一个项目学到的技能迁移到另一个项目
- 跨项目的知识共享机制
- 个性化的智能体"人格"

### 2. 协作智能体
- 多个 LightHermes 实例协作完成任务
- 任务分解与分配策略
- 协作通信协议（轻量级）

### 3. 主动学习
- 智能体主动提问以获取更多信息
- 不确定性估计与查询策略
- 人机协作的最优策略

### 4. 可解释性
- 解释智能体的决策过程
- 可视化记忆检索和技能选择
- 生成决策报告

### 5. 安全与隐私
- 本地模型支持（Ollama 集成）
- 敏感信息检测与过滤
- 记忆加密存储

### 6. 代码理解增强
- AST 分析与代码图谱
- 依赖关系可视化
- 代码变更影响分析

---

## 实施策略

### 开发节奏
- **快速迭代**: 每个 Phase 1-2 周
- **持续集成**: 每个功能完成后立即合并
- **文档同步**: 代码和文档同步更新

### 质量保证
- **测试先行**: 关键功能先写测试
- **代码审查**: 重要改动需要审查
- **性能监控**: 持续监控性能指标

### 社区参与
- **开源协作**: 欢迎社区贡献
- **问题跟踪**: 使用 GitHub Issues
- **讨论交流**: 使用 GitHub Discussions

---

## 成功指标

### 可用性指标
- CLI 启动时间 < 1s
- API 响应时间 < 2s（非流式）
- 记忆检索时间 < 100ms
- 测试覆盖率 > 80%

### 轻量性指标
- 核心代码 < 3000 行
- 核心依赖 < 5 个
- 安装包大小 < 10MB
- 内存占用 < 100MB

### 科研指标
- 发表技术博客 2-3 篇
- 实验报告 3-5 份
- 社区讨论参与度

---

## 风险与挑战

### 技术风险
- **API 变更**: 依赖的 API 可能变更
- **性能瓶颈**: 记忆系统可能成为瓶颈
- **兼容性**: 多平台兼容性问题

### 应对策略
- 适配器模式隔离 API 变更
- 性能测试及早发现瓶颈
- CI/CD 覆盖多平台测试

---

## 参考资源

- **设计文档**: `docs/superpowers/specs/`
- **项目状态**: `docs/PROJECT_STATUS.md`
- **变更日志**: `CHANGELOG.md`
- **贡献指南**: `CONTRIBUTING.md`（待创建）

---

**最后更新**: 2026-05-03  
**维护者**: @wyw  
**反馈**: 欢迎通过 GitHub Issues 提供反馈
