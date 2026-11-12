import json, sys
a,b=int(sys.argv[1]),int(sys.argv[2])
rows=[json.loads(l) for l in open('<DATASET_ROOT>/_build/audit/input_en700_part1.jsonl',encoding='utf-8')]
for r in rows[a:b]:
    t=r['text']; ii=r['injected_instruction']
    if ii and ii in t:
        i=t.find(ii); t=t[:i]+'[[INJ>>'+ii+'<<INJ]]'+t[i+len(ii):]
    print('=====',r['id'],r['label'],r['subset'],r['doc_type'],'|notes:',r.get('notes','')[:160])
    print(t)
