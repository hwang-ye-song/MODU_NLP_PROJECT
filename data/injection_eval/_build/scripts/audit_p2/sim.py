import json,sys,glob,re,os
from difflib import SequenceMatcher
mine=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
others=[]
for f in [sys.argv[2]]+glob.glob(sys.argv[3]):
    for l in open(f,encoding='utf-8'):
        l=l.strip()
        if l: r=json.loads(l); others.append((os.path.basename(f),r['id'],r['text']))
def body(t):
    return re.sub(r'^Subject:[^\n]*\n','',t)
def g5(t):
    w=re.findall(r'\w+',t.lower()); return set(tuple(w[i:i+5]) for i in range(max(0,len(w)-4)))
mg=[g5(r['text']) for r in mine]
res=[]
# within
for i in range(len(mine)):
    for j in range(i+1,len(mine)):
        a,b=mine[i]['text'],mine[j]['text']
        J=len(mg[i]&mg[j])/max(1,len(mg[i]|mg[j]))
        if J<0.05 and abs(len(a)-len(b))>3*min(len(a),len(b)): continue
        r=SequenceMatcher(None,a,b,autojunk=False).ratio() if min(len(a),len(b))<3200 else 0
        if r>=0.45 or J>=0.2: res.append(('IN',mine[i]['id'],mine[j]['id'],round(r,3),round(J,3)))
ids={r['id'] for r in mine}
for i,r in enumerate(mine):
    for f,oid,ot in others:
        if oid==r['id'] and ot==r['text']: continue
        og=g5(ot); J=len(mg[i]&og)/max(1,len(mg[i]|og))
        if J>=0.2: res.append(('EXT',r['id'],f+':'+oid,None,round(J,3)))
        elif J>=0.05:
            rr=SequenceMatcher(None,r['text'],ot,autojunk=True).quick_ratio()
            if rr>=0.8:
                rr=SequenceMatcher(None,r['text'],ot,autojunk=False).ratio()
                if rr>=0.5: res.append(('EXT',r['id'],f+':'+oid,round(rr,3),round(J,3)))
for x in res: print(x)
