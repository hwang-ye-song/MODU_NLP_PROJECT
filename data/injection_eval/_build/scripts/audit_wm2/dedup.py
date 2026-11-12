import json, sys, glob, re, difflib, html
inp=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
ids={r['id'] for r in inp}
others=[]
for f in glob.glob('<DATASET_ROOT>/_build/parts_v2/*.jsonl')+['<DATASET_ROOT>/_build/audit/input_webpage_more_1.jsonl','<DATASET_ROOT>/_build/ja_llmail_candidates.jsonl']:
    try:
        for l in open(f,encoding='utf-8'):
            if l.strip():
                o=json.loads(l); o['_f']=f.split('/')[-1]; others.append(o)
    except FileNotFoundError: print('missing',f)
print('others',len(others),'id overlap',[ (o['id'],o['_f']) for o in others if o['id'] in ids][:10])
# row_index overlap with existing browsesafe items
rows={}
for o in others:
    org=o.get('origin') or {}
    if isinstance(org,dict) and 'browsesafe' in str(org.get('url','')): rows.setdefault(org.get('row_index'),[]).append((o['id'],o['_f']))
for r in inp:
    if r['origin']['row_index'] in rows: print('ROW OVERLAP',r['id'],rows[r['origin']['row_index']])
def vis(t):
    u=html.unescape(html.unescape(t)); u=re.sub(r'<[^>]+>',' ',u); return re.sub(r'\s+',' ',u).strip().lower()
def ng(t,n=5):
    w=re.findall(r'\w+',t); return {tuple(w[i:i+n]) for i in range(max(0,len(w)-n+1))}
pool=[(o['id'],o['_f'],o['text']) for o in others if o['id'] not in ids]+[(r['id'],'self',r['text']) for r in inp]
pv={k:(vis(t),ng(vis(t))) for k,_,t in pool}
for r in inp:
    v,g=pv[r['id']]
    best=[]
    for k,f,t in pool:
        if k==r['id']: continue
        v2,g2=pv[k]
        if not g or not g2: continue
        j=len(g&g2)/len(g|g2)
        if j>0.3:
            ratio=difflib.SequenceMatcher(None,v[:4000],v2[:4000],autojunk=False).ratio()
            best.append((round(j,2),round(ratio,2),k,f))
    best.sort(reverse=True)
    if best: print(r['id'],best[:4])
