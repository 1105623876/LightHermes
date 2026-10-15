"""Host-verified learning and reuse with deterministic extraction; no live API."""
import json
import os
import shlex
import sqlite3
import sys
from types import SimpleNamespace as NS

import pytest

from lighthermes.core import LightHermes
from lighthermes.experience import Experience

CANDIDATE = json.dumps({'applicable_when': '处理带 UTF-8 BOM 的 CSV 文件',
    'procedure': '使用 utf-8-sig 编码读取，避免首列名称包含 BOM',
    'verification': '检查列名正确且所有行数保持不变'}, ensure_ascii=False)


class Model:
    model = 'offline'
    def __init__(self, responses):
        self.responses = iter(responses)
        self.seen = []
    def create(self, messages, **kwargs):
        self.seen.append(messages)
        response = next(self.responses)
        if isinstance(response, Exception):
            raise response
        calls = [NS(id=f'call-{len(self.seen)}-{i}', function=NS(name='bash',
            arguments=json.dumps({'command': command}))) for i, command in enumerate(response)] if isinstance(response, list) else []
        return NS(choices=[NS(message=NS(content='' if calls else response, tool_calls=calls),
                             finish_reason='tool_calls' if calls else 'stop')],
                  usage=NS(total_tokens=10))


def agent(tmp_path, monkeypatch, responses, project='A'):
    model = Model(responses)
    monkeypatch.setattr('lighthermes.core.get_adapter', lambda **kw: model)
    instance = LightHermes(api_key='test', memory_dir=str(tmp_path / 'memory'),
        project_id=project, evolution_enabled=True, skill_dirs=[], config={'context_compression': {'enabled': False}})
    return instance, model


def learn(instance):
    instance.run('修复 CSV 的 BOM 列名问题')
    return instance.learn('宿主检查：列名和行数断言通过', outcome='verified_success')['entry_id']


def test_candidate_trial_approval_recall_revoke_and_sources(tmp_path, monkeypatch):
    a, model = agent(tmp_path, monkeypatch, ['fixed', CANDIDATE, 'ordinary', 'used', 'recall', 'after revoke'])
    identifier = learn(a)
    assert not a.memory.store.search('BOM', a.memory.scope)
    with pytest.raises(ValueError, match='relabelled'):
        a.memory.update_memory('correct', id=identifier, content='promoted procedure', kind='fact')
    with pytest.raises(ValueError, match='successful adopted trial'):
        a.review_experience(identifier, action='approve', reason='candidate not yet tried')
    a.run('BOM', session_id='ordinary')
    assert 'utf-8-sig' not in model.seen[-1][0]['content']
    a.run('另一个带 BOM 的 CSV', session_id='trial', trial_experience=identifier)
    assert 'trial_only' in model.seen[-1][0]['content']
    assert 'utf-8-sig' in model.seen[-1][0]['content']
    count = len(model.seen)
    receipt = a.learn('检查独立文件列名通过；实际采用 utf-8-sig', outcome='verified_success', adopted=True)
    assert receipt['status'] == 'trial_reviewed' and len(model.seen) == count
    a.review_experience(identifier, action='approve', reason='认可仅适用于 BOM CSV 的方法')
    entry = a.memory.store.read_entry(identifier, a.memory.scope)
    types = [Experience.decode(a.memory.store.read_event(ref, a.memory.scope)).get('type') for ref in entry['source_refs']]
    assert types.count('task_outcome') == 2 and 'experience_review' in types
    a.run('BOM CSV', session_id='active')
    assert 'utf-8-sig' in model.seen[-1][0]['content']
    a.review_experience(identifier, action='revoke', reason='撤回试用经验')
    a.memory.store.rebuild_index()
    a.run('BOM CSV', session_id='after')
    assert 'utf-8-sig' not in model.seen[-1][0]['content']
    with pytest.raises(ValueError):
        a.run('BOM CSV', trial_experience=identifier)


