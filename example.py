"""
LightHermes 基础使用示例
"""

from lightherrmes import LightHermes

# 示例 1: 基础对话
def example_basic():
    agent = LightHermes(
        name="MyAgent",
        role="你是一个有用的编程助手",
        model="gpt-4o-mini",
        api_key="your_api_key_here"  # 替换为你的 API key
    )

    response = agent.run("你好,请介绍一下你自己")
    print(response)


# 示例 2: 使用技能
def example_with_skill():
    agent = LightHermes(
        name="CodeHelper",
        model="gpt-4o-mini",
        api_key="your_api_key_here"
    )

    # 这个查询会匹配 explain_code_pattern 技能
    response = agent.run("请解释一下单例模式")
    print(response)


# 示例 3: 流式输出
def example_stream():
    agent = LightHermes(
        name="StreamAgent",
        model="gpt-4o-mini",
        api_key="your_api_key_here"
    )

    print("Agent: ", end="", flush=True)
    for chunk in agent.run("写一个 Python 快速排序", stream=True):
        print(chunk, end="", flush=True)
    print()


if __name__ == "__main__":
    print("=== 示例 1: 基础对话 ===")
    # example_basic()

    print("\n=== 示例 2: 使用技能 ===")
    # example_with_skill()

    print("\n=== 示例 3: 流式输出 ===")
    # example_stream()

    print("\n提示: 取消注释上面的函数调用并设置你的 API key 来运行示例")
    print("或者直接运行: python -m lightherrmes.cli")
