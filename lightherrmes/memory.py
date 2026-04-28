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


class MemoryStats:
    """记忆统计 - 追踪各层级命中率"""

    def __init__(self, stats_file: str):
        self.stats_file = stats_file
        self.stats = self._load_stats()

    def _load_stats(self) -> Dict[str, Dict[str, float]]:
        if not os.path.exists(self.stats_file):
            return {}
        try:
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return {}

    def _save_stats(self):
        try:
            os.makedirs(os.path.dirname(self.stats_file), exist_ok=True)
            with open(self.stats_file, 'w', encoding='utf-8') as f:
                json.dump(self.stats, f, indent=2)
        except Exception as e:
            logger = setup_logger("lightherrmes.memory")
            logger.error(f"保存统计数据失败: {e}")

    def record_hit(self, layer: str, hit_count: int, query_time: float):
        if layer not in self.stats:
            self.stats[layer] = {"hits": 0, "queries": 0, "total_time": 0.0}

        self.stats[layer]["queries"] += 1
        self.stats[layer]["hits"] += hit_count
        self.stats[layer]["total_time"] += query_time

        self._save_stats()

    def get_hit_rate(self, layer: str) -> float:
        if layer not in self.stats or self.stats[layer]["queries"] == 0:
            return 0.0
        return self.stats[layer]["hits"] / self.stats[layer]["queries"]

    def get_all_stats(self) -> Dict[str, Dict[str, float]]:
        return self.stats.copy()


