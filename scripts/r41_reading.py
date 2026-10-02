"""Bounded reading-policy comparison; all policy changes stay in this harness."""
import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import yaml
from openai import OpenAI
from lighthermes.core import LightHermes
from lighthermes.runtime_memory import RuntimeMemory, serialized, clip, token_cost
from lighthermes.semantic import SemanticIndex
from lighthermes.store import MemoryStore
from lighthermes.tools import tool

ARMS = ('snippet', 'clue', 'demand')
CASES = [
    {'name':'approvals','query':'How many reviewers must approve this project release? Reply with the number only in answer.','key':'approval','answer':'5'},
    {'name':'retention','query':'For how many days are backup copies retained in this project? Reply with the number in answer.','key':'retention','answer':'42'},
    {'name':'cipher','query':'Which encryption algorithm does this project use for its backups?','answer':None},
    {'name':'version','query':'What is the current release version number of this project?','answer':None},
    {'name':'correction','query':'项目当前批准的服务端口是多少？只在answer填写端口数字。','key':'port','answer':'9447'},
    {'name':'forgotten','query':'项目部署在哪个地区？如果当前记忆没有可用依据，不要猜测。','answer':None},
    {'name':'apply','query':'将固定输入中的两行文字转换为项目 legacy-v1 接收器接受的行结束格式并写入产物。保持输入不变，可查经验。','key':'procedure','action':'crlf'},
    {'name':'copy','query':'原样复制固定输入到产物，要求逐字节一致，不经过 legacy-v1 接收器，不转换任何字节。','action':'copy'},
    {'name':'unrelated','query':'只计算 6 乘以 7，answer填写结果数字；这与项目记录无关。','answer':'42'},
]
DEV = [
    {'name':'dev-fact','query':'项目审计记录保留多少天？answer填写数字。','key':'fact','answer':'17'},
    {'name':'dev-action','query':'将固定输入整理为开发环境 legacy-v0 接收器接受的行结束格式，写入产物；保持输入不变。','key':'procedure','action':'crlf'},
]
FORMAT = '\n仅返回JSON对象 {"answer":字符串或null,"evidence_ids":[实际支持答案的记忆ID]}。当前记忆没有答案时用null，不以同主题事实推测。行动任务请实际调用工具；若确实采用经验，在工具参数experience_id填其ID，否则省略。'


def populate(store, scope, development=False):
    ids = {}
    def add(key, content, kind='fact', supersedes=None):
        source = store.append_event(scope, 'fixture', key, {'content':content,'authority':'synthetic_host_fixture'})
        ids[key] = store.remember(scope, kind, content, [source], status='active', supersedes=supersedes)
        return ids[key]
    if development:
        add('fact','开发项目的审计记录保留17天。')
        receiver='legacy-v0'
    else:
        add('approval','此项目发布前必须获得5位审核人的同意。')
        add('retention','此项目备份副本保留42天，到期删除。')
        add('schedule','此项目备份在每个工作日凌晨四点运行。')
        add('theme','此项目界面使用深色主题。')
        old=add('old-port','此项目服务端口使用8123。')
        add('port','项目当前服务端口改为9447，替代以前的端口决定。',supersedes=old)
        deleted=add('region','项目部署地区是冰岛。')
        store.forget(deleted,scope)
        receiver='legacy-v1'
    add('procedure',serialized({'applicable_when':f'向项目 {receiver} 接收器发送两行纯文本记录；不适用于原样复制或其他接收器。',
        'procedure':'输出使用CRLF行结束符，每行包括最后一行均以CRLF结束；输入保持原样。',
        'verification':'逐字节检查输出为两行CRLF，输入不变。'}),'experience')
    return ids


def install_policy(memory, arm):
    observed={'shown_ids':[], 'read_ids':[], 'seed_bytes':0}
    original_preview=memory._preview
    original_read=memory.read_memory
    def preview(rows,budget,query=''):
        if arm!='clue':
            result=original_preview(rows,budget,query)
        else:
            parts=[]
            for row in rows:
                key=row['id']
                if key in memory.offsets: continue
                if row['kind']=='experience':
                    hint=json.loads(row['content'])['applicable_when']
                    part=serialized({'id':key,'kind':'experience','applicable_when':clip(hint,400),'more':True,'instruction':'read_memory reads the procedure; applicability alone is not a method.'})
                    offset=0
                else:
                    # Same production preview and metadata for facts, not a fabricated title.
                    part=original_preview([row],budget,query)
                    if not part: continue
                    offset=memory.offsets[key]
                if token_cost(part)+1>budget: break
                parts.append(part); budget-=token_cost(part)+1
                memory.offsets[key]=offset
            result='\n'.join(parts)
        for line in result.splitlines():
            observed['shown_ids'].append(json.loads(line)['id'])
        return result
    def read(id,source=False,offset=None):
        result=original_read(id,source,offset)
        observed['read_ids'].append(id)
        return result
    read.tool_info=original_read.tool_info
    memory._preview=preview
    memory.read_memory=read
    original_seed=memory.seed
    def seed(query):
        result='' if arm=='demand' else original_seed(query)
        observed['seed_bytes']=token_cost(result)
        return result
    memory.seed=seed
    return observed


