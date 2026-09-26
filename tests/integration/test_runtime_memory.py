"""Real agent/store loop with deterministic model responses, never a remote model."""
import json
import sqlite3
from types import SimpleNamespace as NS

import pytest

from lighthermes.core import LightHermes
from lighthermes.runtime_memory import serialized, token_cost
from lighthermes.tools import tool


class Model:
    model = 'offline'

    def __init__(self, steps):
        self.steps = iter(steps)
        self.seen = []

    def create(self, messages, stream=False, **kwargs):
        self.seen.append([dict(m) for m in messages])
        step = next(self.steps)
        step = step(messages) if callable(step) else step
        if isinstance(step, str):
            content, calls = step, []
        else:
            name, args = step
            content = ''
            calls = [NS(id='call', function=NS(name=name, arguments=json.dumps(args)))]
        if stream:
            deltas = [NS(index=i, id=c.id, function=c.function) for i, c in enumerate(calls)]
            return iter([NS(choices=[NS(delta=NS(content=content, tool_calls=deltas),
                finish_reason='tool_calls' if calls else 'stop')])])
        return NS(choices=[NS(message=NS(content=content, tool_calls=calls))], usage={'total_tokens': 7})


def agent(tmp_path, monkeypatch, steps, **kwargs):
    model = Model(steps)
    monkeypatch.setattr('lighthermes.core.get_adapter', lambda **kw: model)
    instance = LightHermes(api_key='test', memory_dir=str(tmp_path / 'memory'), skill_dirs=[],
        config_path=None, config={'context_compression': {'enabled': False}}, **kwargs)
    return instance, model


def run(instance, query, stream=False, **kwargs):
    result = instance.run(query, stream=stream, **kwargs)
    return ''.join(result) if stream else result


def events(instance):
    return [json.loads(json.loads(r[0])['text']) for r in instance.memory.store.db.execute(
        'SELECT payload FROM events ORDER BY rowid')]


@pytest.mark.parametrize('stream', [False, True])
def test_remember_restart_correct_forget_through_model_tools(tmp_path, monkeypatch, stream):
    first, _ = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'kind': 'preference', 'content': 'Use Python'}), 'Saved'])
    assert run(first, 'Remember: use Python', stream) == 'Saved'
    original = first.memory.store.search('Python', first.memory.scope)[0]
    assert original['source_refs'] == [first.memory.source]
    first.memory.store.close()

    second, model = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'correct', 'id': original['id'], 'content': 'Use Rust'}), 'Corrected',
        ('update_memory', {'action': 'forget', 'id': ''}), 'Forgotten'])
    assert run(second, 'Change Python preference to Rust', stream) == 'Corrected'
    assert 'Use Python' in model.seen[0][0]['content']
    assert not second.memory.store.search('Python', second.memory.scope)
    current = second.memory.store.search('Rust', second.memory.scope)[0]
    # Use the actual receipt's current ID for the next scripted request.
    model.steps = iter([('update_memory', {'action': 'forget', 'id': current['id']}), 'Forgotten'])
    assert run(second, 'Forget my language preference', stream) == 'Forgotten'
    assert not second.memory.store.search('Rust', second.memory.scope)
    assert all('Python' not in m['content'] for m in second.memory.get_context())
    second.memory.store.rebuild_index()
    with pytest.raises(ValueError, match='Forgotten'):
        second.memory.store.remember(second.memory.scope, 'fact', 'Use Python', original['source_refs'], status='active')
    statuses = [e['status'] for e in events(second) if e.get('type') == 'turn_status']
    assert statuses == ['completed', 'completed', 'completed']


def test_scope_switch_and_stable_project_id(tmp_path, monkeypatch):
    a, _ = agent(tmp_path, monkeypatch, [('update_memory', {'action': 'remember', 'content': 'zebralang'}), 'Saved'], project_id='A')
    run(a, 'Remember zebralang', user_id='alice')
    identifier = a.memory.store.search('zebralang', a.memory.scope)[0]['id']
    a.memory.store.close()
    for project, user in [('B', 'alice'), ('A', 'bob')]:
        other, model = agent(tmp_path, monkeypatch, ['Nothing'], project_id=project)
        run(other, 'zebralang', user_id=user)
        assert '<memory-context>' not in model.seen[0][0]['content']
        with pytest.raises(KeyError):
            other.memory.read_memory(identifier)
        other.memory.store.close()
    again, model = agent(tmp_path, monkeypatch, ['Recall'], project_id='A', bash_cwd='/private/tmp')
    run(again, 'zebralang', user_id='alice')
    assert 'zebralang' in model.seen[0][0]['content']
    model.steps = iter(['New user'])
    run(again, 'hello', user_id='bob')
    assert not any('Remember zebralang' in m.get('content', '') for m in model.seen[-1])


