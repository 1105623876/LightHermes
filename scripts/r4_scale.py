"""Offline production scale and exact VP-tree experiment; standard library only."""
import argparse
import hashlib
import heapq
import json
import math
import platform
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from lighthermes.runtime_memory import RuntimeMemory, serialized
from lighthermes.semantic import SemanticIndex
from lighthermes.store import MemoryStore
from lighthermes.tools import ToolBudgetExceeded


def stats(values):
    ordered = sorted(values)
    return {'p50_ms': statistics.median(ordered), 'p95_ms': ordered[math.ceil(.95*len(ordered))-1], 'samples': len(ordered)}


def timed(fn):
    start = time.perf_counter(); value = fn()
    return value, (time.perf_counter()-start)*1000


def vector(seed, dimensions):
    rng = random.Random(seed)
    raw = [rng.gauss(0, 1) for _ in range(dimensions)]
    norm = math.hypot(*raw)
    return [x/norm for x in raw]


class VPTree:
    """Exact metric tree prototype. Distance kernel matches the flat control."""
    def __init__(self, vectors):
        self.vectors = vectors
        def build(ids):
            if len(ids) <= 16:
                return ids
            pivot = ids[-1]
            ordered = sorted((math.dist(vectors[pivot], vectors[i]), i) for i in ids[:-1])
            middle = len(ordered)//2
            return (pivot, ordered[middle][0], build([i for _,i in ordered[:middle]]), build([i for _,i in ordered[middle:]]))
        self.root = build(list(range(len(vectors))))

    def search(self, query, k=5):
        heap, visited = [], 0
        def visit(node):
            nonlocal visited
            def consider(identifier):
                nonlocal visited
                distance = math.dist(query, self.vectors[identifier]); visited += 1
                item = (-distance, -identifier)
                if len(heap) < k: heapq.heappush(heap, item)
                elif item > heap[0]: heapq.heapreplace(heap, item)
                return distance
            if isinstance(node, list):
                for identifier in node: consider(identifier)
                return
            pivot, radius, left, right = node
            distance = consider(pivot)
            tau = lambda: -heap[0][0] if len(heap) == k else math.inf
            if distance < radius:
                if distance-tau() <= radius: visit(left)
                if distance+tau() >= radius: visit(right)
            else:
                if distance+tau() >= radius: visit(right)
                if distance-tau() <= radius: visit(left)
        visit(self.root)
        return sorted((-d,-i) for d,i in heap), visited


def tree_case(n, dimensions, clustered):
    vectors = []
    centers = [vector(100+i, dimensions) for i in range(8)]
    for i in range(n):
        raw = vector(4204+i, dimensions)
        if clustered:
            raw = [x + .12*y for x,y in zip(centers[i%8],raw)]
            norm = math.hypot(*raw); raw = [x/norm for x in raw]
        vectors.append(raw)
    tree, build_ms = timed(lambda: VPTree(vectors))
    flat_ms, tree_ms, visits, matches = [], [], [], []
    for i in range(10):
        query = vector(70000+i, dimensions)
        if clustered:
            query = [x+.12*y for x,y in zip(centers[i%8],query)]
            norm=math.hypot(*query); query=[x/norm for x in query]
        flat, elapsed = timed(lambda: heapq.nsmallest(5, ((math.dist(query,v),j) for j,v in enumerate(vectors))))
        result, elapsed_tree = timed(lambda: tree.search(query))
        flat_ms.append(elapsed); tree_ms.append(elapsed_tree); visits.append(result[1]/n)
        matches.append([i for _,i in flat] == [i for _,i in result[0]])
    return {'n': n, 'dimensions': dimensions, 'distribution': 'clustered' if clustered else 'independent',
            'build_ms': build_ms, 'flat': stats(flat_ms), 'tree': stats(tree_ms),
            'mean_visit_fraction': statistics.mean(visits), 'exact_top5_all': all(matches)}


