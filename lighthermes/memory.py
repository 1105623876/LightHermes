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

from lighthermes.logger import setup_logger


def parse_memory_file_content(content: str) -> Optional[Dict[str, Any]]:
    """解析记忆文件内容的通用函数"""
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


def parse_memory_file(file_path: str) -> Optional[Dict[str, Any]]:
    """解析记忆文件的通用函数"""
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except Exception:
        return None

    return parse_memory_file_content(content)


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
            logger = setup_logger("lighthermes.memory")
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
            logger = setup_logger("lighthermes.memory")
            logger.error(f"保存索引失败: {e}")

    def add(self, name: str, content: str):
        """添加文档到索引"""
        words = set(self._tokenize(content))
        for word in words:
            # 中文单字保留，英文单字符过滤
            if len(word) == 0:
                continue
            if len(word) == 1 and word.isascii():
                continue
            if word not in self.inverted_index:
                self.inverted_index[word] = set()
            self.inverted_index[word].add(name)
        self._save_index()

    def _tokenize(self, text: str) -> List[str]:
        """轻量分词：支持中英文混合"""
        text = text.lower()
        tokens = []
        current_token = ""

        for char in text:
            # 中文字符（CJK统一汉字）
            if '一' <= char <= '鿿':
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                tokens.append(char)  # 中文按字索引
            # 英文字母和数字
            elif char.isalnum():
                current_token += char
            # 分隔符（空格、标点等）
            else:
                if current_token:
                    tokens.append(current_token)
                    current_token = ""

        if current_token:
            tokens.append(current_token)

        return tokens

    def remove(self, name: str):
        """从索引中移除文档"""
        for word in list(self.inverted_index.keys()):
            if name in self.inverted_index[word]:
                self.inverted_index[word].discard(name)
                if not self.inverted_index[word]:
                    del self.inverted_index[word]
        self._save_index()

    def search(self, query_words: List[str]) -> set:
        """搜索包含任意查询词的文档（并集），按匹配度排序"""
        if not query_words:
            return set()

        # 分词查询
        tokens = []
        for word in query_words:
            tokens.extend(self._tokenize(word))

        tokens = [t for t in tokens if len(t) > 0]
        if not tokens:
            return set()

        # 收集所有匹配的文档（并集而非交集）
        matched_docs = set()
        for token in tokens:
            if token in self.inverted_index:
                matched_docs.update(self.inverted_index[token])

        return matched_docs


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
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    session_id TEXT PRIMARY KEY,
                    user_id TEXT,
                    messages TEXT,
                    timestamp TEXT
                )
            """)
            conn.commit()
            conn.close()
        except Exception as e:
            logger = setup_logger("lighthermes.memory")
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
            logger = setup_logger("lighthermes.memory")
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
        cursor.execute("DELETE FROM conversations WHERE timestamp < ?", (cutoff,))
        conn.commit()
        conn.close()

    def save_conversation(self, session_id: str, user_id: str, messages: List[Dict[str, str]]):
        """持久化会话消息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            messages_json = json.dumps(messages, ensure_ascii=False)
            cursor.execute("""
                INSERT OR REPLACE INTO conversations (session_id, user_id, messages, timestamp)
                VALUES (?, ?, ?, ?)
            """, (session_id, user_id, messages_json, datetime.now().isoformat()))
            conn.commit()
            conn.close()
        except Exception as e:
            logger = setup_logger("lighthermes.memory")
            logger.error(f"保存会话消息失败: {e}")

    def load_conversation(self, session_id: str) -> List[Dict[str, str]]:
        """加载历史会话消息"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT messages FROM conversations WHERE session_id = ?
            """, (session_id,))
            result = cursor.fetchone()
            conn.close()

            if result:
                return json.loads(result[0])
            return []
        except Exception as e:
            logger = setup_logger("lighthermes.memory")
            logger.error(f"加载会话消息失败: {e}")
            return []

    def get_latest_session(self, user_id: str) -> Optional[str]:
        """获取用户最近的会话ID"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.execute("""
                SELECT session_id FROM conversations
                WHERE user_id = ?
                ORDER BY timestamp DESC
                LIMIT 1
            """, (user_id,))
            result = cursor.fetchone()
            conn.close()
            return result[0] if result else None
        except Exception as e:
            logger = setup_logger("lighthermes.memory")
            logger.error(f"获取最近会话失败: {e}")
            return None


class EpisodicMemory:
    """情景记忆 - 项目/任务相关的记忆"""

    def __init__(self, storage_dir: str):
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # 初始化索引
        index_file = str(Path(storage_dir).parent / "episodic_index.json")
        self.index = MemoryIndex(index_file)

    def _parse_memory(self, content: str) -> Optional[Dict[str, Any]]:
        """解析记忆文件内容"""
        return parse_memory_file_content(content)

    def save(self, name: str, content: str, metadata: Dict[str, Any] = None):
        """保存情景记忆"""
        metadata = metadata or {}
        metadata.setdefault("type", "episodic")
        metadata.setdefault("status", "active")
        metadata.setdefault("created", datetime.now().strftime("%Y-%m-%d"))
        metadata.setdefault("last_accessed", datetime.now().isoformat())
        metadata.setdefault("access_count", 0)

        frontmatter = "---\n"
        for key, value in metadata.items():
            frontmatter += f"{key}: {value}\n"
        frontmatter += "---\n\n"

        file_path = self.storage_dir / f"{name}.md"
        file_path.write_text(frontmatter + content, encoding="utf-8")

        # 更新索引
        self.index.add(name, content)

    def update_access(self, name: str):
        """更新访问记录"""
        memory = self.load(name)
        if not memory:
            return

        metadata = memory.get("metadata", {})
        metadata["last_accessed"] = datetime.now().isoformat()
        metadata["access_count"] = int(metadata.get("access_count", 0)) + 1

        self.save(name, memory["content"], metadata)

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

            memory = parse_memory_file(str(file_path))

            if memory and query_lower in memory["content"].lower():
                memory["name"] = name
                results.append(memory)

        return results[:limit]


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
        self.hybrid_retriever = None

        if use_hybrid_retrieval:
            try:
                from lighthermes.retrieval import HybridRetriever
                self.hybrid_retriever = HybridRetriever(
                    embedding_provider=embedding_provider,
                    embedding_model=embedding_model,
                    api_key=api_key
                )
            except ImportError:
                print("混合检索不可用,使用简单关键词匹配")
            except Exception as e:
                print(f"混合检索初始化失败,使用简单关键词匹配: {e}")

    def _parse_memory(self, content: str) -> Optional[Dict[str, Any]]:
        """解析记忆文件内容"""
        return parse_memory_file_content(content)

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

    def update_access(self, name: str):
        """更新访问记录"""
        memory = self.load(name)
        if not memory:
            return

        metadata = memory.get("metadata", {})
        metadata["last_accessed"] = datetime.now().isoformat()
        metadata["access_count"] = int(metadata.get("access_count", 0)) + 1

        self.save(name, memory["content"], metadata)

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
        # 使用相同的分词逻辑
        query_tokens = set(self.index._tokenize(query))

        for name in candidate_names:
            file_path = self.storage_dir / f"{name}.md"
            if not file_path.exists():
                continue

            memory = parse_memory_file(str(file_path))

            if memory:
                # 使用相同的分词逻辑
                content_tokens = set(self.index._tokenize(memory["content"]))

                matches = len(query_tokens & content_tokens)
                if matches > 0:
                    memory["name"] = name
                    memory["score"] = matches
                    results.append(memory)

        results.sort(key=lambda x: x.get("score", 0), reverse=True)
        return results[:limit]

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
        api_key: str = None,
        working_to_episodic_limit: int = 20,
        episodic_to_semantic_access_threshold: int = 10,
        archive_inactive_days: int = 30
    ):
        self.memory_dir = Path(memory_dir)
        self.memory_dir.mkdir(parents=True, exist_ok=True)

        self.use_hybrid_retrieval = use_hybrid_retrieval
        self.working_to_episodic_limit = working_to_episodic_limit
        self.episodic_to_semantic_access_threshold = episodic_to_semantic_access_threshold
        self.archive_inactive_days = archive_inactive_days
        self.logger = setup_logger("lighthermes.memory")

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

    def save_user_preference(self, key: str, value: str):
        """保存用户偏好到语义记忆"""
        import hashlib
        name = hashlib.md5(key.encode()).hexdigest()[:8]
        self.semantic.save(
            name=f"user_pref_{name}",
            content=f"{key}: {value}",
            metadata={"type": "user_preference", "key": key}
        )
        self.logger.info(f"已保存用户偏好: {key}")

    def get_all_user_preferences(self) -> str:
        """获取所有用户偏好记忆，用于注入到 system prompt"""
        preferences = []
        for file_path in self.semantic.storage_dir.glob("user_pref_*.md"):
            memory = parse_memory_file(str(file_path))
            if memory and memory.get("metadata", {}).get("type") == "user_preference":
                preferences.append(memory["content"])

        if preferences:
            return "\n".join(preferences)
        return ""

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
                "name": name,
                "content": f"项目/任务 {name}: {content}",
                "priority": 2,
                "score": memory.get("score", 0),
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
                "name": name,
                "content": f"知识 {name}: {content}",
                "priority": 1,
                "score": memory.get("score", 0),
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

        # 按优先级和检索分数排序
        filtered_memories.sort(
            key=lambda x: (x.get("priority", 0), x.get("score", 0)),
            reverse=True
        )

        # Token预算：总上限约2000字符
        total_chars = 0
        max_chars = 2000
        result_parts = []
        selected_memories = []

        for mem in filtered_memories:
            content = mem["content"]
            if total_chars + len(content) > max_chars:
                # 截断以适应预算
                remaining = max_chars - total_chars
                if remaining > 100:  # 至少保留100字符
                    content = content[:remaining] + "..."
                    result_parts.append(content)
                    selected_memories.append(mem)
                break
            result_parts.append(content)
            selected_memories.append(mem)
            total_chars += len(content)

        for mem in selected_memories:
            name = mem.get("name")
            if not name:
                continue
            if mem["type"] == "episodic":
                self.episodic.update_access(name)
            elif mem["type"] == "semantic":
                self.semantic.update_access(name)

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
        self.archive_inactive_memories()

    def archive_inactive_memories(self, inactive_days: int = None):
        """归档长期未访问的记忆"""
        inactive_days = self.archive_inactive_days if inactive_days is None else inactive_days
        cutoff = datetime.now() - timedelta(days=inactive_days)

        # 归档情景记忆
        for file_path in self.episodic.storage_dir.glob("*.md"):
            memory = self.episodic.load(file_path.stem)
            if not memory:
                continue

            metadata = memory.get("metadata", {})
            last_accessed = metadata.get("last_accessed")
            if last_accessed:
                try:
                    last_access_time = datetime.fromisoformat(last_accessed)
                    if last_access_time < cutoff:
                        archive_dir = self.episodic.storage_dir / "archived"
                        archive_dir.mkdir(exist_ok=True)
                        name = file_path.stem
                        file_path.rename(archive_dir / file_path.name)
                        self.episodic.index.remove(name)
                        self.logger.info(f"归档情景记忆: {name}")
                except Exception:
                    pass

        # 归档语义记忆
        for file_path in self.semantic.storage_dir.glob("*.md"):
            memory = self.semantic.load(file_path.stem)
            if not memory:
                continue

            metadata = memory.get("metadata", {})
            last_accessed = metadata.get("last_accessed")
            if last_accessed:
                try:
                    last_access_time = datetime.fromisoformat(last_accessed)
                    if last_access_time < cutoff:
                        archive_dir = self.semantic.storage_dir / "archived"
                        archive_dir.mkdir(exist_ok=True)
                        name = file_path.stem
                        file_path.rename(archive_dir / file_path.name)
                        self.semantic.index.remove(name)
                        self.logger.info(f"归档语义记忆: {name}")
                except Exception:
                    pass

    def promote_memories(self):
        """提升高频访问的记忆到更高层级"""
        # 工作记忆 → 情景记忆：高频访问的会话提升为项目记忆
        recent_sessions = self.working.get_recent_sessions(
            "default",
            limit=self.working_to_episodic_limit
        )
        for session in recent_sessions:
            session_id = session["session_id"]
            episodic_name = f"working_{session_id}"
            if (self.episodic.storage_dir / f"{episodic_name}.md").exists():
                continue

            self.episodic.save(
                episodic_name,
                session["summary"],
                {
                    "promoted_from": "working",
                    "source_session_id": session_id,
                    "user_id": "default",
                    "source_timestamp": session.get("timestamp", "")
                }
            )
            self.logger.info(f"提升工作记忆到情景记忆: {session_id} → {episodic_name}")

        # 情景记忆 → 语义记忆：反复使用的项目知识抽象为通用知识
        for file_path in self.episodic.storage_dir.glob("*.md"):
            memory = self.episodic.load(file_path.stem)
            if not memory:
                continue

            metadata = memory.get("metadata", {})
            access_count = int(metadata.get("access_count", 0))

            if access_count > self.episodic_to_semantic_access_threshold:
                semantic_name = f"knowledge_{file_path.stem}"
                if not (self.semantic.storage_dir / f"{semantic_name}.md").exists():
                    self.semantic.save(
                        semantic_name,
                        memory["content"],
                        {
                            "promoted_from": "episodic",
                            "original_name": file_path.stem,
                            "promotion_reason": "high_access_count",
                            "source_access_count": access_count
                        }
                    )
                    self.logger.info(f"提升情景记忆到语义记忆: {file_path.stem} → {semantic_name}")

    def migrate_short_to_working(self, session_id: str, user_id: str, summary: str):
        """短期记忆 → 工作记忆：会话结束时迁移"""
        # 保存会话摘要到工作记忆
        self.working.add_session(session_id, user_id, summary)

        # 保存完整对话历史
        messages = self.short_term.get_messages()
        if messages:
            self.working.save_conversation(session_id, user_id, messages)

        self.logger.info(f"迁移短期记忆到工作记忆: session={session_id}")

    def auto_migrate(self):
        """自动执行记忆迁移"""
        try:
            # 归档低频记忆
            self.archive_inactive_memories()

            # 提升高频记忆
            self.promote_memories()

            self.logger.info("自动记忆迁移完成")
        except Exception as e:
            self.logger.error(f"自动记忆迁移失败: {e}")
