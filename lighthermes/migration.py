"""Explicit, one-shot legacy import into a NEW directory. Default is read-only inventory.

Unknown files/fields are retained in a verified source snapshot, never discarded.
All imported long-term content is candidate until reviewed by the host.
"""
import argparse
import base64
import hashlib
import json
import shutil
import sqlite3
import tempfile
from pathlib import Path

from .store import MemoryStore


def inventory(source):
    root = Path(source).resolve(strict=True)
    if not root.is_dir():
        raise ValueError('Source must be a directory')
    files = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('Symlinks require explicit handling before import')
        if path.is_file():
            digest, size = hashlib.sha256(), 0
            with path.open('rb') as handle:
                while block := handle.read(1024 * 1024):
                    digest.update(block)
                    size += len(block)
            files.append({'path': path.relative_to(root).as_posix(), 'bytes': size,
                          'sha256': digest.hexdigest()})
    encoded = json.dumps(files, sort_keys=True).encode()
    return {'snapshot': hashlib.sha256(encoded).hexdigest(), 'files': files,
            'bytes': sum(item['bytes'] for item in files)}


def _scope(user):
    if not isinstance(user, str) or not user.strip():
        raise ValueError('An explicit user is required for unowned legacy records')
    return json.dumps(['user', user], ensure_ascii=False, separators=(',', ':'))


def convert(source, target, *, user_id):
    """Source stays untouched; atomically publish a verified new directory or nothing."""
    source = Path(source).resolve(strict=True)
    target = Path(target).resolve()
    _scope(user_id)
    if source == target or source in target.parents or target in source.parents:
        raise ValueError('Target must be a separate new directory, outside the source')
    manifest = inventory(source)
    identity = {'snapshot': manifest['snapshot'], 'unowned_user': user_id}
    if target.exists():
        receipt = target / 'import.json'
        if receipt.is_file():
            previous = json.loads(receipt.read_text())
            if previous.get('identity') == identity:
                if not (target / 'lighthermes.sqlite3').is_file() or inventory(target / 'legacy_sources') != previous['manifest']:
                    raise ValueError('Completed import artifacts are missing or changed')
                return {**previous, 'already_imported': True}
        raise FileExistsError('Target exists and is not this exact completed import')
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.lighthermes-import-', dir=target.parent) as workspace:
        staging = Path(workspace) / 'publish'
        snapshot = staging / 'legacy_sources'
        shutil.copytree(source, snapshot)
        staging.chmod(0o700)
        if inventory(snapshot) != manifest or inventory(source) != manifest:
            raise RuntimeError('Source changed during snapshot; no import published')
        mapping = []
        with MemoryStore(staging / 'lighthermes.sqlite3', managed_paths=[staging]) as store:
            def write(origin, payload, content=None, user=None, session=None):
                scope = _scope(user or user_id)
                event = store.append_event(scope, 'legacy:' + str(session or origin), origin,
                                           {'legacy_source': origin, 'record': payload})
                entries = []
                if isinstance(content, str) and content.strip():
                    # Keep full original in the event; bounded chunks index the tail too.
                    for offset in range(0, len(content), 2000):
                        entries.append(store.remember(scope, 'fact', content[offset:offset+2000], [event]))
                mapping.append({'source': origin, 'event': event, 'entries': entries, 'scope': scope})

            for item in manifest['files']:
                relative = item['path']
                path = snapshot / relative
                if relative == 'SOUL.md' or (relative == 'USER.md' and user_id == 'default_user'):
                    shutil.copy2(path, staging / relative)
                elif path.suffix == '.md' and Path(relative).parts[0] in ('semantic', 'episodic'):
                    raw = path.read_text(encoding='utf-8')
                    # Preserve YAML/unknown metadata verbatim in source; don't interpret confidence as activation.
                    body = raw.split('---', 2)[-1].strip() if raw.startswith('---') else raw
                    write(relative, {'raw': raw, 'sha256': item['sha256']}, body)
                elif path.suffix in ('.db', '.sqlite', '.sqlite3'):
                    # Read a disposable copy: SQLite WAL/shm handling cannot alter the verified snapshot.
                    with tempfile.TemporaryDirectory(dir=workspace) as dbwork:
                        database = Path(dbwork) / path.name
                        shutil.copy2(path, database)
                        for suffix in ('-wal', '-shm', '-journal'):
                            companion = Path(str(path) + suffix)
                            if companion.exists():
                                shutil.copy2(companion, Path(str(database) + suffix))
                        connection = sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)
                        connection.row_factory = sqlite3.Row
                        try:
                            tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
                            for table in ('sessions', 'conversations'):
                                if table not in tables:
                                    continue
                                for row in connection.execute(f'SELECT rowid AS _rowid_, * FROM {table}'):
                                    record = dict(row)
                                    record = {key: {'base64_bytes': base64.b64encode(value).decode()} if isinstance(value, bytes) else value
                                              for key, value in record.items()}
                                    origin = f'{relative}#{table}:{record["_rowid_"]}'
                                    write(origin, record, record.get('summary'), record.get('user_id'), record.get('session_id'))
                        finally:
                            connection.close()
            if store.db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
                raise RuntimeError('Imported database failed integrity check')
            candidate_entries = store.db.execute('SELECT count(*) FROM entries').fetchone()[0]
        if inventory(source) != manifest or inventory(snapshot) != manifest:
            raise RuntimeError('Source or snapshot changed; no import published')
        receipt = {'identity': identity, 'manifest': manifest, 'mapping': mapping,
                   'candidate_entries': candidate_entries,
                   'policy': 'All entries candidate; original users preserved; unowned records use explicit user; unknown files retained; USER.md for non-default owners stays in snapshot, not global injection'}
        (staging / 'import.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2))
        with MemoryStore(staging / 'lighthermes.sqlite3', managed_paths=[staging]):
            pass  # Include the receipt and verified snapshot in the final capacity check.
        # Never merge into an existing target, including one created while importing.
        if target.exists():
            raise FileExistsError('Target appeared during import')
        staging.rename(target)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('--target', type=Path)
    parser.add_argument('--user')
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--preview', action='store_true', help='Validate conversion in a disposable directory and print counts only')
    args = parser.parse_args()
    if args.apply and args.preview:
        parser.error('--apply and --preview are mutually exclusive')
    if args.preview:
        if not args.user:
            parser.error('--preview requires explicit --user for unowned records')
        with tempfile.TemporaryDirectory(prefix='lighthermes-preview-') as workspace:
            result = convert(args.source, Path(workspace) / 'converted', user_id=args.user)
            print(json.dumps({'source_files': len(result['manifest']['files']),
                'source_bytes': result['manifest']['bytes'], 'snapshot': result['identity']['snapshot'],
                'events': len(result['mapping']), 'candidate_entries': result['candidate_entries'],
                'active_entries': 0, 'unowned_user': args.user, 'policy': result['policy'],
                'real_source_unchanged': inventory(args.source)['snapshot'] == result['identity']['snapshot']}, ensure_ascii=False))
    elif args.apply:
        if not args.target or not args.user:
            parser.error('--apply requires --target and --user')
        result = convert(args.source, args.target, user_id=args.user)
        print(json.dumps({'snapshot': result['identity']['snapshot'],
                          'candidate_entries': result['candidate_entries'],
                          'already_imported': result.get('already_imported', False)}))
    else:
        print(json.dumps(inventory(args.source), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
