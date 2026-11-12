import json,statistics as st,collections,glob
R=[json.loads(l) for l in open('parts_v2/sep_more.jsonl',encoding='utf-8')]
O=[json.loads(l) for l in open('parts_v2/sep.jsonl',encoding='utf-8')]
print(len(R),len({r['id'] for r in R}),collections.Counter(r['label'] for r in R))
for r in R:
    if r['injected_instruction']: assert r['injected_instruction'] in r['text']
print({l:st.median(len(r['text']) for r in R if r['label']==l) for l in('injection','benign')}, max(len(r['text']) for r in R))
inj=[r for r in R if r['label']=='injection']
print(len({r['origin']['appended_task_id'] for r in inj}), len({r['origin']['subtask'] for r in R}))
print(collections.Counter(r['origin']['task_domain'] for r in inj),collections.Counter(r['origin']['task_domain'] for r in R if r['label']=='benign'))
oi={r['origin']['index'] for r in O}; print(any(r['origin']['index'] in oi for r in R))
op={r['origin']['appended_task_id'] for r in O if r['label']=='injection'}; print(any(r['origin']['appended_task_id'] in op for r in inj))
print(len({r['origin']['index'] for r in R}))
for r in R[:3]+R[20:23]+R[-3:]: print(r['id'],r['text'][:300].replace('\n',' '),'\n')
