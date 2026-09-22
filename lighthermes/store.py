"""R2 storage foundation. Not yet wired into the agent or legacy data.

All reads require an exact scope; callers combine user/project scopes explicitly.
Events are immutable source records. Only active entries enter lexical search.
No model calls, implicit migration, background maintenance or embedding cache.
"""

import json
import sqlite3
import uuid
from contextlib import contextmanager
from pathlib import Path

from lighthermes.retrieval import tokenize_text


class MemoryStore:
    def __init__(self, path, max_bytes=256 * 1024 * 1024):
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise ValueError("max_bytes must be a positive integer")
        self.path = Path(path)
        self.max_bytes = max_bytes
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA foreign_keys=ON")
            self.db.execute("PRAGMA secure_delete=ON")
            version = self.db.execute("PRAGMA user_version").fetchone()[0]
            if version not in (0, 1):
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
            page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
            self.db.execute(f"PRAGMA max_page_count={max(1, max_bytes // page_size)}")
            self._check_capacity()
        except BaseException:
            self.db.close()
            raise

    def close(self):
        self.db.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _check_capacity(self):
        # Application guard, not an OS quota. Include SQLite's temporary journal.
        total = sum(p.stat().st_size for p in
                    (self.path, Path(str(self.path) + '-journal'),
                     Path(str(self.path) + '-wal'), Path(str(self.path) + '-shm'))
                    if p.exists())
        pages = self.db.execute("PRAGMA page_count").fetchone()[0]
        page_size = self.db.execute("PRAGMA page_size").fetchone()[0]
        if max(total, pages * page_size) > self.max_bytes:
            raise sqlite3.OperationalError("Memory storage capacity exceeded")

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

    def append_event(self, scope, session_id, turn_id, payload):
        """Persist one already bounded/redacted observation before acknowledging it.

        Payload policy belongs to the host integration; this storage API does not
        claim to redact arbitrary tool output or validate a task's success.
        """
        self._required(scope=scope, session_id=session_id, turn_id=turn_id)
        event_id = uuid.uuid4().hex
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
        return result

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
        if status == 'active':
            self.db.execute("INSERT INTO entry_fts(id,tokens) VALUES(?,?)",
                            (entry_id, ' '.join(tokenize_text(content))))

    def remember(self, scope, kind, content, source_refs, *, status='candidate', supersedes=None):
        """Create an entry or exact-ID correction, atomically invalidating old search.

        Activation is a host decision, not a model's self-reported verification.
        A correction cannot change scope or replace an already historical entry.
        """
        self._required(scope=scope, kind=kind, content=content)
        if status not in ('candidate', 'active'):
            raise ValueError("New entries must be candidate or active")
        refs = list(dict.fromkeys(source_refs))
        if not refs:
            raise ValueError("At least one source event is required")
        entry_id = uuid.uuid4().hex
        with self._write():
            for ref in refs:
                event = self.read_event(ref, scope)
                if event['excluded']:
                    raise ValueError("Forgotten source cannot be extracted again")
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

    def set_status(self, entry_id, scope, status):
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

    def search(self, query, scope, limit=4):
        if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 50:
            raise ValueError("Search limit must be between 1 and 50")
        # Quoted tokens are data, never FTS syntax. Bound query work as well as results.
        terms = list(dict.fromkeys(tokenize_text(query)))[:64]
        if not terms:
            return []
        match = ' OR '.join('"' + t.replace('"', '""') + '"' for t in terms)
        rows = self.db.execute("""
            SELECT e.id FROM entry_fts f JOIN entries e ON e.id=f.id
            WHERE entry_fts MATCH ? AND e.scope=? AND e.status='active'
            ORDER BY bm25(entry_fts),e.id LIMIT ?
        """, (match, scope, limit)).fetchall()
        return [self.read_entry(r[0], scope) for r in rows]

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
                self.db.execute("INSERT OR IGNORE INTO excluded_sources VALUES(?)", (ref,))
                if erase_sources:
                    self.db.execute("DELETE FROM events WHERE id=? AND scope=?", (ref, scope))

    def rebuild_index(self):
        with self._write():
            self.db.execute("DELETE FROM entry_fts")
            for row in self.db.execute("SELECT id,content,status FROM entries WHERE status='active'"):
                self._index(*row)
