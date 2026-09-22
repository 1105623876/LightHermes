# LightHermes 上下文压缩系统设计

**日期**: 2026-04-28（初稿）/ 2026-04-29（完成）  
**版本**: v0.3.0 规划  
**状态**: 设计完成，待实现

---

## 背景

LightHermes 当前缺少自动上下文管理机制，长对话和大量记忆会导致：
1. Token 溢出，无法继续对话
2. 记忆检索效率下降
3. API 调用成本增加

## 设计目标

**核心原则**：保持轻量（< 300 行代码），借鉴 hermes-agent 核心思路

**主要场景**：
- **A. 长对话压缩** - CLI 中长时间对话导致的 token 溢出
- **B. 记忆系统压缩** - 压缩存储的情景记忆，减少检索开销

**触发方式**：
- **C. 混合模式** - 自动检测（token 阈值）+ 手动命令（`/compress`）

**压缩策略**：
- 待明天讨论确定

---

## 参考实现分析

### Hermes-agent 核心算法

**文件**: `hermes-agent/agent/context_compressor.py` (~1300 行)

**核心流程**：
1. **工具输出预剪枝** - 便宜，无 LLM 调用
   - 旧工具结果替换为占位符
   - 保留工具调用信息，删除详细输出
   
2. **保护头部消息** - 系统提示 + 首次交互
   - `protect_first_n = 3` 条消息
   
3. **保护尾部消息** - 按 token 预算
   - 约 20K tokens 的最近对话
   - 动态计算，不是固定消息数
   
4. **中间对话总结** - 使用辅助模型（便宜/快速）
   - 结构化摘要模板（已解决/待处理问题）
   - 摘要预算：`min(2000, compressed_content * 0.20, 12000)` tokens
   
5. **迭代摘要更新** - 多次压缩时更新而非重新总结
   - 保留之前的摘要，追加新内容
   - 避免信息丢失

**关键特性**：
- 摘要前缀标记：`[CONTEXT COMPACTION — REFERENCE ONLY]`
- 防止模型混淆摘要和当前任务
- Token 估算：`chars / 4` 粗略估计

### LightAgent 分析

**文件**: `LightAgent/LightAgent/la_core.py`

**发现**：
- 没有专门的上下文压缩实现
- 主要依赖基础的对话历史管理
- 可借鉴的内容较少

---

## 核心设计（2026-04-29 确定）

### 1. 长对话压缩（Phase 1 实现）

**目标**：解决 CLI 中长时间对话的 token 溢出

**核心组件**：
- `ContextCompressor` 类（< 200 行）
- 参考 hermes-agent 核心算法

**压缩策略**（参考 hermes-agent）：
1. **工具输出预剪枝**（无 LLM 调用）
   - 旧工具结果替换为占位符
   - 保留工具调用信息，删除详细输出
   
2. **保护头部消息**
   - 系统提示 + 前 3 条消息
   
3. **保护尾部消息**
   - 最近 ~20K tokens 的对话
   - 动态计算，不是固定消息数
   
4. **中间对话总结**
   - 使用辅助模型（便宜/快速）
   - 结构化摘要模板
   - 摘要预算：`min(2000, compressed_content * 0.20, 12000)` tokens
   
5. **摘要前缀标记**
   - `[CONTEXT COMPACTION — REFERENCE ONLY]`
   - 防止模型混淆摘要和当前任务

**触发机制**：
- **自动触发**：token 使用达到阈值（默认 75% 上下文窗口）
- **手动触发**：`/compress` 命令

### 2. 记忆系统压缩（Phase 2 实验）

**决策**：暂不实现
- 专注 Phase 1 长对话压缩
- 作为 Phase 2 科研实验（记忆压缩与蒸馏）
- 当前归档功能已基本够用

### 3. 配置项

