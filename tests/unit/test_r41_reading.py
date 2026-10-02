"""Oracles and treatment separation for the reading-policy experiment."""
import json
from scripts.r41_reading import install_policy, populate, score, artifact_tool
from lighthermes.runtime_memory import RuntimeMemory


def test_clue_hides_procedure_but_read_starts_at_beginning(tmp_path):
    memory=RuntimeMemory(tmp_path,project_id='test')
    memory.begin('legacy-v1','default_user','setup')
    ids=populate(memory.store,memory.scope)
    observed=install_policy(memory,'clue')
    text=memory.seed('legacy-v1')
    assert ids['procedure'] in text
    assert 'CRLF' not in text
    content=memory.read_memory(ids['procedure'])
    assert 'CRLF' in content
    assert json.loads(content)['offset']==0
    assert observed['read_ids']==[ids['procedure']]
    assert 0 <= memory.remaining <= 4000
    memory.store.close()


def test_demand_does_not_query_or_spend_until_search(tmp_path):
    memory=RuntimeMemory(tmp_path,project_id='test')
    memory.begin('legacy-v1','default_user','setup')
    ids=populate(memory.store,memory.scope)
    observed=install_policy(memory,'demand')
    assert memory.seed('legacy-v1')==''
    assert memory.remaining==4000 and not memory.offsets
    assert ids['procedure'] in memory.search_memory('legacy-v1')
    assert observed['shown_ids']
    memory.store.close()


def test_oracle_separates_unsupported_answer_and_action_metadata(tmp_path):
    (tmp_path/'input').write_bytes(b'alpha\nbeta\n')
    write,operations=artifact_tool(tmp_path)
    write('crlf',experience_id='nonexistent')
    assert (tmp_path/'output').read_bytes()==b'alpha\r\nbeta\r\n'
    observation={'shown_ids':[],'read_ids':[]}
    verdict=score({'answer':None},'{"answer":"AES","evidence_ids":[]}',observation,{},[],None,b'')
    assert verdict['unsupported_positive'] and not verdict['correct']
    verdict=score({'action':'copy'},'{}',observation,{},operations,b'alpha\nbeta\n',b'alpha\nbeta\n')
    assert verdict['correct'] and verdict['wrong_experience']
