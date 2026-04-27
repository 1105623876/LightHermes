"""
LightHermes 四级记忆系统

实现短期、工作、情景、语义四层记忆管理
"""

import json
import os
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any, Optional
import re

from lightherrmes.logger import setup_logger


class ShortTermMemory:
    """短期记忆 - 当前会话的上下文"""

    def __init__(self, max_turns: int = 50):
        self.max_turns = max_turns
        self.messages: List[Dict[str, str]] = []

    def add(self, role: str, content: str):
        """添加消息到短期记忆"""
        self.messages.append({"role": role, "content": content})
        if len(self.messages) > self.max_turns * 2:
            self.messages = self.messages[-self.max_turns * 2:]

    def get_messages(self) -> List[Dict[str, str]]:
        """获取所有消息"""
        return self.messages.copy()

    def clear(self):
        """清空短期记忆"""
        self.messages.clear()


class WorkingMemory:
    """工作记忆 - 近期会话的摘要"""

    def __init__(self, db_path: str, retention_days: int = 7):
        self.db_path = db_path
        self.retention_days = retention_days
        self._init_db()

    def _init_db(self):
        """初始化数据库"""
        try:
            os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    summary TEXT,
                    timestamp TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger = setup_logger("lightherrmes.memory")
            logger.error(f"初始化工作记忆数据库失败: {e}")
            raise

    def add_session(self, session_id: str, user_id: str, summary: str):
        """添加会话摘要"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                INSERT OR REPLACE INTO sessions (session_id, user_id, summary, timestamp)
                VALUES (?, ?, ?, ?)
            """, (session_id, user_id, summary, datetime.now().isoformat()))
            conn.commit()
            conn.close()
            self._cleanup_old_sessions()
        except Exception as e:
            logger = setup_logger("lightherrmes.memory")
            logger.error(f"添加会话摘要失败: {e}")

    def get_recent_sessions(self, user_id: str, limit: int = 20) -> List[Dict[str, Any]]:
        """获取最近的会话摘要"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("""
            SELECT session_id, summary, timestamp
            FROM sessions
            WHERE user_id = ?
            ORDER BY timestamp DESC
            LIMIT ?
        """, (user_id, limit))
        results = cursor.fetchall()
        conn.close()

        return [
            {"session_id": r[0], "summary": r[1], "timestamp": r[2]}
            for r in results
        ]

    def _cleanup_old_sessions(self):
        """清理过期的会话"""
        cutoff = (datetime.now() - timedelta(days=self.retention_days)).isoformat()
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM sessions WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()


class EpisodicMemory:
    """情景记忆 - 项目/任务相关的记忆"""

    def __init__(self, storage_dir: str):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

    def save(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存情景记忆"""
        metadata = metadata or {}
        metadata.setdefault("type", "episodic")
        metadata.setdefault("status", "active")
        metadata.setdefault("created", datetime.now().strftime("%Y-%m-%d"))

        frontmatter = "---\n"
        for key, value in metadata.items():
            frontmatter += f"{key}: {value}\n"
        frontmatter += "---\n\n"

        file_path = self.storage_dir / f"{name}.md"
        file_path.write_text(frontmatter + content, encoding="utf-8")

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """加载情景记忆"""
        file_path = self.storage_dir / f"{name}.md"
        if not file_path.exists():
            return None

        content = file_path.read_text(encoding="utf-8")
        return self._parse_memory(content)

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索情景记忆"""
        results = []
        query_lower = query.lower()

        for file_path in self.storage_dir.glob("*.md"):
            content = file_path.read_text(encoding="utf-8")
            memory = self._parse_memory(content)

            if memory and query_lower in memory["content"].lower():
                memory["name"] = file_path.stem
                results.append(memory)

        return results[:limit]

    def _parse_memory(self, content: str) -> Optional[Dict[str, Any]]:
        """解析记忆文件"""
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        metadata = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        return {
            "metadata": metadata,
            "content": parts[2].strip()
        }


class SemanticMemory:
    """语义记忆 - 抽象知识和用户偏好"""

    def __init__(self, storage_dir: str, max_entries: int = 1000, use_hybrid_retrieval: bool = False,
                 embedding_provider: str = "openai", embedding_model: str = "text-embedding-3-small", api_key: str = None):
        self.storage_dir = Path(storage_dir)
        self.max_entries = max_entries
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        if use_hybrid_retrieval:
            try:
                from lightherrmes.retrieval import HybridRetriever
                self.hybrid_retriever = HybridRetriever(
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    api_key=api_key
                )
            except ImportError:
                print("混合检索不可用,使用简单关键词匹配")
                self.hybrid_retriever = None
        else:
            self.hybrid_retriever = None

    def save(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存语义记忆"""
        metadata = metadata or {}
        metadata.setdefault("type", "semantic")
        metadata.setdefault("created", datetime.now().strftime("%Y-%m-%d"))

        frontmatter = "---\n"
        for key, value in metadata.items():
            frontmatter += f"{key}: {value}\n"
        frontmatter += "---\n\n"

        file_path = self.storage_dir / f"{name}.md"
        file_path.write_text(frontmatter + content, encoding="utf-8")

        self._cleanup_if_needed()

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """加载语义记忆"""
        file_path = self.storage_dir / f"{name}.md"
        if not file_path.exists():
            return None

        content = file_path.read_text(encoding="utf-8")
        return self._parse_memory(content)

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索语义记忆 - 自动选择最佳检索方式"""
        # 如果启用了混合检索,使用混合检索
        if hasattr(self, 'hybrid_retriever') and self.hybrid_retriever:
            documents = []
            for file_path in self.storage_dir.glob("*.md"):
                content = file_path.read_text(encoding="utf-8")
                memory = self._parse_memory(content)
                if memory:
                    memory["name"] = file_path.stem
                    documents.append(memory)

            if documents:
                try:
                    self.hybrid_retriever.index_documents(documents)
                    return self.hybrid_retriever.search(query, top_k=limit)
                except Exception as e:
                    print(f"混合检索失败,回退到关键词匹配: {e}")

        # 默认使用简单关键词匹配
        results = []
        query_lower = query.lower()
        query_words = set(query_lower.split())

        for file_path in self.storage_dir.glob("*.md"):
            content = file_path.read_text(encoding="utf-8")
            memory = self._parse_memory(content)

            if memory:
                content_lower = memory["content"].lower()
                content_words = set(content_lower.split())

                matches = len(query_words & content_words)
                if matches > 0:
                    memory["name"] = file_path.stem
                    memory["score"] = matches
                    results.append(memory)

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

    def _parse_memory(self, content: str) -> Optional[Dict[str, Any]]:
        """解析记忆文件"""
        if not content.startswith("---"):
            return None

        parts = content.split("---", 2)
        if len(parts) < 3:
            return None

        metadata = {}
        for line in parts[1].strip().split("\n"):
            if ":" in line:
                key, value = line.split(":", 1)
                metadata[key.strip()] = value.strip()

        return {
            "metadata": metadata,
            "content": parts[2].strip()
        }

    def _cleanup_if_needed(self):
        """清理过多的记忆条目"""
        files = list(self.storage_dir.glob("*.md"))
        if len(files) > self.max_entries:
            # 按修改时间排序,删除最旧的
            files.sort(key=lambda f: f.stat().st_mtime)
            for f in files[:len(files) - self.max_entries]:
                f.unlink()


class MemoryManager:
    """四级记忆管理器"""

    def __init__(
        self,
        memory_dir: str = "memory",
        short_term_turns: int = 50,
        working_memory_days: int = 7,
        semantic_max_entries: int = 1000,
        use_hybrid_retrieval: bool = False,
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-small",
        api_key: str = None
    ):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        # 初始化四级记忆
        self.short_term = ShortTermMemory(max_turns=short_term_turns)
        self.working = WorkingMemory(
            db_path=str(self.memory_dir / "working.db"),
            retention_days=working_memory_days
        )
        self.episodic = EpisodicMemory(
            storage_dir=str(self.memory_dir / "episodic")
        )
        self.semantic = SemanticMemory(
            storage_dir=str(self.memory_dir / "semantic"),
            max_entries=semantic_max_entries,
            use_hybrid_retrieval=use_hybrid_retrieval,
            embedding_provider=embedding_provider,
            embedding_model=embedding_model,
            api_key=api_key
        )

    def add_message(self, role: str, content: str):
        """添加消息到短期记忆"""
        self.short_term.add(role, content)

    def get_context(self) -> List[Dict[str, str]]:
        """获取当前上下文(短期记忆)"""
        return self.short_term.get_messages()

    def save_session(self, session_id: str, user_id: str, summary: str):
        """保存会话摘要到工作记忆"""
        self.working.add_session(session_id, user_id, summary)

    def recall(self, query: str, user_id: str = "default") -> str:
        """召回相关记忆"""
        context_parts = []

        # 1. 从工作记忆中召回最近的会话
        recent_sessions = self.working.get_recent_sessions(user_id, limit=3)
        if recent_sessions:
            context_parts.append("## 最近的对话")
            for session in recent_sessions[:2]:
                context_parts.append(f"- {session['summary']}")

        # 2. 从情景记忆中召回相关项目/任务
        episodic_results = self.episodic.search(query, limit=2)
        if episodic_results:
            context_parts.append("\n## 相关项目/任务")
            for memory in episodic_results:
                name = memory.get("name", "unknown")
                content = memory["content"][:200]
                context_parts.append(f"- {name}: {content}...")

        # 3. 从语义记忆中召回相关知识
        semantic_results = self.semantic.search(query, limit=3)
        if semantic_results:
            context_parts.append("\n## 相关知识")
            for memory in semantic_results:
                name = memory.get("name", "unknown")
                content = memory["content"][:150]
                context_parts.append(f"- {name}: {content}...")

        return "\n".join(context_parts) if context_parts else ""

    def save_episodic(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存情景记忆"""
        self.episodic.save(name, content, metadata)

    def save_semantic(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存语义记忆"""
        self.semantic.save(name, content, metadata)

    def clear_short_term(self):
        """清空短期记忆"""
        self.short_term.clear()