def test_candidate_and_unrelated_seed_are_empty(tmp_path, monkeypatch):
    instance, model = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'kind': 'experience', 'content': 'zebra procedure'}), 'Candidate', 'Nothing'])
    run(instance, 'Remember zebra procedure')
    assert not instance.memory.store.search('zebra', instance.memory.scope)
    run(instance, 'zebra', session_id='new')
    assert '<memory-context>' not in model.seen[-1][0]['content']


@pytest.mark.parametrize('stream', [False, True])
def test_events_commit_before_action_and_observation(tmp_path, monkeypatch, stream):
    instance, _ = agent(tmp_path, monkeypatch, [('probe', {}), 'Done'])

    @tool('probe', 'Verify durable intent', [])
    def probe():
        saved = events(instance)
        assert saved[0]['role'] == 'user'
        assert saved[-1]['tool_calls'][0]['function']['name'] == 'probe'
        return 'observation'

    instance.tool_dispatcher.register_tool(probe)
    run(instance, 'Do probe', stream)
    saved = events(instance)
    assert any(e.get('role') == 'tool' and e['content'] == 'observation' for e in saved)
    assert saved[-1] == {'type': 'turn_status', 'status': 'completed'}


@pytest.mark.parametrize('stream', [False, True])
def test_storage_error_stops_before_side_effect(tmp_path, monkeypatch, stream):
    instance, _ = agent(tmp_path, monkeypatch, [('bash', {'command': 'touch should-not-exist'})],
                        bash_cwd=str(tmp_path), bash_authorized=True)
    original = instance.memory.record

    def record(payload):
        if payload.get('tool_calls'):
            raise sqlite3.OperationalError('disk full')
        return original(payload)

    monkeypatch.setattr(instance.memory, 'record', record)
    with pytest.raises(sqlite3.OperationalError, match='disk full'):
        run(instance, 'Run command', stream)
    assert not (tmp_path / 'should-not-exist').exists()
    assert events(instance)[-1]['status'] == 'error'


def test_cancel_stream_persists_partial_text_not_completion(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, ['partial output'])
    stream = instance.run('hello', stream=True)
    assert next(stream) == 'partial output'
    stream.close()
    saved = events(instance)
    assert saved[-2] == {'type': 'assistant_delta', 'content': 'partial output'}
    assert saved[-1]['status'] == 'cancelled'
    assert instance.last_turn['status'] == 'cancelled'
    assert instance.query_count == 0


def test_unused_stream_does_not_start_a_turn(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, ['ordinary'])
    instance.run('never consumed', stream=True).close()
    assert events(instance) == []
    assert run(instance, 'actual') == 'ordinary'


def test_seed_search_read_and_skill_share_budget(tmp_path, monkeypatch):
    instance, model = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'content': 'zebra ' + '汉字代码' * 500}), 'Saved', 'Later'])
    run(instance, 'Remember zebra')
    entry = instance.memory.store.search('zebra', instance.memory.scope)[0]
    instance.skill_loader.match_skill = lambda query: {'content': 'guide' * 1000}
    run(instance, 'zebra', session_id='restart')
    assert instance.memory.remaining >= 1500
    assert token_cost(model.seen[-1][0]['content']) < 3000
    assert json.loads(instance.memory.search_memory('zebra'))['status'] == 'already_in_context'
    output = instance.memory.read_memory(entry['id'])
    assert json.loads(output)['offset'] > 0
    assert instance.memory.remaining >= 0
    instance.memory.search_memory('zebra')
    assert 'budget' in instance.memory.search_memory('zebra').lower()


def test_legacy_guard_does_not_write_into_old_directory(tmp_path, monkeypatch):
    directory = tmp_path / 'memory' / 'semantic'
    directory.mkdir(parents=True)
    old = directory / 'fact.md'
    old.write_text('Old source')
    with pytest.raises(ValueError, match='Legacy memory detected'):
        agent(tmp_path, monkeypatch, [])
    assert old.read_text() == 'Old source'
    assert not (directory.parent / 'lighthermes.sqlite3').exists()


def test_broken_search_fails_turn_instead_of_empty_answer(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, ['Should not be called'])
    instance.memory.store.db.execute('DROP TABLE entry_fts')
    with pytest.raises(sqlite3.OperationalError):
        run(instance, 'zebra')
    assert instance.last_turn['status'] == 'error'
    assert instance.api_call_count == 0


