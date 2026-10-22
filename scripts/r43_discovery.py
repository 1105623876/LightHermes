"""Bounded R4.3 failure discovery; macOS Seatbelt is only an acceptance fixture.

Two synthetic tasks (or one selected case), six chat calls per task, no retries.
Model commands run inside a checked filesystem/network policy. The coordinator
alone holds API credentials, memory, reports and independent verification code.
"""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import shlex
import sys
import tempfile
import time
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lighthermes.bash import BashExecutor
from lighthermes.core import LightHermes


INPUT = b'\xef\xbb\xbfenvironment=staging\r\n# keep this comment\nport=8080\r\n'
EXPECTED = INPUT.replace(b'environment=staging', b'environment=production')
TASKS = {
    'bytes': '读取 input.cfg，把 environment=staging 改为 environment=production，结果写入 output.cfg。'
             '保留原文件的编码标记、每处换行及其他所有内容，不能修改输入。通过 bash 实际完成并自行检查。',
    'transaction': '在当前目录创建 batch.py，提供 insert_batch(connection, rows)。rows 是一列字符串元组的列表，'
             '插入已存在的 items(name TEXT UNIQUE) 表；成功返回 None，约束冲突时原样抛出 sqlite3.IntegrityError。'
             '一次调用必须全部成功或全部撤销。调用者传入的连接可能处于自动提交模式，也可能已有未提交的修改；'
             '必须保留调用者原有修改，不能替调用者提交或回滚整笔事务，不能关闭连接。通过 bash 实现并自行验证。',
}

# Executed in a separate restricted process, never imported into the coordinator.
TRANSACTION_CHECK = '''import json, sqlite3, sys
sys.path.insert(0, '.')
from batch import insert_batch
checks = {}
for mode in ('autocommit', 'caller_transaction'):
    c = sqlite3.connect(':memory:', isolation_level=None if mode == 'autocommit' else '')
    c.execute('CREATE TABLE items(name TEXT UNIQUE)')
    c.execute("INSERT INTO items VALUES ('base')")
    c.commit()
    original = [('base',)]
    if mode == 'caller_transaction':
        c.execute("INSERT INTO items VALUES ('pending')")
        original.append(('pending',))
    raised = False
    try:
        insert_batch(c, [('partial',), ('base',)])
    except sqlite3.IntegrityError:
        raised = True
    checks[mode + '_raises'] = raised
    checks[mode + '_atomic'] = c.execute('SELECT name FROM items ORDER BY rowid').fetchall() == original
    checks[mode + '_return'] = insert_batch(c, [('first',), ('second',)]) is None
    checks[mode + '_success'] = c.execute('SELECT name FROM items ORDER BY rowid').fetchall() == original + [('first',), ('second',)]
    if mode == 'caller_transaction':
        checks['caller_transaction_owned'] = c.in_transaction
        c.rollback()
        checks['caller_rollback'] = c.execute('SELECT name FROM items').fetchall() == [('base',)]
    c.close()
print('R43_CHECKS=' + json.dumps(checks, sort_keys=True))
'''


def sandbox_profile(workspace):
    """Deny by default; allow runtime reads and writes only in this task."""
    reads = [str(workspace.resolve()), str(Path(sys.base_prefix).resolve()),
             '/System/Library', '/System/Cryptexes', '/System/Volumes/Preboot/Cryptexes',
             '/usr/lib', '/usr/bin', '/bin', '/dev', '/private/etc']
    return ('(version 1)(deny default)'
            '(allow process-exec process-fork sysctl-read file-read-metadata)'
            '(allow signal (target same-sandbox))'
            '(allow mach-lookup (global-name "com.apple.logd") (global-name "com.apple.system.logger"))'
            # dyld opens / itself; metadata permission alone causes SIGABRT.
            '(allow file-read* (literal "/"))'
            + ''.join('(allow file-read* file-map-executable (subpath ' + json.dumps(p) + '))' for p in reads)
            + '(allow file-write* (subpath ' + json.dumps(str(workspace.resolve())) + ') (literal "/dev/null"))')


