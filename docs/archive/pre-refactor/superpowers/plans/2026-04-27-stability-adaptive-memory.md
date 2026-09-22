# 稳定性增强 + 自适应记忆实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在保持轻量（+300 行）的前提下，提升生产稳定性和理念前沿性

**Architecture:** 三层架构 - 稳定性层（日志+降级+错误处理）、自适应记忆层（统计+调整+归档）、配置集成层

**Tech Stack:** Python 标准库 logging、sqlite3、json、gzip

---

## Task 1: 日志系统

**Files:**
- Create: `lighthermes/logger.py`

- [ ] **Step 1: 创建日志模块**

```python
"""
LightHermes 轻量日志系统
"""

import logging
import os
from pathlib import Path


def setup_logger(
    name: str,
    level: str = "INFO",
    log_file: str = None
) -> logging.Logger:
    """
    设置日志记录器
    
    Args:
        name: 日志记录器名称
        level: 日志级别 (DEBUG/INFO/WARNING/ERROR)
        log_file: 日志文件路径（可选）
    
    Returns:
        配置好的日志记录器
    """
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, level.upper()))
    
    # 避免重复添加 handler
    if logger.handlers:
        return logger
    
    formatter = logging.Formatter(
        '[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    if log_file:
        log_dir = os.path.dirname(log_file)
        if log_dir:
            os.makedirs(log_dir, exist_ok=True)
        file_handler = logging.FileHandler(log_file, encoding='utf-8')
        file_handler.setFormatter(formatter)
        logger.addHandler(file_handler)
    
    return logger
```

- [ ] **Step 2: 提交日志模块**

```bash
git add lighthermes/logger.py
git commit -m "feat: 添加轻量日志系统"
```

---

## Task 2: 模型降级机制

**Files:**
- Modify: `lighthermes/core.py:164-200`

- [ ] **Step 1: 在 LightHermes.__init__ 添加降级配置**

在 `core.py` 的 `LightHermes.__init__` 方法中，添加以下参数和初始化逻辑：

```python
# 在 __init__ 参数列表中添加（约第 181 行）
fallback_models: List[str] = None,

# 在初始化逻辑中添加（约第 190 行后）
from lighthermes.logger import setup_logger
self.logger = setup_logger(
    name="lighthermes",
    level=log_level,
    log_file=log_file
)

self.fallback_models = fallback_models or []
self.query_count = 0
```

- [ ] **Step 2: 添加带降级的 API 调用方法**

在 `LightHermes` 类中添加新方法（约第 230 行前）：

```python
def _call_api_with_fallback(
    self,
    messages: List[Dict],
    **kwargs
) -> Any:
    """
    带降级机制的 API 调用
    """
    models = [self.model] + self.fallback_models
    last_error = None
    
    for i, model in enumerate(models):
        try:
            response = self.client.chat.completions.create(
                model=model,
                messages=messages,
                **kwargs
            )
            if i > 0:
                self.logger.warning(f"降级到模型 {model}")
            return response
        except Exception as e:
            last_error = e
            if i == len(models) - 1:
                self.logger.error(f"所有模型失败: {e}")
                raise
            self.logger.warning(f"模型 {model} 失败，尝试降级: {e}")
    
    raise last_error
```

- [ ] **Step 3: 修改 run 方法使用降级 API**

在 `run` 方法中，找到 `self.client.chat.completions.create` 调用（约第 280 行），替换为：

```python
response = self._call_api_with_fallback(
    messages=messages,
    stream=stream,
    tools=tool_schemas if tool_schemas else None
)
```

- [ ] **Step 4: 提交模型降级功能**

```bash
git add lighthermes/core.py
git commit -m "feat: 添加模型降级机制"
```

---

## Task 3: 记忆系统错误处理

**Files:**
- Modify: `lighthermes/memory.py:46-100`

- [ ] **Step 1: 在 MemoryManager 添加日志**

在 `memory.py` 顶部导入日志（约第 13 行后）：

```python
from lighthermes.logger import setup_logger
```

