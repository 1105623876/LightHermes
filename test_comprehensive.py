"""
LightHermes 综合测试
测试核心功能、记忆系统、自适应调整等
"""

import os
import sys
import tempfile
import shutil

# 设置 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

def test_imports():
    """测试模块导入"""
    print("=== 测试 1: 模块导入 ===")
    try:
        from lightherrmes import LightHermes
        from lightherrmes.memory import MemoryManager, MemoryStats
        from lightherrmes.logger import setup_logger
        from lightherrmes.evolution import EvolutionEngine
        print("✓ 所有核心模块导入成功")
        return True
    except Exception as e:
        print(f"✗ 模块导入失败: {e}")
        return False

def test_logger():
    """测试日志系统"""
    print("\n=== 测试 2: 日志系统 ===")
    try:
        from lightherrmes.logger import setup_logger

        logger = setup_logger("test", level="INFO")
        logger.info("日志测试")
        logger.warning("警告测试")
        logger.error("错误测试")

        print("✓ 日志系统正常工作")
        return True
    except Exception as e:
        print(f"✗ 日志系统失败: {e}")
        return False

def test_memory_stats():
    """测试记忆统计系统"""
    print("\n=== 测试 3: 记忆统计系统 ===")
    try:
        from lightherrmes.memory import MemoryStats

        temp_dir = tempfile.mkdtemp()
        stats_file = os.path.join(temp_dir, "stats.json")

        stats = MemoryStats(stats_file)
        stats.record_hit("working", 1, 0.1)
        stats.record_hit("episodic", 2, 0.2)
        stats.record_hit("semantic", 0, 0.05)

        working_rate = stats.get_hit_rate("working")
        episodic_rate = stats.get_hit_rate("episodic")

        print(f"✓ 工作记忆命中率: {working_rate:.2%}")
        print(f"✓ 情景记忆命中率: {episodic_rate:.2%}")
        print("✓ 记忆统计系统正常工作")

        shutil.rmtree(temp_dir)
        return True
    except Exception as e:
        print(f"✗ 记忆统计系统失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_memory_manager():
    """测试记忆管理器"""
    print("\n=== 测试 4: 记忆管理器 ===")
    try:
        from lightherrmes.memory import MemoryManager

        temp_dir = tempfile.mkdtemp()

        memory = MemoryManager(
            memory_dir=temp_dir,
            short_term_turns=50,
            working_memory_days=7
        )

        # 测试短期记忆
        memory.add_message("user", "测试消息1")
        memory.add_message("assistant", "测试回复1")
        context = memory.get_context()
        print(f"✓ 短期记忆: {len(context)} 条消息")

        # 测试工作记忆
        memory.save_session("test_session", "test_user", "测试会话摘要")
        print("✓ 工作记忆保存成功")

        # 测试情景记忆
        memory.save_episodic("test_project", "测试项目内容", {"status": "active"})
        print("✓ 情景记忆保存成功")

        # 测试语义记忆
        memory.save_semantic("test_knowledge", "测试知识内容")
        print("✓ 语义记忆保存成功")

        # 测试召回
        recalled = memory.recall("测试", "test_user")
        print(f"✓ 记忆召回: {len(recalled)} 字符")

        print("✓ 记忆管理器所有功能正常")

        shutil.rmtree(temp_dir)
        return True
    except Exception as e:
        print(f"✗ 记忆管理器失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_adaptive_memory():
    """测试自适应记忆调整"""
    print("\n=== 测试 5: 自适应记忆调整 ===")
    try:
        from lightherrmes.memory import MemoryManager

        temp_dir = tempfile.mkdtemp()

        memory = MemoryManager(
            memory_dir=temp_dir,
            short_term_turns=50,
            working_memory_days=7
        )

        # 模拟一些查询以生成统计数据
        for i in range(10):
            memory.recall(f"测试查询 {i}", "test_user")

        # 测试自适应调整
        old_turns = memory.short_term.max_turns
        old_days = memory.working.retention_days

        memory.adapt_weights()

        print(f"✓ 短期记忆容量: {old_turns} → {memory.short_term.max_turns}")
        print(f"✓ 工作记忆保留期: {old_days} → {memory.working.retention_days} 天")
        print("✓ 自适应记忆调整正常工作")

        shutil.rmtree(temp_dir)
        return True
    except Exception as e:
        print(f"✗ 自适应记忆调整失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_config_loading():
    """测试配置加载"""
    print("\n=== 测试 6: 配置加载 ===")
    try:
        import yaml

        if not os.path.exists("config.yaml"):
            print("⚠ config.yaml 不存在，跳过测试")
            return True

        with open("config.yaml", 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # 检查关键配置项
        assert "model" in config, "缺少 model 配置"
        assert "memory" in config, "缺少 memory 配置"
        assert "logging" in config, "缺少 logging 配置"

        # 检查自适应记忆配置
        assert "adaptive" in config["memory"], "缺少 adaptive 配置"
        assert "fallback_models" in config["model"], "缺少 fallback_models 配置"

        print("✓ 配置文件结构正确")
        print(f"✓ 主模型: {config['model']['model_name']}")
        print(f"✓ 降级模型: {config['model']['fallback_models']}")
        print(f"✓ 自适应间隔: {config['memory']['adaptive']['adapt_interval']} 次查询")
        print("✓ 配置加载正常工作")

        return True
    except Exception as e:
        print(f"✗ 配置加载失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def test_lightherrmes_init():
    """测试 LightHermes 初始化"""
    print("\n=== 测试 7: LightHermes 初始化 ===")
    try:
        from lightherrmes import LightHermes

        # 检查 API key
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 OPENAI_API_KEY 环境变量）")
            return True

        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="gpt-4o-mini",
            fallback_models=["gpt-3.5-turbo"],
            log_level="WARNING"
        )

        print(f"✓ Agent 名称: {agent.name}")
        print(f"✓ 主模型: {agent.model}")
        print(f"✓ 降级模型: {agent.fallback_models}")
        print(f"✓ 记忆系统: {'启用' if agent.memory_enabled else '禁用'}")
        print(f"✓ 查询计数: {agent.query_count}")
        print("✓ LightHermes 初始化成功")

        return True
    except Exception as e:
        print(f"✗ LightHermes 初始化失败: {e}")
        import traceback
        traceback.print_exc()
        return False

def main():
    """运行所有测试"""
    print("╭─────────────────────────────────────╮")
    print("│  LightHermes 综合测试               │")
    print("╰─────────────────────────────────────╯\n")

    tests = [
        test_imports,
        test_logger,
        test_memory_stats,
        test_memory_manager,
        test_adaptive_memory,
        test_config_loading,
        test_lightherrmes_init,
    ]

    results = []
    for test in tests:
        try:
            result = test()
            results.append(result)
        except Exception as e:
            print(f"✗ 测试异常: {e}")
            results.append(False)

    # 统计结果
    passed = sum(results)
    total = len(results)

    print("\n" + "="*40)
    print(f"测试结果: {passed}/{total} 通过")

    if passed == total:
        print("✓ 所有测试通过")
        return 0
    else:
        print(f"✗ {total - passed} 个测试失败")
        return 1

if __name__ == "__main__":
    sys.exit(main())
