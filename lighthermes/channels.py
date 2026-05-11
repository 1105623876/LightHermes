"""
LightHermes 轻量消息通道边界
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


class BaseChannel:
    """通道抽象基类"""

    def __init__(self, name: str):
        self.name = name

    def send(self, message: "ChannelMessage") -> None:
        raise NotImplementedError

    def receive(self) -> Optional["ChannelMessage"]:
        raise NotImplementedError


@dataclass
class ChannelMessage:
    content: str
    user_id: str = "default_user"
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DirectChannel(BaseChannel):
    """直接把通道消息交给 Agent 执行"""

    def __init__(self, name: str = "direct"):
        super().__init__(name)

    def send(self, message: ChannelMessage) -> None:
        return None

    def receive(self) -> Optional[ChannelMessage]:
        return None

    def send_to_agent(self, agent: Any, message: ChannelMessage, **kwargs):
        return agent.run(
            message.content,
            user_id=message.user_id,
            session_id=message.session_id,
            **kwargs
        )


class ChannelRegistry:
    """轻量通道注册表"""

    def __init__(self):
        self.channels: Dict[str, BaseChannel] = {}

    def register(self, channel: BaseChannel) -> bool:
        name = getattr(channel, "name", None)
        if not name:
            return False

        self.channels[name] = channel
        return True

    def get(self, name: str) -> Optional[BaseChannel]:
        return self.channels.get(name)

    def list_channels(self) -> list[str]:
        return sorted(self.channels.keys())
