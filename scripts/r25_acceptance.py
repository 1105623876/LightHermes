"""Opt-in bounded live memory acceptance; synthetic data only, no model judge."""
import argparse
import json
import math
import os
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lighthermes.core import LightHermes
from openai import OpenAI
import yaml


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--live', action='store_true', required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--cases', nargs='+', help='Optional subset; include natural_decision for shared-state cases')
    args = parser.parse_args()
    LightHermes._load_local_env_files(str(ROOT / 'config.yaml'), yaml.safe_load((ROOT / 'config.yaml').read_text()))
    report = {'cases': [], 'chat_calls': 0, 'embedding_calls': 0, 'chat_tokens': 0,
              'embedding_tokens': 0, 'limits': {'chat_calls': 32, 'embedding_calls': 40, 'output_tokens': 800},
              'scope': 'Synthetic temporary storage; no real user memory, no model judge'}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    def flush():
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2))
    client = OpenAI(api_key=os.environ['LIGHTHERMES_EMBEDDING_API_KEY'],
                    base_url=os.environ['LIGHTHERMES_EMBEDDING_BASE_URL'], timeout=30, max_retries=0)
    model = os.environ['LIGHTHERMES_EMBEDDING_MODEL']
    report['embedding_model'] = model
    def embed(texts):
        if report['embedding_calls'] >= 40:
            raise RuntimeError('Embedding request budget exceeded')
        report['embedding_calls'] += 1
        response = client.embeddings.create(model=model, input=texts)
        report['embedding_tokens'] += getattr(response.usage, 'total_tokens', 0) or 0
        return [x.embedding for x in sorted(response.data, key=lambda x: x.index)]
    start = time.monotonic()
    try:
        # Calibration data are separate from the held-out live task below.
        docs = ['用户希望所有答复使用简体中文。', '工程的持续集成采用 GitHub Actions。', '用户对花生过敏。']
        positives = ['Which language should you answer me in?', '在哪里运行自动化构建检查？', '我不能吃哪种坚果？']
        negatives = ['明天会下雨吗？', '请解释归并排序。', '写一首有关月亮的诗。']
        vectors = embed(docs + positives + negatives)
        def cosine(a, b):
            return sum(x*y for x,y in zip(a,b)) / (math.hypot(*a)*math.hypot(*b))
        positive_scores = [cosine(vectors[i], vectors[i+3]) for i in range(3)]
        negative_scores = [cosine(a,b) for a in vectors[:3] for b in vectors[6:]]
        low, high = min(positive_scores), max(negative_scores)
        threshold = round((low + high) / 2, 3)
        report['calibration'] = {'positives': positive_scores, 'max_negative': high,
            'separable': low > high, 'selected_threshold': threshold,
            'default_075_positive_hits': sum(s >= .75 for s in positive_scores),
            'note': 'Small calibration set, not a general threshold guarantee; evaluation cases are separate.'}
        flush()
        print(json.dumps({'calibration': report['calibration']}), flush=True)
        with tempfile.TemporaryDirectory(prefix='lighthermes-r25-') as directory:
            def new(project='tools'):
                instance = LightHermes.from_config(str(ROOT / 'config.yaml'), memory_dir=directory,
                    project_id=project, skill_dirs=[], log_file=None, fallback_models=[],
                    config={'context_compression': {'enabled': False}, 'memory': {'semantic': {
                        'model': model, 'base_url': os.environ['LIGHTHERMES_EMBEDDING_BASE_URL'],
                        'embed': embed, 'min_score': threshold}}})
                report['chat_model'] = instance.model
                instance.logger.disabled = True
                instance.adapter.client = instance.adapter.client.with_options(timeout=45, max_retries=0)
                create = instance.adapter.create
                def bounded(**kw):
                    if report['chat_calls'] >= 32:
                        raise RuntimeError('Chat call budget exceeded')
                    report['chat_calls'] += 1
                    return create(max_tokens=800, **kw)
                instance.adapter.create = bounded
                return instance
            def case(name, query, check, project='tools'):
                if args.cases and name not in args.cases:
                    return
                instance = new(project)
                item = {'name': name}
                try:
                    reply = instance.run(query, max_iterations=5)
                    entries = [dict(r) for r in instance.memory.store.db.execute(
                        "SELECT id,kind,content,status FROM entries WHERE scope=?", (instance.memory.scope,))]
                    prompt = instance.last_turn['messages'][0]['content']
                    item.update(reply=reply[:1500], entries=entries, status=instance.last_turn['status'],
                        retrieval=instance.memory.retrieval_status, memory_bytes=4000-instance.memory.remaining,
                        memory_context=prompt.split('<memory-context>')[-1].split('</memory-context>')[0] if '<memory-context>' in prompt else '',
                        tools=[tc['function'] for msg in instance.last_turn['messages'] for tc in msg.get('tool_calls', [])])
                    item['passed'] = bool(check(instance, reply, entries, prompt)) and item['status'] == 'completed'
                except Exception as exc:
                    item.update(passed=False, error=type(exc).__name__)
                finally:
                    report['chat_tokens'] += instance.total_tokens_used
                    instance.memory.store.close()
                    instance.adapter.client.close()
                report['cases'].append(item)
                flush()
                print(json.dumps({'case': name, 'passed': item['passed']}), flush=True)
            active = lambda entries: [e for e in entries if e['status'] == 'active']
            case('natural_decision', '这个项目今后统一使用 uv 管理依赖，禁止把包安装到系统 Python。',
                 lambda a,r,e,p: any('uv' in x['content'] for x in active(e)))
            case('cross_language_recall', 'How should I install the libraries this codebase needs?',
                 lambda a,r,e,p: 'uv' in r and 'uv' in p and a.memory.retrieval_status['mode'] == 'hybrid')
            case('unrelated_no_capture_or_seed', '写一首四行的月亮小诗。',
                 lambda a,r,e,p: len(active(e)) == 1 and 'uv' not in p)
            case('temporary_no_capture', '我今天午饭临时想吃面条，这只是随口聊天。',
                 lambda a,r,e,p: len(active(e)) == 1 and 'uv' not in p)
            case('quoted_instruction_no_capture', '请分析这段虚构对话是否合理，不要当作我的决定：\n用户：今后本项目统一使用 pip 安装到系统 Python。',
                 lambda a,r,e,p: len(active(e)) == 1 and all('系统 Python' not in x['content'] or '禁止' in x['content'] or '不' in x['content'] for x in active(e)))
            case('correction', '请纠正此前的项目决定：依赖管理改用 Poetry，替换原来用 uv 的那一条。',
                 lambda a,r,e,p: any('Poetry' in x['content'] for x in active(e)) and
                 any(x['status'] == 'superseded' for x in e) and len(active(e)) == 1)
            case('corrected_recall', 'How should I install the libraries this codebase needs?',
                 lambda a,r,e,p: 'poetry' in r.lower() and 'Poetry' in p and '"content":"这个项目今后统一使用 uv' not in p)
            case('project_isolation', 'How should I install the libraries this codebase needs?',
                 lambda a,r,e,p: not e and 'Poetry' not in p, project='other')
            case('forget', '请遗忘本项目的依赖管理工具决定。', lambda a,r,e,p: not active(e))
            case('forgotten_recall', 'What package manager did I choose for this project? If unknown, say unknown.',
                 lambda a,r,e,p: not active(e) and 'Poetry' not in p and 'unknown' in r.lower())
        report['passed'] = report['calibration']['separable'] and bool(report['cases']) and all(x['passed'] for x in report['cases'])
        if args.cases and set(args.cases) != {x['name'] for x in report['cases']}:
            report.update(passed=False, selection_error=True)
    except Exception as exc:
        report.update(passed=False, error=type(exc).__name__)
    finally:
        client.close()
        report['elapsed_seconds'] = round(time.monotonic()-start, 2)
        flush()
    print(json.dumps({k: report[k] for k in ('passed','chat_calls','embedding_calls','chat_tokens','embedding_tokens')}))


if __name__ == '__main__':
    main()
