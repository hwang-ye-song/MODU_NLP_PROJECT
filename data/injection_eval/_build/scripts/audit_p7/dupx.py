import json, sys, difflib, re, glob
mine=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
pool={}
for f in [sys.argv[2]]+glob.glob(sys.argv[3]):
    for l in open(f,encoding='utf-8'):
        l=l.strip()
        if not l: continue
        r=json.loads(l); pool.setdefault(r['id'],r)
print('pool',len(pool))
def ng(t,n=5):
    w=re.findall(r'\w+',t.lower()); return set(tuple(w[i:i+n]) for i in range(max(0,len(w)-n+1)))
P=[(k,v['text'],ng(v['text'])) for k,v in pool.items()]
ids=set(r['id'] for r in mine)
for r in mine:
    a=r['text']; ga=ng(a)
    if r['id'] not in pool: print('NOT IN POOL',r['id'])
    elif pool[r['id']]['text']!=a: print('TEXT DIFFERS FROM POOL',r['id'])
    for k,t,g in P:
        if k==r['id'] or (k in ids and k<r['id']): continue
        j=len(ga&g)/max(1,len(ga|g))
        sm=difflib.SequenceMatcher(None,a,t)
        if j>=0.3 or (sm.real_quick_ratio()>0.8 and sm.quick_ratio()>0.8 and sm.ratio()>0.7):
            print(r['id'],k,'jac',round(j,2),'ratio',round(difflib.SequenceMatcher(None,a,t).ratio(),2))