def scale_case(root, n, dimensions):
    path = root / f'n{n}' / 'lighthermes.sqlite3'
    embed_calls, embed_texts = 0, 0
    batch_sizes=[]; candidate_counts=[]; result_counts=[]
    def embed(texts):
        nonlocal embed_calls, embed_texts
        embed_calls += 1; embed_texts += len(texts)
        batch_sizes.append(len(texts))
        return [vector(4204+int.from_bytes(hashlib.sha256(t.encode()).digest()[:8], 'big'), dimensions) for t in texts]
    start=time.perf_counter()
    store=MemoryStore(path)
    scope=serialized(['project','default_user','scale'])
    ids=[]
    for i in range(n):
        text=f'project record item{i:05d} release rule {i}。项目约束。'
        source=store.append_event(scope, 'seed', str(i), {'content':text})
        ids.append(store.remember(scope,'fact',text,[source],status='active'))
    write_ms=(time.perf_counter()-start)*1000
    index=SemanticIndex(store,model='offline-1024',embed=embed,min_score=.01)
    start=time.perf_counter()
    while True:
        index.begin(); index.index([scope])
        if index.status['pending']==0: break
    index_ms=(time.perf_counter()-start)*1000
    document_embeddings=embed_texts
    store.close(); store=MemoryStore(path)
    index=SemanticIndex(store,model='offline-1024',embed=embed,min_score=.01)
    def search(q):
        index.begin()
        lexical=store.search(q,scope,50)
        original=store.read_entry
        count=0
        def counted(*args, **kwargs):
            nonlocal count
            count+=1
            return original(*args, **kwargs)
        store.read_entry=counted
        try:
            result=index.search(q,[scope],lexical,4)
            candidate_counts.append(count); result_counts.append(len(result))
            return result
        finally:
            store.read_entry=original
    _,first_ms=timed(lambda:search('item00000'))
    full=[]; fts=[]
    for i in range(10):
        q=f'item{(i*997)%n:05d}'
        _,ms=timed(lambda:search(q));full.append(ms)
        _,ms=timed(lambda:store.search(q,scope,50));fts.append(ms)
    rows,read_ms=timed(lambda:store.db.execute('SELECT vector FROM entry_vectors').fetchall())
    vectors,decode_ms=timed(lambda:[json.loads(r[0]) for r in rows])
    q=vector(4204,dimensions)
    _,dot_ms=timed(lambda:[sum(x*y for x,y in zip(q,v)) for v in vectors])
    current=store.read_entry(ids[0],scope)
    duplicate=store.remember(scope,'fact',current['content'],current['source_refs'],status='active')
    source=store.append_event(scope,'modify','one',{'content':'replacement omega'})
    replacement,update_ms=timed(lambda:store.remember(scope,'fact','replacement omega',[source],status='active',supersedes=ids[0]))
    index.begin(); index.index([scope])
    _,forget_ms=timed(lambda:store.forget(replacement,scope))
    correctness={'duplicate_same_id':duplicate==ids[0], 'old_not_searchable':not store.search('item00000',scope),
        'forgotten_not_searchable':not store.search('omega',scope),
        'vectors_invalidated':not store.db.execute('SELECT 1 FROM entry_vectors WHERE entry_id IN (?,?)',(ids[0],replacement)).fetchone(),
        'other_scope_empty':not index.search('item00001',['unrelated'],[],4),
        'old_documents_not_reembedded':embed_texts == n+12,
        'candidates_bounded':max(candidate_counts)<=50 and max(result_counts)<=4,
        'incremental_batch_bounded':max(batch_sizes)<=16}
    usage=store.usage(); store.close()
    memory=RuntimeMemory(path.parent,project_id='scale',semantic={'model':'offline-1024','embed':embed,'min_score':.01})
    memory.begin('item00001','default_user','budget')
    seed=memory.seed('item00001')
    budget_stopped=False
    try:
        for query in ('item00002', 'item00003'):
            memory.search_memory(query)
    except ToolBudgetExceeded:
        budget_stopped=True
    correctness['injection_within_4000_bytes']=0<=memory.remaining<=4000
    memory.store.close()
    return {'n':n,'dimensions':dimensions,'write_ms':write_ms,'index_ms':index_ms,'first_query_ms':first_ms,
        'warm_query':stats(full),'fts':stats(fts),'profile_ms':{'sqlite_read':read_ms,'json_decode':decode_ms,'python_dot':dot_ms},
        'correct_ms':update_ms,'forget_ms':forget_ms,'document_embeddings':document_embeddings,
        'embedding_calls':embed_calls,'max_embedding_batch':max(batch_sizes),
        'semantic_candidate_counts':candidate_counts,'returned_counts':result_counts,'usage':usage,'seed_bytes':len(seed.encode()),'budget_stopped':budget_stopped,'checks':correctness}


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    report={'seed':4204,'python':sys.version,'platform':platform.platform(),'machine':platform.machine(),
            'note':'Synthetic local embeddings. First query is a new connection, not OS cold cache. Standard-library VP-tree prototype, not a production ANN comparison.', 'scale':[],'trees':[]}
    def flush(): args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='lighthermes-r4-scale-') as root:
        for n in (100,1000,10000):
            report['scale'].append(scale_case(Path(root),n,1024));flush()
            print(json.dumps({'scale_done':n}),flush=True)
    with tempfile.TemporaryDirectory(prefix='lighthermes-r4-long-') as root:
        memory=RuntimeMemory(root,project_id='long')
        memory.begin('固定约束 alpha','default_user','same-session')
        identifier=memory.store.remember(memory.scope,'fact','固定约束 alpha',[memory.source],status='active')
        byte_counts=[]
        for turn in range(200):
            memory.begin('alpha','default_user','same-session')
            byte_counts.append(len(memory.seed('alpha').encode()))
        report['long_session']={'turns':200,'seed_bytes_min':min(byte_counts),'seed_bytes_max':max(byte_counts),
            'checks':{'no_injection_growth':len(set(byte_counts))==1,'bounded':max(byte_counts)<=1500,
                      'one_active_fact':memory.store.db.execute("SELECT count(*) FROM entries WHERE status='active'").fetchone()[0]==1}}
        memory.store.close();flush()
    for dimensions in (8,1024):
        for clustered in (False,True):
            report['trees'].append(tree_case(10000,dimensions,clustered));flush()
            print(json.dumps({'tree_done':dimensions,'clustered':clustered}),flush=True)
    report['passed']=all(all(x['checks'].values()) for x in report['scale']) and all(x['exact_top5_all'] for x in report['trees']) and all(report['long_session']['checks'].values());flush()


if __name__=='__main__': main()
