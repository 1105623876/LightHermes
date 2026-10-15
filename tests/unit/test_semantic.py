"""Deterministic vectors test mechanics, not real-model semantic quality."""
import json
import math
import sqlite3
import struct

import pytest

from lighthermes.runtime_memory import RuntimeMemory
from lighthermes.semantic import SemanticIndex
from lighthermes.store import MemoryStore, decode_vector, encode_vector


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


def make_legacy_cache(store):
    """Recreate the actual schema-4 table in a disposable database."""
    store.db.execute('DROP TABLE entry_vectors')
    store.db.execute('CREATE TABLE entry_vectors (entry_id TEXT PRIMARY KEY '
        'REFERENCES entries(id) ON DELETE CASCADE, model TEXT NOT NULL, vector TEXT NOT NULL)')
    store.db.execute('PRAGMA user_version=4')


def test_binary_cache_is_lossless_and_legacy_conversion_is_explicit(tmp_path):
    path = tmp_path / 'db'
    values = [0.75, math.sqrt(1 - .75**2), -0.0, 1e-300]
    assert encode_vector(values) == struct.pack('<4d', *json.loads(json.dumps(values)))
    assert encode_vector(decode_vector(encode_vector(values))) == encode_vector(values)
    with MemoryStore(path) as store:
        assert store.binary_vectors
        make_legacy_cache(store)
        first = save(store, 'threshold')
        second = save(store, 'tie')
        save(store, 'other', 'bob')
        calls = []
        def embed(texts):
            calls.append(list(texts))
            return [[1, 0, 0, 0] if t == 'query' else values for t in texts]
        index = SemanticIndex(store, model='fixture', embed=embed, min_score=.75)
        before = index.search('query', ['alice'], [], 4)
        assert {row['id'] for row in before} == {first, second}
        assert store.db.execute('SELECT DISTINCT typeof(vector) FROM entry_vectors').fetchall()[0][0] == 'text'
    with MemoryStore(path) as store:
        assert not store.binary_vectors  # Opening old data must not convert it.
        original = {table: [tuple(r) for r in store.db.execute(f'SELECT * FROM {table} ORDER BY rowid')]
                    for table in ('events', 'entries', 'sources')}
        cached = [tuple(r) for r in store.db.execute('SELECT * FROM entry_vectors ORDER BY entry_id')]
        assert store.compact_vectors() == {'converted': 2, 'schema': 5}
        for table, rows in original.items():
            assert [tuple(r) for r in store.db.execute(f'SELECT * FROM {table} ORDER BY rowid')] == rows
        for identifier, model, value in cached:
            row = store.db.execute('SELECT model,vector FROM entry_vectors WHERE entry_id=?', (identifier,)).fetchone()
            assert row['model'] == model
            assert list(decode_vector(row['vector'])) == json.loads(value)
        assert store.compact_vectors() == {'converted': 0, 'schema': 5}
    with MemoryStore(path) as store:
        calls.clear()
        index = SemanticIndex(store, model='fixture', embed=embed, min_score=.75)
        assert index.search('query', ['alice'], [], 4) == before
        assert calls == [['query']]  # No document re-embedding after conversion/reopen.
        assert store.binary_vectors


@pytest.mark.parametrize('failure', ['corrupt', 'capacity'])
def test_cache_conversion_failure_preserves_old_schema_and_every_vector(tmp_path, failure):
    with MemoryStore(tmp_path / 'db') as store:
        make_legacy_cache(store)
        first = save(store, '统一使用 uv')
        second = save(store, 'another')
        index = SemanticIndex(store, model='fixture', embed=Embeddings())
        index.index(['alice'])
        if failure == 'corrupt':
            store.db.execute('UPDATE entry_vectors SET vector=? WHERE entry_id=?', ('[NaN, 0]', second))
        else:
            store.max_bytes = store.usage()['managed_bytes']  # No headroom for the SQLite journal.
        before = [tuple(r) for r in store.db.execute('SELECT * FROM entry_vectors ORDER BY entry_id')]
        with pytest.raises((ValueError, sqlite3.OperationalError)):
            store.compact_vectors()
        assert not store.binary_vectors
        assert [tuple(r) for r in store.db.execute('SELECT * FROM entry_vectors ORDER BY entry_id')] == before
        assert store.read_entry(first, 'alice')['content'] == '统一使用 uv'


@pytest.mark.parametrize('payload', [b'', b'bad', struct.pack('<2d', float('nan'), 0)])
def test_corrupt_binary_cache_is_reported_not_silently_treated_as_empty(tmp_path, payload):
    with MemoryStore(tmp_path / 'db') as store:
        identifier = save(store, '统一使用 uv')
        index = SemanticIndex(store, model='fixture', embed=Embeddings())
        index.index(['alice'])
        store.db.execute('UPDATE entry_vectors SET vector=? WHERE entry_id=?', (payload, identifier))
        rows = index.search('uv', ['alice'], store.search('uv', 'alice'), 4)
        assert rows[0]['id'] == identifier
        assert index.status['mode'] == 'lexical'
        assert index.status['error'] == 'ValueError'
