import json, os
OLD='<SCRATCH>/dl/bipia/benchmark/'
ctxs={}
for task in ['email','table','code']:
    s=set()
    for sp in ['test','train']:
        for l in open(OLD+f'{task}/{sp}.jsonl',encoding='utf-8'):
            if l.strip():
                c=json.loads(l)['context']
                if task=='code': c='\n'.join(c)
                s.add(c)
    ctxs[task]=s
atk=set()
for f in ['text_attack_test.json','text_attack_train.json','code_attack_test.json','code_attack_train.json']:
    d=json.load(open(OLD+f,encoding='utf-8'))
    for v in d.values(): atk.update(v)
rows=[json.loads(l) for l in open('<DATASET_ROOT>/_build/audit/input_en700_part1.jsonl',encoding='utf-8')]
for r in rows:
    t,ii=r['text'],r['injected_instruction']
    ok_atk = ii in atk
    i=t.find(ii)
    if i==0: c=t[len(ii)+1:]
    elif i+len(ii)==len(t): c=t[:i-1]
    else: c=t[:i-1]+t[i+len(ii)+1:]
    src = 'n/a'
    if r['subset'] in ctxs: src = c in ctxs[r['subset']]
    if not ok_atk or src is False: print(r['id'],'attack_in_bipia=',ok_atk,'ctx_exact_in_src=',src)
print('done')
