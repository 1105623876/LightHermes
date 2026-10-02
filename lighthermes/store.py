"""Transactional R2 storage used by the agent and explicit legacy import.

All reads require an exact scope; callers combine user/project scopes explicitly.
Events are immutable source records. Only active entries enter lexical search.
No model calls, implicit legacy import or background maintenance.
"""

import json
import hashlib
import re
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from lighthermes.retrieval import tokenize_text


def memory_terms(text):
    """FTS features: shared Latin tokenizer, adjacent CJK pairs instead of lone 的/是.

    This avoids observed single-character contamination without a model call.
    It remains lexical: synonyms and cross-language matches are not guaranteed.
    """
    stop = {'a', 'an', 'the', 'is', 'are', 'was', 'i', 'my', 'you', 'your', 'what',
            'how', 'of', 'to', 'in', 'for', 'and', 'it', 'this', 'that'}
    terms = [t for t in tokenize_text(text) if not re.fullmatch('[一-鿿]', t) and t not in stop]
    for run in re.findall('[一-鿿]+', text):
        terms.extend(run[i:i+2] for i in range(len(run)-1))
    return list(dict.fromkeys(terms))


class MemoryStore:
    def __init__(self, path, max_bytes=256 * 1024 * 1024, *, managed_paths=()):
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.managed_paths = [Path(p) for p in managed_paths]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA secure_delete=ON")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1, 2, 3, 4):
                raise ValueError(f"Unsupported memory schema: {version}")
            tables = self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            if version == 0 and tables:
                raise ValueError("Not an empty database; legacy import must be explicit")
            if version == 0:
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE events (
                        id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                        session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                        payload TEXT NOT NULL,
                        created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    );
                    CREATE TABLE entries (
                        id TEXT PRIMARY KEY, scope TEXT NOT NULL,
                        kind TEXT NOT NULL CHECK(kind IN ('fact','preference','decision','experience','skill')),
                        content TEXT NOT NULL,
                        status TEXT NOT NULL CHECK(status IN ('candidate','active','superseded','archived')),
                        supersedes TEXT REFERENCES entries(id) ON DELETE SET NULL,
                        updated_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
                    );
                    CREATE TABLE sources (
                        entry_id TEXT NOT NULL REFERENCES entries(id) ON DELETE CASCADE,
                        event_id TEXT NOT NULL REFERENCES events(id),
                        PRIMARY KEY(entry_id,event_id)
                    );
                    CREATE TABLE excluded_sources (event_id TEXT PRIMARY KEY);
                    CREATE INDEX entries_scope ON entries(scope,status);
                    CREATE INDEX events_turn ON events(scope,session_id,turn_id);
                    CREATE VIRTUAL TABLE entry_fts USING fts5(id UNINDEXED, tokens);
                    PRAGMA user_version=1;
                    COMMIT;
                """)
            if version in (0, 1):
                self.db.executescript("""
                    BEGIN IMMEDIATE;
                    CREATE TABLE excluded_turns (
                        scope TEXT NOT NULL, session_id TEXT NOT NULL, turn_id TEXT NOT NULL,
                        PRIMARY KEY(scope,session_id,turn_id)
                    );
                    INSERT OR IGNORE INTO excluded_turns
                        SELECT e.scope,e.session_id,e.turn_id FROM events e
                        JOIN excluded_sources s ON s.event_id=e.id;
                    PRAGMA user_version=2;
                    COMMIT;
                """)
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            self.db.execute(f"PRAGMA max_page_count={max(1, max_bytes // page_size)}")
            self._check_capacity()
            if version < 3:
                with self._write():
                    self.db.execute('DELETE FROM entry_fts')
                    for row in self.db.execute("SELECT id,content,status FROM entries WHERE status='active'"):
                        self._index(*row)
                    self.db.execute('PRAGMA user_version=3')
            if version < 4:
                with self._write():
                    self.db.execute("""CREATE TABLE entry_vectors (
                        entry_id TEXT PRIMARY KEY REFERENCES entries(id) ON DELETE CASCADE,
                        model TEXT NOT NULL, vector TEXT NOT NULL)""")
                    self.db.execute('PRAGMA user_version=4')
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _disk_bytes(self):
        files = set()
        for path in [self.path, Path(str(self.path) + '-journal'),
                     Path(str(self.path) + '-wal'), Path(str(self.path) + '-shm'), *self.managed_paths]:
            if path.is_dir():
                files.update(p for p in path.rglob('*') if p.is_file() and not p.is_symlink())
            elif path.is_file():
                files.add(path)
        return sum(p.stat().st_size for p in {p.resolve() for p in files})

    def _check_capacity(self):
        # Application guard, not an OS quota. Include journals, managed logs and snapshots.
        total = self._disk_bytes()
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        projected = total - self.path.stat().st_size + pages * page_size
        if max(total, projected) > self.max_bytes:
            raise sqlite3.OperationalError("Memory storage capacity exceeded")

    def usage(self):
        """Physical managed total and separately labelled logical payload sizes."""
        groups = {row[0]: {'count': row[1], 'logical_bytes': row[2]} for row in self.db.execute(
            'SELECT status,count(*),coalesce(sum(length(cast(content AS BLOB))),0) FROM entries GROUP BY status')}
        count, size = self.db.execute('SELECT count(*),coalesce(sum(length(cast(payload AS BLOB))),0) FROM events').fetchone()
        return {'managed_bytes': self._disk_bytes(), 'max_bytes': self.max_bytes,
                'events': {'count': count, 'logical_bytes': size}, 'entries': groups,
                'embedding_cache_bytes': self.db.execute(
                    'SELECT coalesce(sum(length(cast(vector AS BLOB))),0) FROM entry_vectors').fetchone()[0],
                'note': 'Logical payload sizes exclude SQLite overhead; archive does not release physical space'}

    @contextmanager
    def _write(self):
        self._check_capacity()
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._check_capacity()
            self.db.execute("COMMIT")
        except BaseException:
            if self.db.in_transaction:
                self.db.execute("ROLLBACK")
            raise

    @staticmethod
    def _required(**values):
        if any(not isinstance(v, str) or not v.strip() for v in values.values()):
            raise ValueError("Nonempty strings required: " + ', '.join(values))

    def append_event(self, scope, session_id, turn_id, payload, *, event_id=None):
        """Persist one already bounded/redacted observation before acknowledging it.

        Payload policy belongs to the host integration; this storage API does not
        claim to redact arbitrary tool output or validate a task's success.
        """
        self._required(scope=scope, session_id=session_id, turn_id=turn_id)
        event_id = event_id or uuid.uuid4().hex
        encoded = json.dumps(payload, ensure_ascii=False, allow_nan=False)
        with self._write():
            self.db.execute("INSERT INTO events(id,scope,session_id,turn_id,payload) VALUES(?,?,?,?,?)",
                            (event_id, scope, session_id, turn_id, encoded))
        return event_id

    def read_event(self, event_id, scope):
        row = self.db.execute("SELECT * FROM events WHERE id=? AND scope=?", (event_id, scope)).fetchone()
        if row is None:
            raise KeyError(event_id)
        result = dict(row)
        result['payload'] = json.loads(result['payload'])
        result['excluded'] = self.db.execute(
            "SELECT 1 FROM excluded_sources WHERE event_id=?", (event_id,)).fetchone() is not None
        result['excluded'] |= self.db.execute(
            "SELECT 1 FROM excluded_turns WHERE scope=? AND session_id=? AND turn_id=?",
            (row['scope'], row['session_id'], row['turn_id'])).fetchone() is not None
        return result

    def task_state(self, scope, session_id, turn_id):
        """Bounded audit context for an explicit resume, never executable messages."""
        first = self.db.execute('SELECT id FROM events WHERE scope=? AND session_id=? AND turn_id=? ORDER BY rowid LIMIT 1',
                                (scope, session_id, turn_id)).fetchone()
        if first is None or self.read_event(first[0], scope)['excluded']:
            raise KeyError('Task not found in this scope or excluded by forgetting')
        recent = self.db.execute('SELECT id FROM events WHERE scope=? AND session_id=? AND turn_id=? ORDER BY rowid DESC LIMIT 12',
                                 (scope, session_id, turn_id)).fetchall()
        status = 'interrupted_or_running'
        for row in recent:
            payload = self.read_event(row[0], scope)['payload']
            try:
                decoded = json.loads(payload.get('text', '{}'))
            except (ValueError, TypeError):
                continue
            if isinstance(decoded, dict) and decoded.get('type') == 'turn_status':
                status = decoded['status']
                break
        def excerpt(identifier):
            payload = self.read_event(identifier, scope)['payload']
            text = json.dumps(payload, ensure_ascii=False)
            return text.encode('utf-8')[:240].decode('utf-8', errors='ignore')
        return {'status': status, 'session_id': session_id, 'turn_id': turn_id,
                'goal_source': first[0], 'goal_excerpt': excerpt(first[0]),
                'latest_source': recent[0][0], 'latest_excerpt': excerpt(recent[0][0]),
                'truncated': True, 'note': 'Bounded audit reference; inspect sources before action, never replay commands automatically.'}

    def _entry(self, entry_id, scope):
        row = self.db.execute("SELECT * FROM entries WHERE id=? AND scope=?", (entry_id, scope)).fetchone()
        if row is None:
            raise KeyError(entry_id)
        result = dict(row)
        result['source_refs'] = [r[0] for r in self.db.execute(
            "SELECT event_id FROM sources WHERE entry_id=? ORDER BY event_id", (entry_id,))]
        return result

    def read_entry(self, entry_id, scope, *, include_history=False):
        entry = self._entry(entry_id, scope)
        if not include_history and entry['status'] != 'active':
            raise KeyError(entry_id)
        return entry

    def _index(self, entry_id, content, status):
        self.db.execute("DELETE FROM entry_fts WHERE id=?", (entry_id,))
        if status != 'active':
            self.db.execute("DELETE FROM entry_vectors WHERE entry_id=?", (entry_id,))
        if status == 'active':
            self.db.execute("INSERT INTO entry_fts(id,tokens) VALUES(?,?)",
                            (entry_id, ' '.join(memory_terms(content))))

    def remember(self, scope, kind, content, source_refs, *, status='candidate', supersedes=None):
        """Create an entry or exact-ID correction, atomically invalidating old search.

        Activation is a host decision, not a model's self-reported verification.
        A correction cannot change scope or replace an already historical entry.
        """
        self._required(scope=scope, kind=kind, content=content)
        if status not in ('candidate', 'active'):
            raise ValueError("New entries must be candidate or active")
        if status == 'candidate' and self._disk_bytes() >= self.max_bytes * 0.9:
            raise ValueError('Candidate extraction paused near storage capacity')
        refs = list(dict.fromkeys(source_refs))
        if not refs:
            raise ValueError("At least one source event is required")
        entry_id = uuid.uuid4().hex
        with self._write():
            for ref in refs:
                event = self.read_event(ref, scope)
                if event['excluded']:
                    raise ValueError("Forgotten source cannot be extracted again")
            if supersedes is None:
                duplicate = self.db.execute(
                    'SELECT id FROM entries WHERE scope=? AND kind=? AND content=? AND status=? LIMIT 1',
                    (scope, kind, content, status)).fetchone()
                if duplicate:
                    return duplicate[0]
            if supersedes:
                previous = self._entry(supersedes, scope)
                if previous['status'] not in ('active', 'candidate'):
                    raise ValueError("Cannot correct a historical entry")
                if previous['status'] == 'active' and status != 'active':
                    raise ValueError("An unapproved candidate cannot replace an active fact")
                self.db.execute("UPDATE entries SET status='superseded',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                                (supersedes,))
                self._index(supersedes, '', 'superseded')
            self.db.execute("INSERT INTO entries(id,scope,kind,content,status,supersedes) VALUES(?,?,?,?,?,?)",
                            (entry_id, scope, kind, content, status, supersedes))
            self.db.executemany("INSERT INTO sources VALUES(?,?)", [(entry_id, ref) for ref in refs])
            self._index(entry_id, content, status)
        return entry_id

    def set_status(self, entry_id, scope, status, *, audit=None):
        """Explicit host approval or archive. Historical facts cannot be reactivated."""
        if status not in ('active', 'archived'):
            raise ValueError("Only explicit activation or archive is supported")
        with self._write():
            entry = self._entry(entry_id, scope)
            if entry['status'] not in ('candidate', 'active'):
                raise ValueError("Historical entries cannot be reactivated")
            self.db.execute("UPDATE entries SET status=?,updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now') WHERE id=?",
                            (status, entry_id))
            self._index(entry_id, entry['content'], status)
            if audit is not None:
                event_id = uuid.uuid4().hex
                self.db.execute('INSERT INTO events(id,scope,session_id,turn_id,payload) VALUES(?,?,?,?,?)',
                    (event_id, scope, audit['session_id'], audit['turn_id'], json.dumps(audit['payload'], ensure_ascii=False)))
                self.db.execute('INSERT INTO sources VALUES(?,?)', (entry_id, event_id))
                return event_id

    def search(self, query, scope, limit=4):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("Search limit must be between 1 and 50")
        # Quoted tokens are data, never FTS syntax. Bound query work as well as results.
        terms = memory_terms(query)[:64]
        if not terms:
            return []
        match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
        scopes = [scope] if isinstance(scope, str) else list(scope)
        if not scopes:
            return []
        placeholders = ','.join('?' for _ in scopes)
        rows = self.db.execute(f"""
            SELECT e.id,e.scope FROM entry_fts f JOIN entries e ON e.id=f.id
            WHERE entry_fts MATCH ? AND e.scope IN ({placeholders}) AND e.status='active'
            ORDER BY bm25(entry_fts),e.id LIMIT ?
        """, (match, *scopes, limit)).fetchall()
        return [self.read_entry(r[0], r[1]) for r in rows]

    def forget(self, entry_id, scope, *, erase_sources=False):
        """Delete a correction chain and exclude its sources from re-extraction.

        Source erasure refuses shared events instead of silently destroying other
        facts' provenance. Backups and external exports are outside this database.
        """
        with self._write():
            self._entry(entry_id, scope)
            rows = self.db.execute("""
                WITH RECURSIVE chain(id) AS (
                    SELECT ? UNION
                    SELECT e.supersedes FROM entries e JOIN chain c ON e.id=c.id WHERE e.supersedes IS NOT NULL
                    UNION SELECT e.id FROM entries e JOIN chain c ON e.supersedes=c.id
                ) SELECT e.id FROM entries e JOIN chain c ON e.id=c.id WHERE e.scope=?
            """, (entry_id, scope)).fetchall()
            ids = [r[0] for r in rows]
            refs = {r[0] for item in ids for r in self.db.execute(
                "SELECT event_id FROM sources WHERE entry_id=?", (item,))}
            if erase_sources:
                for ref in refs:
                    linked = {r[0] for r in self.db.execute("SELECT entry_id FROM sources WHERE event_id=?", (ref,))}
                    if linked.difference(ids):
                        raise ValueError("Source is shared; explicit wider erasure is required")
            for item in ids:
                self._index(item, '', 'deleted')
                self.db.execute("DELETE FROM entries WHERE id=?", (item,))
            for ref in refs:
                event = self.read_event(ref, scope)
                # Tool intents/observations may repeat the same fact. Exclude the
                # source turn, including later events, from future extraction.
                self.db.execute("INSERT OR IGNORE INTO excluded_turns VALUES(?,?,?)",
                                (scope, event['session_id'], event['turn_id']))
                self.db.execute("INSERT OR IGNORE INTO excluded_sources VALUES(?)", (ref,))
                if erase_sources:
                    self.db.execute("DELETE FROM events WHERE id=? AND scope=?", (ref, scope))

    def rebuild_index(self):
        with self._write():
            self.db.execute("DELETE FROM entry_fts")
            for row in self.db.execute("SELECT id,content,status FROM entries WHERE status='active'"):
                self._index(*row)

    def plan_erasure(self, entry_id, scope):
        """Preview exact source-turn deletion. Does not include other turns or backups."""
        self._entry(entry_id, scope)
        ids = [r[0] for r in self.db.execute("""
            WITH RECURSIVE chain(id) AS (
                SELECT ? UNION SELECT e.supersedes FROM entries e JOIN chain c ON e.id=c.id WHERE e.supersedes IS NOT NULL
                UNION SELECT e.id FROM entries e JOIN chain c ON e.supersedes=c.id
            ) SELECT e.id FROM entries e JOIN chain c ON e.id=c.id WHERE e.scope=? ORDER BY e.id
        """, (entry_id, scope))]
        turns = {tuple(row) for item in ids for row in self.db.execute('''
            SELECT e.session_id,e.turn_id FROM events e JOIN sources s ON s.event_id=e.id WHERE s.entry_id=?
        ''', (item,))}
        events = sorted({r[0] for session, turn in turns for r in self.db.execute(
            'SELECT id FROM events WHERE scope=? AND session_id=? AND turn_id=?', (scope, session, turn))})
        blockers = sorted({r[0] for event in events for r in self.db.execute(
            'SELECT entry_id FROM sources WHERE event_id=?', (event,))} - set(ids))
        plan = {'entry_id': entry_id, 'scope': scope, 'entries': ids, 'events': events,
                'source_turns': sorted(turns), 'blocked_by_entries': blockers,
                'boundary': 'Only this correction chain and its source turns; other turns, external logs, exports and backups excluded'}
        plan['fingerprint'] = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
        return plan

    def erase(self, entry_id, scope, *, approved_fingerprint):
        """Host-only execution of an exact reviewed plan; never called by a model tool."""
        with self._write():
            plan = self.plan_erasure(entry_id, scope)
            if plan['fingerprint'] != approved_fingerprint:
                raise ValueError('Erasure plan changed; review a new preview')
            if plan['blocked_by_entries']:
                raise ValueError('Source turns also support other entries; wider deletion was not authorized')
            for identifier in plan['entries']:
                self._index(identifier, '', 'deleted')
                self.db.execute('DELETE FROM entries WHERE id=?', (identifier,))
            for session, turn in plan['source_turns']:
                self.db.execute('INSERT OR IGNORE INTO excluded_turns VALUES(?,?,?)', (scope, session, turn))
            for identifier in plan['events']:
                self.db.execute('INSERT OR IGNORE INTO excluded_sources VALUES(?)', (identifier,))
                self.db.execute('DELETE FROM events WHERE id=? AND scope=?', (identifier, scope))
        return {'erased_entries': len(plan['entries']), 'erased_events': len(plan['events'])}
