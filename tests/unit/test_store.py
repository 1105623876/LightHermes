"""R2 storage behavior, through public writes and reopen (no prefilled SQL)."""

import sqlite3

import pytest

from lighthermes.store import MemoryStore


def save(store, text, scope='user:u', **kwargs):
    event = store.append_event(scope, 'session-1', 'turn-1', {'role': 'user', 'content': text})
    entry = store.remember(scope, 'preference', text, [event], **kwargs)
    return event, entry


def test_restart_correction_history_and_scope(tmp_path):
    path = tmp_path / 'memory.db'
    with MemoryStore(path) as store:
        source, old = save(store, '使用 Python', status='active')
        other_source, other = save(store, '使用 TypeScript', scope='project:A', status='active')
    with MemoryStore(path) as store:
        assert store.search('Python', 'user:u')[0]['id'] == old
        assert store.read_event(source, 'user:u')['payload']['content'] == '使用 Python'
        assert store.search('TypeScript', 'project:B') == []
        for read, identifier in ((store.read_entry, other), (store.read_event, other_source)):
            with pytest.raises(KeyError):
                read(identifier, 'project:B')
        _, new = save(store, '使用 Rust', status='active', supersedes=old)
        assert store.search('Python', 'user:u') == []
        assert store.search('Rust', 'user:u')[0]['id'] == new
        assert store.read_entry(old, 'user:u', include_history=True)['status'] == 'superseded'
        with pytest.raises(KeyError):
            store.read_entry(old, 'user:u')
        with pytest.raises(ValueError):
            store.set_status(old, 'user:u', 'active')
        store.rebuild_index()
        assert store.search('Python', 'user:u') == []


def test_candidate_archive_tail_and_query_syntax(tmp_path):
    with MemoryStore(tmp_path / 'memory.db') as store:
        _, entry = save(store, '开头说明。' * 300 + '\n最终约束：海豚协议 zebra')
        assert store.search('zebra', 'user:u') == []
        store.set_status(entry, 'user:u', 'active')
        assert store.search('海豚', 'user:u')[0]['id'] == entry
        assert store.search('"zebra" OR *', 'user:u')[0]['id'] == entry
        assert store.search('completelyunrelated', 'user:u') == []
        assert store.search('***', 'user:u') == []
        store.set_status(entry, 'user:u', 'archived')
        store.rebuild_index()
        assert store.search('zebra', 'user:u') == []


@pytest.mark.parametrize('erase', [False, True])
def test_forget_chain_cannot_resurrect(tmp_path, erase):
    path = tmp_path / 'memory.db'
    with MemoryStore(path) as store:
        first_source, first = save(store, 'Python', status='active')
        last_source, last = save(store, 'Rust', status='active', supersedes=first)
        store.forget(last, 'user:u', erase_sources=erase)
    with MemoryStore(path) as store:
        store.rebuild_index()
        assert store.search('Python Rust', 'user:u') == []
        for entry in (first, last):
            with pytest.raises(KeyError):
                store.read_entry(entry, 'user:u', include_history=True)
        for ref in (first_source, last_source):
            with pytest.raises((KeyError, ValueError)):
                store.remember('user:u', 'fact', 'Extracted again', [ref], status='active')
            if not erase:
                assert store.read_event(ref, 'user:u')['excluded']
            else:
                with pytest.raises(KeyError):
                    store.read_event(ref, 'user:u')


def test_shared_source_erasure_is_atomic(tmp_path):
    with MemoryStore(tmp_path / 'memory.db') as store:
        ref, first = save(store, 'Python', status='active')
        second = store.remember('user:u', 'fact', 'Rust', [ref], status='active')
        with pytest.raises(ValueError, match='shared'):
            store.forget(first, 'user:u', erase_sources=True)
        assert store.read_entry(first, 'user:u')
        assert store.read_entry(second, 'user:u')
        assert not store.read_event(ref, 'user:u')['excluded']