def test_forget_excludes_duplicate_and_later_source_turn_events(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'content': 'Python'}), 'Saved'])
    run(instance, 'Remember Python')
    old = instance.memory.store.search('Python', instance.memory.scope)[0]
    duplicate = instance.memory.record({'role': 'tool', 'content': 'Python'})
    instance.memory.store.forget(old['id'], instance.memory.scope)
    later = instance.memory.record({'role': 'assistant', 'content': 'Python'})
    for ref in (duplicate, later):
        with pytest.raises(ValueError, match='Forgotten'):
            instance.memory.store.remember(instance.memory.scope, 'fact', 'Python', [ref], status='active')


def test_credentials_bounded_in_persisted_events(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, ['Done'])
    run(instance, 'Authorization: Bearer abcdef123456 sk-testsecretkey')
    data = instance.memory.store.db.execute('SELECT payload FROM events').fetchall()
    assert all('abcdef123456' not in row[0] and 'sk-testsecretkey' not in row[0] for row in data)
    ref = instance.memory.record({'role': 'tool', 'content': '界' * 20000})
    saved = instance.memory.store.read_event(ref, instance.memory.scope)
    assert saved['payload']['truncated']
    assert token_cost(saved['payload']['text']) <= 32000


def test_no_keyword_write_or_automatic_setting_change(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, ['No write requested by model'])
    setup = tmp_path / 'memory' / 'USER.md'
    setup.write_text('Human owned setup')
    run(instance, '记住 Python')
    assert setup.read_text() == 'Human owned setup'
    assert not instance.memory.store.search('Python', instance.memory.scope)


@pytest.mark.parametrize('stream', [False, True])
def test_failed_memory_write_cannot_return_saved_reply(tmp_path, monkeypatch, stream):
    instance, _ = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'content': 'Python'}), 'Saved'])
    def failure(*args, **kwargs):
        raise sqlite3.OperationalError('write failed')
    monkeypatch.setattr(instance.memory.store, 'remember', failure)
    with pytest.raises(sqlite3.OperationalError, match='write failed'):
        run(instance, 'Remember Python', stream)
    assert instance.query_count == 0
    assert instance.last_turn['status'] == 'error'


def test_cli_uses_committed_events_and_reset_preserves_database(tmp_path, monkeypatch, capsys):
    from lighthermes.cli import CLI
    instance, model = agent(tmp_path, monkeypatch, ['first', 'second'])
    cli = CLI()
    cli.agent = instance
    monkeypatch.setattr(cli, 'authorize_bash', lambda: None)
    run(instance, 'one', session_id=cli.session_id)
    first = cli.session_id
    cli.show_memory_stats()
    cli.reset_session()
    assert cli.session_id != first
    assert instance.memory.get_context() == []
    run(instance, 'two', session_id=cli.session_id)
    sessions = {r[0] for r in instance.memory.store.db.execute('SELECT session_id FROM events')}
    assert sessions == {first, cli.session_id}
    assert cli.end_session()


def test_tail_search_and_offset_read_through_tools(tmp_path, monkeypatch):
    content = 'intro ' * 800 + 'tailconstraint'
    instance, model = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'content': content}), 'Saved', 'Found'])
    run(instance, 'Remember this long constraint')
    run(instance, 'tailconstraint', session_id='new')
    assert '<memory-context>' in model.seen[-1][0]['content']
    entry = instance.memory.store.search('tailconstraint', instance.memory.scope)[0]
    result = json.loads(instance.memory.read_memory(entry['id'], offset=len(content) - 14))
    assert result['content'] == 'tailconstraint'
    assert not result['more']


def test_explicit_resume_restores_reference_without_replaying_tools(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, [('bash', {'command': 'echo once >> effects'})],
                        bash_cwd=str(tmp_path), bash_authorized=True)
    assert '任务未完成' in run(instance, 'perform task', max_iterations=1)
    prior = (instance.last_turn['session_id'], instance.last_turn['turn_id'])
    instance.memory.store.close()
    resumed, model = agent(tmp_path, monkeypatch, ['Reviewing previous state'],
                           bash_cwd=str(tmp_path), bash_authorized=True)
    run(resumed, 'Resume after checking saved state', resume_from=prior)
    assert '旧任务审计参考' in model.seen[0][0]['content']
    assert (tmp_path / 'effects').read_text() == 'once\n'
    assert resumed.memory.remaining >= 0
    # Scope cannot be widened by supplying a known turn ID.
    model.steps = iter(['Should not be called'])
    with pytest.raises(KeyError):
        run(resumed, 'Resume', user_id='another-user', resume_from=prior)