def artifact_tool(workspace):
    operations=[]
    @tool('write_artifact','Write only the fixed two-line input to the fixed output; no paths or code. mode: copy, lf, crlf. Follow current task/project requirements.',[
        {'name':'mode','type':'string','description':'copy / lf / crlf','required':True},
        {'name':'experience_id','type':'string','description':'ID only if actually using an applicable memory procedure; otherwise omit','required':False}])
    def write_artifact(mode,experience_id=None):
        if mode not in ('copy','lf','crlf'): raise ValueError('Invalid mode')
        raw=(workspace/'input').read_bytes()
        output=raw if mode=='copy' else (b'\n' if mode=='lf' else b'\r\n').join(raw.splitlines())+(b'\n' if mode=='lf' else b'\r\n')
        (workspace/'output').write_bytes(output)
        operations.append({'mode':mode,'experience_id':experience_id})
        return 'Output written; fixed input unchanged.'
    return write_artifact,operations


def score(case, reply, observation, ids, operations, output, original):
    try:
        value=json.loads(reply)
        valid=isinstance(value,dict) and set(value)=={'answer','evidence_ids'} and (isinstance(value['answer'],str) or value['answer'] is None) and isinstance(value['evidence_ids'],list) and all(isinstance(x,str) for x in value['evidence_ids'])
    except (ValueError,TypeError): value={};valid=False
    key=case.get('key'); target=ids.get(key)
    if 'action' in case:
        expected=original if case['action']=='copy' else b'alpha\r\nbeta\r\n'
        correct=output==expected
        grounded=correct
    else:
        correct=valid and value['answer']==case['answer']
        grounded=correct and (target in value['evidence_ids'] if target else not value['evidence_ids'])
    return {'format_valid':valid,'correct':correct,'grounded':grounded,
        'unsupported_positive': 'answer' in case and case['answer'] is None and valid and value['answer'] is not None,
        'missing_memory':bool(target and target not in observation['shown_ids']+observation['read_ids']),
        'adopted':bool(case.get('action')=='crlf' and any(x['experience_id']==ids['procedure'] and x['mode']=='crlf' for x in operations)),
        'wrong_experience':bool(case.get('action')=='copy' and any(x['experience_id'] for x in operations)),
        'unknown_without_search':bool('answer' in case and case['answer'] is None and valid and value['answer'] is None and not observation['read_ids'] and not observation['shown_ids'])}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true',required=True);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    config=yaml.safe_load((ROOT/'config.yaml').read_text());LightHermes._load_local_env_files(str(ROOT/'config.yaml'),config)
    report={'protocol':'R41_PROTOCOL.md','cases':[],'chat_calls':0,'chat_tokens':0,'embedding_calls':0,'embedding_tokens':0,'preparation':{},'complete':False}
    args.output.parent.mkdir(parents=True,exist_ok=True)
    if args.output.exists(): raise FileExistsError('Preserve existing results; use a new output path')
    def flush():args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    client=OpenAI(api_key=os.environ['LIGHTHERMES_EMBEDDING_API_KEY'],base_url=os.environ['LIGHTHERMES_EMBEDDING_BASE_URL'],timeout=45,max_retries=0)
    embedding_model=os.environ['LIGHTHERMES_EMBEDDING_MODEL'];report['embedding_model']=embedding_model
    def embed(texts):
        if report['embedding_calls']>=110:raise RuntimeError('Embedding budget exhausted')
        report['embedding_calls']+=1
        response=client.embeddings.create(model=embedding_model,input=texts)
        report['embedding_tokens']+=getattr(response.usage,'total_tokens',0) or 0
        return [x.embedding for x in sorted(response.data,key=lambda x:x.index)]
    started=time.monotonic(); failures=0
    try:
        with tempfile.TemporaryDirectory(prefix='lighthermes-r41-') as temporary:
            root=Path(temporary)
            for development,cases in ((True,DEV),(False,CASES)):
                group='development' if development else 'evaluation'
                scope=serialized(['project','default_user',group])
                base=root/f'{group}.sqlite3';store=MemoryStore(base)
                prep_before={k:report[k] for k in ('embedding_calls','embedding_tokens')}
                try:
                    ids=populate(store,scope,development)
                    index=SemanticIndex(store,model=embedding_model,embed=embed,min_score=.46)
                    if not index.index([scope]) or index.status['pending']:raise RuntimeError('Incomplete prepared index')
                    active_count=store.db.execute("SELECT count(*) FROM entries WHERE status='active'").fetchone()[0]
                finally:store.close()
                report['preparation'][group]={**{k:report[k]-prep_before[k] for k in prep_before},'active_entries':active_count}
                for i,case in enumerate(cases):
                    order=ARMS[i%3:]+ARMS[:i%3]
                    for arm in order:
                        path=root/f'{group}-{i}-{arm}';path.mkdir();(path/'input').write_bytes(b'alpha\nbeta\n')
                        with sqlite3.connect(base) as src,sqlite3.connect(path/'lighthermes.sqlite3') as dst:src.backup(dst)
                        write,operations=artifact_tool(path)
                        agent=LightHermes.from_config(str(ROOT/'config.yaml'),project_id=group,memory_dir=str(path),tools=[write],bash_authorized=False,
                            evolution_enabled=False,skill_dirs=[],log_file=None,fallback_models=[],config={'context_compression':{'enabled':False},'tools':{'builtin':{'enabled':False}},
                            'memory':{'semantic':{'model':embedding_model,'embed':embed,'min_score':.46}}})
                        agent.logger.disabled=True;agent.adapter.client=agent.adapter.client.with_options(timeout=45,max_retries=0)
                        observed=install_policy(agent.memory,arm)
                        agent.tool_dispatcher.register_tools([agent.memory.search_memory,agent.memory.read_memory])
                        create=agent.adapter.create
                        def bounded(**kw):
                            if report['chat_calls']>=140:raise RuntimeError('Chat budget exhausted')
                            report['chat_calls']+=1;kw['max_tokens']=600
                            return create(**kw)
                        agent.adapter.create=bounded;report['model']=agent.model
                        before={k:report[k] for k in ('chat_calls','embedding_calls','embedding_tokens')}
                        item={'group':group,'name':case['name'],'arm':arm,'expected_key':case.get('key')};start=time.monotonic()
                        try:
                            reply=agent.run(case['query']+FORMAT,max_iterations=4)
                            output=(path/'output').read_bytes() if (path/'output').exists() else None
                            item.update(score(case,reply,observed,ids,operations,output,b'alpha\nbeta\n'))
                            item.update(reply=reply,status=agent.last_turn['status'],retrieval=agent.memory.retrieval_status.copy())
                            item['input_unchanged']=(path/'input').read_bytes()==b'alpha\nbeta\n'
                            item['passed']=item['correct'] and item['grounded'] and item['input_unchanged'] and item['status']=='completed' and not item['wrong_experience']
                            if agent.memory.retrieval_status.get('error'):failures+=1
                            else:failures=0
                        except Exception as exc:
                            item.update(passed=False,error=type(exc).__name__);failures+=1
                        finally:
                            messages=agent.last_turn.get('messages',[])
                            item['unknown_without_search']=bool(item.get('unknown_without_search') and agent.memory.searches==0 and arm=='demand')
                            item.update(observed,operations=operations,memory_bytes=4000-agent.memory.remaining,tokens=agent.total_tokens_used,
                                tool_calls=[c['function'] for m in messages for c in m.get('tool_calls',[])],elapsed_seconds=round(time.monotonic()-start,3),
                                **{k:report[k]-before[k] for k in before})
                            report['chat_tokens']+=agent.total_tokens_used
                            agent.memory.store.close();agent.adapter.client.close()
                        report['cases'].append(item);flush()
                        print(json.dumps({'group':group,'case':case['name'],'arm':arm,'passed':item['passed'],'calls':item['chat_calls']}),flush=True)
                        if failures>=3:raise RuntimeError('Stopped after three consecutive infrastructure failures')
            report['complete']=True
    except Exception as exc:report['error']=type(exc).__name__
    finally:
        client.close();report['elapsed_seconds']=round(time.monotonic()-started,2)
        report['summary']={}
        for arm in ARMS:
            rows=[x for x in report['cases'] if x['group']=='evaluation' and x['arm']==arm]
            report['summary'][arm]={'attempted':len(rows),**{k:sum(x.get(k,0) for x in rows) for k in ('passed','correct','grounded','unsupported_positive','missing_memory','wrong_experience','adopted','tokens','chat_calls','embedding_calls','embedding_tokens','memory_bytes','elapsed_seconds')},'tool_calls':sum(len(x['tool_calls']) for x in rows)}
        flush()
        print(json.dumps({'complete':report['complete'],'chat_calls':report['chat_calls'],'tokens':report['chat_tokens'],'error':report.get('error')}))

if __name__=='__main__':main()
