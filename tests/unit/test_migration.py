import json
import sqlite3

import pytest

from lighthermes.migration import convert, inventory
from lighthermes.runtime_memory import RuntimeMemory
from lighthermes.store import MemoryStore


def legacy(tmp_path):
    root = tmp_path / 'old'
    (root / 'semantic').mkdir(parents=True)
    (root / 'semantic' / 'fact.md').write_text('---\nconfidence: 0.99\nunknown: preserve me\n---\nUse Python')
    (root / 'USER.md').write_text('Human preference')
    (root / 'unknown.bin').write_bytes(b'\x00\xff')
    with sqlite3.connect(root / 'working.db') as db:
        db.execute('CREATE TABLE sessions(session_id TEXT, user_id TEXT, summary TEXT, extra TEXT)')
        db.execute('INSERT INTO sessions VALUES(?,?,?,?)', ('s1', 'default', 'Rust decision', 'unknown field'))
        db.execute('CREATE TABLE conversations(session_id TEXT, user_id TEXT, messages TEXT)')
        db.execute('INSERT INTO conversations VALUES(?,?,?)', ('s1', 'default', '[{"role":"user","content":"Rust"}]'))
    return root


def test_verified_idempotent_import_preserves_unknowns_and_users(tmp_path):
    source = legacy(tmp_path)
    original = inventory(source)
    target = tmp_path / 'new'
    receipt = convert(source, target, user_id='chosen-user')
    assert inventory(source) == original
    assert inventory(target / 'legacy_sources') == original
    assert (target / 'legacy_sources' / 'USER.md').read_text() == 'Human preference'
    assert not (target / 'USER.md').exists()  # chosen-user setup must not leak into default_user
    assert receipt['candidate_entries'] == 2
    assert convert(source, target, user_id='chosen-user')['already_imported']
    with MemoryStore(target / 'lighthermes.sqlite3') as store:
        assert store.db.execute('SELECT count(*) FROM entries').fetchone()[0] == 2
        assert store.search('Python', '["user","chosen-user"]') == []
        assert {r[0] for r in store.db.execute('SELECT scope FROM entries')} == {'["user","chosen-user"]', '["user","default"]'}
        payloads = ' '.join(r[0] for r in store.db.execute('SELECT payload FROM events'))
        assert 'preserve me' in payloads and 'unknown field' in payloads
    runtime = RuntimeMemory(target)
    runtime.store.close()


def test_changed_source_does_not_merge_or_overwrite_target(tmp_path):
    source = legacy(tmp_path)
    target = tmp_path / 'new'
    convert(source, target, user_id='u')
    before = inventory(target)
    (source / 'semantic' / 'fact.md').write_text('Changed')
    with pytest.raises(FileExistsError):
        convert(source, target, user_id='u')
    assert inventory(target) == before


def test_import_failure_does_not_publish_or_modify_source(tmp_path, monkeypatch):
    source = legacy(tmp_path)
    before = inventory(source)
    def failure(*args, **kwargs):
        raise sqlite3.OperationalError('simulated disk full')
    monkeypatch.setattr(MemoryStore, 'remember', failure)
    with pytest.raises(sqlite3.OperationalError):
        convert(source, tmp_path / 'new', user_id='u')
    assert not (tmp_path / 'new').exists()
    assert inventory(source) == before
    assert not list(tmp_path.glob('.lighthermes-import-*'))


def test_symlink_and_in_place_import_are_rejected(tmp_path):
    source = legacy(tmp_path)
    with pytest.raises(ValueError):
        convert(source, source / 'new', user_id='u')
    (source / 'link').symlink_to(tmp_path / 'elsewhere')
    with pytest.raises(ValueError, match='Symlink'):
        inventory(source)


def test_blob_metadata_and_unknown_tables_remain_recoverable(tmp_path):
    source = legacy(tmp_path)
    with sqlite3.connect(source / 'working.db') as db:
        db.execute('ALTER TABLE sessions ADD COLUMN opaque BLOB')
        db.execute("UPDATE sessions SET opaque=x'00ff'")
        db.execute('CREATE TABLE unknown_table(payload TEXT)')
        db.execute("INSERT INTO unknown_table VALUES('keep forever')")
    target = tmp_path / 'new'
    convert(source, target, user_id='u')
    with MemoryStore(target / 'lighthermes.sqlite3') as store:
        assert any('base64_bytes' in row[0] for row in store.db.execute('SELECT payload FROM events'))
    with sqlite3.connect(target / 'legacy_sources' / 'working.db') as db:
        assert db.execute('SELECT payload FROM unknown_table').fetchone()[0] == 'keep forever'
