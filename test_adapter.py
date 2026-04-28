"""
测试 Anthropic Adapter 功能
"""

import os
import sys

# 设置 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def test_openai_adapter():
    """测试 OpenAI adapter"""
    print("=== 测试 1: OpenAI Adapter ===")
    try:
        from lighthermes.adapters import get_adapter

        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 OPENAI_API_KEY 环境变量）")
            return True

        adapter = get_adapter(
            provider="openai",
            model="gpt-4o-mini",
            api_key=api_key
        )

        print(f"✓ OpenAI adapter 创建成功")
        print(f"✓ 模型: {adapter.model}")
        print(f"✓ Provider: openai")

        return True
    except Exception as e:
        print(f"✗ OpenAI adapter 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_anthropic_adapter():
    """测试 Anthropic adapter"""
    print("\n=== 测试 2: Anthropic Adapter ===")
    try:
        from lighthermes.adapters import get_adapter

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 ANTHROPIC_API_KEY 环境变量）")
            return True

        adapter = get_adapter(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key=api_key
        )

        print(f"✓ Anthropic adapter 创建成功")
        print(f"✓ 模型: {adapter.model}")
        print(f"✓ Provider: anthropic")

        return True
    except Exception as e:
        print(f"✗ Anthropic adapter 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_lighthermes_with_openai():
    """测试 LightHermes 使用 OpenAI"""
    print("\n=== 测试 3: LightHermes + OpenAI ===")
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

        print(f"✓ LightHermes 初始化成功")
        print(f"✓ Provider: {agent.provider}")
        print(f"✓ 模型: {agent.model}")

        return True
    except Exception as e:
        print(f"✗ LightHermes + OpenAI 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_lighthermes_with_anthropic():
    """测试 LightHermes 使用 Anthropic"""
    print("\n=== 测试 4: LightHermes + Anthropic ===")
    try:
        from lighthermes import LightHermes

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 ANTHROPIC_API_KEY 环境变量）")
            return True

        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="claude-sonnet-4-6",
            provider="anthropic",
            api_key=api_key,
            memory_enabled=False,
            evolution_enabled=False,
            log_level="WARNING"
        )

        print(f"✓ LightHermes 初始化成功")
        print(f"✓ Provider: {agent.provider}")
        print(f"✓ 模型: {agent.model}")

        return True
    except Exception as e:
        print(f"✗ LightHermes + Anthropic 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_anthropic_api_call():
    """测试 Anthropic API 真实调用"""
    print("\n=== 测试 5: Anthropic API 真实调用 ===")
    try:
        from lighthermes import LightHermes

        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("⚠ 跳过测试（需要 ANTHROPIC_API_KEY 环境变量）")
            return True

        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="claude-sonnet-4-6",
            provider="anthropic",
            api_key=api_key,
            memory_enabled=False,
            evolution_enabled=False,
            log_level="WARNING"
        )

        print("发送测试查询...")
        response = agent.run("你好，请用一句话介绍你自己", stream=False)

        print(f"✓ API 调用成功")
        print(f"✓ 响应: {response[:100]}...")

        return True
    except Exception as e:
        print(f"✗ Anthropic API 调用失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("╭─────────────────────────────────────╮")
    print("│  LightHermes Adapter 测试           │")
    print("╰─────────────────────────────────────╯\n")

    tests = [
        test_openai_adapter,
        test_anthropic_adapter,
        test_lighthermes_with_openai,
        test_lighthermes_with_anthropic,
        test_anthropic_api_call,
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