在 `MemoryManager.__init__` 中添加日志初始化（约第 200 行）：

```python
self.logger = setup_logger("lighthermes.memory")
```

- [ ] **Step 2: 为 WorkingMemory 添加错误处理**

在 `WorkingMemory._init_db` 方法中添加错误处理（约第 46 行）：

```python
def _init_db(self):
    try:
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                user_id TEXT,
                summary TEXT,
                timestamp TEXT
            )
        """)
        conn.commit()
        conn.close()
    except Exception as e:
        logger = setup_logger("lighthermes.memory")
        logger.error(f"初始化工作记忆数据库失败: {e}")
        raise
```

- [ ] **Step 3: 为 add_session 添加错误处理**

在 `WorkingMemory.add_session` 方法中添加错误处理（约第 62 行）：

```python
def add_session(self, session_id: str, user_id: str, summary: str):
    try:
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO sessions (session_id, user_id, summary, timestamp)
            VALUES (?, ?, ?, ?)
        """, (session_id, user_id, summary, datetime.now().isoformat()))
        conn.commit()
        conn.close()
        self._cleanup_old_sessions()
    except Exception as e:
        logger = setup_logger("lighthermes.memory")
        logger.error(f"添加会话摘要失败: {e}")
```

- [ ] **Step 4: 提交错误处理**

```bash
git add lighthermes/memory.py
git commit -m "feat: 添加记忆系统错误处理"
```

---

## Task 4: 记忆统计系统

**Files:**
- Modify: `lighthermes/memory.py:15-100`

- [ ] **Step 1: 添加 MemoryStats 类**

在 `memory.py` 中，在 `ShortTermMemory` 类之前添加（约第 16 行）：

```python
class MemoryStats:
    """记忆统计 - 追踪各层级命中率"""
    
    def __init__(self, stats_file: str):
        self.stats_file = stats_file
        self.stats = self._load_stats()
    
    def _load_stats(self) -> Dict[str, Dict[str, float]]:
        if not os.path.exists(self.stats_file):
            return {}
        try:
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}
    
    def _save_stats(self):
        try:
            os.makedirs(os.path.dirname(self.stats_file), exist_ok=True)
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger = setup_logger("lighthermes.memory")
            logger.error(f"保存统计数据失败: {e}")
    
    def record_hit(self, layer: str, hit_count: int, query_time: float):
        if layer not in self.stats:
            self.stats[layer] = {"hits": 0, "queries": 0, "total_time": 0.0}
        
        self.stats[layer]["queries"] += 1
        self.stats[layer]["hits"] += hit_count
        self.stats[layer]["total_time"] += query_time
        
        self._save_stats()
    
    def get_hit_rate(self, layer: str) -> float:
        if layer not in self.stats or self.stats[layer]["queries"] == 0:
            return 0.0
        return self.stats[layer]["hits"] / self.stats[layer]["queries"]
    
    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        return self.stats.copy()
```

- [ ] **Step 2: 在 MemoryManager 集成统计**

在 `MemoryManager.__init__` 中添加统计初始化（约第 200 行）：

```python
stats_file = os.path.join(memory_dir, "stats.json")
self.stats = MemoryStats(stats_file)
```

- [ ] **Step 3: 在 retrieve 方法中记录统计**

在 `MemoryManager.retrieve` 方法中添加统计记录（约第 250 行）：

```python
def retrieve(self, query: str, user_id: str = "default_user") -> str:
    import time
    start_time = time.time()
    
    context_parts = []
    
    # 短期记忆
    short_term_msgs = self.short_term.get_messages()
    if short_term_msgs:
        context_parts.append("## 短期记忆\n" + str(short_term_msgs[-10:]))
        self.stats.record_hit("short_term", 1 if short_term_msgs else 0, time.time() - start_time)
    
    # 工作记忆
    working_sessions = self.working.get_recent_sessions(user_id, limit=5)
    if working_sessions:
        context_parts.append("## 工作记忆\n" + str(working_sessions))
        self.stats.record_hit("working", 1 if working_sessions else 0, time.time() - start_time)
    
    # 情景记忆
    episodic_results = self.episodic.search(query, limit=3)
    if episodic_results:
        context_parts.append("## 情景记忆\n" + str(episodic_results))
        self.stats.record_hit("episodic", len(episodic_results), time.time() - start_time)
    
    # 语义记忆
    if self.use_hybrid_retrieval:
        semantic_results = self.semantic.search(query, limit=5)
        if semantic_results:
            context_parts.append("## 语义记忆\n" + str(semantic_results))
            self.stats.record_hit("semantic", len(semantic_results), time.time() - start_time)
    
    return "\n\n".join(context_parts) if context_parts else ""
```

