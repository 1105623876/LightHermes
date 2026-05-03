"""上下文压缩系统单元测试"""

import pytest

from lighthermes.compressor import ContextCompressor, estimate_tokens


class FakeResponse:
    def __init__(self, content):
        class Message:
            def __init__(self, text):
                self.content = text

        class Choice:
            def __init__(self, text):
                self.message = Message(text)

        self.choices = [Choice(content)]


class FakeAdapter:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.unit
class TestContextCompressor:
    """测试上下文压缩器"""

    def test_should_compress_respects_threshold(self):
        compressor = ContextCompressor(
            FakeAdapter("摘要"),
            {"trigger_threshold": 0.5}
        )
        messages = [{"role": "user", "content": "x" * 100}]

        assert compressor.should_compress(messages, context_window=40) is True
        assert compressor.should_compress(messages, context_window=1000) is False

    def test_prune_tool_outputs_keeps_tool_name(self):
        compressor = ContextCompressor(FakeAdapter("摘要"))
        messages = [
            {"role": "user", "content": "查询天气"},
            {"role": "tool", "name": "weather", "content": "大量输出"}
        ]

        pruned = compressor._prune_tool_outputs(messages)

        assert pruned[0] == messages[0]
        assert pruned[1] == {
            "role": "tool",
            "name": "weather",
            "content": "[Tool output pruned: weather]"
        }

    def test_compress_summarizes_middle_messages(self):
        adapter = FakeAdapter(FakeResponse("保留关键结论"))
        compressor = ContextCompressor(
            adapter,
            {
                "protect_first_n": 1,
                "protect_recent_tokens": 1,
                "summary_min_tokens": 10,
                "summary_max_tokens": 50,
                "summary_ratio": 0.5
            }
        )
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "中间消息一"},
            {"role": "assistant", "content": "中间消息二"},
            {"role": "user", "content": "最近消息"}
        ]

        compressed = compressor.compress(messages)

        assert compressed[0] == messages[0]
        assert compressed[1]["role"] == "assistant"
        assert compressed[1]["content"].startswith("[CONTEXT COMPACTION")
        assert "保留关键结论" in compressed[1]["content"]
        assert compressor.compression_count == 1
        assert adapter.calls[0]["model"] == "gpt-4o-mini"
        assert adapter.calls[0]["stream"] is False

    def test_summarize_falls_back_when_adapter_fails(self):
        compressor = ContextCompressor(FakeAdapter(RuntimeError("boom")))

        summary = compressor._summarize([
            {"role": "user", "content": "需要总结"}
        ])

        assert summary["role"] == "assistant"
        assert "摘要生成失败: boom" in summary["content"]

    def test_get_stats_returns_average_saved_tokens(self):
        compressor = ContextCompressor(FakeAdapter("摘要"))
        compressor.compression_count = 2
        compressor.tokens_saved = 9

        stats = compressor.get_stats()

        assert stats == {
            "compression_count": 2,
            "tokens_saved": 9,
            "avg_tokens_saved": 4
        }

    def test_estimate_tokens_uses_simple_character_ratio(self):
        assert estimate_tokens("x" * 12) == 3
