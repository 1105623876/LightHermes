# 测试框架说明

当前测试基线为 **220/220 通过**（Active Memory P1 运行时协议 + 停答点 trigger + 3.3a 抽象/原文分流 + 合成 case 场景 + A/B 冻结前最小修复后）。

## 安装测试依赖

优先使用项目虚拟环境：

```powershell
.\venv\Scripts\python.exe -m pip install pytest pytest-asyncio pytest-cov pytest-mock
```

如果需要刷新测试依赖：

```powershell
.\venv\Scripts\python.exe -m pip install --upgrade pip
.\venv\Scripts\python.exe -m pip install pytest pytest-asyncio pytest-cov pytest-mock --no-cache-dir
```

## 运行测试

```powershell
# 全量回归
.\venv\Scripts\python.exe -m pytest tests -v

# 按层运行
.\venv\Scripts\python.exe -m pytest tests/unit -v
.\venv\Scripts\python.exe -m pytest tests/integration -v
.\venv\Scripts\python.exe -m pytest tests/performance -v

# 记忆与评测聚焦测试
.\venv\Scripts\python.exe -m pytest tests/unit/test_memory.py -v
.\venv\Scripts\python.exe -m pytest tests/unit/test_retrieval.py -v
.\venv\Scripts\python.exe -m pytest tests/unit/test_evaluation.py -v
.\venv\Scripts\python.exe -m pytest tests/unit/test_locomo_benchmark.py -v

# 覆盖率与慢测试过滤
.\venv\Scripts\python.exe -m pytest tests --cov=lighthermes --cov-report=html
.\venv\Scripts\python.exe -m pytest tests -v -m "not slow"
```

## 测试结构

```text
tests/
├── conftest.py
├── unit/
│   ├── test_active_memory.py
│   ├── test_adapters.py
│   ├── test_builtin_tools.py
│   ├── test_compressor.py
│   ├── test_core_active_memory.py
│   ├── test_core_memory.py
│   ├── test_evaluation.py
│   ├── test_evolution.py
│   ├── test_locomo_benchmark.py
│   ├── test_memory.py
│   ├── test_retrieval.py
│   └── test_tools.py
├── integration/
│   └── test_cli.py
└── performance/
    └── test_memory_performance.py
```

## 覆盖范围

- **Memory**：索引、四级记忆、结构化召回、生命周期、迁移、蒸馏、合并和容量治理
- **Active Memory**：MemoryRecord、evidence ledger、候选分数 trace、两轮预算、无新增停止、工具覆盖、流式取消与错误、模型 `judge_claim` 判定、query rewrite、searched 区分
- **Memory source**：按 source 读取原文、工作记忆原始对话、邻接 session / distilled_from 展开、`read_memory` 工具
- **Retrieval**：独立 embedding 端点、批量请求、缓存、hybrid 候选扩展、阈值与分数间隔
- **Memory Eval v2.1**：来源级 Recall@K、MRR、Precision@K、噪声率、分类汇总和质量门槛
- **LoCoMo 工具**：分层抽样、session 文档、evidence 排名、QA 指标、成本与独立缓存
- **Core**：配置解析、环境变量引用、记忆注入、工具循环、流式生命周期和 Evolution 适配
- **Builtin tools**：记忆搜索、按 source 读取、受控文件读/搜索/写入和安全边界
- **Evolution**：轨迹质量、技能生成和失败报告
- **Adapters / Compressor / CLI**：供应商适配、流式兼容、上下文压缩和交互命令
- **Performance**：索引、搜索、召回和大规模记忆集合

## 测试标记

- `@pytest.mark.unit`
- `@pytest.mark.integration`
- `@pytest.mark.performance`
- `@pytest.mark.slow`：预计运行超过 1 秒

## 待补测试

- [ ] 真实 API 集成测试（需要外部凭据，不进入默认离线回归）
- [ ] Active Memory static / agentic A/B
- [ ] 冻结验证集、最终 holdout 和跨场景工作流回放
