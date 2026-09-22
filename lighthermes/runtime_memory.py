"""Single runtime path for R2 memory; host owns scopes and provenance."""
import json
import re
import uuid
from pathlib import Path
from types import SimpleNamespace

from .store import MemoryStore
from .tools import ToolBudgetExceeded, tool

DEFAULT_USER_ID = 'default_user'


def token_cost(text):
    # Conservative byte-based upper estimate, including CJK/code/JSON punctuation.
    # Deliberately not a provider tokenizer or a claim about billed tokens.
    return len(text.encode('utf-8'))


def clip(text, budget):
    return text.encode('utf-8')[:max(0, budget)].decode('utf-8', errors='ignore')


def serialized(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'))


def protect(payload):
    """Bound and redact common credential forms, not arbitrary secret detection."""
    text = serialized(payload)
    text = re.sub(r'(?i)(bearer\s+)[A-Za-z0-9_.\-/+]+', r'\1[REDACTED]', text)
    text = re.sub(r'\bsk-[A-Za-z0-9_-]{8,}', '[REDACTED]', text)
    # A JSON envelope preserves validity even when the original observation is clipped.
    return {'text': clip(text, 32000), 'truncated': token_cost(text) > 32000}


class RuntimeMemory:
    def __init__(self, memory_dir, *, max_bytes=256 * 1024 * 1024, project_id=None, log_files=()):
        self.memory_dir = Path(memory_dir)
        legacy = list(self.memory_dir.glob('*.db')) + list(self.memory_dir.glob('*.sqlite*'))
        legacy = [p for p in legacy if p.name != 'lighthermes.sqlite3' and not p.name.startswith('lighthermes.sqlite3-')]
        legacy += list((self.memory_dir / 'semantic').glob('*.md'))
        legacy += list((self.memory_dir / 'episodic').glob('*.md'))
        if legacy:
            raise ValueError('Legacy memory detected; inventory/import required. Use an explicit empty memory_dir for new sessions.')
        if project_id is not None and (not isinstance(project_id, str) or not project_id.strip()):
            raise ValueError('project_id must be a stable nonempty identifier')
        self.project_id = project_id
        self.store = MemoryStore(self.memory_dir / 'lighthermes.sqlite3', max_bytes,
                                 managed_paths=[self.memory_dir, *log_files])
        self.short_term = SimpleNamespace(messages=[])
        self.identity = None
        self.turn_id = None
        self.remaining = 4000
        self.searches = 0
        self.offsets = {}

    def begin(self, query, user_id, session_id):
        if not isinstance(user_id, str) or not user_id.strip():
            raise ValueError('user_id is required')
        identity = (user_id, session_id)
        if identity != self.identity:
            self.short_term.messages.clear()
        self.identity = identity
        user_scope = serialized(['user', user_id])
        self.scope = serialized(['project', user_id, self.project_id]) if self.project_id else user_scope
        self.scopes = list(dict.fromkeys([self.scope, user_scope]))
        self.session_id = session_id
        self.turn_id = uuid.uuid4().hex
        self.remaining, self.searches, self.offsets = 4000, 0, {}
        self.source = self.record({'role': 'user', 'content': query})
        self.short_term.messages.append({'role': 'user', 'content': query})
        return self.turn_id

    def record(self, payload):
        if self.turn_id is None:
            return None
        return self.store.append_event(self.scope, self.session_id, self.turn_id, protect(payload))

    def status(self, status):
        self.record({'type': 'turn_status', 'status': status})

    def finish(self, reply):
        self.record({'role': 'assistant', 'content': reply})
        self.short_term.messages.append({'role': 'assistant', 'content': reply})
        self.short_term.messages = self.short_term.messages[-100:]

    def get_context(self):
        return list(self.short_term.messages)

    def on_session_end(self, *args, **kwargs):
        # Every observation is already committed; closing is not a summary rewrite.
        self.store._check_capacity()

    def _read(self, identifier, *, event=False):
        for scope in self.scopes:
            try:
                if event:
                    row = self.store.read_event(identifier, scope)
                    if row['excluded']:
                        raise KeyError(identifier)
                    return row
                return self.store.read_entry(identifier, scope)
            except KeyError:
                pass
        raise KeyError(identifier)

    def spend(self, text, limit=None):
        result = clip(text, min(self.remaining, limit if limit is not None else self.remaining))
        self.remaining -= token_cost(result)
        return result

    def _results(self, query, limit=4):
        # Bound aggregate candidates to 50 across both scopes.
        rows = []
        for scope in self.scopes:
            rows.extend(self.store.search(query, scope, limit=min(limit, 50 - len(rows))))
            if len(rows) >= limit:
                break
        return rows[:limit]

    def _preview(self, rows, budget):
        parts = []
        for row in rows:
            key = row['id']
            if key in self.offsets:
                continue
            excerpt = clip(row['content'], 400)
            part = serialized({'id': key, 'scope': row['scope'], 'content': excerpt,
                               'source_refs': row['source_refs'], 'length': len(row['content']),
                               'more': len(excerpt) < len(row['content'])})
            if token_cost(part) + 1 > budget:
                break
            parts.append(part)
            budget -= token_cost(part) + 1
            self.offsets[key] = len(excerpt)
        return '\n'.join(parts)

    def seed(self, query):
        return self.spend(self._preview(self._results(query), min(1500, self.remaining)), 1500)

    @tool('search_memory', 'Search current project and user active memory, at most twice per turn. Empty is not proof of absence.', [
        {'name': 'query', 'type': 'string', 'description': 'Lexical search query', 'required': True}])
    def search_memory(self, query):
        if self.remaining < 160:
            raise ToolBudgetExceeded('记忆上下文预算耗尽，任务未完成')
        if self.searches >= 2:
            return self.spend(serialized({'status': 'budget_exhausted', 'instruction': 'No more memory searches this turn; report uncertainty.'}))
        self.searches += 1
        rows = self._results(query, 50)
        preview = self._preview(rows, self.remaining)
        if preview:
            return self.spend(preview)
        if rows and any(row['id'] not in self.offsets for row in rows):
            raise ToolBudgetExceeded('记忆上下文预算耗尽，任务未完成')
        return self.spend(serialized({'status': 'already_in_context' if rows else 'no_match',
                                     'remaining_searches': 2 - self.searches}))

    @tool('read_memory', 'Read active memory or source event by exact ID. Repeated reads continue from previous offset.', [
        {'name': 'id', 'type': 'string', 'description': 'Entry or source event ID', 'required': True},
        {'name': 'source', 'type': 'boolean', 'description': 'Read source event instead of entry', 'required': False},
        {'name': 'offset', 'type': 'integer', 'description': 'Optional character offset for a long record', 'required': False}])
    def read_memory(self, id, source=False, offset=None):
        if self.remaining < 200:
            raise ToolBudgetExceeded('记忆读取预算耗尽，任务未完成')
        row = self._read(id, event=source)
        text = serialized(row['payload']) if source else row['content']
        offset = self.offsets.get(id, 0) if offset is None else offset
        if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
            raise ValueError('offset must be a nonnegative integer')
        excerpt = clip(text[offset:], max(0, self.remaining // 2 - 200))
        # JSON escaping can expand code/control characters; shrink to the exact budget.
        metadata = {'id': id, 'offset': offset, 'status': row.get('status', 'source_event'),
                    'updated_at': row.get('updated_at', row.get('created_at')), 'source_refs': row.get('source_refs', [])}
        if token_cost(serialized({**metadata, 'content': '', 'more': True})) > self.remaining:
            raise ToolBudgetExceeded('记忆读取元数据预算不足，任务未完成')
        while True:
            result = serialized({**metadata, 'content': excerpt, 'more': offset + len(excerpt) < len(text)})
            if token_cost(result) <= self.remaining:
                break
            excerpt = excerpt[:len(excerpt) // 2]
        self.offsets[id] = offset + len(excerpt)
        return self.spend(result)

    @tool('update_memory', 'Only on explicit user request: remember, correct, archive or forget in current scope. Experience/skill remain candidates. Never claim saved after an error.', [
        {'name': 'action', 'type': 'string', 'description': 'remember/correct/archive/forget; erase returns a host-review preview only', 'required': True},
        {'name': 'content', 'type': 'string', 'description': 'Fact or preference content', 'required': False},
        {'name': 'id', 'type': 'string', 'description': 'Exact current-scope ID for correction/removal', 'required': False},
        {'name': 'kind', 'type': 'string', 'description': 'fact/preference/decision/experience/skill', 'required': False}])
    def update_memory(self, action, content='', id=None, kind='fact'):
        # Reserve a complete receipt before any mutation; never truncate a success ID.
        if self.remaining < 200:
            return self.spend('Memory context budget exhausted; no change made.')
        if action in ('remember', 'correct'):
            if token_cost(content) > 8000:
                raise ValueError('Memory entry exceeds 8000 UTF-8 bytes; split the fact explicitly')
            if action == 'correct' and not id:
                raise ValueError('Correction requires an exact ID')
            result = self.store.remember(self.scope, kind, content, [self.source],
                status='candidate' if kind in ('experience', 'skill') else 'active',
                supersedes=id if action == 'correct' else None)
            if action == 'correct':
                self.short_term.messages.clear()
            return self.spend(serialized({'saved': result, 'status': 'candidate' if kind in ('experience', 'skill') else 'active'}))
        if action == 'archive':
            self.store.set_status(id, self.scope, 'archived')
        elif action == 'forget':
            self.store.forget(id, self.scope)
        elif action == 'erase':
            plan = self.store.plan_erasure(id, self.scope)
            return self.spend(serialized({'requires_host_confirmation': True,
                'fingerprint': plan['fingerprint'], 'events': len(plan['events']),
                'entries': len(plan['entries']), 'blocked': bool(plan['blocked_by_entries'])}))
        else:
            raise ValueError('Unknown memory action')
        self.offsets.pop(id, None)
        self.short_term.messages.clear()
        return self.spend(serialized({'done': action, 'id': id}))
