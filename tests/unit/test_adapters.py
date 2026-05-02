"""Adapter 单元测试"""
import pytest
from lighthermes.adapters import get_adapter
from lighthermes.adapters.openai_adapter import OpenAIAdapter
from lighthermes.adapters.anthropic_adapter import AnthropicAdapter


@pytest.mark.unit
class TestAdapterFactory:
    """测试 Adapter 工厂"""

    def test_get_openai_adapter(self, mock_api_key):
        """测试获取 OpenAI adapter"""
        adapter = get_adapter(
            provider="openai",
            model="gpt-4o-mini",
            api_key=mock_api_key
        )
        assert isinstance(adapter, OpenAIAdapter)
        assert adapter.model == "gpt-4o-mini"

    def test_get_anthropic_adapter(self, mock_api_key):
        """测试获取 Anthropic adapter"""
        adapter = get_adapter(
            provider="anthropic",
            model="claude-sonnet-4-6",
            api_key=mock_api_key
        )
        assert isinstance(adapter, AnthropicAdapter)
        assert adapter.model == "claude-sonnet-4-6"

    def test_invalid_provider(self, mock_api_key):
        """测试无效的 provider"""
        with pytest.raises(ValueError, match="Unsupported provider"):
            get_adapter(
                provider="invalid_provider",
                model="test-model",
                api_key=mock_api_key
            )


@pytest.mark.unit
class TestOpenAIAdapter:
    """测试 OpenAI Adapter"""

    def test_initialization(self, mock_api_key):
        """测试初始化"""
        adapter = OpenAIAdapter(
            model="gpt-4o-mini",
            api_key=mock_api_key
        )
        assert adapter.model == "gpt-4o-mini"
        assert adapter.client is not None

    def test_custom_base_url(self, mock_api_key):
        """测试自定义 base_url"""
        custom_url = "https://custom.api.com/v1"
        adapter = OpenAIAdapter(
            model="gpt-4o-mini",
            api_key=mock_api_key,
            base_url=custom_url
        )
        assert adapter.client.base_url == custom_url


@pytest.mark.unit
class TestAnthropicAdapter:
    """测试 Anthropic Adapter"""

    def test_initialization(self, mock_api_key):
        """测试初始化"""
        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6",
            api_key=mock_api_key
        )
        assert adapter.model == "claude-sonnet-4-6"
        assert adapter.client is not None

    def test_stream_handling(self, mock_api_key):
        """测试流式响应处理"""
        adapter = AnthropicAdapter(
            model="claude-sonnet-4-6",
            api_key=mock_api_key
        )

        # 模拟流式事件
        class MockEvent:
            def __init__(self, event_type, text=None):
                self.type = event_type
                if text is not None:
                    self.delta = MockDelta(text)

        class MockDelta:
            def __init__(self, text):
                self.text = text

        # 测试累积文本处理
        events = [
            MockEvent("content_block_delta", "Hello"),
            MockEvent("content_block_delta", "Hello world"),
            MockEvent("content_block_delta", "Hello world!"),
        ]

        result = []
        for chunk in adapter._handle_stream(iter(events)):
            result.append(chunk.choices[0].delta.content)

        assert "".join(result) == "Hello world!"
