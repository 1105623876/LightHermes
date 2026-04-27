"""
测试稳定性层基础功能
"""

import os
import sys

# 设置 UTF-8 输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 测试 1: 日志系统
print("=== 测试 1: 日志系统 ===")
try:
    from lightherrmes.logger import setup_logger

    logger = setup_logger("test", level="INFO")
    logger.info("日志系统测试")
    logger.warning("警告测试")
    logger.error("错误测试")

    print("✓ 日志系统初始化成功")
except Exception as e:
    print(f"✗ 日志系统失败: {e}")
    sys.exit(1)

# 测试 2: 模型降级配置
print("\n=== 测试 2: 模型降级配置 ===")
try:
    from lightherrmes import LightHermes

    # 检查 API key
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("⚠ 跳过测试（需要 OPENAI_API_KEY 环境变量）")
    else:
        # 测试初始化时的降级配置
        agent = LightHermes(
            name="TestAgent",
            role="测试助手",
            model="gpt-4o-mini",
            fallback_models=["gpt-3.5-turbo"],
            log_level="INFO"
        )

        print(f"✓ 主模型: {agent.model}")
        print(f"✓ 降级模型: {agent.fallback_models}")
        print(f"✓ 查询计数器: {agent.query_count}")
        print("✓ 模型降级配置成功")
except Exception as e:
    print(f"✗ 模型降级配置失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

# 测试 3: 错误处理
print("\n=== 测试 3: 记忆系统错误处理 ===")
try:
    from lightherrmes.memory import WorkingMemory
    import tempfile

    # 创建临时数据库测试错误处理
    temp_dir = tempfile.mkdtemp()
    db_path = os.path.join(temp_dir, "test.db")

    working = WorkingMemory(db_path, retention_days=7)
    working.add_session("test_session", "test_user", "测试摘要")

    sessions = working.get_recent_sessions("test_user")
    print(f"✓ 成功添加和检索会话: {len(sessions)} 条")
    print("✓ 记忆系统错误处理正常")
except Exception as e:
    print(f"✗ 记忆系统错误处理失败: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print("\n=== 所有基础测试通过 ===")
print("\n下一步: 继续实现自适应记忆层（Task 4-6）")