def test_failed_correction_preserves_fact_and_index(tmp_path, monkeypatch):
    with MemoryStore(tmp_path / 'memory.db') as store:
        ref, old = save(store, 'Python', status='active')
        index = store._index

        def fail_new(identifier, content, status):
            index(identifier, content, status)
            if content:
                raise sqlite3.OperationalError('simulated disk failure')

        monkeypatch.setattr(store, '_index', fail_new)
        with pytest.raises(sqlite3.OperationalError):
            store.remember('user:u', 'fact', 'Rust', [ref], status='active', supersedes=old)
        assert store.read_entry(old, 'user:u')['status'] == 'active'
        assert store.search('Python', 'user:u')[0]['id'] == old
        assert store.search('Rust', 'user:u') == []


def test_scope_and_candidate_cannot_replace_active(tmp_path):
    with MemoryStore(tmp_path / 'memory.db') as store:
        ref, old = save(store, 'Python', status='active')
        other_ref = store.append_event('project:A', 's', 't', {'content': 'Rust'})
        with pytest.raises(KeyError):
            store.remember('project:A', 'fact', 'Rust', [ref], status='active')
        with pytest.raises(KeyError):
            store.remember('project:A', 'fact', 'Rust', [other_ref], status='active', supersedes=old)
        with pytest.raises(ValueError):
            store.remember('user:u', 'fact', 'Rust', [ref], supersedes=old)
        assert store.read_entry(old, 'user:u')


def test_capacity_failure_keeps_previously_saved_data(tmp_path):
    path = tmp_path / 'memory.db'
    with MemoryStore(path, max_bytes=256 * 1024) as store:
        ref, old = save(store, 'Python', status='active')
        with pytest.raises(sqlite3.OperationalError):
            store.remember('user:u', 'fact', 'x' * 500_000, [ref], status='active', supersedes=old)
        assert store.read_entry(old, 'user:u')
    with MemoryStore(path) as store:
        assert store.search('Python', 'user:u')[0]['id'] == old


def test_foreign_database_is_not_migrated(tmp_path):
    path = tmp_path / 'legacy.db'
    with sqlite3.connect(path) as db:
        db.execute('CREATE TABLE sessions (id TEXT)')
    before = path.read_bytes()
    with pytest.raises(ValueError, match='legacy import'):
        MemoryStore(path)
    assert path.read_bytes() == before


def test_incremental_observations_survive_interruption_without_replay(tmp_path):
    path = tmp_path / 'memory.db'
    with MemoryStore(path) as store:
        request = store.append_event('project:A', 's', 't', {'role': 'user', 'content': 'fix'})
        tool = store.append_event('project:A', 's', 't', {'role': 'assistant', 'tool_calls': [{'name': 'bash'}]})
        observation = store.append_event('project:A', 's', 't', {'role': 'tool', 'content': 'exit 1'})
        # No completed event before interruption. Reopen only reads saved data.
    with MemoryStore(path) as store:
        for ref in (request, tool, observation):
            assert store.read_event(ref, 'project:A')['turn_id'] == 't'
        assert store.read_event(observation, 'project:A')['payload']['content'] == 'exit 1'


def test_broken_index_is_an_error_not_empty_recall(tmp_path):
    with MemoryStore(tmp_path / 'memory.db') as store:
        save(store, 'Python', status='active')
        store.db.execute('DROP TABLE entry_fts')
        with pytest.raises(sqlite3.OperationalError):
            store.search('Python', 'user:u')


def test_owned_v1_upgrade_preserves_data_and_exclusions(tmp_path):
    path = tmp_path / 'memory.db'
    with MemoryStore(path) as store:
        source, old = save(store, 'Python', status='active')
        store.forget(old, 'user:u')
        store.db.execute('DROP TABLE excluded_turns')
        store.db.execute('PRAGMA user_version=1')
    with MemoryStore(path) as store:
        assert store.db.execute('PRAGMA user_version').fetchone()[0] == 2
        assert store.read_event(source, 'user:u')['excluded']
        later = store.append_event('user:u', 'session-1', 'turn-1', {'content': 'Python repeated'})
        with pytest.raises(ValueError, match='Forgotten'):
            store.remember('user:u', 'fact', 'Python', [later], status='active')