def restricted_executor(workspace):
    """Wrap the existing executor; never pass model text to the outer shell."""
    workspace = workspace.resolve()
    runtime = Path(sys.base_prefix).resolve()
    executor = BashExecutor(workspace, authorized=True, env={
        'PATH': str(runtime / 'bin') + ':/usr/bin:/bin', 'HOME': str(workspace),
        'TMPDIR': str(workspace), 'LANG': 'en_US.UTF-8', 'PYTHONNOUSERSITE': '1',
        'PYTHONDONTWRITEBYTECODE': '1',
    })
    profile = sandbox_profile(workspace)

    def execute(command, cwd=None, timeout=30):
        target = Path(cwd) if cwd is not None else workspace
        if not target.is_absolute():
            target = workspace / target
        if not target.resolve().is_relative_to(workspace):
            raise ValueError('cwd must stay inside this task')
        wrapped = shlex.join(['/usr/bin/sandbox-exec', '-p', profile,
                             '/bin/bash', '--noprofile', '--norc', '-c', command])
        return executor.execute('exec ' + wrapped, cwd=target, timeout=min(float(timeout), 30))
    return execute


def python_command(source):
    return shlex.join([str(Path(sys.executable).resolve()), '-I', '-c', source])


def preflight(root):
    task = root / 'probe'
    task.mkdir()
    outside = root / 'outside.txt'
    outside.write_text('unchanged')
    source = '''import json, socket, sqlite3
from pathlib import Path
Path('inside').write_text('ok')
checks = {'inside_write': Path('inside').read_text() == 'ok',
          'sqlite': sqlite3.connect('probe.db').execute('select 1').fetchone()[0] == 1}
Path('outside-link').symlink_to(OUTSIDE)
for name, operation in [
    ('outside_read_denied', lambda: Path(OUTSIDE).read_text()),
    ('outside_write_denied', lambda: Path(OUTSIDE).write_text('bad')),
    ('symlink_read_denied', lambda: Path('outside-link').read_text()),
    ('symlink_write_denied', lambda: Path('outside-link').write_text('bad')),
    ('data_alias_read_denied', lambda: Path('/System/Volumes/Data' + OUTSIDE).read_text()),
    ('network_denied', lambda: socket.socket().connect(('127.0.0.1', 9))),
]:
    try:
        operation()
        checks[name] = False
    except PermissionError:
        checks[name] = True
print(json.dumps(checks))
'''.replace('OUTSIDE', repr(str(outside)))
    result = restricted_executor(task)(python_command(source))
    try:
        checks = json.loads(result['output'])
    except ValueError:
        checks = {}
    passed = (result['exit_code'] == 0 and len(checks) == 8
              and all(value is True for value in checks.values())
              and outside.read_text() == 'unchanged')
    return {'passed': passed, 'checks': checks, 'execution': result}


def artifact_bytes(path):
    # The coordinator must not follow a model-created link outside the sandbox.
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 1024 * 1024:
        return None
    return path.read_bytes()


def verify(family, workspace, execute):
    if family == 'bytes':
        source = artifact_bytes(workspace / 'input.cfg')
        output = artifact_bytes(workspace / 'output.cfg')
        checks = {'input_unchanged': source == INPUT, 'output_exact': output == EXPECTED}
        return {'artifact_present': output is not None or source != INPUT,
                'passed': all(checks.values()), 'checks': checks}
    module = artifact_bytes(workspace / 'batch.py')
    if module is None:
        return {'artifact_present': False, 'passed': False, 'checks': {}}
    result = execute(python_command(TRANSACTION_CHECK))
    lines = [line for line in result['output'].splitlines() if line.startswith('R43_CHECKS=')]
    try:
        checks = json.loads(lines[-1].split('=', 1)[1]) if lines else {}
    except ValueError:
        checks = {}
    passed = result['exit_code'] == 0 and len(checks) == 10 and all(value is True for value in checks.values())
    return {'artifact_present': True, 'passed': passed, 'checks': checks, 'execution': result}


