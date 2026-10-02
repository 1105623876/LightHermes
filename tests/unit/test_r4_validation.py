"""Check experiment oracles offline; never call a configured model."""
import json

import pytest

from scripts.r4_replay import DEVELOPMENT, EVALUATION, task_tools
from scripts.r4_scale import VPTree, vector
import heapq
import math


def test_fixed_tools_match_frozen_outputs_and_reject_unscoped_requests(tmp_path):
    for i, case in enumerate(DEVELOPMENT + EVALUATION):
        workspace = tmp_path / str(i)
        workspace.mkdir()
        (workspace / 'input').write_bytes(case[1].encode())
        funcs, calls = task_tools(workspace, case, str(i), {'approved'})
        inspect, process = funcs
        assert json.loads(inspect())['family'] == case[0]
        op, method = {'csv': ('extract','utf-8-sig'), 'money': ('money','decimal'),
                      'copy': ('copy','literal'), 'integer': ('passthrough','literal')}[case[0]]
        process(op, field=case[2], method=method)
        raw = (workspace/'output').read_bytes()
        assert (raw if isinstance(case[3],bytes) else json.loads(raw)) == case[3]
        assert (workspace/'input').read_bytes() == case[1].encode()
        with pytest.raises(ValueError, match='Unknown experience'):
            process(op, field=case[2], method=method, experience_id='unscoped')
        with pytest.raises(ValueError, match='Unsupported'):
            process('bash')
        assert calls[-1]['ok'] is False


def test_exact_tree_matches_flat_with_ties_and_small_leaves():
    for vectors in ([vector(i,8) for i in range(100)], [[1.,0.]]*40, [[1.,0.], [0.,1.]]):
        tree = VPTree(vectors)
        for query in (vectors[0], vector(999,len(vectors[0]))):
            expected = heapq.nsmallest(5, ((math.dist(query,v),i) for i,v in enumerate(vectors)))
            actual, visited = tree.search(query)
            assert actual == expected
            assert 0 < visited <= len(vectors)