class MemoryIndex:
    """内存倒排索引 - 加速关键词检索"""

    def __init__(self, index_file: str):
        self.index_file = index_file
        self.inverted_index: Dict[str, set] = {}
        self._load_index()

    def _load_index(self):
        """从文件加载索引"""
        if not os.path.exists(self.index_file):
            return
        try:
            with open(self.index_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # 将列表转换回集合
                self.inverted_index = {k: set(v) for k, v in data.items()}
        except Exception:
            self.inverted_index = {}

    def _save_index(self):
        """保存索引到文件"""
        try:
            os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
            # 将集合转换为列表以便 JSON 序列化
            data = {k: list(v) for k, v in self.inverted_index.items()}
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger = setup_logger("lightherrmes.memory")
            logger.error(f"保存索引失败: {e}")

    def add(self, name: str, content: str):
        """添加文档到索引"""
        # 简单分词：转小写 + 按空格分割
        words = set(content.lower().split())
        for word in words:
            if len(word) > 1:  # 过滤单字符
                if word not in self.inverted_index:
                    self.inverted_index[word] = set()
                self.inverted_index[word].add(name)
        self._save_index()

    def remove(self, name: str):
        """从索引中移除文档"""
        for word in list(self.inverted_index.keys()):
            if name in self.inverted_index[word]:
                self.inverted_index[word].discard(name)
                if not self.inverted_index[word]:
                    del self.inverted_index[word]
        self._save_index()

    def search(self, query_words: List[str]) -> set:
        """搜索包含所有查询词的文档（交集）"""
        if not query_words:
            return set()

        # 转小写
        query_words = [w.lower() for w in query_words if len(w) > 1]
        if not query_words:
            return set()

        # 获取每个词的文档集合
        results = []
        for word in query_words:
            if word in self.inverted_index:
                results.append(self.inverted_index[word])
            else:
                return set()  # 如果有词不存在，返回空集

        # 返回交集
        return set.intersection(*results) if results else set()


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

        # 初始化索引
        index_file = str(Path(storage_dir).parent / "episodic_index.json")
        self.index = MemoryIndex(index_file)

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

        # 更新索引
        self.index.add(name, content)

    def load(self, name: str) -> Optional[Dict[str, Any]]:
        """加载情景记忆"""
        file_path = self.storage_dir / f"{name}.md"
        if not file_path.exists():
            return None

        content = file_path.read_text(encoding="utf-8")
        return self._parse_memory(content)

    def search(self, query: str, limit: int = 5) -> List[Dict[str, Any]]:
        """搜索情景记忆 - 使用索引加速"""
        query_words = query.lower().split()

        # 使用索引定位候选文件
        candidate_names = self.index.search(query_words)

        # 如果索引没有结果，回退到全扫描
        if not candidate_names:
            candidate_names = {f.stem for f in self.storage_dir.glob("*.md")}

        results = []
        query_lower = query.lower()

        for name in candidate_names:
            file_path = self.storage_dir / f"{name}.md"
            if not file_path.exists():
                continue

            content = file_path.read_text(encoding="utf-8")
            memory = self._parse_memory(content)

            if memory and query_lower in memory["content"].lower():
                memory["name"] = name
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

        # 初始化索引
        index_file = str(Path(storage_dir).parent / "semantic_index.json")
        self.index = MemoryIndex(index_file)

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

        # 更新索引
        self.index.add(name, content)

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

        # 默认使用简单关键词匹配 - 使用索引加速
        query_lower = query.lower()
        query_words = query_lower.split()

        # 使用索引定位候选文件
        candidate_names = self.index.search(query_words)

        # 如果索引没有结果，回退到全扫描
        if not candidate_names:
            candidate_names = {f.stem for f in self.storage_dir.glob("*.md")}

        results = []
        query_words_set = set(query_words)

        for name in candidate_names:
            file_path = self.storage_dir / f"{name}.md"
            if not file_path.exists():
                continue

            content = file_path.read_text(encoding="utf-8")
            memory = self._parse_memory(content)

            if memory:
                content_lower = memory["content"].lower()
                content_words = set(content_lower.split())

                matches = len(query_words_set & content_words)
                if matches > 0:
                    memory["name"] = name
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

        self.use_hybrid_retrieval = use_hybrid_retrieval
        self.logger = setup_logger("lightherrmes.memory")

        # 初始化统计系统
        stats_file = str(self.memory_dir / "stats.json")
        self.stats = MemoryStats(stats_file)

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
        """召回相关记忆 - 优化版：排序、token预算、去重"""
        import time
        start_time = time.time()

        # 收集所有记忆
        memories = []

        # 1. 工作记忆
        recent_sessions = self.working.get_recent_sessions(user_id, limit=3)
        for session in recent_sessions[:2]:
            memories.append({
                "type": "working",
                "content": f"最近对话: {session['summary']}",
                "priority": 3  # 最高优先级
            })
        self.stats.record_hit("working", 1 if recent_sessions else 0, time.time() - start_time)

        # 2. 情景记忆
        episodic_results = self.episodic.search(query, limit=3)
        for memory in episodic_results:
            name = memory.get("name", "unknown")
            content = memory["content"][:500]  # 扩展到500字符
            memories.append({
                "type": "episodic",
                "content": f"项目/任务 {name}: {content}",
                "priority": 2,
                "full_content": memory["content"]
            })
        self.stats.record_hit("episodic", len(episodic_results), time.time() - start_time)

        # 3. 语义记忆
        semantic_results = self.semantic.search(query, limit=3)
        for memory in semantic_results:
            name = memory.get("name", "unknown")
            content = memory["content"][:500]  # 从150扩展到500字符
            memories.append({
                "type": "semantic",
                "content": f"知识 {name}: {content}",
                "priority": 1,
                "full_content": memory["content"]
            })
        self.stats.record_hit("semantic", len(semantic_results), time.time() - start_time)

        # 去重：检查情景记忆和语义记忆的重叠
        def jaccard_similarity(text1: str, text2: str) -> float:
            words1 = set(text1.lower().split())
            words2 = set(text2.lower().split())
            if not words1 or not words2:
                return 0.0
            intersection = len(words1 & words2)
            union = len(words1 | words2)
            return intersection / union if union > 0 else 0.0

        # 去重逻辑
        filtered_memories = []
        for i, mem in enumerate(memories):
            if mem["type"] == "working":
                filtered_memories.append(mem)
                continue

            # 检查与已添加的记忆是否重叠
            is_duplicate = False
            for existing in filtered_memories:
                if existing["type"] == "working":
                    continue
                sim = jaccard_similarity(
                    mem.get("full_content", mem["content"]),
                    existing.get("full_content", existing["content"])
                )
                if sim > 0.5:
                    is_duplicate = True
                    break

            if not is_duplicate:
                filtered_memories.append(mem)

        # 按优先级排序
        filtered_memories.sort(key=lambda x: x["priority"], reverse=True)

        # Token预算：总上限约2000字符
        total_chars = 0
        max_chars = 2000
        result_parts = []

        for mem in filtered_memories:
            content = mem["content"]
            if total_chars + len(content) > max_chars:
                # 截断以适应预算
                remaining = max_chars - total_chars
                if remaining > 100:  # 至少保留100字符
                    content = content[:remaining] + "..."
                    result_parts.append(content)
                break
            result_parts.append(content)
            total_chars += len(content)

        return "\n".join(result_parts) if result_parts else ""

    def save_episodic(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存情景记忆"""
        self.episodic.save(name, content, metadata)

    def save_semantic(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存语义记忆"""
        self.semantic.save(name, content, metadata)

    def clear_short_term(self):
        """清空短期记忆"""
        self.short_term.clear()

    def adapt_weights(self):
        """根据命中率自适应调整记忆层级权重"""
        # 短期记忆自适应
        short_term_rate = self.stats.get_hit_rate("short_term")
        if short_term_rate > 0.7 and self.short_term.max_turns < 100:
            old_max = self.short_term.max_turns
            self.short_term.max_turns = min(100, self.short_term.max_turns + 10)
            self.logger.info(
                f"短期记忆容量增加: {old_max} → {self.short_term.max_turns} "
                f"(命中率: {short_term_rate:.2%})"
            )
        elif short_term_rate < 0.3 and self.short_term.max_turns > 30:
            old_max = self.short_term.max_turns
            self.short_term.max_turns = max(30, self.short_term.max_turns - 10)
            self.logger.info(
                f"短期记忆容量减少: {old_max} → {self.short_term.max_turns} "
                f"(命中率: {short_term_rate:.2%})"
            )

        # 工作记忆自适应
        working_rate = self.stats.get_hit_rate("working")
        if working_rate < 0.3 and self.working.retention_days > 3:
            old_days = self.working.retention_days
            self.working.retention_days = max(3, self.working.retention_days - 1)
            self.logger.info(
                f"工作记忆保留期缩短: {old_days} → {self.working.retention_days} 天 "
                f"(命中率: {working_rate:.2%})"
            )
        elif working_rate > 0.6 and self.working.retention_days < 14:
            old_days = self.working.retention_days
            self.working.retention_days = min(14, self.working.retention_days + 1)
            self.logger.info(
                f"工作记忆保留期延长: {old_days} → {self.working.retention_days} 天 "
                f"(命中率: {working_rate:.2%})"
            )

        # 语义记忆自适应
        if self.use_hybrid_retrieval:
            semantic_rate = self.stats.get_hit_rate("semantic")
            if semantic_rate < 0.2:
                self.use_hybrid_retrieval = False
                self.logger.warning(
                    f"语义记忆命中率过低 ({semantic_rate:.2%})，暂时禁用"
                )

        # 定期归档低频记忆
        archived_count = self.archive_old_memories(days_threshold=30)

    def archive_old_memories(self, days_threshold: int = 30) -> int:
        """归档低频记忆"""
        cutoff = (datetime.now() - timedelta(days=days_threshold)).isoformat()

        try:
            # 检查 episodic 是否使用数据库存储
            episodic_db = str(self.memory_dir / "episodic.db")
            if not os.path.exists(episodic_db):
                # 如果使用文件存储，跳过归档
                return 0

            conn = sqlite3.connect(episodic_db)
            cursor = conn.cursor()

            # 检查表是否存在 archived 字段
            cursor.execute("PRAGMA table_info(episodes)")
            columns = [col[1] for col in cursor.fetchall()]
            if "archived" not in columns:
                conn.close()
                return 0

            cursor.execute("""
                SELECT id, summary FROM episodes
                WHERE last_accessed < ? AND archived = 0
            """, (cutoff,))

            to_archive = cursor.fetchall()

            for episode_id, summary in to_archive:
                cursor.execute("""
                    UPDATE episodes
                    SET content = ?, archived = 1
                    WHERE id = ?
                """, (f"[已归档] {summary}", episode_id))

            conn.commit()
            conn.close()

            if to_archive:
                self.logger.info(f"归档了 {len(to_archive)} 条低频记忆")

            return len(to_archive)
        except Exception as e:
            self.logger.error(f"归档记忆失败: {e}")
            return 0
