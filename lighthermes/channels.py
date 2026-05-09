"""
LightHermes 轻量消息通道边界
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class ChannelMessage:
    content: str
    user_id: str = "default_user"
    session_id: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class DirectChannel:
    """直接把通道消息交给 Agent 执行"""

    def send_to_agent(self, agent: Any, message: ChannelMessage, **kwargs):
        return agent.run(
            message.content,
            user_id=message.user_id,
            session_id=message.session_id,
            **kwargs
        )
