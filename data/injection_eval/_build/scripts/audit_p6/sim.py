import json, difflib, re, sys, glob
inp = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
ds = [json.loads(l) for l in open(sys.argv[2], encoding='utf-8')]
def grams(t, n=5):
    w = re.findall(r'\w+', t.lower())
    return set(tuple(w[i:i+n]) for i in range(max(0, len(w)-n+1)))
G = {d['id']: grams(d['text']) for d in ds}
T = {d['id']: d['text'] for d in ds}
L = {d['id']: d['label'] for d in ds}
ids_in = {r['id'] for r in inp}
# check input in dataset and identical
for r in inp:
    if r['id'] not in T: print('MISSING in ds', r['id'])
    elif T[r['id']] != r['text']: print('TEXT DIFFERS', r['id'])
for r in inp:
    g = grams(r['text'])
    for d in ds:
        if d['id'] == r['id']: continue
        if d['id'] in ids_in and d['id'] < r['id']: continue
        g2 = G[d['id']]
        j = len(g & g2) / max(1, len(g | g2))
        if j >= 0.3:
            ratio = difflib.SequenceMatcher(None, r['text'], d['text']).ratio()
            print(f"{r['id']} ~ {d['id']}({L[d['id']]}) jac={j:.2f} ratio={ratio:.2f}")
        else:
            if abs(len(r['text']) - len(d['text'])) < 0.5*max(len(r['text']), len(d['text'])):
                q = difflib.SequenceMatcher(None, r['text'], d['text'])
                if q.quick_ratio() >= 0.8 and q.ratio() >= 0.8:
                    print(f"{r['id']} ~ {d['id']}({L[d['id']]}) jac={j:.2f} ratio={q.ratio():.2f} (ratio only)")