@pytest.mark.parametrize('response', [TimeoutError('secret should not leak'), 'not JSON', 'null'])
def test_extraction_failure_does_not_change_answer_or_retry(tmp_path, monkeypatch, response):
    a, model = agent(tmp_path, monkeypatch, ['delivered', response])
    assert a.run('do task') == 'delivered'
    receipt = a.learn('验收尚未完成')
    assert receipt['status'] in ('extraction_failed', 'no_candidate')
    assert a.last_turn['status'] == 'completed'
    assert 'secret' not in json.dumps(receipt)
    assert a.learn('重复关闭时调用')['status'] == 'already_attempted'
    assert len(model.seen) == 2
    a.memory.store.close()
    reopened, other = agent(tmp_path, monkeypatch, [])
    # Reattach the exact checkpoint as a host recovering its own finished task.
    reopened.memory.begin('recover', 'default_user', 'new')
    reopened.memory.turn_id = a.memory.turn_id
    reopened.memory.session_id = a.memory.session_id
    reopened.memory.source = a.memory.source
    reopened.last_turn = dict(a.last_turn)
    assert reopened.learn('显式恢复同一任务')['status'] == 'already_attempted'
    assert not other.seen


@pytest.mark.parametrize('outcome,adopted', [('verified_success', False), ('verified_failure', True), ('unknown', True)])
def test_recall_or_failed_trial_is_not_successful_adoption(tmp_path, monkeypatch, outcome, adopted):
    a, _ = agent(tmp_path, monkeypatch, ['fixed', CANDIDATE, 'trial'])
    identifier = learn(a)
    a.run('trial', trial_experience=identifier)
    a.learn('具体检查结果', outcome=outcome, adopted=adopted)
    with pytest.raises(ValueError, match='successful adopted trial'):
        a.review_experience(identifier, action='approve', reason='不能凭召回激活')


def test_trial_cannot_cross_scope_and_normal_read_cannot_read_candidate(tmp_path, monkeypatch):
    a, _ = agent(tmp_path, monkeypatch, ['fixed', CANDIDATE])
    identifier = learn(a)
    with pytest.raises(KeyError):
        a.memory.read_memory(identifier)
    b, _ = agent(tmp_path, monkeypatch, [], project='B')
    with pytest.raises(KeyError):
        b.run('trial', trial_experience=identifier)


def test_forgotten_task_not_extracted_and_failed_audit_is_atomic(tmp_path, monkeypatch):
    a, _ = agent(tmp_path, monkeypatch, ['done'])
    a.run('task')
    entry = a.memory.store.remember(a.memory.scope, 'fact', 'fact', [a.memory.source], status='active')
    a.memory.store.forget(entry, a.memory.scope)
    with pytest.raises(ValueError, match='Forgotten'):
        a.learn('do not call model')
    assert a.api_call_count == 1


def test_cli_exposes_explicit_checkpoint_trial_and_adoption(tmp_path, monkeypatch, capsys):
    from lighthermes.cli import CLI
    a, _ = agent(tmp_path, monkeypatch, ['fixed', CANDIDATE, 'trial'])
    a.run('fix BOM CSV')
    cli = CLI(); cli.agent = a
    assert cli.handle_command('/learn success 已检查列名和行数')
    identifier = a.experiences()[0]['id']
    assert cli.handle_command('/experiences')
    assert cli.handle_command(f'/trial {identifier} 第二个 BOM CSV')
    assert cli.handle_command('/learn used-success 已采用该编码并通过独立文件检查')
    assert cli.handle_command(f'/approve {identifier} 限定为 BOM CSV')
    assert a.memory.store.read_entry(identifier, a.memory.scope)['status'] == 'active'
    assert cli.handle_command(f'/revoke {identifier} 验收结束')
    assert not a.memory.store.search('BOM', a.memory.scope)
    assert 'candidate' in capsys.readouterr().out


