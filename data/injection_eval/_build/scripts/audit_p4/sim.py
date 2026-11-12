import json, re, difflib, sys
def ngrams(s, n=5):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i+n]) for i in range(max(0, len(w)-n+1))}
P = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
A = [json.loads(l) for l in open(sys.argv[2], encoding='utf-8')]
ids = {r['id'] for r in P}
print('part ids in dataset:', sum(1 for r in A if r['id'] in ids), 'dataset size', len(A))
G = {r['id']: ngrams(r['text']) for r in A}
for r in P:
    G.setdefault(r['id'], ngrams(r['text']))
pairs = []
for p in P:
    gp = G[p['id']]
    for a in A:
        if a['id'] == p['id']: continue
        if a['id'] in ids and a['id'] < p['id']: continue
        ga = G[a['id']]
        j = len(gp & ga)/len(gp | ga) if gp and ga else 0
        sm = difflib.SequenceMatcher(None, p['text'], a['text'], autojunk=False)
        if sm.real_quick_ratio() < 0.8 and j < 0.5: continue
        if sm.quick_ratio() < 0.8 and j < 0.5: continue
        r = sm.ratio()
        if r >= 0.8 or j >= 0.5:
            pairs.append((p['id'], a['id'], round(r,3), round(j,3)))
for x in pairs: print(*x)
