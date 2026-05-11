"""轻量通道注册表测试"""

import pytest

from lighthermes.channels import ChannelMessage, ChannelRegistry, DirectChannel


@pytest.mark.unit
class TestChannelRegistry:
    def test_register_and_get_channel(self):
        registry = ChannelRegistry()
        channel = DirectChannel(name="local_debug")

        registry.register(channel)

        assert registry.get("local_debug") is channel
        assert registry.list_channels() == ["local_debug"]

    def test_register_overwrites_same_name(self):
        registry = ChannelRegistry()
        old_channel = DirectChannel(name="local_debug")
        new_channel = DirectChannel(name="local_debug")

        registry.register(old_channel)
        registry.register(new_channel)

        assert registry.get("local_debug") is new_channel
        assert registry.list_channels() == ["local_debug"]

    def test_register_rejects_non_channel_object(self):
        class NotAChannel:
            name = "not_channel"

        registry = ChannelRegistry()

        assert registry.register(NotAChannel()) is False
        assert registry.get("not_channel") is None

    def test_direct_channel_send_to_agent_uses_message_identity(self):
        class FakeAgent:
            def run(self, content, **kwargs):
                return {"content": content, "kwargs": kwargs}

        channel = DirectChannel(name="direct")
        message = ChannelMessage(content="hello", user_id="u1", session_id="s1")

        result = channel.send_to_agent(FakeAgent(), message, stream=False)

        assert result == {
            "content": "hello",
            "kwargs": {"user_id": "u1", "session_id": "s1", "stream": False},
        }
