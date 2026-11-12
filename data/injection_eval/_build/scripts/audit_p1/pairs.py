import json, difflib, sys, glob
base='<DATASET_ROOT>/_build/'
inp=[json.loads(l) for l in open(base+'audit/input_en700_part1.jsonl',encoding='utf-8')]
allp={}
for f in glob.glob(base+'parts_v2/*.jsonl'):
    for l in open(f,encoding='utf-8'):
        if l.strip():
            r=json.loads(l); allp[r['id']]=r
def ng(t,n=5):
    w=t.lower().split(); return set(tuple(w[i:i+n]) for i in range(len(w)-n+1))
def ctx(r):
    t=r['text']; ii=r['injected_instruction']
    return t.replace(ii,'').strip() if ii else t
ids=[r['id'] for r in inp]
for r in inp:
    o=allp.get(r['id'],{}).get('origin',{})
    r['_o']=(o.get('file'),o.get('index'),o.get('attack_category'),o.get('position'))
# within-input pair stats on full text and context
for a in range(len(inp)):
    for b in range(a+1,len(inp)):
        A,B=inp[a],inp[b]
        na,nb=ng(A['text']),ng(B['text'])
        j=len(na&nb)/max(1,len(na|nb))
        if j>=0.3 or (A['_o'][:2]==B['_o'][:2] and A['_o'][0]):
            r=difflib.SequenceMatcher(None,A['text'],B['text']).ratio()
            rc=difflib.SequenceMatcher(None,ctx(A),ctx(B)).ratio()
            print(A['id'],B['id'],'jac=%.2f ratio=%.2f ctxratio=%.2f'%(j,r,rc),A['_o'],B['_o'])
# cross against rest of parts_v2 (excluding ids in input)
inset=set(ids)
others=[r for k,r in allp.items() if k not in inset]
ong=[(r,ng(r['text'])) for r in others]
for A in inp:
    na=ng(A['text'])
    for r,nb in ong:
        if not nb: continue
        j=len(na&nb)/max(1,len(na|nb))
        if j>=0.4:
            print('CROSS',A['id'],r['id'],r['label'],'jac=%.2f'%j)
