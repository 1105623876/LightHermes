"""Opt-in live R2 acceptance using synthetic data, isolated storage and bounded calls.

Run: .venv/bin/python scripts/r2_acceptance.py --live --output /tmp/r2.json
No credentials, real memory, or model exception bodies are written to the report.
"""
import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lighthermes.core import LightHermes


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', help='Optional named subset; include required setup cases')
    args = parser.parse_args()
    report = {'cases': [], 'api_calls': 0, 'usage_tokens': 0,
              'limits': {'model_calls': 32, 'per_call_output_tokens': 600, 'timeout_seconds': 45, 'retries': 0},
              'scope': 'Synthetic memory only; no model judge; no real data migration'}
    start = time.monotonic()
    with tempfile.TemporaryDirectory(prefix='lighthermes-r2-live-') as directory:
        dbdir = Path(directory) / 'memory'

        def new(project=None):
            instance = LightHermes.from_config(str(ROOT / 'config.yaml'),
                memory_dir=str(dbdir), project_id=project, skill_dirs=[], log_file=None,
                config={'context_compression': {'enabled': False}}, fallback_models=[])
            if not hasattr(instance.adapter, 'client') or instance.provider != 'openai':
                raise ValueError('This bounded harness currently supports the configured OpenAI-compatible adapter')
            instance.adapter.client = instance.adapter.client.with_options(timeout=45, max_retries=0)
            instance.logger.disabled = True  # Do not emit provider exception bodies or credentials.
            create = instance.adapter.create
            report['model'] = instance.model
            def bounded(**kw):
                if report['api_calls'] >= 32:
                    raise RuntimeError('Live call budget exhausted')
                report['api_calls'] += 1
                if kw.get('stream'):
                    kw['stream_options'] = {'include_usage': True}
                return create(max_tokens=600, **kw)
            instance.adapter.create = bounded
            return instance

        def case(name, query, check, *, project=None, stream=False):
            if args.cases and name not in args.cases:
                return None
            instance = new(project)
            item = {'name': name, 'stream': stream}
            try:
                reply = instance.run(query, stream=stream, max_iterations=4)
                reply = ''.join(reply) if stream else reply
                item['passed'] = bool(check(instance, reply)) and instance.last_turn['status'] == 'completed'
                item['reply'] = reply[:1500]
                item['status'] = instance.last_turn['status']
                item['seed_injected'] = '<memory-context>' in instance.last_turn['messages'][0]['content']
                item['memory_bytes_used'] = 4000 - instance.memory.remaining
                item['tools'] = [tc['function']['name'] for msg in instance.last_turn['messages']
                                 for tc in msg.get('tool_calls', [])]
                report['usage_tokens'] += instance.total_tokens_used
            except Exception as exc:
                item.update(passed=False, error_type=type(exc).__name__)
            finally:
                instance.memory.store.close()
                instance.adapter.client.close()
            report['cases'].append(item)
            print(json.dumps({'case': name, 'passed': item['passed']}, ensure_ascii=False), flush=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
            return item

        def active(agent, word):
            return agent.memory.store.search(word, agent.memory.scope)

        case('remember', '请记住：我的默认编程语言是 Python。', lambda a,r: bool(active(a, 'Python')))
        case('restart_recall', '我默认使用哪种编程语言？', lambda a,r: 'Python' in r and bool(active(a, 'Python')))
        case('unrelated_zero_seed', '今天的天气怎么样？如果没有联网工具就说无法查询实时天气。',
             lambda a,r: '<memory-context>' not in a.last_turn['messages'][0]['content'])
        case('correction', '请把我之前默认使用 Python 的偏好纠正为 Rust，替换原记录，不要新增并存的偏好。',
             lambda a,r: bool(active(a, 'Rust')) and not active(a, 'Python'))
        case('restart_corrected', '我默认使用哪种编程语言？', lambda a,r: 'Rust' in r and 'Python' not in r)
        case('project_a_write', '请记住：这个项目的发布代号是 ORCHID731。', lambda a,r: bool(active(a, 'ORCHID731')), project='A')
        case('project_b_isolation', '这个项目的发布代号是什么？不知道就直接说不知道。',
             lambda a,r: 'ORCHID731' not in r and not active(a, 'ORCHID731') and '<memory-context>' not in a.last_turn['messages'][0]['content'], project='B')
        case('project_a_restart', '这个项目的发布代号是什么？', lambda a,r: 'ORCHID731' in r, project='A', stream=True)
        long_record = '会话迁移记录：' + 'Preparation checklist passed. ' * 24 + '最终回滚口令为 MINT928。'
        case('long_record_write', '请把以下完整记录保存为一条记忆，不要摘要或省略：' + long_record,
             lambda a,r: any(len(e['content'].encode()) > 400 for e in active(a, 'MINT928')), project='tail')
        case('long_record_tail', '迁移记录中的最终回滚口令是什么？请准确给出口令。',
             lambda a,r: 'MINT928' in r, project='tail')
        case('forget', '请遗忘我的默认编程语言偏好，删除那条 Rust 偏好。', lambda a,r: not active(a, 'Rust'))
        case('restart_forgotten', '我默认使用哪种编程语言？如果没有记录，请说不知道，不要猜。',
             lambda a,r: not active(a, 'Rust') and 'Rust' not in r and 'Python' not in r)
    report['elapsed_seconds'] = round(time.monotonic() - start, 2)
    report['passed'] = bool(report['cases']) and all(item['passed'] for item in report['cases'])
    if args.cases and set(args.cases) != {item['name'] for item in report['cases']}:
        report['passed'] = False
        report['selection_error'] = 'One or more requested case names were not run'
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    print(json.dumps({'passed': report['passed'], 'api_calls': report['api_calls'], 'usage_tokens': report['usage_tokens']}))


if __name__ == '__main__':
    main()
