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

    def _tokenize(self, text: str) -> List[str]:
        """轻量分词：支持中英文混合"""
        text = text.lower()
        tokens = []
        current_token = ""

        for char in text:
            if '一' <= char <= '鿿':
                if current_token:
                    tokens.append(current_token)
                    current_token = ""
                tokens.append(char)
            elif char.isalnum():
                current_token += char
            else:
                if current_token:
                    tokens.append(current_token)
                    current_token = ""

        if current_token:
            tokens.append(current_token)

        return [token for token in tokens if token]

    def index_documents(self, documents: List[Dict[str, Any]]):
        """索引文档"""
        self.documents = documents
        self._compute_idf()

    def _compute_idf(self):
        """计算 IDF"""
        doc_count = len(self.documents)
        word_doc_count = Counter()

        for doc in self.documents:
            words = set(self._tokenize(doc["content"]))
            for word in words:
                word_doc_count[word] += 1

        self.idf = {
            word: math.log(doc_count / count)
            for word, count in word_doc_count.items()
        }

    def search(self, query: str, top_k: int = 20) -> List[Dict[str, Any]]:
        """TF-IDF 搜索"""
        query_words = self._tokenize(query)
        scores = []

        for doc in self.documents:
            content_words = self._tokenize(doc["content"])
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

    def __init__(
        self,
        provider: str = "openai",
        model: str = "text-embedding-3-small",
        api_key: str = None,
        base_url: str = None
    ):
        self.provider = provider
        self.model = model
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY")
        self.base_url = base_url
        self.embeddings_cache: Dict[str, List[float]] = {}
        self.cache_file = Path("memory/.embeddings/cache.json")

        if self.provider == "openai":
            from openai import OpenAI
            client_kwargs = {"api_key": self.api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self.client = OpenAI(**client_kwargs)
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
        temp_file = self.cache_file.with_suffix(self.cache_file.suffix + ".tmp")
        try:
            self.cache_file.parent.mkdir(parents=True, exist_ok=True)
            with open(temp_file, "w", encoding="utf-8") as f:
                json.dump(self.embeddings_cache, f)
            temp_file.replace(self.cache_file)
            return True
        except (OSError, ValueError):
            try:
                temp_file.unlink(missing_ok=True)
            except OSError:
                pass
            return False

    def embed(self, text: str) -> List[float]:
        """生成文本嵌入"""
        return self.embed_many([text])[0]

    def embed_many(self, texts: List[str]) -> List[List[float]]:
        """批量生成文本嵌入，并复用本地缓存"""
        if not texts:
            return []

        missing_texts = []
        seen = set()
        for text in texts:
            if text not in self.embeddings_cache and text not in seen:
                missing_texts.append(text)
                seen.add(text)

        if missing_texts:
            if self.provider == "openai":
                response = self.client.embeddings.create(
                    model=self.model,
                    input=missing_texts
                )
                response_data = sorted(
                    response.data,
                    key=lambda item: getattr(item, "index", 0)
                )
                embeddings = [item.embedding for item in response_data]
            elif self.provider == "local":
                embeddings = self.model_instance.encode(missing_texts).tolist()
            else:
                raise ValueError(f"不支持的提供者: {self.provider}")

            if len(embeddings) != len(missing_texts):
                raise ValueError("嵌入接口返回数量与输入数量不一致")

            self.embeddings_cache.update(zip(missing_texts, embeddings))
            self._save_cache()

        return [self.embeddings_cache[text] for text in texts]

    def cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        dot_product = sum(a * b for a, b in zip(vec1, vec2))
        norm1 = math.sqrt(sum(a * a for a in vec1))
        norm2 = math.sqrt(sum(b * b for b in vec2))
        return dot_product / (norm1 * norm2) if norm1 and norm2 else 0

    def rerank(
        self,
        query: str,
        documents: List[Dict[str, Any]],
        top_k: int = 5,
        min_score: float = None,
        score_margin: float = None
    ) -> List[Dict[str, Any]]:
        """使用嵌入模型重排"""
        if not documents:
            return []

        document_texts = [doc["content"][:500] for doc in documents]
        embeddings = self.embed_many([query, *document_texts])
        query_embedding = embeddings[0]
        scores = []

        for doc, doc_embedding in zip(documents, embeddings[1:]):
            score = self.cosine_similarity(query_embedding, doc_embedding)
            if min_score is not None and score < min_score:
                continue
            ranked_doc = dict(doc)
            ranked_doc["score"] = score
            ranked_doc["embedding_score"] = score
            scores.append((score, ranked_doc))

        scores.sort(reverse=True, key=lambda x: x[0])
        if score_margin is not None and scores:
            cutoff = scores[0][0] - score_margin
            scores = [item for item in scores if item[0] >= cutoff]
        return [doc for _, doc in scores[:top_k]]


class HybridRetriever:
    """混合检索器 - TF-IDF + 嵌入"""

    def __init__(
        self,
        embedding_provider: str = "openai",
        embedding_model: str = "text-embedding-3-small",
        api_key: str = None,
        embedding_base_url: str = None,
        min_candidates: int = 5,
        fallback_to_all: bool = True,
        semantic_threshold: float = None,
        score_margin: float = 0.12,
        full_rerank_max_docs: int = 200,
        tfidf_candidate_limit: int = 20
    ):
        self.tfidf = TFIDFRetriever()
        self.min_candidates = min_candidates
        self.fallback_to_all = fallback_to_all
        self.semantic_threshold = semantic_threshold
        self.score_margin = score_margin
        self.full_rerank_max_docs = full_rerank_max_docs
        self.tfidf_candidate_limit = tfidf_candidate_limit
        self.embedding = EmbeddingRetriever(
            provider=embedding_provider,
            model=embedding_model,
            api_key=api_key,
            base_url=embedding_base_url
        )

    def index_documents(self, documents: List[Dict[str, Any]]):
        """索引文档"""
        self.tfidf.index_documents(documents)

    def search(self, query: str, top_k: int = 5) -> List[Dict[str, Any]]:
        """混合检索"""
        candidates = self.tfidf.search(query, top_k=self.tfidf_candidate_limit)
        documents = self.tfidf.documents

        if self.fallback_to_all and (
            len(documents) <= self.full_rerank_max_docs or
            len(candidates) < self.min_candidates
        ):
            candidates = documents[:self.full_rerank_max_docs]

        if not candidates:
            return []

        results = self.embedding.rerank(
            query,
            candidates,
            top_k=top_k,
            min_score=self.semantic_threshold,
            score_margin=self.score_margin
        )
        return results