def discover(root, report, flush):
    for family in report['selected_cases']:
        task = TASKS[family]
        workspace = root / family
        workspace.mkdir()
        if family == 'bytes':
            (workspace / 'input.cfg').write_bytes(INPUT)
        item = {'family': family, 'task': task, 'chat_calls': 0, 'actions': [], 'requests': []}
        report['cases'].append(item)
        agent = LightHermes.from_config(str(ROOT / 'config.yaml'),
            memory_dir=str(root / ('memory-' + family)), project_id='r43-' + family,
            evolution_enabled=False, skill_dirs=[], log_file=None, fallback_models=[],
            bash_authorized=True, bash_cwd=str(workspace),
            role='完成当前任务并如实报告。bash 已限制在临时任务目录，网络不可用；可用 Python 标准库。',
            config={'context_compression': {'enabled': False},
                    'tools': {'builtin': {'enabled': True, 'file_read': False, 'file_write': False, 'file_search': False}}})
        agent.logger.disabled = True
        agent.adapter.client = agent.adapter.client.with_options(timeout=report['limits']['request_timeout'], max_retries=0)
        report['model'] = agent.model
        report['provider'] = agent.provider
        report['endpoint_host'] = urlsplit(str(agent.adapter.client.base_url)).hostname
        execute = restricted_executor(workspace)
        create = agent.adapter.create

        def bounded(**kwargs):
            if item['chat_calls'] >= 6 or report['chat_calls'] >= report['limits']['chat_calls']:
                raise RuntimeError('Discovery request budget exhausted')
            item['chat_calls'] += 1
            report['chat_calls'] += 1
            kwargs['max_tokens'] = 1800
            request = {'index': item['chat_calls']}
            item['requests'].append(request)
            flush()
            request_started = time.monotonic()
            try:
                response = create(**kwargs)
                request['finish_reason'] = response.choices[0].finish_reason
                return response
            except Exception as exc:
                request['error'] = type(exc).__name__
                raise
            finally:
                request['elapsed_seconds'] = round(time.monotonic() - request_started, 3)
                flush()

        def tracked(command, cwd=None, timeout=30):
            result = execute(command, cwd, timeout)
            # Independent checks are recorded, not injected into model feedback.
            item['actions'].append({'command': command, 'result': result,
                                    'verification': verify(family, workspace, execute)})
            flush()
            return result

        agent.adapter.create = bounded
        agent.bash.execute = tracked
        started = time.monotonic()
        try:
            item['reply'] = agent.run(task, max_iterations=6)
        except Exception as exc:
            item['error'] = type(exc).__name__
        finally:
            item['verification'] = verify(family, workspace, execute)
            item['turn'] = getattr(agent, 'last_turn', {})
            item['tokens'] = agent.total_tokens_used
            item['elapsed_seconds'] = round(time.monotonic() - started, 3)
            artifact = workspace / ('output.cfg' if family == 'bytes' else 'batch.py')
            data = artifact_bytes(artifact)
            item['artifact_hex' if family == 'bytes' else 'artifact_source'] = (
                data.hex() if family == 'bytes' and data is not None else
                data.decode('utf-8', errors='replace') if data is not None else None)
            item['model_failure_observed'] = any(
                action['verification']['artifact_present'] and not action['verification']['passed']
                for action in item['actions'])
            item['passed'] = item['verification']['passed'] and item['turn'].get('status') == 'completed'
            report['tokens'] += item['tokens']
            agent.memory.store.close()
            agent.adapter.client.close()
            flush()
            print(json.dumps({key: item[key] for key in ('family', 'passed', 'model_failure_observed', 'chat_calls', 'tokens')}), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', help='Explicitly permit the bounded model requests')
    parser.add_argument('--case', choices=tuple(TASKS), help='Run only this task; otherwise run both')
    parser.add_argument('--request-timeout', type=int, choices=(45, 120), default=45,
                        help='120 seconds is a separately reported service-timeout diagnostic')
    parser.add_argument('--max-calls', type=int, help='Reduce the total request budget for a targeted diagnostic')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != 'darwin':
        parser.error('This acceptance fixture requires macOS sandbox-exec')
    selected = [args.case] if args.case else list(TASKS)
    call_limit = 6 * len(selected) if args.max_calls is None else args.max_calls
    if not 1 <= call_limit <= 6 * len(selected):
        parser.error('--max-calls must be between 1 and six times the selected task count')
    report = {'selected_cases': selected,
              'limits': {'chat_calls': call_limit, 'calls_per_task': 6, 'tool_calls_per_task': 6,
                         'max_output_tokens': 1800, 'request_timeout': args.request_timeout, 'retries': 0},
              'python': platform.python_version(), 'platform': platform.platform(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'chat_calls': 0, 'tokens': 0, 'cases': []}
    # Refuse to overwrite earlier measurements before doing any work.
    with args.output.open('x', encoding='utf-8') as output:
        def flush():
            output.seek(0)
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.truncate()
            output.flush()
        with tempfile.TemporaryDirectory(prefix='lighthermes-r43-') as temporary:
            root = Path(temporary).resolve()
            report['preflight'] = preflight(root)
            flush()
            if not report['preflight']['passed']:
                raise SystemExit('Isolation preflight failed; no model requests made')
            print('Isolation preflight passed', flush=True)
            if args.live:
                discover(root, report, flush)
            report['result'] = ('model_failure_observed' if any(case['model_failure_observed'] for case in report['cases'])
                                else 'no_failure_observed' if report['cases'] and all(case['passed'] for case in report['cases'])
                                else 'inconclusive' if args.live else 'preflight_only')
            flush()
    print(json.dumps({key: report[key] for key in ('result', 'chat_calls', 'tokens')}))


if __name__ == '__main__':
    main()
