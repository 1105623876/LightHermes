"""
测试 @tool 装饰器功能
"""

import os
import sys

# 设置 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')


def test_tool_decorator_import():
    """测试 @tool 装饰器导入"""
    print("=== 测试 1: @tool 装饰器导入 ===")
    try:
        from lightherrmes import tool
        print(f"✓ @tool 装饰器导入成功")
        print(f"✓ 类型: {type(tool)}")
        return True
    except Exception as e:
        print(f"✗ @tool 装饰器导入失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_decorator_usage():
    """测试 @tool 装饰器使用"""
    print("\n=== 测试 2: @tool 装饰器使用 ===")
    try:
        from lightherrmes import tool

        @tool(
            name="get_weather",
            description="获取指定城市的天气",
            params=[
                {"name": "city", "type": "string", "description": "城市名称", "required": True}
            ]
        )
        def get_weather(city: str) -> str:
            return f"{city} 的天气是晴天"

        # 检查 tool_info 属性
        if not hasattr(get_weather, "tool_info"):
            print("✗ 函数缺少 tool_info 属性")
            return False

        tool_info = get_weather.tool_info
        print(f"✓ tool_info 存在")
        print(f"✓ 工具名称: {tool_info['tool_name']}")
        print(f"✓ 工具描述: {tool_info['tool_description']}")
        print(f"✓ 参数数量: {len(tool_info['tool_params'])}")

        # 检查函数仍然可调用
        result = get_weather("北京")
        print(f"✓ 函数可调用: {result}")

        print("✓ @tool 装饰器使用测试通过")
        return True

    except Exception as e:
        print(f"✗ @tool 装饰器使用测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_tool_registration():
    """测试工具注册"""
    print("\n=== 测试 3: 工具注册 ===")
    try:
        from lightherrmes import LightHermes, tool
        from lightherrmes.core import ToolDispatcher

        @tool(
            name="test_tool",
            description="测试工具",
            params=[
                {"name": "arg1", "type": "string", "description": "参数1", "required": True}
            ]
        )
        def test_tool(arg1: str) -> str:
            return f"收到参数: {arg1}"

        # 创建 ToolDispatcher 并注册工具
        dispatcher = ToolDispatcher()
        success = dispatcher.register_tool(test_tool)

        if not success:
            print("✗ 工具注册失败")
            return False

        print(f"✓ 工具注册成功")
        print(f"✓ 已注册工具: {list(dispatcher.tools.keys())}")
        print(f"✓ 工具 schema 数量: {len(dispatcher.tool_schemas)}")

        # 测试工具调用
        result = dispatcher.call_tool("test_tool", {"arg1": "测试值"})
        print(f"✓ 工具调用成功: {result}")

        print("✓ 工具注册测试通过")
        return True

    except Exception as e:
        print(f"✗ 工具注册测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """运行所有测试"""
    print("╭─────────────────────────────────────╮")
    print("│  LightHermes @tool 装饰器测试       │")
    print("╰─────────────────────────────────────╯\n")

    tests = [
        test_tool_decorator_import,
        test_tool_decorator_usage,
        test_tool_registration,
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
