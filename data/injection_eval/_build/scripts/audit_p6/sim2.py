import json, difflib, re, sys
inp = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
ds = [json.loads(l) for l in open(sys.argv[2], encoding='utf-8')]
ids_in = {r['id'] for r in inp}
def grams(t, n=5):
    w = re.findall(r'\w+', t.lower())
    return set(tuple(w[i:i+n]) for i in range(max(0, len(w)-n+1)))
for r in inp:
    g = grams(r['text'])
    for d in ds:
        if d['id'] == r['id'] or d['source'] != r['source']: continue
        if d['id'] in ids_in and d['id'] < r['id']: continue
        a, b = r['text'], d['text']
        if abs(len(a)-len(b)) > 0.4*max(len(a), len(b)): continue
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        if sm.real_quick_ratio() < 0.7 or sm.quick_ratio() < 0.7: continue
        ratio = sm.ratio()
        g2 = grams(b); j = len(g & g2)/max(1, len(g | g2))
        if ratio >= 0.7 or j >= 0.4:
            print(f"{r['id']} ~ {d['id']}({d['label']}) ratio_nojunk={ratio:.2f} jac={j:.2f}")
