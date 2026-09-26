"""Deterministic vectors test mechanics, not real-model semantic quality."""
import json

import pytest

from lighthermes.runtime_memory import RuntimeMemory
from lighthermes.semantic import SemanticIndex
from lighthermes.store import MemoryStore


class Embeddings:
    def __init__(self):
        self.calls = []

    def __call__(self, texts):
        self.calls.append(list(texts))
        return [[1, 0] if text in ('统一使用 uv', '安装依赖的方式', 'use uv') else [0, 1] for text in texts]


def save(store, text, scope='alice', status='active', supersedes=None):
    ref = store.append_event(scope, 's', text, {'content': text})
    return store.remember(scope, 'decision', text, [ref], status=status, supersedes=supersedes)


def test_independent_candidates_reopen_no_reembedding_and_scope(tmp_path):
    path = tmp_path / 'memory.sqlite3'
    embed = Embeddings()
    with MemoryStore(path) as store:
        wanted = save(store, '统一使用 uv')
        save(store, 'use uv', 'bob')
        save(store, 'use uv', status='candidate')
        assert not store.search('安装依赖的方式', 'alice')
        index = SemanticIndex(store, model='fixture', embed=embed)
        assert [r['id'] for r in index.search('安装依赖的方式', ['alice'], [], 4)] == [wanted]
        assert embed.calls == [['统一使用 uv'], ['安装依赖的方式']]
        assert index.search('海边天气', ['alice'], [], 4) == []
    with MemoryStore(path) as store:
        embed.calls.clear()
        index = SemanticIndex(store, model='fixture', embed=embed)
        assert index.search('安装依赖的方式', ['alice'], [], 4)[0]['id'] == wanted
        assert embed.calls == [['安装依赖的方式']]
        assert store.usage()['embedding_cache_bytes'] > 0


@pytest.mark.parametrize('action', ['correct', 'archive', 'forget', 'erase'])
def test_invalidated_vectors_cannot_resurrect(tmp_path, action):
    with MemoryStore(tmp_path / 'db') as store:
        identifier = save(store, '统一使用 uv')
        index = SemanticIndex(store, model='fixture', embed=Embeddings())
        assert index.search('安装依赖的方式', ['alice'], [], 4)
        if action == 'correct':
            save(store, '改用别的工具', supersedes=identifier)
        elif action == 'archive':
            store.set_status(identifier, 'alice', 'archived')
        elif action == 'erase':
            plan = store.plan_erasure(identifier, 'alice')
            store.erase(identifier, 'alice', approved_fingerprint=plan['fingerprint'])
        else:
            store.forget(identifier, 'alice')
        store.rebuild_index()
        assert index.search('安装依赖的方式', ['alice'], [], 4) == []
        assert not store.db.execute('SELECT 1 FROM entry_vectors WHERE entry_id=?', (identifier,)).fetchone()


def test_backlog_is_bounded_and_visible_and_resumes_next_turn(tmp_path):
    with MemoryStore(tmp_path / 'db') as store:
        for i in range(20):
            save(store, f'item {i}')
        embed = Embeddings()
        index = SemanticIndex(store, model='fixture', embed=embed)
        index.search('question', ['alice'], [], 4)
        assert index.status == {'mode': 'partial', 'pending': 4}
        index.search('question', ['alice'], [], 4)
        assert [len(call) for call in embed.calls] == [16, 1]
        index.begin()
        index.search('question', ['alice'], [], 4)
        assert index.status == {'mode': 'hybrid', 'pending': 0}
        assert [len(call) for call in embed.calls] == [16, 1, 4, 1]


@pytest.mark.parametrize('bad', [[], [[float('nan'), 0]], [[0, 0]], [[1], [1]]])
def test_invalid_provider_output_reports_lexical_without_corrupt_cache(tmp_path, bad):
    with MemoryStore(tmp_path / 'db') as store:
        identifier = save(store, 'uv')
        index = SemanticIndex(store, model='fixture', embed=lambda texts: bad)
        rows = index.search('uv', ['alice'], store.search('uv', 'alice'), 4)
        assert rows[0]['id'] == identifier
        assert index.status['mode'] == 'lexical'
        assert store.db.execute('SELECT count(*) FROM entry_vectors').fetchone()[0] == 0


