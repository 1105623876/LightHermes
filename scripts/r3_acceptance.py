"""Opt-in experience acceptance with fixed, scoped CSV tools and host checks.

No shell or model-generated code execution. Model arguments can only select a
whitelisted operation/encoding on one host-selected temporary input/output pair.
"""
import argparse
import csv
import io
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lighthermes.core import LightHermes
from lighthermes.tools import tool


def csv_tools(workspace, field, trial_id=None):
    calls = []
    @tool('inspect_csv', 'Inspect the fixed task input: first bytes and UTF-8 header. No path arguments.', [])
    def inspect_csv():
        data = (workspace / 'input.csv').read_bytes()
        return json.dumps({'first_bytes': list(data[:8]), 'header': data.decode('utf-8').splitlines()[0]}, ensure_ascii=False)
    @tool('process_csv', 'Process only the fixed task input/output. extract selects the required column as JSON; copy preserves every byte. No commands or paths accepted.', [
        {'name': 'operation', 'type': 'string', 'description': 'extract or copy', 'required': True},
        {'name': 'encoding', 'type': 'string', 'description': 'utf-8 or utf-8-sig; only relevant to extract', 'required': False},
        {'name': 'experience_id', 'type': 'string', 'description': 'Only when actually applying the selected trial experience, supply its exact ID; omit when not applying it', 'required': False}])
    def process_csv(operation, encoding='utf-8', experience_id=None):
        if operation not in ('extract', 'copy') or encoding not in ('utf-8', 'utf-8-sig'):
            raise ValueError('Only extract/copy and utf-8/utf-8-sig are allowed')
        if experience_id is not None and (trial_id is None or experience_id != trial_id):
            raise ValueError('Experience ID must match the host-selected trial')
        calls.append({'operation': operation, 'encoding': encoding, 'experience_id': experience_id})
        data = (workspace / 'input.csv').read_bytes()
        if operation == 'copy':
            (workspace / 'output').write_bytes(data)
        else:
            rows = list(csv.DictReader(io.StringIO(data.decode(encoding))))
            result = [row[field] for row in rows]
            (workspace / 'output').write_text(json.dumps(result, ensure_ascii=False))
        return json.dumps({'operation': operation, 'encoding': encoding, 'written': True})
    return [inspect_csv, process_csv], calls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'cases': [], 'chat_calls': 0, 'tokens': 0,
              'limits': {'chat_calls': 24, 'max_output_tokens': 1000, 'timeout': 45, 'retries': 0},
              'scope': 'Fixed tools on temporary synthetic CSV only; no shell/code execution; no causal improvement claim'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def flush():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='lighthermes-r3-') as directory:
        root = Path(directory)
        def new(name, data, field, trial_id=None):
            workspace = root / name
            workspace.mkdir()
            (workspace / 'input.csv').write_bytes(data)
            tools, calls = csv_tools(workspace, field, trial_id)
            instance = LightHermes.from_config(str(ROOT / 'config.yaml'), memory_dir=str(root / 'memory'),
                project_id='csv-import', evolution_enabled=True, skill_dirs=[], log_file=None, fallback_models=[],
                tools=tools, bash_authorized=False,
                config={'context_compression': {'enabled': False}, 'tools': {'builtin': {'enabled': False}}})
            instance.logger.disabled = True
            instance.adapter.client = instance.adapter.client.with_options(timeout=45, max_retries=0)
            report['model'] = instance.model
            create = instance.adapter.create
            def bounded(**kw):
                if report['chat_calls'] >= 24:
                    raise RuntimeError('Call budget exceeded')
                report['chat_calls'] += 1
                kw.setdefault('max_tokens', 1000)
                return create(**kw)
            instance.adapter.create = bounded
            return instance, workspace, calls
        def observe(instance, name, query, workspace, data, expected, calls, trial=None):
            reply = instance.run(query, max_iterations=6, trial_experience=trial)
            output = (workspace / 'output').read_bytes()
            checks = (workspace / 'input.csv').read_bytes() == data and (
                output == expected if isinstance(expected, bytes) else json.loads(output) == expected)
            item = {'name': name, 'passed': checks and instance.last_turn['status'] == 'completed',
                    'host_checks': checks, 'status': instance.last_turn['status'], 'reply': reply[:1200],
                    'operations': list(calls)}
            report['cases'].append(item)
            flush()
            print(json.dumps({'case': name, 'passed': item['passed']}), flush=True)
            if not item['passed']:
                raise ValueError('Task verification failed')
        opened = []
        try:
            data = '\ufeffname,amount\n林,7\n陈,9\n'.encode()
            first, workspace, calls = new('first', data, 'name'); opened.append(first)
            observe(first, 'origin_task', '用现有工具把指定 CSV 的 name 列提取到输出 JSON 数组。不能修改输入，请实际处理，检查编码/列名问题，不需要写代码。', workspace, data, ['林','陈'], calls)
            learned = first.learn('宿主独立检查：输出 JSON == ["林","陈"]，输入字节未变。', outcome='verified_success')
            report['learning'] = learned
            if learned.get('status') != 'candidate':
                raise ValueError('No candidate extracted')
            identifier = learned['entry_id']
            entry = first.memory.store.read_entry(identifier, first.memory.scope, include_history=True)
            report['candidate'] = {'id': identifier, 'content': entry['content'], 'source_count': len(entry['source_refs'])}
            flush()
            data = '\ufeffcity,units\n東京,3\n大阪,4\n'.encode()
            second, workspace, calls = new('second', data, 'city', identifier); opened.append(second)
            observe(second, 'independent_trial', '用现有工具把指定 CSV 的 city 列提取到输出 JSON 数组，不能修改输入。检查候选经验是否适用，适用才采用；实际处理，不需要写代码。', workspace, data, ['東京','大阪'], calls, identifier)
            adopted = any(c == {'operation': 'extract', 'encoding': 'utf-8-sig', 'experience_id': identifier} for c in calls)
            report['adoption_checked'] = adopted
            if not adopted:
                raise ValueError('Cannot attest adoption of the candidate method')
            report['trial_feedback'] = second.learn('独立城市文件输出数组和输入不变检查通过；实际工具参数采用 utf-8-sig。', outcome='verified_success', adopted=True)
            data = b'name,value\nA,1\n'
            negative, workspace, calls = new('negative', data, 'name', identifier); opened.append(negative)
            observe(negative, 'inapplicable_trial', '指定 input.csv 无 BOM；只需原样复制到输出，要求逐字节一致，不要解析重写 CSV。先判断候选经验适用条件，不适用不要套用。用现有工具实际处理。', workspace, data, data, calls, identifier)
            if any(c['experience_id'] is not None for c in calls):
                raise ValueError('Inapplicable task incorrectly adopted the experience')
            report['negative_feedback'] = negative.learn('逐字节复制验证通过；该任务没有编码修复，不采用候选方法。', outcome='verified_success', adopted=False)
            report['approval'] = second.review_experience(identifier, action='approve', reason='宿主验证独立 BOM CSV 复用成功，仅认可该范围；原样复制反例不应用。')
            report['active_recall'] = bool(second.memory.store.search('BOM CSV', second.memory.scope))
            report['revocation'] = second.review_experience(identifier, action='revoke', reason='合成验收结束，检查撤回')
            report['revoked_recall_empty'] = not second.memory.store.search('BOM CSV', second.memory.scope)
            report['passed'] = all(x['passed'] for x in report['cases']) and report['active_recall'] and report['revoked_recall_empty']
        except Exception as exc:
            report.update(passed=False, error=type(exc).__name__)
        finally:
            for instance in opened:
                report['tokens'] += instance.total_tokens_used
                instance.memory.store.close()
                instance.adapter.client.close()
            report['elapsed_seconds'] = round(time.monotonic()-start, 2)
            flush()
    print(json.dumps({k: report[k] for k in ('passed','chat_calls','tokens')}))


if __name__ == '__main__':
    main()
