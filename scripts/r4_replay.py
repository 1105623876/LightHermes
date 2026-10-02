"""Opt-in, bounded three-arm replay. Fixed data operations; no shell/code tools."""
import argparse
import csv
import io
import json
import sqlite3
import sys
import tempfile
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lighthermes.core import LightHermes
from lighthermes.tools import tool

# Frozen before execution; development and evaluation values are separate.
DEVELOPMENT = [
    ('csv', '\ufeffname,n\n林,7\n陈,9\n', 'name', ['林', '陈']),
    ('csv', '\ufeffcity,n\n東京,3\n大阪,4\n', 'city', ['東京', '大阪']),
    ('money', '["1,234.56", "0.29"]', None, [123456, 29]),
    ('money', '["2,345.67", "0.58"]', None, [234567, 58]),
]
EVALUATION = [
    ('csv', '\ufeffproduct,n\n茶,2\n水,5\n', 'product', ['茶', '水']),
    ('csv', '\ufeffteam,n\n甲,8\n乙,6\n', 'team', ['甲', '乙']),
    ('money', '["3,456.78", "0.57"]', None, [345678, 57]),
    ('money', '["9,876.54", "0.28"]', None, [987654, 28]),
    ('copy', 'name,n\r\nA,1\r\n', None, b'name,n\r\nA,1\r\n'),
    ('integer', '[29, 58]', None, [29, 58]),
]
FACT = 'CSV 导出项目列映射：dev0=name，dev1=city，eval0=product，eval1=team。金额字符串转换目标单位为整数分；整数原样返回任务禁止缩放。'


