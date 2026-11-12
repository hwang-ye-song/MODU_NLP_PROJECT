import json, yaml, ast
SRC='<DATASET_ROOT>/_build/parts_v2/agentdojo_tools.jsonl'
NL_KEYS={'subject','body','title','description','location','content'}
def load():
    return [r for r in map(json.loads, open(SRC,encoding='utf8')) if r['label']=='benign']
def kind(r):
    t=r['text']
    if r['subset'].startswith('travel'): return 'review'
    if r['subset']=='banking_file': return 'raw'
    return 'yaml'
def parse(r):
    k=kind(r); t=r['text']
    if k=='review':
        d=ast.literal_eval(t); assert str(d)==t; return d
    if k=='raw': return t
    o=yaml.safe_load(t); assert yaml.safe_dump(o).strip()==t, r['id']; return o
def leaves(o, out, key=None):
    if isinstance(o,dict):
        for k,v in o.items(): leaves(v,out,k)
    elif isinstance(o,list):
        for v in o: leaves(v,out,key)
    elif isinstance(o,str) and key in NL_KEYS: out.append((key,o))
    return out
def nl_strings(r):
    o=parse(r); k=kind(r)
    if k=='raw': return [('raw',o)]
    if k=='review':
        (name,s),=o.items()
        h,rv=s.split('\nReviews: ',1)
        return [('review',x) for x in rv.split('\n')]
    return leaves(o,[])
