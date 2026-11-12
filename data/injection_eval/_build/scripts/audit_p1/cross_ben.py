import json, difflib, glob
base='<DATASET_ROOT>/_build/'
inp=[json.loads(l) for l in open(base+'audit/input_en700_part1.jsonl',encoding='utf-8')]
ben=[]
for f in glob.glob(base+'parts_v2/*.jsonl'):
    for l in open(f,encoding='utf-8'):
        if l.strip():
            r=json.loads(l)
            if r['label']=='benign': ben.append(r)
print('benign total',len(ben))
for A in inp:
    c=A['text'].replace(A['injected_instruction'],'').strip()
    best=(0,None)
    for B in ben:
        if abs(len(B['text'])-len(c))>0.5*max(len(c),1): continue
        sm=difflib.SequenceMatcher(None,c,B['text'])
        if sm.real_quick_ratio()<0.7 or sm.quick_ratio()<0.7: continue
        r=sm.ratio()
        if r>best[0]: best=(r,B['id'])
    if best[0]>=0.7: print(A['id'],'best benign ctx ratio %.2f'%best[0],best[1])
