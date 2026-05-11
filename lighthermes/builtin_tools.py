"""
LightHermes 内置工具
"""

import fnmatch
import json
from pathlib import Path
from typing import Callable, List

from lighthermes.tools import tool


EXCLUDED_DIRS = {".git", ".hg", ".svn", ".claude", "venv", ".venv", "node_modules", "__pycache__", "memory"}
SENSITIVE_PATTERNS = [".env", ".env.*", "*.pem", "*.key", "credentials*", "secrets*"]


class PathGuard:
    def __init__(self, roots):
        roots = roots or ["."]
        self.roots = [Path(root).resolve(strict=False) for root in roots]

    def resolve(self, path: str) -> Path:
        target = Path(path).expanduser()
        if not target.is_absolute():
            target = self.roots[0] / target
        resolved = target.resolve(strict=False)
        if not any(self._is_relative_to(resolved, root) for root in self.roots):
            raise ValueError("拒绝访问 root 外路径")
        self._reject_excluded_or_sensitive(resolved)
        return resolved

    def relative(self, path: Path) -> str:
        for root in self.roots:
            if self._is_relative_to(path, root):
                return path.relative_to(root).as_posix()
        return path.name

    def _reject_excluded_or_sensitive(self, path: Path):
        relative_parts = []
        for root in self.roots:
            if self._is_relative_to(path, root):
                relative_parts = path.relative_to(root).parts
                break
        if any(part in EXCLUDED_DIRS for part in relative_parts[:-1]):
            raise ValueError("拒绝访问排除目录")
        name = path.name
        if any(fnmatch.fnmatch(name, pattern) for pattern in SENSITIVE_PATTERNS):
            raise ValueError("拒绝访问敏感文件")

    @staticmethod
    def _is_relative_to(path: Path, root: Path) -> bool:
        try:
            path.relative_to(root)
            return True
        except ValueError:
            return False


def _is_binary(path: Path) -> bool:
    try:
        return b"\0" in path.read_bytes()[:1024]
    except OSError:
        return True


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


def create_file_tools(config: dict = None) -> List[Callable]:
    config = config or {}
    guard = PathGuard(config.get("roots") or ["."])
    max_read_chars = int(config.get("max_read_chars", 20000))
    max_write_chars = int(config.get("max_write_chars", 20000))
    max_search_results = int(config.get("max_search_results", 20))
    tools = []

    if config.get("file_read"):
        @tool(
            "read_file",
            "读取允许目录内的文本文件片段",
            [
                {"name": "path", "type": "string", "description": "文件路径", "required": True},
                {"name": "start_line", "type": "integer", "description": "起始行号，默认 1", "required": False},
                {"name": "max_lines", "type": "integer", "description": "最多读取行数，默认 200", "required": False},
            ]
        )
        def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> str:
            try:
                target = guard.resolve(path)
                if not target.is_file():
                    return "拒绝: 不是普通文件"
                if _is_binary(target):
                    return "拒绝: 二进制文件"
                text = target.read_text(encoding="utf-8")[:max_read_chars]
            except Exception as e:
                return f"拒绝: {e}"

            lines = text.splitlines()
            start = max(int(start_line or 1), 1)
            count = max(int(max_lines or 200), 1)
            selected = lines[start - 1:start - 1 + count]
            return "\n".join(f"{start + index}\t{line}" for index, line in enumerate(selected))

        tools.append(read_file)

    if config.get("file_search"):
        @tool(
            "search_files",
            "搜索允许目录内的文件名或文本内容",
            [
                {"name": "query", "type": "string", "description": "搜索关键词", "required": True},
                {"name": "directory", "type": "string", "description": "搜索目录，默认 .", "required": False},
                {"name": "glob", "type": "string", "description": "文件名 glob，默认 *", "required": False},
                {"name": "search_content", "type": "boolean", "description": "是否搜索文件内容", "required": False},
                {"name": "limit", "type": "integer", "description": "结果上限", "required": False},
            ]
        )
        def search_files(query: str, directory: str = ".", glob: str = "*", search_content: bool = False, limit: int = 20) -> str:
            safe_limit = max(1, min(int(limit or max_search_results), max_search_results))
            pattern = glob or "*"
            results = []
            try:
                root = guard.resolve(directory or ".")
            except Exception as e:
                return json.dumps({"query": query or "", "results": [], "error": f"拒绝: {e}"}, ensure_ascii=False)

            for path in root.rglob(pattern):
                if len(results) >= safe_limit:
                    break
                if any(part in EXCLUDED_DIRS for part in path.relative_to(root).parts[:-1]):
                    continue
                try:
                    target = guard.resolve(str(path))
                except Exception:
                    continue
                if not target.is_file() or _is_binary(target):
                    continue

                relative = guard.relative(target)
                if search_content:
                    try:
                        for line_number, line in enumerate(target.read_text(encoding="utf-8", errors="ignore").splitlines(), 1):
                            if query.lower() in line.lower():
                                results.append({"path": relative, "line": line_number, "snippet": line.strip()[:300]})
                                break
                    except OSError:
                        continue
                elif query.lower() in target.name.lower():
                    results.append({"path": relative, "line": None, "snippet": target.name})

            return json.dumps({"query": query or "", "results": results[:safe_limit]}, ensure_ascii=False)

        tools.append(search_files)

    if config.get("file_write"):
        @tool(
            "write_file",
            "写入允许目录内的文本文件，默认关闭",
            [
                {"name": "path", "type": "string", "description": "文件路径", "required": True},
                {"name": "content", "type": "string", "description": "写入内容", "required": True},
                {"name": "mode", "type": "string", "description": "create、overwrite 或 append", "required": True},
            ]
        )
        def write_file(path: str, content: str, mode: str = "create") -> str:
            try:
                if mode not in {"create", "overwrite", "append"}:
                    return "拒绝: mode 只允许 create、overwrite、append"
                if len(content or "") > max_write_chars:
                    return "拒绝: 内容超过最大字符数"
                target = guard.resolve(path)
                if not target.parent.exists():
                    return "拒绝: 父目录不存在"
                if mode == "create" and target.exists():
                    return "拒绝: create 模式不覆盖已有文件"
                if mode in {"overwrite", "append"} and not target.exists():
                    return "拒绝: 目标文件不存在"
                if target.exists() and (not target.is_file() or _is_binary(target)):
                    return "拒绝: 目标不是可写文本文件"

                if mode == "append":
                    target.write_text(target.read_text(encoding="utf-8") + (content or ""), encoding="utf-8")
                else:
                    target.write_text(content or "", encoding="utf-8")
            except Exception as e:
                return f"拒绝: {e}"

            return json.dumps({
                "path": guard.relative(target),
                "mode": mode,
                "written_chars": len(content or ""),
            }, ensure_ascii=False)

        tools.append(write_file)

    return tools