def test_review_and_trial_feedback_are_atomic_and_revocation_blocks_read(tmp_path, monkeypatch):
    import sqlite3
    a, _ = agent(tmp_path, monkeypatch, ['fixed', CANDIDATE, 'trial'])
    identifier = learn(a)
    a.run('another BOM CSV', trial_experience=identifier)
    assert 'utf-8-sig' in json.loads(a.memory.read_memory(identifier, offset=0))['content']
    a.learn('独立检查通过', outcome='verified_success', adopted=True)
    with pytest.raises(sqlite3.IntegrityError):
        a.memory.store.set_status(identifier, a.memory.scope, 'active',
            audit={'session_id': None, 'turn_id': a.memory.turn_id, 'payload': {}})
    assert not a.memory.store.search('BOM', a.memory.scope)
    a.review_experience(identifier, action='revoke', reason='撤回')
    with pytest.raises(KeyError):
        a.memory.read_memory(identifier, offset=0)


@pytest.mark.parametrize('activate_first', [False, True])
def test_later_failed_adoption_blocks_approval_and_withdraws_active(tmp_path, monkeypatch, activate_first):
    a, _ = agent(tmp_path, monkeypatch, ['fixed', CANDIDATE, 'success', 'regression'])
    identifier = learn(a)
    a.run('success', trial_experience=identifier)
    a.learn('通过独立检查', outcome='verified_success', adopted=True)
    if activate_first:
        a.review_experience(identifier, action='approve', reason='认可适用范围')
    a.run('regression', trial_experience=identifier)
    a.learn('已采用方法但目标检查失败，需要撤回判断', outcome='verified_failure', adopted=True)
    assert not a.memory.store.search('BOM', a.memory.scope)
    with pytest.raises(ValueError):
        a.review_experience(identifier, action='approve', reason='不能只看早期成功忽略后来失败')


def test_many_sources_do_not_break_trial_or_read_budget(tmp_path, monkeypatch):
    a, model = agent(tmp_path, monkeypatch, ['start', 'trial'])
    a.run('start')
    refs = [a.memory.store.append_event(a.memory.scope, 'history', str(i), {'content': 'evidence'}) for i in range(60)]
    identifier = a.memory.store.remember(a.memory.scope, 'experience', CANDIDATE, refs)
    a.run('BOM CSV', trial_experience=identifier)
    prompt = model.seen[-1][0]['content']
    assert '"source_count":60' in prompt and '"status":"trial_only"' in prompt
    result = json.loads(a.memory.read_memory(identifier, offset=0))
    assert result['source_count'] == 60 and len(result['source_refs']) == 8
    assert a.memory.remaining >= 0


def test_explicit_disable_overrides_config_and_makes_no_learning_call(tmp_path, monkeypatch):
    model = Model(['answered'])
    monkeypatch.setattr('lighthermes.core.get_adapter', lambda **kw: model)
    a = LightHermes(api_key='test', memory_dir=str(tmp_path / 'memory'), skill_dirs=[],
        evolution_enabled=False, config={'evolution': {'enabled': True}, 'context_compression': {'enabled': False}})
    a.run('task')
    with pytest.raises(ValueError, match='evolution.enabled'):
        a.learn('must not request extraction')
    assert len(model.seen) == 1


def python_command(code):
    return f'{shlex.quote(sys.executable)} -c {shlex.quote(code)}'


