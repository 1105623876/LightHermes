"""
LightHermes 生命周期钩子安全调用边界
"""

from typing import Any


def call_hook_safely(target: Any, hook_name: str, logger: Any, warning_prefix: str, *args, **kwargs):
    """调用钩子并隔离异常"""
    try:
        method = getattr(target, hook_name)
        return method(*args, **kwargs)
    except Exception as e:
        logger.warning(f"{warning_prefix} {hook_name} 执行失败: {e}")
        return None