def test_changed_model_rebuilds_incrementally_and_query_failure_is_visible(tmp_path):
    with MemoryStore(tmp_path / 'db') as store:
        save(store, '统一使用 uv')
        old = SemanticIndex(store, model='old', embed=Embeddings())
        old.index(['alice'])
        embed = Embeddings()
        new = SemanticIndex(store, model='new', embed=embed)
        assert new.search('安装依赖的方式', ['alice'], [], 4)
        assert embed.calls == [['统一使用 uv'], ['安装依赖的方式']]
        new.begin()
        def fail(texts):
            raise TimeoutError('do not expose provider secrets')
        new.embed = fail
        assert new.search('uv', ['alice'], store.search('uv', 'alice'), 4)
        assert new.status['error'] == 'TimeoutError'
        assert 'secrets' not in json.dumps(new.status)


def test_natural_capture_requires_current_quote_and_caps_growth(tmp_path):
    memory = RuntimeMemory(tmp_path)
    memory.begin('这个项目统一使用 uv；不要安装到系统 Python。', 'alice', 's')
    with pytest.raises(ValueError, match='evidence'):
        memory.update_memory('capture', content='Use Rust', evidence='Rust')
    for i in range(3):
        memory.update_memory('capture', kind='decision', content=f'uv rule {i}', evidence='统一使用 uv')
    with pytest.raises(ValueError, match='three'):
        memory.update_memory('capture', content='fourth', evidence='统一使用 uv')
    with pytest.raises(ValueError, match='Capture only'):
        memory.update_memory('capture', kind='experience', content='verified', evidence='统一使用 uv')
    assert memory.store.search('uv', memory.scope)[0]['source_refs'] == [memory.source]
    memory.store.close()


def test_tail_preview_shows_matching_text_and_explicit_offset(tmp_path):
    memory = RuntimeMemory(tmp_path)
    memory.begin('save', 'alice', 's')
    text = '开头材料。' * 300 + '特别约束 zebracode'
    memory.update_memory('remember', content=text)
    memory.begin('zebracode', 'alice', 'new')
    card = json.loads(memory.seed('zebracode'))
    assert 'zebracode' in card['content']
    assert card['offset'] > 0
    assert not card['more']
    assert json.loads(memory.read_memory(card['id'], offset=0))['content'].startswith('开头材料')
    memory.store.close()


def test_failed_query_calls_also_consume_budget(tmp_path):
    with MemoryStore(tmp_path / 'db') as store:
        save(store, '统一使用 uv')
        index = SemanticIndex(store, model='fixture', embed=Embeddings())
        index.index(['alice'])
        calls = []
        def fail(texts):
            calls.append(texts)
            raise TimeoutError()
        index.embed = fail
        for _ in range(5):
            index.search('query', ['alice'], [], 4)
        assert len(calls) == 3
        assert index.status['mode'] == 'lexical'


def test_schema3_upgrade_keeps_existing_sources_and_entries(tmp_path):
    path = tmp_path / 'db'
    with MemoryStore(path) as store:
        identifier = save(store, '统一使用 uv')
        original = store.read_entry(identifier, 'alice')
        store.db.execute('DROP TABLE entry_vectors')
        store.db.execute('PRAGMA user_version=3')
    with MemoryStore(path) as store:
        assert store.read_entry(identifier, 'alice') == original
        assert store.search('uv', 'alice')[0]['id'] == identifier
        assert SemanticIndex(store, model='fixture', embed=Embeddings()).search(
            '安装依赖的方式', ['alice'], [], 4)[0]['id'] == identifier


def test_provider_adapter_uses_effective_endpoint_and_orders_response(tmp_path, monkeypatch):
    from types import SimpleNamespace as NS
    calls = []
    endpoint = ['https://first.invalid/v1/']
    def client(**kwargs):
        assert kwargs['timeout'] == 15 and kwargs['max_retries'] == 0
        def create(**request):
            calls.append(request)
            return NS(data=[NS(index=i, embedding=[1, 0]) for i in reversed(range(len(request['input'])))])
        return NS(base_url=endpoint[0], embeddings=NS(create=create))
    monkeypatch.setattr('openai.OpenAI', client)
    with MemoryStore(tmp_path / 'db') as store:
        save(store, '统一使用 uv')
        first = SemanticIndex(store, model='example', api_key='fake')
        assert first.search('安装依赖的方式', ['alice'], [], 4)
        assert calls[0] == {'model': 'example', 'input': ['统一使用 uv']}
        endpoint[0] = 'https://second.invalid/v1/'
        second = SemanticIndex(store, model='example', api_key='fake')
        assert first.key != second.key
        second.index(['alice'])
        assert len(calls) == 3  # Changed endpoint rebuilds the document vector.