@pytest.mark.parametrize('family', ['bytes', 'transaction'])
@pytest.mark.skipif(os.name != 'posix', reason='Real bash replay requires POSIX')
def test_actual_bash_failure_repair_and_trial_keep_actions_as_learning_sources(tmp_path, monkeypatch, family):
    """Fixed, reviewed commands verify evidence plumbing, not model learning quality."""
    if family == 'bytes':
        raw = b'\xef\xbb\xbfkey=old\r\ncount=1\r\n'
        (tmp_path / 'input').write_bytes(raw)
        bad = "from pathlib import Path as P; P('output').write_text(P('input').read_text().replace('old','new')); assert P('output').read_bytes()==P('input').read_bytes().replace(b'old',b'new')"
        fixed = "from pathlib import Path as P; P('output').write_bytes(P('input').read_bytes().replace(b'old',b'new')); print('verified')"
        second = "from pathlib import Path as P; P('output2').write_bytes(P('input2').read_bytes().replace(b'before',b'after')); print('verified')"
        candidate = {'applicable_when': '已知字节串替换，要求保留输入其余字节',
            'procedure': '按字节读取和替换再写出，不用会转换换行的文本读写',
            'verification': '对照输入，只允许目标字节变化'}
        method = 'write_bytes'
    else:
        for filename, value in [('items.db', 'base'), ('trial.db', 'before')]:
            connection = sqlite3.connect(tmp_path / filename)
            connection.execute('CREATE TABLE items(id TEXT UNIQUE)')
            connection.execute('INSERT INTO items VALUES (?)', (value,))
            connection.commit(); connection.close()
        bad = "import sqlite3\nc=sqlite3.connect('items.db',isolation_level=None)\ntry:c.executemany('INSERT INTO items VALUES (?)',[('new',),('base',)])\nexcept sqlite3.IntegrityError:pass\nassert c.execute('SELECT id FROM items').fetchall()==[('base',)]"
        fixed = "import sqlite3\nc=sqlite3.connect('items.db',isolation_level=None)\nc.execute(\"DELETE FROM items WHERE id='new'\")\nc.execute('SAVEPOINT b')\ntry:c.executemany('INSERT INTO items VALUES (?)',[('new',),('base',)])\nexcept sqlite3.IntegrityError:c.execute('ROLLBACK TO b')\nc.execute('RELEASE b')\nprint('verified')"
        second = "import sqlite3\nc=sqlite3.connect('trial.db')\nc.execute(\"INSERT INTO items VALUES ('pending')\")\nc.execute('SAVEPOINT b')\ntry:c.executemany('INSERT INTO items VALUES (?)',[('temp',),('before',)])\nexcept sqlite3.IntegrityError:c.execute('ROLLBACK TO b')\nc.execute('RELEASE b')\nassert c.execute('SELECT count(*) FROM items').fetchone()[0]==2\nc.rollback()\nassert c.execute('SELECT id FROM items').fetchall()==[('before',)]\nprint('verified')"
        candidate = {'applicable_when': 'SQLite批量插入必须失败整体撤销且保留调用者事务',
            'procedure': '使用SAVEPOINT包围本次批量操作；失败ROLLBACK TO后RELEASE，不提交调用者事务',
            'verification': '失败后原有数据和调用者待提交更改仍在，调用者仍可自行回滚'}
        method = 'SAVEPOINT'
    a, model = agent(tmp_path, monkeypatch, [[python_command(bad)], [python_command(fixed)],
        '已修复', json.dumps(candidate, ensure_ascii=False), [python_command(second)], '独立试用完成'])
    a.bash.authorized = True
    try:
        a.run(candidate['applicable_when'])
        tools = [json.loads(m['content']) for m in a.last_turn['messages'] if m['role'] == 'tool']
        assert [r['status'] for r in tools] == ['failed', 'completed']
        if family == 'bytes':
            assert (tmp_path / 'input').read_bytes() == raw
            assert (tmp_path / 'output').read_bytes() == raw.replace(b'old', b'new')
        else:
            with sqlite3.connect(tmp_path / 'items.db') as db:
                assert db.execute('SELECT id FROM items').fetchall() == [('base',)]
        receipt = a.learn('宿主独立核验产物和原始数据；失败已修复，固定目标检查通过', outcome='verified_success')
        evidence = json.loads(model.seen[-1][1]['content'])['observations']
        assert len(evidence) == 2
        assert method in json.dumps(evidence), 'Learning must see the verified method, not just its exit output'
        assert all(not item['action_missing'] for item in evidence)
        assert method in evidence[1]['action']
        assert 'failed' in evidence[0]['observation']
        entry = a.memory.store.read_entry(receipt['entry_id'], a.memory.scope, include_history=True)
        assert entry['status'] == 'candidate'
        for item in evidence:
            assert item['id'] in entry['source_refs'] and item['action_source'] in entry['source_refs']
            source = Experience.decode(a.memory.store.read_event(item['action_source'], a.memory.scope))
            assert source['role'] == 'assistant' and source['tool_calls']
        if family == 'bytes':
            (tmp_path / 'input2').write_bytes(b'key=before\r\nend\r\n')
        a.run('用独立输入试用该适用方法', session_id='independent', trial_experience=entry['id'])
        if family == 'bytes':
            assert (tmp_path / 'output2').read_bytes() == b'key=after\r\nend\r\n'
            assert (tmp_path / 'input2').read_bytes() == b'key=before\r\nend\r\n'
        else:
            with sqlite3.connect(tmp_path / 'trial.db') as db:
                assert db.execute('SELECT id FROM items').fetchall() == [('before',)]
        calls = len(model.seen)
        assert a.learn('宿主核对实际方法采用且独立目标检查通过', outcome='verified_success', adopted=True)['status'] == 'trial_reviewed'
        assert len(model.seen) == calls
        assert a.review_experience(entry['id'], action='approve', reason='仅认可本次已核验适用范围')['status'] == 'active'
    finally:
        a.memory.store.close()