def task_tools(workspace, case, name, known):
    family, data, field, expected = case
    calls = []
    spec = {'task': name, 'family': family, 'field': field, 'target_unit': 'integer cents' if family == 'money' else None}
    @tool('inspect_task', 'Read the fixed input and task specification, including the target column/unit. No path or command arguments.', [])
    def inspect_task():
        return json.dumps({**spec, 'input': data, 'first_bytes': list(data.encode()[:8])}, ensure_ascii=False)
    @tool('process_task', 'Process only the fixed input/output. extract CSV column, convert money strings to integer cents, copy exact bytes, or passthrough integer JSON. No code or paths.', [
        {'name': 'operation', 'type': 'string', 'description': 'extract / money / copy / passthrough', 'required': True},
        {'name': 'field', 'type': 'string', 'description': 'Column for extract, per task specification', 'required': False},
        {'name': 'method', 'type': 'string', 'description': 'extract: utf-8 or utf-8-sig; money: float or decimal; decimal also removes thousands separators; copy/passthrough: literal', 'required': False},
        {'name': 'experience_id', 'type': 'string', 'description': 'Exact memory ID only if consciously applying that experience; otherwise omit', 'required': False},
    ])
    def process_task(operation, field=None, method='utf-8', experience_id=None):
        record = {'operation': operation, 'field': field, 'method': method, 'experience_id': experience_id}
        calls.append(record)
        try:
            if experience_id is not None and experience_id not in known:
                raise ValueError('Unknown experience ID')
            raw = (workspace / 'input').read_bytes()
            if operation == 'copy':
                output = raw
            elif operation == 'extract' and method in ('utf-8', 'utf-8-sig'):
                output = json.dumps([r[field] for r in csv.DictReader(io.StringIO(raw.decode(method)))], ensure_ascii=False).encode()
            elif operation == 'money' and method in ('float', 'decimal'):
                values = json.loads(raw)
                values = [int(Decimal(str(v).replace(',', '')) * 100) if method == 'decimal' else int(float(v)*100) for v in values]
                output = json.dumps(values).encode()
            elif operation == 'passthrough':
                output = json.dumps(json.loads(raw)).encode()
            else:
                raise ValueError('Unsupported fixed operation/method')
            (workspace / 'output').write_bytes(output)
            record['ok'] = True
            return 'Output written; input unchanged.'
        except Exception as exc:
            record.update(ok=False, error=type(exc).__name__)
            raise
    return [inspect_task, process_task], calls


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    report = {'protocol': 'R4_PROTOCOL.md', 'preparation': [], 'evaluation': [], 'chat_calls': 0, 'tokens': 0,
              'limits': {'chat_calls': 110, 'max_output_tokens': 900, 'timeout': 45, 'retries': 0, 'iterations': 4},
              'automatic_activation': False}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def flush(): args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='lighthermes-r4-replay-') as directory:
        root = Path(directory)
        approved, candidates = {}, {}
        def run(name, case, memory_dir, trial=None, learn=False):
            workspace = root / name
            workspace.mkdir()
            (workspace / 'input').write_bytes(case[1].encode())
            fixed, operations = task_tools(workspace, case, name.split('-')[0], set(candidates.values()))
            agent = LightHermes.from_config(str(ROOT / 'config.yaml'), memory_dir=str(memory_dir), project_id='r4',
                evolution_enabled=True, skill_dirs=[], log_file=None, fallback_models=[], tools=fixed, bash_authorized=False,
                config={'context_compression': {'enabled': False}, 'tools': {'builtin': {'enabled': False}}})
            agent.logger.disabled = True
            agent.tool_dispatcher.register_tools([agent.memory.search_memory, agent.memory.read_memory, agent.memory.update_memory])
            agent.adapter.client = agent.adapter.client.with_options(timeout=45, max_retries=0)
            report['model'] = agent.model
            original = agent.adapter.create
            def bounded(**kw):
                if report['chat_calls'] >= 110: raise RuntimeError('Global API budget exhausted')
                report['chat_calls'] += 1
                kw['max_tokens'] = 900
                return original(**kw)
            agent.adapter.create = bounded
            family = case[0]
            requests = {'csv': '完成 CSV 列提取到 JSON 数组，列名按项目映射或 inspect_task 说明。',
                        'money': '完成金额字符串转换为整数分并写入 JSON 数组。',
                        'copy': '原样复制输入到输出，必须逐字节一致；不需要 CSV 解析或编码转换。',
                        'integer': '整数数组已经是最终单位，原样返回 JSON 数组，禁止乘100。'}
            query = f'任务 {name.split("-")[0]}：{requests[family]}使用提供的工具实际处理，保持输入不变。可查询项目记忆；经验仅在适用时采用并填写 experience_id。'
            item = {'name': name, 'family': family}
            before = report['chat_calls']; start = time.monotonic()
            try:
                if name == 'dev0':
                    agent.memory.begin(FACT, 'default_user', 'setup')
                    agent.memory.store.remember(agent.memory.scope, 'fact', FACT, [agent.memory.source], status='active')
                reply = agent.run(query, max_iterations=4, trial_experience=trial)
                output = workspace / 'output'
                matches = False
                if output.exists():
                    try: matches = output.read_bytes() == case[3] if isinstance(case[3], bytes) else json.loads(output.read_bytes()) == case[3]
                    except ValueError: pass
                item.update(passed=matches and (workspace/'input').read_bytes() == case[1].encode() and agent.last_turn['status'] == 'completed',
                            status=agent.last_turn['status'], reply=reply[:1000], operations=operations)
                expected_method = 'utf-8-sig' if family == 'csv' else 'decimal'
                expected_op = 'extract' if family == 'csv' else 'money'
                identifier = trial or approved.get(family)
                item['adopted'] = bool(identifier and any(c.get('ok') and c['experience_id'] == identifier and c['operation'] == expected_op and c['method'] == expected_method for c in operations))
                item['false_adoption'] = family in ('copy', 'integer') and any(c['experience_id'] for c in operations)
                item['tool_errors'] = sum(not c.get('ok', False) for c in operations)
                if learn and item['passed']:
                    feedback = '宿主独立检查：输出精确符合本任务预期，输入字节不变；正确方法为 ' + expected_method + '。只保留格式条件与参数化流程，不保存样本答案。'
                    learned = agent.learn(feedback, outcome='verified_success', adopted=item['adopted'] if trial else False)
                    item['learning'] = learned
                    if not trial and learned.get('status') == 'candidate':
                        candidates[family] = learned['entry_id']
                        item['candidate_content'] = agent.memory.store.read_entry(learned['entry_id'], agent.memory.scope, include_history=True)['content']
                    elif trial and item['adopted']:
                        item['review'] = agent.review_experience(trial, action='approve', reason='宿主核实独立开发任务的产物和实际方法采用，仅认可该格式范围。')
                        approved[family] = trial
            except Exception as exc:
                item.update(passed=False, error=type(exc).__name__, operations=operations)
            finally:
                item.update(chat_calls=report['chat_calls']-before, tokens=agent.total_tokens_used, tool_calls=sum(m.get('role')=='tool' for m in getattr(agent,'last_turn',{}).get('messages',[])),
                            elapsed_seconds=round(time.monotonic()-start, 3))
                report['tokens'] += agent.total_tokens_used
                agent.memory.store.close(); agent.adapter.client.close()
            print(json.dumps({'case': name, 'passed': item['passed'], 'calls': item['chat_calls']}), flush=True)
            return item
        memory = root / 'development'
        for i, case in enumerate(DEVELOPMENT):
            trial = candidates.get(case[0]) if i%2 else None
            report['preparation'].append(run(f'dev{i}', case, memory, trial, learn=True)); flush()
        report['approved_families'] = list(approved)
        for i, case in enumerate(EVALUATION):
            arms = ['none', 'facts', 'experience']
            arms = arms[i%3:] + arms[:i%3]
            for arm in arms:
                target = root / f'memory-{i}-{arm}'; target.mkdir()
                with sqlite3.connect(memory/'lighthermes.sqlite3') as src, sqlite3.connect(target/'lighthermes.sqlite3') as dst:
                    src.backup(dst)
                    if arm == 'none': dst.execute("UPDATE entries SET status='archived' WHERE status='active'")
                    elif arm == 'facts': dst.execute("UPDATE entries SET status='archived' WHERE kind='experience'")
                    # FTS joins status in production; rebuild explicitly to exclude stale control rows.
                    dst.commit()
                item = run(f'eval{i}-{arm}', case, target)
                item['arm'] = arm
                report['evaluation'].append(item); flush()
        report['summary'] = {}
        for arm in ('none','facts','experience'):
            rows = [r for r in report['evaluation'] if r['arm'] == arm]
            report['summary'][arm] = {k: sum(r.get(k,0) for r in rows) for k in ('passed','tokens','chat_calls','tool_calls','tool_errors','adopted','false_adoption','elapsed_seconds')}
        gains = []
        for family in ('csv','money'):
            facts = [r for r in report['evaluation'] if r['arm']=='facts' and r['family']==family]
            exp = [r for r in report['evaluation'] if r['arm']=='experience' and r['family']==family]
            sf, se = sum(r['passed'] for r in facts), sum(r['passed'] for r in exp)
            gains.append(se>sf or (se==sf and sum(r.get('tool_errors',0) for r in exp)<sum(r.get('tool_errors',0) for r in facts)))
        negatives = [r for r in report['evaluation'] if r['family'] in ('copy','integer') and r['arm']=='experience']
        report['benefit_gate'] = len(approved)==2 and all(gains) and all(r['passed'] and not r.get('false_adoption') for r in negatives)
        report['complete'] = len(report['evaluation'])==18
        report['elapsed_seconds'] = round(time.monotonic()-started,2)
        flush()
    print(json.dumps({'complete': report['complete'], 'benefit_gate': report['benefit_gate'], 'chat_calls': report['chat_calls'], 'tokens':report['tokens']}))

if __name__ == '__main__': main()
