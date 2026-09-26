"""Small, independent semantic candidate channel over scoped SQLite vectors.

Exact local cosine scan (O(n) in scoped indexed entries), no ANN or second cache.
Remote work is bounded to 16 changed entries and 3 queries per turn. Missing
vectors remain visibly partial; failures leave lexical retrieval available.
"""
import hashlib
import heapq
import json
import math
import sqlite3


class SemanticIndex:
    def __init__(self, store, *, model, api_key=None, base_url=None, min_score=0.75, embed=None):
        if not isinstance(model, str) or not model.strip():
            raise ValueError('memory.semantic.model must be explicit')
        if not isinstance(min_score, (int, float)) or isinstance(min_score, bool) or not 0 < min_score <= 1:
            raise ValueError('memory.semantic.min_score must be in (0, 1]')
        self.store, self.min_score = store, min_score
        if embed is None:
            from openai import OpenAI
            client = OpenAI(api_key=api_key, base_url=base_url, timeout=15, max_retries=0)
            base_url = str(client.base_url)

            def embed(texts):
                response = client.embeddings.create(model=model, input=texts)
                items = sorted(response.data, key=lambda item: item.index)
                if [item.index for item in items] != list(range(len(texts))):
                    raise ValueError('Embedding response indices do not match input')
                return [item.embedding for item in items]
        self.key = hashlib.sha256(json.dumps([base_url, model]).encode()).hexdigest()
        self.embed = embed
        self.begin()

    def begin(self):
        self.remaining = 16
        self.queries = {}
        self.query_calls = 0
        self.status = {'mode': 'partial', 'pending': None}

    def _vectors(self, texts):
        vectors = self.embed(texts)
        if len(vectors) != len(texts):
            raise ValueError('Embedding count mismatch')
        normalized = []
        for vector in vectors:
            if not 1 <= len(vector) <= 8192 or any(
                isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector
            ):
                raise ValueError('Invalid embedding vector')
            norm = math.hypot(*vector)
            if not math.isfinite(norm) or norm == 0:
                raise ValueError('Invalid embedding norm')
            normalized.append([x / norm for x in vector])
        if len({len(v) for v in normalized}) > 1:
            raise ValueError('Embedding dimension mismatch')
        return normalized

    def index(self, scopes):
        slots = ','.join('?' for _ in scopes)
        pending = f"""FROM entries e LEFT JOIN entry_vectors v
            ON e.id=v.entry_id AND v.model=?
            WHERE e.scope IN ({slots}) AND e.status='active' AND v.entry_id IS NULL"""
        args = (self.key, *scopes)
        count = self.store.db.execute('SELECT count(*) ' + pending, args).fetchone()[0]
        rows = self.store.db.execute('SELECT e.id,e.content ' + pending + ' ORDER BY e.rowid LIMIT ?',
                                     (*args, self.remaining)).fetchall()
        if rows:
            self.remaining -= len(rows)
            try:
                vectors = self._vectors([r['content'] for r in rows])
            except Exception as exc:
                self.status = {'mode': 'lexical', 'pending': count, 'error': type(exc).__name__}
                return False
            with self.store._write():
                for row, vector in zip(rows, vectors):
                    self.store.db.execute('INSERT OR REPLACE INTO entry_vectors VALUES(?,?,?)',
                                          (row['id'], self.key, json.dumps(vector)))
        self.status = {'mode': 'partial' if count > len(rows) else 'hybrid', 'pending': count - len(rows)}
        return True

    def search(self, query, scopes, lexical, limit):
        if not self.index(scopes):
            return lexical[:limit]
        slots = ','.join('?' for _ in scopes)
        sql = f"""SELECT e.id,e.scope,v.vector FROM entry_vectors v JOIN entries e ON e.id=v.entry_id
            WHERE v.model=? AND e.status='active' AND e.scope IN ({slots})"""
        # No query request when no scoped vector can possibly match.
        if not self.store.db.execute(sql + ' LIMIT 1', (self.key, *scopes)).fetchone():
            return lexical[:limit]
        query = query.encode('utf-8')[:8000].decode('utf-8', errors='ignore')
        try:
            if query not in self.queries:
                if self.query_calls >= 3:
                    raise ValueError('Semantic query budget exhausted')
                self.query_calls += 1
                self.queries[query] = self._vectors([query])[0]
            vector = self.queries[query]
            def scored():
                for row in self.store.db.execute(sql, (self.key, *scopes)):
                    cached = json.loads(row['vector'])
                    if len(cached) != len(vector):
                        raise ValueError('Cached embedding dimension changed; use a new model identifier')
                    score = sum(a * b for a, b in zip(cached, vector))
                    if score >= self.min_score:
                        yield (score, row['id'], row['scope'])
            matches = heapq.nlargest(50, scored())
        except sqlite3.Error:
            raise
        except Exception as exc:
            self.status = {**self.status, 'mode': 'lexical', 'error': type(exc).__name__}
            return lexical[:limit]
        semantic = [self.store.read_entry(identifier, scope) for _, identifier, scope in matches]
        # Equal-weight reciprocal rank fusion; frequency is not evidence of truth.
        scores, entries = {}, {}
        for channel in (lexical, semantic):
            for rank, row in enumerate(channel, 1):
                identifier = row['id']
                entries[identifier] = row
                scores[identifier] = scores.get(identifier, 0) + 1 / (60 + rank)
        return [entries[i] for i in sorted(scores, key=lambda i: (-scores[i], i))[:limit]]