def intent(identifier, command):
    return {'role': 'assistant', 'tool_calls': [{'id': identifier, 'function': {
        'name': 'bash', 'arguments': json.dumps({'command': command}, ensure_ascii=False)}}]}


def test_learning_pairs_same_batch_and_never_borrows_other_turn_or_excluded_action(tmp_path, monkeypatch):
    a, model = agent(tmp_path, monkeypatch, ['done', CANDIDATE])
    a.run('current task')
    m = a.memory
    m.store.append_event(m.scope, m.session_id, 'other-turn', intent('missing', 'OTHER_TURN'))
    m.store.append_event('other-scope', m.session_id, m.turn_id, intent('missing', 'OTHER_SCOPE'))
    m.record({'role': 'tool', 'tool_call_id': 'missing', 'content': 'orphan result'})
    first = m.record(intent('same', 'FIRST_COMMAND'))
    m.record({'role': 'tool', 'tool_call_id': 'same', 'content': 'first result'})
    excluded = m.record(intent('same', 'EXCLUDED_COMMAND'))
    m.store.db.execute('INSERT INTO excluded_sources VALUES(?)', (excluded,))
    m.record({'role': 'tool', 'tool_call_id': 'same', 'content': 'second result'})
    receipt = a.learn('宿主反馈：证据存在缺口，不能认定已验证', outcome='unknown')
    observations = json.loads(model.seen[-1][1]['content'])['observations']
    assert [r['action_missing'] for r in observations] == [True, False, True]
    assert observations[1]['action_source'] == first
    assert all('OTHER_' not in r['action'] and 'EXCLUDED' not in r['action'] for r in observations)
    entry = m.store.read_entry(receipt['entry_id'], m.scope, include_history=True)
    assert excluded not in entry['source_refs'] and first in entry['source_refs']
    m.store.close()


def test_learning_action_output_budget_and_lookback_are_bounded(tmp_path, monkeypatch):
    a, model = agent(tmp_path, monkeypatch, ['done', 'null'])
    a.run('current task')
    for i in range(20):
        a.memory.record(intent(str(i), f'command{i} ' + '界' * 2000))
        a.memory.record({'role': 'tool', 'tool_call_id': str(i), 'content': f'output{i} ' + '文' * 2000})
    a.learn('宿主尚未验证，不允许按截断内容猜测', outcome='unknown')
    observations = json.loads(model.seen[-1][1]['content'])['observations']
    assert len(observations) == 6
    for i, item in enumerate(observations, 14):
        assert f'command{i} ' in item['action'] and f'output{i} ' in item['observation']
        assert len(item['action'].encode()) + len(item['observation'].encode()) <= 1000
        assert item['truncated'] and not item['action_missing']
    a.memory.store.close()


def test_learning_uses_redacted_persisted_arguments(tmp_path, monkeypatch):
    a, model = agent(tmp_path, monkeypatch, ['done', 'null'])
    a.run('current task')
    secret = 'sk-fixtureSecret123456'
    a.memory.record(intent('one', f'echo {secret}'))  # Record only; never execute this command.
    a.memory.record({'role': 'tool', 'tool_call_id': 'one', 'content': 'done'})
    a.learn('宿主尚未验证', outcome='unknown')
    request = model.seen[-1][1]['content']
    assert secret not in request and '[REDACTED]' in request
    a.memory.store.close()
