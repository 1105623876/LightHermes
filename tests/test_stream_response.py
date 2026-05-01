"""测试流式响应处理逻辑"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from lighthermes.adapters.anthropic_adapter import AnthropicAdapter


class MockEvent:
    """模拟流式响应事件"""
    def __init__(self, event_type, text=None):
        self.type = event_type
        if text is not None:
            self.delta = MockDelta(text)


class MockDelta:
    """模拟 delta 对象"""
    def __init__(self, text):
        self.text = text


def test_standard_anthropic_stream():
    """测试标准 Anthropic 流式响应（增量文本）"""
    print("测试标准 Anthropic 流式响应...")

    adapter = AnthropicAdapter(model="claude-sonnet-4-6", api_key="test")

    # 模拟标准 Anthropic 流式响应（每次返回增量文本）
    mock_events = [
        MockEvent("content_block_delta", "Hello"),
        MockEvent("content_block_delta", " "),
        MockEvent("content_block_delta", "world"),
        MockEvent("content_block_delta", "!"),
    ]

    result = []
    for chunk in adapter._handle_stream(iter(mock_events)):
        result.append(chunk.choices[0].delta.content)

    full_text = "".join(result)
    expected = "Hello world!"

    assert full_text == expected, f"期望 '{expected}'，实际 '{full_text}'"
    print(f"[PASS] 标准流式响应测试通过: '{full_text}'")


def test_minimax_cumulative_stream():
    """测试 MiniMax 流式响应（累积文本）"""
    print("\n测试 MiniMax 流式响应（累积文本）...")

    adapter = AnthropicAdapter(model="claude-sonnet-4-6", api_key="test")

    # 模拟 MiniMax 流式响应（每次返回累积文本）
    mock_events = [
        MockEvent("content_block_delta", "Hello"),
        MockEvent("content_block_delta", "Hello "),
        MockEvent("content_block_delta", "Hello world"),
        MockEvent("content_block_delta", "Hello world!"),
    ]

    result = []
    for chunk in adapter._handle_stream(iter(mock_events)):
        result.append(chunk.choices[0].delta.content)

    full_text = "".join(result)
    expected = "Hello world!"

    assert full_text == expected, f"期望 '{expected}'，实际 '{full_text}'"
    print(f"[PASS] MiniMax 累积文本测试通过: '{full_text}'")
    print(f"  增量输出: {result}")


def test_mixed_stream():
    """测试混合模式（部分累积，部分增量）"""
    print("\n测试混合模式流式响应...")

    adapter = AnthropicAdapter(model="claude-sonnet-4-6", api_key="test")

    # 模拟混合模式（可能出现的边缘情况）
    mock_events = [
        MockEvent("content_block_delta", "Hello"),
        MockEvent("content_block_delta", "Hello world"),  # 累积
        MockEvent("content_block_delta", "!"),  # 增量
    ]

    result = []
    for chunk in adapter._handle_stream(iter(mock_events)):
        result.append(chunk.choices[0].delta.content)

    full_text = "".join(result)
    expected = "Hello world!"

    assert full_text == expected, f"期望 '{expected}'，实际 '{full_text}'"
    print(f"[PASS] 混合模式测试通过: '{full_text}'")
    print(f"  增量输出: {result}")


def test_empty_deltas():
    """测试空增量（边缘情况）"""
    print("\n测试空增量处理...")

    adapter = AnthropicAdapter(model="claude-sonnet-4-6", api_key="test")

    mock_events = [
        MockEvent("content_block_delta", "Hello"),
        MockEvent("content_block_delta", "Hello"),  # 重复，应该被过滤
        MockEvent("content_block_delta", "Hello world"),
    ]

    result = []
    for chunk in adapter._handle_stream(iter(mock_events)):
        result.append(chunk.choices[0].delta.content)

    full_text = "".join(result)
    expected = "Hello world"

    assert full_text == expected, f"期望 '{expected}'，实际 '{full_text}'"
    print(f"[PASS] 空增量测试通过: '{full_text}'")


def test_unicode_stream():
    """测试 Unicode 字符处理"""
    print("\n测试 Unicode 字符处理...")

    adapter = AnthropicAdapter(model="claude-sonnet-4-6", api_key="test")

    # 模拟包含中文的累积文本
    mock_events = [
        MockEvent("content_block_delta", "你好"),
        MockEvent("content_block_delta", "你好世界"),
        MockEvent("content_block_delta", "你好世界！"),
    ]

    result = []
    for chunk in adapter._handle_stream(iter(mock_events)):
        result.append(chunk.choices[0].delta.content)

    full_text = "".join(result)
    expected = "你好世界！"

    assert full_text == expected, f"期望 '{expected}'，实际 '{full_text}'"
    print(f"[PASS] Unicode 测试通过: '{full_text}'")


if __name__ == "__main__":
    print("=" * 60)
    print("流式响应处理测试")
    print("=" * 60)

    try:
        test_standard_anthropic_stream()
        test_minimax_cumulative_stream()
        test_mixed_stream()
        test_empty_deltas()
        test_unicode_stream()

        print("\n" + "=" * 60)
        print("所有测试通过！")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n测试失败: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n测试出错: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
