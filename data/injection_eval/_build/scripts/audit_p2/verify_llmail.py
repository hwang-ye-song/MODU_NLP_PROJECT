import json,sys
mine={json.loads(l)['id']:json.loads(l) for l in open(sys.argv[1],encoding='utf-8')}
parts={}
for l in open(sys.argv[2],encoding='utf-8'):
    r=json.loads(l); parts[r['id']]=r
need={}
for i,r in mine.items():
    if i.startswith('llmail'):
        need[parts[i]['origin']['row_index']]=i
found=0
with open(sys.argv[3],encoding='utf-8') as f:
    for idx,l in enumerate(f):
        if idx in need:
            raw=json.loads(l); i=need[idx]; t=mine[i]['text']
            subj=raw.get('subject'); body=raw.get('body')
            cand="Subject: %s\n\n%s"%(subj,body)
            found+=1
            if cand!=t:
                print('MISMATCH',i,idx,len(cand),len(t), repr(cand[:80]), repr(t[:80]))
            if parts[i]['origin'].get('RowKey_or_job_id') not in (raw.get('RowKey'),raw.get('job_id')): print('KEYDIFF',i,list(raw.keys())[:12])
print('checked',found,'of',len(need))