```yaml
context_compression:
  enabled: true
  
  # 触发阈值
  trigger_threshold: 0.75  # 75% 上下文窗口
  
  # 摘要模型
  summary_model: gpt-4o-mini  # 默认便宜模型
  # summary_model: null  # 使用主模型
  
  # 保护策略
  protect_first_n: 3  # 保护前 N 条消息
  protect_recent_tokens: 20000  # 保护最近 N tokens
  
  # 摘要预算
  summary_min_tokens: 2000
  summary_max_tokens: 12000
  summary_ratio: 0.20  # 压缩内容的 20%
  
  # 可选：压缩时提取关键信息到记忆系统
  extract_to_memory: true
```

### 4. CLI 命令

- `/compress` - 立即压缩当前对话
- `/compress stats` - 显示压缩统计（已压缩次数、节省 tokens 等）

---

## 技术实现细节

### Token 估算

使用简单估算（轻量，无需新依赖）：
```python
def estimate_tokens(text: str) -> int:
    """粗略估算 token 数量"""
    return len(text) // 4
```

**理由**：
- 参考 hermes-agent 实现
- 对压缩触发判断足够精确
- 不增加 tiktoken 依赖

### 摘要生成

使用结构化提示模板：
```python
SUMMARY_PROMPT = """
[CONTEXT COMPACTION — REFERENCE ONLY]

请总结以下对话内容，保留关键信息：

{conversation}

总结要求：
1. 保留已解决的问题和解决方案
2. 保留待处理的问题和讨论点
3. 保留重要的决策和原因
4. 使用简洁的语言，避免冗余

总结：
"""
```

### 压缩算法

```python
class ContextCompressor:
    def compress(self, messages: List[Dict]) -> List[Dict]:
        """压缩消息列表"""
        # 1. 工具输出预剪枝
        pruned = self._prune_tool_outputs(messages)
        
        # 2. 分离头部、中间、尾部
        head = pruned[:self.protect_first_n]
        tail = self._get_recent_messages(pruned, self.protect_recent_tokens)
        middle = pruned[len(head):-len(tail)]
        
        # 3. 总结中间部分
        if middle:
            summary = self._summarize(middle)
            return head + [summary] + tail
        
        return pruned
    
    def _prune_tool_outputs(self, messages: List[Dict]) -> List[Dict]:
        """剪枝工具输出"""
        result = []
        for msg in messages:
            if msg.get("role") == "tool":
                # 保留工具调用信息，删除详细输出
                result.append({
                    "role": "tool",
                    "content": f"[Tool output pruned: {msg.get('name')}]"
                })
            else:
                result.append(msg)
        return result
    
    def _get_recent_messages(self, messages: List[Dict], 
                            token_budget: int) -> List[Dict]:
        """获取最近的消息（在 token 预算内）"""
        result = []
        tokens = 0
        for msg in reversed(messages):
            msg_tokens = estimate_tokens(str(msg))
            if tokens + msg_tokens > token_budget:
                break
            result.insert(0, msg)
            tokens += msg_tokens
        return result
    
    def _summarize(self, messages: List[Dict]) -> Dict:
        """总结消息列表"""
        conversation = "\n".join([
            f"{msg['role']}: {msg['content']}" 
            for msg in messages
        ])
        
        summary = self.llm.generate(
            SUMMARY_PROMPT.format(conversation=conversation),
            model=self.summary_model
        )
        
        return {
            "role": "assistant",
            "content": f"[CONTEXT COMPACTION — REFERENCE ONLY]\n\n{summary}"
        }
```

### 集成到 LightHermes

在 `core.py` 中集成：
```python
class LightHermes:
    def __init__(self, ..., compression_enabled=True):
        self.compression_enabled = compression_enabled
        if compression_enabled:
            self.compressor = ContextCompressor(
                config=self.config.get("context_compression", {})
            )
    
    def run(self, user_input: str, ...):
        # 检查是否需要压缩
        if self.compression_enabled:
            total_tokens = self._estimate_context_tokens()
            threshold = self.compressor.trigger_threshold
            
            if total_tokens > threshold * self.context_window:
                self.memory.short_term.messages = \
                    self.compressor.compress(self.memory.short_term.messages)
        
        # 正常处理
        ...
```