- [ ] **Step 4: 提交统计系统**

```bash
git add lighthermes/memory.py
git commit -m "feat: 添加记忆统计系统"
```

---

## Task 5: 自适应权重调整

**Files:**
- Modify: `lighthermes/memory.py:200-250`

- [ ] **Step 1: 添加 adapt_weights 方法**

在 `MemoryManager` 类中添加方法（约第 280 行）：

```python
def adapt_weights(self):
    """
    根据命中率自适应调整记忆层级权重
    """
    # 短期记忆自适应
    short_term_rate = self.stats.get_hit_rate("short_term")
    if short_term_rate > 0.7 and self.short_term.max_turns < 100:
        old_max = self.short_term.max_turns
        self.short_term.max_turns = min(100, self.short_term.max_turns + 10)
        self.logger.info(
            f"短期记忆容量增加: {old_max} → {self.short_term.max_turns} "
            f"(命中率: {short_term_rate:.2%})"
        )
    elif short_term_rate < 0.3 and self.short_term.max_turns > 30:
        old_max = self.short_term.max_turns
        self.short_term.max_turns = max(30, self.short_term.max_turns - 10)
        self.logger.info(
            f"短期记忆容量减少: {old_max} → {self.short_term.max_turns} "
            f"(命中率: {short_term_rate:.2%})"
        )
    
    # 工作记忆自适应
    working_rate = self.stats.get_hit_rate("working")
    if working_rate < 0.3 and self.working.retention_days > 3:
        old_days = self.working.retention_days
        self.working.retention_days = max(3, self.working.retention_days - 1)
        self.logger.info(
            f"工作记忆保留期缩短: {old_days} → {self.working.retention_days} 天 "
            f"(命中率: {working_rate:.2%})"
        )
    elif working_rate > 0.6 and self.working.retention_days < 14:
        old_days = self.working.retention_days
        self.working.retention_days = min(14, self.working.retention_days + 1)
        self.logger.info(
            f"工作记忆保留期延长: {old_days} → {self.working.retention_days} 天 "
            f"(命中率: {working_rate:.2%})"
        )
    
    # 语义记忆自适应
    if self.use_hybrid_retrieval:
        semantic_rate = self.stats.get_hit_rate("semantic")
        if semantic_rate < 0.2:
            self.use_hybrid_retrieval = False
            self.logger.warning(
                f"语义记忆命中率过低 ({semantic_rate:.2%})，暂时禁用"
            )
```

- [ ] **Step 2: 在 core.py 集成自适应调整**

在 `core.py` 的 `run` 方法中添加调用（约第 350 行）：

```python
# 在对话循环末尾添加
self.query_count += 1
if self.memory and self.query_count % 100 == 0:
    self.memory.adapt_weights()
    self.logger.info(f"已完成 {self.query_count} 次查询，执行记忆自适应调整")
```

- [ ] **Step 3: 提交自适应调整**

```bash
git add lighthermes/memory.py lighthermes/core.py
git commit -m "feat: 添加自适应权重调整"
```

---

## Task 6: 记忆归档

**Files:**
- Modify: `lighthermes/memory.py:100-150`

- [ ] **Step 1: 为 EpisodicMemory 添加归档支持**

在 `EpisodicMemory._init_db` 方法中添加归档字段（约第 120 行）：

