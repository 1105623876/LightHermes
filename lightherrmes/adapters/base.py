"""
BaseAdapter - 统一的 API 适配器接口
"""

from abc import ABC, abstractmethod
from typing import List, Dict, Any, Generator, Optional


class BaseAdapter(ABC):
    """API 适配器基类"""

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self.kwargs = kwargs

    @abstractmethod
    def create(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        stream: bool = False,
        **kwargs
    ) -> Any:
        """
        统一的 API 调用接口

        Args:
            messages: 消息列表 (OpenAI 格式)
            tools: 工具列表 (OpenAI 格式)
            stream: 是否流式输出
            **kwargs: 其他参数

        Returns:
            流式: Generator[str] (逐字符输出)
            非流式: 完整响应对象
        """
        pass
