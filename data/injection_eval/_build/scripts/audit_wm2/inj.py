import json, sys, re
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
print(json.dumps(recs[0]['origin']), recs[0]['notes'], recs[20]['notes'], sep='\n')
lo,hi=int(sys.argv[2]),int(sys.argv[3])
for r in recs[lo:hi]:
    t=r['text']; ii=r['injected_instruction']
    i=t.find(ii)
    print('=====',r['id'],len(t),'pos',i,'count',t.count(ii), 'origin_row', r['origin'].get('row', r['origin'].get('index')))
    print('II:',repr(ii)[:700])
    print('CTX_BEFORE:',repr(t[max(0,i-200):i]))
    print('CTX_AFTER:',repr(t[i+len(ii):i+len(ii)+150]))
