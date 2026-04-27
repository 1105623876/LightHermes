# 稳定性增强 + 自适应记忆设计

**日期**: 2026-04-27  
**目标**: 在保持轻量（+300 行）的前提下，提升生产稳定性和理念前沿性

## 核心理念

**自适应记忆**：系统不仅有分层记忆，还能根据使用情况自我优化，越用越高效。

## 三大模块

### 1. 稳定性层（~140 行）

**轻量日志系统**
- 标准库 `logging`，零依赖
- 三级日志：ERROR（关键错误）、WARNING（降级/重试）、INFO（关键节点）
- 输出：控制台 + 可选文件
- 实现：新增 `lightherrmes/logger.py`（~40 行）

**模型降级机制**
- 配置降级链：`gpt-4o-mini → gpt-3.5-turbo → 抛出异常`
- API 失败时自动切换下一个模型
- 记录降级事件到日志（WARNING 级别）
- 实现：在 `core.py` 包装 API 调用（~50 行）

**关键路径错误处理**
- 三个关键路径：API 调用、文件 I/O、工具执行
- 策略：记录日志 + 返回友好错误信息
- 实现：在 `memory.py`、`core.py` 补充（~50 行）

### 2. 自适应记忆层（~140 行）

**记忆命中率追踪**
- 记录：查询内容、命中层级、是否有效
- 统计：各层级命中率、平均检索耗时
- 存储：轻量级 JSON 文件（`memory/stats.json`）
- 实现：新增 `MemoryStats` 类（~50 行）

**自适应权重调整**
- 策略：
  - 短期记忆命中率 > 70% → 增加 `max_turns`（50 → 80）
  - 工作记忆命中率 < 30% → 减少 `retention_days`（7 → 5）
  - 语义记忆命中率 < 20% → 降低检索频率或禁用
- 触发：每 100 次查询后评估一次
- 实现：在 `memory.py` 新增 `adapt_weights` 方法（~60 行）

**记忆压缩归档**
- 识别低频记忆（30 天未访问）并归档
- 策略：保留摘要，删除详细内容
- 格式：JSON 压缩（`gzip`）
- 实现：新增 `archive_old_memories` 方法（~30 行）

### 3. 配置与集成（~20 行）

**config.yaml 新增配置**
```yaml
# 日志配置
logging:
  level: INFO
  file: logs/lightherrmes.log

# 模型降级配置
model:
  fallback_models:
    - gpt-3.5-turbo

# 自适应记忆配置
memory:
  adaptive:
    enabled: true
    adapt_interval: 100  # 每 100 次查询评估一次
    archive_days: 30     # 30 天未访问则归档
```

**集成点**
- 在 `core.py` 对话循环中每 100 轮调用 `memory.adapt_weights()`
- 在 `MemoryManager` 初始化时加载统计数据

## 文件变更

- 新增：`lightherrmes/logger.py`（~40 行）
- 修改：`lightherrmes/core.py`（+100 行）
- 修改：`lightherrmes/memory.py`（+140 行）
- 修改：`config.yaml`（+20 行）

**总计**：~300 行（20% 增量）

## 实现顺序

1. 日志系统（`logger.py`）
2. 模型降级（`core.py`）
3. 错误处理（`memory.py`、`core.py`）
4. 记忆统计（`memory.py` - `MemoryStats`）
5. 自适应调整（`memory.py` - `adapt_weights`）
6. 记忆归档（`memory.py` - `archive_old_memories`）
7. 配置集成（`config.yaml`）
