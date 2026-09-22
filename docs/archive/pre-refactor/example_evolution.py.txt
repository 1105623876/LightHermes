"""
LightHermes 自进化系统测试示例
"""

from lighthermes import LightHermes
import time

def test_evolution():
    """测试自进化功能"""

    agent = LightHermes(
        name="EvolutionAgent",
        model="gpt-4o-mini",
        api_key="your_api_key_here",  # 替换为你的 API key
        evolution_enabled=True,
        auto_generate_skills=True,
        debug=True
    )

    # 模拟多次相似任务,触发模式识别
    print("=== 第一次调试任务 ===")
    agent.run("帮我调试这个 Python 函数的错误", user_id="user1")

    time.sleep(1)

    print("\n=== 第二次调试任务 ===")
    agent.run("这段代码报错了,帮我看看", user_id="user1")

    time.sleep(1)

    print("\n=== 第三次调试任务 ===")
    agent.run("为什么这个测试失败了?", user_id="user1")

    # 手动触发自进化
    print("\n=== 触发自进化 ===")
    if agent.evolution:
        results = agent.evolution.evolve()
        print(f"生成的技能: {results}")
    else:
        print("自进化系统未启用")


if __name__ == "__main__":
    print("提示: 设置你的 API key 后运行此示例")
    print("自进化系统会在多次相似任务后自动生成新技能\n")
    # test_evolution()
