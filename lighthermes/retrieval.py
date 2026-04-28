"""
混合检索系统 - TF-IDF + 嵌入模型

为记忆系统提供更精确的语义检索能力
"""

import os
import json
import math
from pathlib import Path
from typing import List, Dict, Any, Optional
from collections import Counter


class TFIDFRetriever:
    """TF-IDF 检索器 - 快速初筛"""

    def __init__(self):
        self.documents: List[Dict[str, Any]] = []
        self.idf: Dict[str, float] = {}

    def index_documents(self, documents: List[Dict[str, Any]]):
        """索引文档"""
        self.documents = documents
        self._compute_idf()

    def _compute_idf(self):
        """计算 IDF"""
        doc_count = len(self.documents)
        word_doc_count = Counter()

        for doc in self.documents:
            words = set(doc["content"].lower().split())
            for word in words:
                word_doc_count[word] += 1

        self.idf = {
            word: math.log(doc_count / count)
            for word, count in word_doc_count.items()
        }

    def search(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        """TF-IDF 搜索"""
        query_words = query.lower().split()
        scores = []

        for doc in self.documents:
            content_lower = doc["content"].lower()
            content_words = content_lower.split()
            word_count = Counter(content_words)

            score = 0
            for word in query_words:
                if word in word_count:
                    tf = word_count[word] / len(content_words)
                    idf = self.idf.get(word, 0)
                    score += tf * idf

            if score > 0:
                scores.append((score, doc))

        scores.sort(reverse=True, key=lambda x: x[0])
        return [doc for _, doc in scores[:top_k]]


class EmbeddingRetriever:
    """嵌入检索器 - 精确重排"""

    def __init__(self, provider: str = "openai", model: str = "text-embedding-3-small", api_key: str = None):
        self.provider = provider
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.embeddings_cache: Dict[str, List[float]] = {}
        self.cache_file = Path("memory/.embeddings/cache.json")

        if self.provider == "openai":
            from openai import OpenAI
            self.client = OpenAI(api_key=self.api_key)
        elif self.provider == "local":
            try:
                from sentence_transformers import SentenceTransformer
                self.model_instance = SentenceTransformer(model or "all-MiniLM-L6-v2")
            except ImportError:
                raise ImportError("请安装 sentence-transformers: pip install sentence-transformers")

        self._load_cache()

    def _load_cache(self):
        """加载嵌入缓存"""
        if self.cache_file.exists():
            with open(self.cache_file, "r", encoding="utf-8") as f:
                self.embeddings_cache = json.load(f)

    def _save_cache(self):
        """保存嵌入缓存"""
        self.cache_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_file, "w", encoding="utf-8") as f:
            json.dump(self.embeddings_cache, f)

    def embed(self, text: str) -> List[float]:
        """生成文本嵌入"""
        if text in self.embeddings_cache:
            return self.embeddings_cache[text]

        if self.provider == "openai":
            response = self.client.embeddings.create(
                model=self.model,
                input=text
            )
            embedding = response.data[0].embedding
        elif self.provider == "local":
            embedding = self.model_instance.encode(text).tolist()
        else:
            raise ValueError(f"不支持的提供者: {self.provider}")

        self.embeddings_cache[text] = embedding
        self._save_cache()
        return embedding

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        return dot_product / (norm1 * norm2) if norm1 and norm2 else 0

    def rerank(self, query: str, documents: List[Dict[str, Any]], top_k: int = 5) -> List[Dict[str, Any]]:
        """使用嵌入模型重排"""
        query_embedding = self.embed(query)
        scores = []

        for doc in documents:
            doc_embedding = self.embed(doc["content"][:500])
            score = self.cosine_similarity(query_embedding, doc_embedding)
            scores.append((score, doc))

        scores.sort(reverse=True, key=lambda x: x[0])
        return [doc for _, doc in scores[:top_k]]


class HybridRetriever:
    """混合检索器 - TF-IDF + 嵌入"""

    def __init__(
        self,
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-small",
        api_key: str = None
    ):
        self.tfidf = TFIDFRetriever()
        self.embedding = EmbeddingRetriever(
            provider=embedding_provider,
            model=embedding_model,
            api_key=api_key
        )

    def index_documents(self, documents: List[Dict[str, Any]]):
        """索引文档"""
        self.tfidf.index_documents(documents)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """混合检索"""
        candidates = self.tfidf.search(query, top_k=20)

        if not candidates:
            return []

        results = self.embedding.rerank(query, candidates, top_k=top_k)
        return results