```python
cursor.execute("""
    CREATE TABLE IF NOT EXISTS episodes (
        id TEXT PRIMARY KEY,
        user_id TEXT,
        content TEXT,
        summary TEXT,
        timestamp TEXT,
        last_accessed TEXT,
        archived INTEGER DEFAULT 0
    )
""")
```

- [ ] **Step 2: 添加 archive_old_memories 方法**

在 `MemoryManager` 类中添加方法（约第 320 行）：

```python
def archive_old_memories(self, days_threshold: int = 30):
    """
    归档低频记忆
    """
    cutoff = (datetime.now() - timedelta(days=days_threshold)).isoformat()
    
    try:
        conn = sqlite3.connect(self.episodic.db_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT id, summary FROM episodes 
            WHERE last_accessed < ? AND archived = 0
        """, (cutoff,))
        
        to_archive = cursor.fetchall()
        
        for episode_id, summary in to_archive:
            cursor.execute("""
                UPDATE episodes 
                SET content = ?, archived = 1 
                WHERE id = ?
            """, (f"[已归档] {summary}", episode_id))
        
        conn.commit()
        conn.close()
        
        if to_archive:
            self.logger.info(f"归档了 {len(to_archive)} 条低频记忆")
        
        return len(to_archive)
    except Exception as e:
        self.logger.error(f"归档记忆失败: {e}")
        return 0
```

- [ ] **Step 3: 在 adapt_weights 中调用归档**

在 `adapt_weights` 方法末尾添加（约第 315 行）：

```python
# 定期归档低频记忆
archived_count = self.archive_old_memories(days_threshold=30)
```

- [ ] **Step 4: 提交归档功能**

```bash
git add lighthermes/memory.py
git commit -m "feat: 添加记忆归档功能"
```

---

## Task 7: 配置集成

**Files:**
- Modify: `config.yaml:1-70`

- [ ] **Step 1: 更新 config.yaml**

在 `config.yaml` 中添加新配置（约第 60 行后）：

```yaml
# 日志配置
logging:
  level: INFO
  file: logs/lighthermes.log
  debug: false

# 模型降级配置
model:
  provider: openai
  model_name: gpt-4o-mini
  api_key: ${OPENAI_API_KEY}
  base_url: https://api.openai.com/v1
  fallback_models:
    - gpt-3.5-turbo

# 记忆配置
memory:
  enabled: true
  storage_dir: memory
  
  # 自适应记忆配置
  adaptive:
    enabled: true
    adapt_interval: 100
    archive_days: 30
  
  # 混合检索配置
  hybrid_retrieval:
    enabled: false
    provider: openai
    model: text-embedding-3-small
  
  retention:
    short_term_turns: 50
    working_memory_days: 7
    episodic_auto_archive: true
    semantic_max_entries: 1000
```

- [ ] **Step 2: 在 core.py 读取配置**

在 `LightHermes.__init__` 中添加配置读取（约第 186 行）：

```python
# 读取配置文件
config = {}
config_path = "config.yaml"
if os.path.exists(config_path):
    with open(config_path, 'r', encoding='utf-8') as f:
        config = yaml.safe_load(f) or {}

# 应用配置
if not fallback_models and config.get("model", {}).get("fallback_models"):
    fallback_models = config["model"]["fallback_models"]

if not log_level and config.get("logging", {}).get("level"):
    log_level = config["logging"]["level"]

if not log_file and config.get("logging", {}).get("file"):
    log_file = config["logging"]["file"]
```

- [ ] **Step 3: 提交配置集成**

```bash
git add config.yaml lighthermes/core.py
git commit -m "feat: 添加配置集成"
```

---

## Task 8: 测试验证

**Files:**
- Create: `test_stability.py`

- [ ] **Step 1: 创建测试脚本**

