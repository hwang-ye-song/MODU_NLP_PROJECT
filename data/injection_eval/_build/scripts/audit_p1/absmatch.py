import json
D='<SCRATCH>/dl/bipia_abstract/ctx/'
s=set()
for sp in ['test','train']:
    for l in open(D+sp+'.jsonl',encoding='utf-8'):
        if l.strip():
            r=json.loads(l)
            c=r.get('context') or r.get('document') or r.get('text')
            if isinstance(c,list): c='\n'.join(c)
            s.add(c)
print('n ctx',len(s))
rows=[json.loads(l) for l in open('<DATASET_ROOT>/_build/audit/input_en700_part1.jsonl',encoding='utf-8')]
for r in rows:
    if r['subset']!='abstract': continue
    t,ii=r['text'],r['injected_instruction']; i=t.find(ii)
    if i==0: c=t[len(ii)+1:]
    elif i+len(ii)==len(t): c=t[:i-1]
    else: c=t[:i-1]+t[i+len(ii)+1:]
    print(r['id'], c in s)
