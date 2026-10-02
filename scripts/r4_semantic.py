"""Fixed held-out semantic probes; optional network, no threshold fitting."""
import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from openai import OpenAI
from lighthermes.core import LightHermes
from lighthermes.semantic import SemanticIndex
from lighthermes.store import MemoryStore

DOCUMENTS = [
    '此项目发布前必须经过两位维护者审核。',
    '项目数据备份保留三十天，过期后删除。',
    '用户偏好把界面切换为深色主题。',
    '此项目每个工作日凌晨三点执行备份。',
]
QUERIES = [
    ('How many maintainers must approve before a release?', 0),
    ('How long do we keep backup copies?', 1),
    ('Which color scheme should the interface use?', 2),
    ('When are backups scheduled on weekdays?', 3),
    ('What is the release version number?', None),
    ('Which encryption algorithm protects backup copies?', None),
]


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true',required=True)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    LightHermes._load_local_env_files(str(ROOT/'config.yaml'),yaml.safe_load((ROOT/'config.yaml').read_text()))
    report={'threshold':.46,'embedding_calls':0,'embedding_tokens':0,'cases':[], 'documents':DOCUMENTS}
    client=OpenAI(api_key=os.environ['LIGHTHERMES_EMBEDDING_API_KEY'],base_url=os.environ['LIGHTHERMES_EMBEDDING_BASE_URL'],timeout=30,max_retries=0)
    model=os.environ['LIGHTHERMES_EMBEDDING_MODEL'];report['model']=model
    def embed(texts):
        if report['embedding_calls']>=20: raise RuntimeError('Embedding budget exhausted')
        report['embedding_calls']+=1
        response=client.embeddings.create(model=model,input=texts)
        report['embedding_tokens']+=getattr(response.usage,'total_tokens',0) or 0
        return [r.embedding for r in sorted(response.data,key=lambda r:r.index)]
    try:
        with tempfile.TemporaryDirectory(prefix='lighthermes-r4-semantic-') as root:
            store=MemoryStore(Path(root)/'lighthermes.sqlite3')
            try:
                ids=[]
                for i,doc in enumerate(DOCUMENTS):
                    source=store.append_event('test','seed',str(i),{'content':doc})
                    ids.append(store.remember('test','fact',doc,[source],status='active'))
                index=SemanticIndex(store,model=model,embed=embed,min_score=.46)
                for query,expected in QUERIES:
                    index.begin(); lexical=store.search(query,'test',50)
                    hybrid=index.search(query,['test'],lexical,4)
                    def outcome(rows):
                        return not rows if expected is None else bool(rows and rows[0]['id']==ids[expected])
                    report['cases'].append({'query':query,'expected':expected,'fts_ids':[ids.index(r['id']) for r in lexical],
                        'hybrid_ids':[ids.index(r['id']) for r in hybrid],'fts_pass':outcome(lexical),'hybrid_pass':outcome(hybrid),'status':index.status.copy()})
                replacement='此项目发布前必须经过三位维护者审核。'
                source=store.append_event('test','correct','one',{'content':replacement})
                new=store.remember('test','fact',replacement,[source],status='active',supersedes=ids[0])
                index.begin(); rows=index.search(QUERIES[0][0],['test'],[],4)
                report['correction']={'old_absent':all(r['id']!=ids[0] for r in rows),'new_recalled':any(r['id']==new for r in rows),'status':index.status.copy()}
                store.forget(new,'test'); index.begin(); rows=index.search(QUERIES[0][0],['test'],[],4)
                report['forget']={'deleted_absent':all(r['id'] not in (ids[0],new) for r in rows),'remaining_matches':[r['content'] for r in rows],'status':index.status.copy()}
                report['transport_ok']=all(r['status']['mode']=='hybrid' for r in report['cases']) and report['correction']['status']['mode']=='hybrid' and report['forget']['status']['mode']=='hybrid'
            finally: store.close()
    except Exception as exc: report['error']=type(exc).__name__
    finally:
        client.close(); args.output.parent.mkdir(parents=True,exist_ok=True)
        args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'embedding_calls':report['embedding_calls'],'tokens':report['embedding_tokens'],'error':report.get('error'),'transport_ok':report.get('transport_ok')}))

if __name__=='__main__':main()