```python
"""
测试稳定性增强和自适应记忆功能
"""

import os
import time
from lighthermes import LightHermes

def test_logging():
    print("=== 测试日志系统 ===")
    agent = LightHermes(
        name="TestAgent",
        role="测试助手",
        model="gpt-4o-mini",
        log_level="INFO",
        log_file="logs/test.log"
    )
    print("✓ 日志系统初始化成功")

def test_fallback():
    print("\n=== 测试模型降级 ===")
    agent = LightHermes(
        name="TestAgent",
        role="测试助手",
        model="invalid-model",
        fallback_models=["gpt-3.5-turbo"],
        log_level="WARNING"
    )
    try:
        response = agent.run("你好", stream=False)
        print("✓ 模型降级成功")
    except Exception as e:
        print(f"✗ 模型降级失败: {e}")

def test_adaptive_memory():
    print("\n=== 测试自适应记忆 ===")
    agent = LightHermes(
        name="TestAgent",
        role="测试助手",
        model="gpt-4o-mini",
        memory_enabled=True,
        log_level="INFO"
    )
    
    # 模拟 100 次查询触发自适应调整
    for i in range(100):
        agent.run(f"测试查询 {i}", stream=False)
    
    print("✓ 自适应记忆调整完成")
    
    # 检查统计文件
    stats_file = "memory/stats.json"
    if os.path.exists(stats_file):
        print(f"✓ 统计文件已生成: {stats_file}")
    else:
        print(f"✗ 统计文件未生成")

if __name__ == "__main__":
    test_logging()
    test_fallback()
    test_adaptive_memory()
    print("\n=== 所有测试完成 ===")
```

- [ ] **Step 2: 运行测试**

```bash
python test_stability.py
```

预期输出：
```
=== 测试日志系统 ===
✓ 日志系统初始化成功

=== 测试模型降级 ===
✓ 模型降级成功

=== 测试自适应记忆 ===
✓ 自适应记忆调整完成
✓ 统计文件已生成: memory/stats.json

=== 所有测试完成 ===
```

- [ ] **Step 3: 提交测试脚本**

```bash
git add test_stability.py
git commit -m "test: 添加稳定性和自适应记忆测试"
```

---

## Task 9: 文档更新

**Files:**
- Modify: `README.md:104-129`

- [ ] **Step 1: 更新 README 特性说明**

在 README.md 的"核心特性"部分添加（约第 10 行）：

```markdown
- **生产稳定性**: 轻量日志 + 模型降级 + 错误处理
- **自适应记忆**: 根据命中率动态优化记忆层级
```

- [ ] **Step 2: 添加配置说明**

在 README.md 的"渐进增强"部分添加（约第 30 行）：

```markdown
## 稳定性配置

**日志系统**:
```yaml
logging:
  level: INFO  # DEBUG/INFO/WARNING/ERROR
  file: logs/lighthermes.log
```

**模型降级**:
```yaml
model:
  fallback_models:
    - gpt-3.5-turbo  # API 失败时自动切换
```

**自适应记忆**:
```yaml
memory:
  adaptive:
    enabled: true
    adapt_interval: 100  # 每 100 次查询评估一次
    archive_days: 30     # 30 天未访问则归档
```
```

- [ ] **Step 3: 提交文档更新**

```bash
git add README.md
git commit -m "docs: 更新 README - 添加稳定性和自适应记忆说明"
```

---

## Task 10: 最终验证

**Files:**
- None (verification only)

- [ ] **Step 1: 检查代码行数**

```bash
find lighthermes -name "*.py" -exec wc -l {} + | tail -1
```

预期输出：约 1819 行（1519 + 300）

- [ ] **Step 2: 运行完整测试**

```bash
python -m lighthermes.cli
```

在 CLI 中测试：
1. 输入查询，观察日志输出
2. 连续输入 100 次查询，观察自适应调整日志
3. 检查 `memory/stats.json` 文件生成

- [ ] **Step 3: 推送到 GitHub**

```bash
git push origin master
```

- [ ] **Step 4: 更新设计文档状态**

在 `docs/superpowers/specs/2026-04-27-stability-adaptive-memory-design.md` 顶部添加：

```markdown
**状态**: ✅ 已完成 (2026-04-27)
```

```bash
git add docs/superpowers/specs/2026-04-27-stability-adaptive-memory-design.md
git commit -m "docs: 标记设计文档为已完成"
git push origin master
```
