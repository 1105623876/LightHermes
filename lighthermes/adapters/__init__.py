"""
LightHermes API 适配器
自动检测 provider 并返回对应的 adapter
"""

from typing import Optional
from .base import BaseAdapter
from .openai_adapter import OpenAIAdapter
from .anthropic_adapter import AnthropicAdapter


def get_adapter(
    provider: str,
    model: str,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    **kwargs
) -> BaseAdapter:
    """
    根据 provider 返回对应的 adapter

    Args:
        provider: "openai" 或 "anthropic"
        model: 模型名称
        api_key: API key
        base_url: API base URL
        **kwargs: 其他参数

    Returns:
        对应的 adapter 实例
    """
    if provider == "openai":
        return OpenAIAdapter(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )
    elif provider == "anthropic":
        return AnthropicAdapter(
            model=model,
            api_key=api_key,
            base_url=base_url,
            **kwargs
        )
    else:
        raise ValueError(f"不支持的 provider: {provider}")


__all__ = ["BaseAdapter", "OpenAIAdapter", "AnthropicAdapter", "get_adapter"]