def test_model_erase_only_previews_and_does_not_delete_sources(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, [
        ('update_memory', {'action': 'remember', 'content': 'Python'}), 'Saved'])
    run(instance, 'Remember Python')
    entry = instance.memory.store.search('Python', instance.memory.scope)[0]
    preview = json.loads(instance.memory.update_memory('erase', id=entry['id']))
    assert preview['requires_host_confirmation']
    assert instance.memory.store.read_entry(entry['id'], instance.memory.scope)


def test_stream_usage_trailer_is_counted_before_completion(tmp_path, monkeypatch):
    instance, model = agent(tmp_path, monkeypatch, [])
    model.create = lambda **kwargs: iter([
        NS(choices=[NS(delta=NS(content='Done', tool_calls=[]), finish_reason='stop')]),
        NS(choices=[], usage=NS(total_tokens=123)),
    ])
    assert run(instance, 'hello', stream=True) == 'Done'
    assert instance.total_tokens_used == 123


@pytest.mark.parametrize('stream', [False, True])
def test_truncated_model_response_is_not_completed(tmp_path, monkeypatch, stream):
    instance, model = agent(tmp_path, monkeypatch, [])
    def response(**kwargs):
        if stream:
            return iter([NS(choices=[NS(delta=NS(content='partial', tool_calls=[]), finish_reason='length')])])
        return NS(choices=[NS(message=NS(content='partial', tool_calls=[]), finish_reason='length')], usage=None)
    model.create = response
    assert '任务未完成' in run(instance, 'hello', stream=stream)
    assert instance.last_turn['status'] == 'incomplete'
    assert instance.query_count == 0


def test_empty_search_is_explicit_and_does_not_imply_tool_failure(tmp_path, monkeypatch):
    instance, _ = agent(tmp_path, monkeypatch, ['hello'])
    run(instance, 'hello')
    first = json.loads(instance.memory.search_memory('unrelated'))
    assert first == {'status': 'no_match', 'remaining_searches': 1}
    instance.memory.search_memory('unrelated')
    assert json.loads(instance.memory.search_memory('unrelated'))['status'] == 'budget_exhausted'


def test_read_metadata_and_search_do_not_spin_at_low_budget(tmp_path, monkeypatch):
    from lighthermes.tools import ToolBudgetExceeded
    instance, _ = agent(tmp_path, monkeypatch, [('update_memory', {'action': 'remember', 'content': 'x' * 500}), 'Saved'])
    run(instance, 'Remember')
    entry = instance.memory.store.db.execute('SELECT id FROM entries').fetchone()[0]
    instance.memory.remaining = 160
    with pytest.raises(ToolBudgetExceeded):
        instance.memory.read_memory(entry)
    instance.memory.remaining = 170
    instance.memory.offsets.clear()
    with pytest.raises(ToolBudgetExceeded):
        instance.memory.search_memory('x' * 500)


@pytest.mark.parametrize('stream', [False, True])
def test_natural_decision_semantic_recall_across_sessions(tmp_path, monkeypatch, stream):
    """Scripted model and vectors verify wiring, not autonomous extraction quality."""
    embedded = []
    def embed(texts):
        embedded.extend(texts)
        return [[1, 0] if text in ('统一使用 uv', '怎样装依赖') else [0, 1] for text in texts]
    config = {'context_compression': {'enabled': False},
              'memory': {'semantic': {'model': 'fixture', 'embed': embed}}}
    first_model = Model([('update_memory', {'action': 'capture', 'kind': 'decision',
        'content': '统一使用 uv', 'evidence': '统一使用 uv'}), '已保存项目决定'])
    monkeypatch.setattr('lighthermes.core.get_adapter', lambda **kw: first_model)
    first = LightHermes(api_key='test', memory_dir=str(tmp_path / 'memory'),
                       config=config, project_id='project-a', skill_dirs=[])
    run(first, '这个项目统一使用 uv。', stream)
    assert 'capture' in first_model.seen[0][0]['content']
    assert embedded == ['统一使用 uv']
    first.memory.store.close()
    second_model = Model(['使用 uv', '没有相关记忆'])
    monkeypatch.setattr('lighthermes.core.get_adapter', lambda **kw: second_model)
    second = LightHermes(api_key='test', memory_dir=str(tmp_path / 'memory'),
                        config=config, project_id='project-a', skill_dirs=[])
    assert not second.memory.store.search('怎样装依赖', serialized(['project', 'default_user', 'project-a']))
    run(second, '怎样装依赖', stream)
    assert '统一使用 uv' in second_model.seen[0][0]['content']
    assert embedded == ['统一使用 uv', '怎样装依赖']
    run(second, '天气', stream, session_id='irrelevant')
    assert '统一使用 uv' not in second_model.seen[-1][0]['content']
    second.memory.store.close()
