import json, glob, difflib, sys
mine=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
myids={r['id'] for r in mine}
other=[]
for f in glob.glob('<DATASET_ROOT>/_build/parts_v2/*.jsonl')+['<DATASET_ROOT>/_build/ja_llmail_candidates.jsonl']:
    for l in open(f,encoding='utf-8'):
        r=json.loads(l); r['_f']=f.split('/')[-1]; other.append(r)
# check presence & equality
byid={}
for r in other: byid.setdefault(r['id'],[]).append(r)
for m in mine:
    o=[x for x in byid.get(m['id'],[]) if x['_f']!='ja_llmail_candidates.jsonl']
    if not o: print('NOT IN parts_v2', m['id'])
    elif any(x['text']!=m['text'] or x['label']!=m['label'] or x.get('injected_instruction')!=m['injected_instruction'] or x.get('doc_type')!=m['doc_type'] for x in o): print('DIFFERS from parts_v2', m['id'])
def sh(t):
    w=t.lower().split(); return set(tuple(w[i:i+5]) for i in range(len(w)-4))
OS=[(r,sh(r['text'])) for r in other]
for m in mine:
    a=sh(m['text'])
    for r,b in OS:
        if r['id']==m['id'] and r['_f']!='ja_llmail_candidates.jsonl': continue
        if r['id'] in myids and r['id']<=m['id']: continue
        jac=len(a&b)/max(1,len(a|b))
        rat=0
        if abs(len(r['text'])-len(m['text']))<0.3*max(len(r['text']),len(m['text'])):
            sm=difflib.SequenceMatcher(None,m['text'],r['text'],autojunk=False)
            if sm.quick_ratio()>=0.8: rat=sm.ratio()
        if jac>=0.5 or rat>=0.8:
            print(m['id'], r['id'], r['_f'], 'jac',round(jac,2),'ratio',round(rat,2))
