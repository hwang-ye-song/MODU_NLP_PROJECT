import json, sys
recs={json.loads(l)['id']:json.loads(l) for l in open(sys.argv[1],encoding='utf-8')}
for k in sys.argv[2:]:
    r=recs[k]; ii=r['injected_instruction']
    print('=====',k,len(ii)); print('II_TAIL:',repr(ii[-450:]))
