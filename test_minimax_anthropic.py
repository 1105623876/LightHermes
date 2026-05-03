"""
测试 LightHermes 的 Anthropic adapter 连接 MiniMax API
"""

import sys
import io
import os
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from lighthermes import LightHermes

# MiniMax 的 Anthropic 兼容端点
# 注意：Anthropic SDK 会自动添加 /v1/messages，所以这里不需要 /anthropic
API_KEY = os.environ.get("ANTHROPIC_API_KEY")
if not API_KEY:
    raise RuntimeError("请先设置 ANTHROPIC_API_KEY 环境变量")
BASE_URL = "https://api.minimaxi.com/anthropic/../anthropic"  # 绕过 SDK 自动添加的 /v1
MODEL = "claude-sonnet-4-6"  # MiniMax 使用 Claude 模型名

print("=== 测试 LightHermes + Anthropic Adapter + MiniMax API ===\n")

try:
    # 创建 LightHermes 实例，使用 Anthropic provider
    print("1. 初始化 LightHermes (provider=anthropic)...")
    agent = LightHermes(
        name="TestAgent",
        role="测试助手",
        model=MODEL,
        provider="anthropic",
        api_key=API_KEY,
        base_url=BASE_URL,
        memory_enabled=False,
        evolution_enabled=False,
        log_level="WARNING"
    )
    print(f"✓ 初始化成功")
    print(f"  Provider: {agent.provider}")
    print(f"  Model: {agent.model}")
    print(f"  Base URL: {BASE_URL}")

    # 测试非流式调用
    print("\n2. 测试非流式调用...")
    query = "你好，请用一句话介绍你自己"
    print(f"  查询: {query}")

    response = agent.run(query, stream=False)

    print(f"✓ API 调用成功")
    print(f"  响应: {response[:200]}...")

    # 测试流式调用
    print("\n3. 测试流式调用...")
    query2 = "1+1等于几？请简短回答"
    print(f"  查询: {query2}")

    response_stream = agent.run(query2, stream=True)

    print(f"  响应: ", end="")
    full_response = ""
    for chunk in response_stream:
        print(chunk, end="", flush=True)
        full_response += chunk
    print()

    print(f"✓ 流式调用成功")

    print("\n" + "="*50)
    print("✓ 所有测试通过！")
    print("✓ Anthropic adapter 可以正确连接 MiniMax API")

except Exception as e:
    print(f"\n✗ 测试失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)