---

## 实施计划（细化版）

### Phase 1: 核心压缩功能（2-3 小时）

**任务 1.1**: 实现 `ContextCompressor` 类
- [ ] Token 估算函数
- [ ] 工具输出预剪枝
- [ ] 头部/尾部保护逻辑
- [ ] 中间内容总结

**任务 1.2**: 集成到 `LightHermes`
- [ ] 在 `core.py` 中集成压缩器
- [ ] 自动触发逻辑（token 阈值检测）
- [ ] 配置加载

**任务 1.3**: 基础测试
- [ ] 单元测试（压缩算法）
- [ ] 集成测试（长对话场景）

### Phase 2: CLI 命令和配置（1 小时）

**任务 2.1**: CLI 命令
- [ ] `/compress` - 手动压缩
- [ ] `/compress stats` - 显示统计

**任务 2.2**: 配置文件
- [ ] 在 `config.yaml` 添加压缩配置
- [ ] 配置验证和默认值

### Phase 3: 优化和文档（1 小时）

**任务 3.1**: 优化
- [ ] 摘要质量优化
- [ ] 性能测试（大量消息）
- [ ] 边界测试（空消息、单条消息等）

**任务 3.2**: 文档
- [ ] 更新 README 添加压缩功能说明
- [ ] 添加配置示例
- [ ] 更新 CHANGELOG

**总工作量估计**：4-5 小时

### 验收标准

- [ ] 长对话（100+ 轮）不会 token 溢出
- [ ] 压缩后对话质量不明显下降
- [ ] `/compress` 命令正常工作
- [ ] 配置项生效
- [ ] 测试通过
- [ ] 文档完整

---

## 设计决策（2026-04-29 确定）

### 1. 压缩后内容处理方式
**决策：选择 A（仅保留摘要）**
- 保持轻量原则
- CLI 长对话场景不需要完整历史回溯
- 未来可作为增强特性添加归档功能

### 2. Token 估算方式
**决策：简单估算（`len(text) // 4`）**
- 不增加新依赖（tiktoken）
- 参考 hermes-agent 实现
- 对压缩触发判断足够精确
- 可选：未来提供 tiktoken 作为配置增强

### 3. 摘要模型选择
**决策：可配置（默认便宜模型）**
```yaml
context_compression:
  summary_model: gpt-4o-mini  # 默认
```
- 默认使用便宜模型节省成本
- 允许配置使用主模型提升质量

### 4. 存储策略
**决策：内存存储（临时）**
- 摘要仅在当前会话有效
- 会话结束后自动清理
- 持久化需求通过记忆系统处理

### 5. 记忆压缩
**决策：暂不实现**
- Phase 1 专注长对话压缩
- 记忆压缩作为 Phase 2 科研实验
- 当前归档功能已基本够用

### 6. 与记忆系统集成
**决策：松耦合集成**
```yaml
context_compression:
  extract_to_memory: true  # 可选
```
- 压缩系统独立运行
- 可选择性提取关键信息到记忆系统

---

## 参考资源

- **Hermes-agent 实现**: `hermes-agent/agent/context_compressor.py`
- **Hermes-agent 引擎接口**: `hermes-agent/agent/context_engine.py`
- **Hermes-agent 记忆管理**: `hermes-agent/agent/memory_manager.py`
- **LightHermes 当前记忆系统**: `lighthermes/memory.py`
- **LightHermes 核心引擎**: `lighthermes/core.py`

---

## 下一步

**设计阶段**：✅ 完成（2026-04-29）

**实现阶段**：
1. 创建 `lighthermes/compressor.py` 文件
2. 实现 `ContextCompressor` 类
3. 集成到 `core.py`
4. 添加 CLI 命令
5. 更新配置文件
6. 编写测试
7. 更新文档

**预计工作量**：4-5 小时

**目标完成时间**：v0.3.0 发布前
