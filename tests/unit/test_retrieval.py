"""混合检索单元测试"""

import pytest

from lighthermes.retrieval import EmbeddingRetriever, HybridRetriever


@pytest.mark.unit
def test_openai_embedding_retriever_uses_base_url(monkeypatch):
    """测试 OpenAI-compatible embedding endpoint 配置"""
    captured_kwargs = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr("openai.OpenAI", FakeOpenAI)
    monkeypatch.setattr(EmbeddingRetriever, "_load_cache", lambda self: None)

    retriever = EmbeddingRetriever(
        provider="openai",
        model="embedding-model",
        api_key="embedding-key",
        base_url="https://embedding.example.test/v1"
    )

    assert retriever.model == "embedding-model"
    assert retriever.base_url == "https://embedding.example.test/v1"
    assert captured_kwargs["api_key"] == "embedding-key"
    assert captured_kwargs["base_url"] == "https://embedding.example.test/v1"


@pytest.mark.unit
def test_hybrid_retriever_passes_embedding_base_url(monkeypatch):
    """测试 HybridRetriever 透传 embedding base_url"""
    captured_kwargs = {}

    class FakeEmbeddingRetriever:
        def __init__(self, **kwargs):
            captured_kwargs.update(kwargs)

    monkeypatch.setattr("lighthermes.retrieval.EmbeddingRetriever", FakeEmbeddingRetriever)

    HybridRetriever(
        embedding_provider="openai",
        embedding_model="embedding-model",
        api_key="embedding-key",
        embedding_base_url="https://embedding.example.test/v1"
    )

    assert captured_kwargs["provider"] == "openai"
    assert captured_kwargs["model"] == "embedding-model"
    assert captured_kwargs["api_key"] == "embedding-key"
    assert captured_kwargs["base_url"] == "https://embedding.example.test/v1"


@pytest.mark.unit
def test_hybrid_retriever_falls_back_to_all_documents(monkeypatch):
    """测试 TF-IDF 候选为空时回退到全量 embedding rerank"""
    captured = {}

    class FakeEmbeddingRetriever:
        def __init__(self, **kwargs):
            pass

        def rerank(self, query, documents, top_k=5, min_score=None, score_margin=None):
            captured["documents"] = documents
            scored = []
            for doc in documents:
                score = 0.9 if doc["name"] == "answer" else 0.1
                ranked_doc = dict(doc)
                ranked_doc["score"] = score
                ranked_doc["embedding_score"] = score
                scored.append(ranked_doc)
            scored.sort(key=lambda item: item["score"], reverse=True)
            return scored[:top_k]

    monkeypatch.setattr("lighthermes.retrieval.EmbeddingRetriever", FakeEmbeddingRetriever)

    retriever = HybridRetriever(
        fallback_to_all=True,
        min_candidates=2,
        full_rerank_max_docs=10
    )
    retriever.index_documents([
        {"name": "answer", "content": "合成偏好：使用中文回答"},
        {"name": "noise", "content": "合成闲聊：喜欢乌龙茶"},
    ])

    results = retriever.search("preferred language", top_k=1)

    assert [doc["name"] for doc in captured["documents"]] == ["answer", "noise"]
    assert results[0]["name"] == "answer"
    assert results[0]["embedding_score"] == 0.9


@pytest.mark.unit
def test_hybrid_retriever_filters_by_semantic_threshold(monkeypatch):
    """测试 embedding 相似度阈值过滤低相关结果"""
    class FakeEmbeddingRetriever:
        def __init__(self, **kwargs):
            pass

        def rerank(self, query, documents, top_k=5, min_score=None, score_margin=None):
            scored = []
            for doc in documents:
                score = 0.4 if doc["name"] == "answer" else 0.2
                if min_score is not None and score < min_score:
                    continue
                ranked_doc = dict(doc)
                ranked_doc["score"] = score
                ranked_doc["embedding_score"] = score
                scored.append(ranked_doc)
            scored.sort(key=lambda item: item["score"], reverse=True)
            return scored[:top_k]

    monkeypatch.setattr("lighthermes.retrieval.EmbeddingRetriever", FakeEmbeddingRetriever)

    retriever = HybridRetriever(
        fallback_to_all=True,
        semantic_threshold=0.35
    )
    retriever.index_documents([
        {"name": "answer", "content": "alpha answer"},
        {"name": "noise", "content": "alpha noise"},
    ])

    results = retriever.search("alpha", top_k=5)

    assert [doc["name"] for doc in results] == ["answer"]
    assert results[0]["score"] == 0.4


@pytest.mark.unit
def test_embedding_rerank_filters_by_score_margin():
    """测试 embedding rerank 按 top 分数差过滤尾部噪声"""
    class FakeEmbeddingRetriever(EmbeddingRetriever):
        def __init__(self):
            self.embeddings_cache = {}
            self.cache_file = None

        def embed(self, text):
            vectors = {
                "query": [1.0, 0.0],
                "strong": [1.0, 0.0],
                "near": [0.97, 0.03],
                "noise": [0.1, 0.9],
            }
            return vectors[text]

        def _save_cache(self):
            pass

    retriever = FakeEmbeddingRetriever()
    results = retriever.rerank(
        "query",
        [
            {"name": "strong", "content": "strong"},
            {"name": "near", "content": "near"},
            {"name": "noise", "content": "noise"},
        ],
        top_k=5,
        score_margin=0.1
    )

    assert [doc["name"] for doc in results] == ["strong", "near"]
