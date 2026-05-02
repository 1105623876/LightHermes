# 测试框架说明

## 安装测试依赖

```bash
pip install pytest pytest-asyncio pytest-cov pytest-mock
```

如果遇到安装问题，可以尝试：
```bash
pip install --upgrade pip
pip install pytest pytest-asyncio pytest-cov pytest-mock --no-cache-dir
```

## 运行测试

```bash
# 运行所有测试
pytest tests/ -v

# 运行特定类型的测试
pytest tests/unit/ -v                    # 单元测试
pytest tests/integration/ -v             # 集成测试
pytest tests/performance/ -v             # 性能测试

# 运行特定测试文件
pytest tests/unit/test_memory.py -v
pytest tests/unit/test_adapters.py -v

# 运行带覆盖率报告
pytest tests/ --cov=lighthermes --cov-report=html

# 跳过慢速测试
pytest tests/ -v -m "not slow"
```

## 测试结构

```
tests/
├── conftest.py                          # 共享 fixtures
├── unit/                                # 单元测试
│   ├── test_memory.py                   # 记忆系统测试
│   └── test_adapters.py                 # Adapter 测试
├── integration/                         # 集成测试（待添加）
│   └── test_cli.py                      # CLI 集成测试
└── performance/                         # 性能测试
    └── test_memory_performance.py       # 记忆系统性能测试
```

## 测试标记

- `@pytest.mark.unit` - 单元测试
- `@pytest.mark.integration` - 集成测试
- `@pytest.mark.performance` - 性能测试
- `@pytest.mark.slow` - 慢速测试（> 1秒）

## 当前测试覆盖

### 已完成
- ✅ pytest 框架配置（pytest.ini）
- ✅ 共享 fixtures（conftest.py）
- ✅ 记忆系统单元测试（test_memory.py）
  - 记忆索引（分词、搜索）
  - 记忆统计
  - 短期记忆
  - 记忆管理器
  - 文件解析
- ✅ Adapter 单元测试（test_adapters.py）
  - Adapter 工厂
  - OpenAI Adapter
  - Anthropic Adapter
  - 流式响应处理
- ✅ 性能基准测试（test_memory_performance.py）
  - 索引性能
  - 搜索性能
  - 召回性能
  - 可扩展性测试

### 待添加
- [ ] CLI 集成测试
- [ ] Evolution 系统测试
- [ ] Compressor 测试
- [ ] 真实 API 集成测试（需要 API key）
