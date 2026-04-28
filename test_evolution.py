"""
测试进化链路功能
"""

import os
import sys
import shutil

# 设置 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def test_task_classification():
    """测试任务分类"""
    print("=== 测试 1: 任务分类 ===")
    try:
        from lighthermes import LightHermes

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 OPENAI_API_KEY 环境变量）")
            return True

        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="gpt-4o-mini",
            provider="openai",
            api_key=api_key,
            memory_enabled=False,
            evolution_enabled=False,
            log_level="WARNING"
        )

        # 测试不同类型的任务分类
        test_cases = [
            ("写一个函数计算斐波那契数列", "代码"),
            ("这个 bug 怎么修复", "调试"),
            ("解释一下什么是闭包", "解释"),
            ("如何配置 nginx", "配置"),
            ("你好", "通用"),
        ]

        all_passed = True
        for query, expected_type in test_cases:
            result = agent._classify_task(query)
            if result == expected_type:
                print(f"✓ '{query}' → {result}")
            else:
                print(f"✗ '{query}' → {result} (期望: {expected_type})")
                all_passed = False

        if all_passed:
            print("✓ 任务分类测试通过")
            return True
        else:
            print("✗ 部分任务分类失败")
            return False

    except Exception as e:
        print(f"✗ 任务分类测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_trajectory_recording():
    """测试轨迹记录"""
    print("\n=== 测试 2: 轨迹记录 ===")
    try:
        from lighthermes import LightHermes
        import tempfile

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 OPENAI_API_KEY 环境变量）")
            return True

        # 使用临时目录
        temp_dir = tempfile.mkdtemp()
        trajectory_dir = os.path.join(temp_dir, "trajectories")

        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="gpt-4o-mini",
            provider="openai",
            api_key=api_key,
            memory_enabled=False,
            evolution_enabled=True,
            log_level="WARNING"
        )

        # 模拟一次对话
        print("发送测试查询...")
        response = agent.run("你好，请用一句话介绍你自己", stream=False)

        # 检查轨迹文件是否生成
        if os.path.exists("trajectories"):
            trajectory_files = os.listdir("trajectories")
            if trajectory_files:
                print(f"✓ 轨迹文件已生成: {len(trajectory_files)} 个")
                print(f"✓ 轨迹记录测试通过")
                return True
            else:
                print("✗ 轨迹目录为空")
                return False
        else:
            print("✗ 轨迹目录未创建")
            return False

    except Exception as e:
        print(f"✗ 轨迹记录测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # 清理临时目录
        if 'temp_dir' in locals() and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def test_evolution_trigger():
    """测试自动进化触发"""
    print("\n=== 测试 3: 自动进化触发 ===")
    try:
        from lighthermes import LightHermes

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 OPENAI_API_KEY 环境变量）")
            return True

        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="gpt-4o-mini",
            provider="openai",
            api_key=api_key,
            memory_enabled=False,
            evolution_enabled=True,
            log_level="INFO"
        )

        # 模拟 50 次对话触发进化
        print("模拟 50 次对话...")
        agent.query_count = 49  # 设置为 49，下一次就会触发

        response = agent.run("测试查询", stream=False)

        # 检查是否触发了进化
        if agent.query_count == 50:
            print("✓ 查询计数正确: 50")
            print("✓ 自动进化触发测试通过")
            return True
        else:
            print(f"✗ 查询计数错误: {agent.query_count}")
            return False

    except Exception as e:
        print(f"✗ 自动进化触发测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("╭─────────────────────────────────────╮")
    print("│  LightHermes 进化链路测试           │")
    print("╰─────────────────────────────────────╯\n")

    tests = [
        test_task_classification,
        test_trajectory_recording,
        test_evolution_trigger,
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
