"""
LightHermes 内置工具
"""

import json
from typing import Callable, List

from lighthermes.tools import tool


def create_memory_tools(memory_manager) -> List[Callable]:
    @tool(
        "search_memory",
        "搜索 LightHermes 持久记忆",
        [
            {"name": "query", "type": "string", "description": "搜索关键词，可为空以列出指定层级记忆", "required": True},
            {"name": "layer", "type": "string", "description": "记忆层级：all、working、episodic、semantic", "required": False},
            {"name": "limit", "type": "integer", "description": "返回数量上限，最大 10", "required": False},
        ]
    )
    def search_memory(query: str, layer: str = "all", limit: int = 5) -> str:
        safe_limit = max(1, min(int(limit or 5), 10))
        safe_layer = layer if layer in {"all", "working", "episodic", "semantic"} else "all"
        results = memory_manager.search_memory(
            query or "",
            layer=safe_layer,
            limit=safe_limit,
            include_metadata=True
        )
        payload = {
            "query": query or "",
            "layer": safe_layer,
            "limit": safe_limit,
            "results": [
                {
                    "layer": item.get("layer", ""),
                    "name": item.get("name", ""),
                    "content": item.get("content", "")[:500],
                    "score": item.get("score", 0),
                    "source": item.get("source", ""),
                    "metadata": item.get("metadata", {}),
                }
                for item in results
            ]
        }
        return json.dumps(payload, ensure_ascii=False)

    return [search_memory]
