import json, glob, difflib, re
def ng(t, n=5):
    w = re.findall(r'\w+', t.lower()); return set(tuple(w[i:i+n]) for i in range(max(1, len(w)-n+1)))
def clean(r):
    t = r['text']; ii = r.get('injected_instruction')
    return t.replace(ii, '').strip() if ii else t
recs = [json.loads(l) for l in open('<DATASET_ROOT>/_build/parts_v2/sep_more.jsonl', encoding='utf-8')]
others = []
files = [f for f in glob.glob('<DATASET_ROOT>/_build/parts_v2/*.jsonl') if not f.endswith('sep_more.jsonl')]
files += ['<DATASET_ROOT>/_build/ja_llmail_candidates.jsonl', '<DATASET_ROOT>/en/dataset_en_700.jsonl', '<DATASET_ROOT>/judge_attack/dataset_ja_600.jsonl']
ids = set()
for f in files:
    try:
        for l in open(f, encoding='utf-8'):
            r = json.loads(l); others.append((f.replace(chr(92), '/').split('/')[-1], r.get('id'), r.get('text',''), clean(r) if 'text' in r else '')); ids.add(r.get('id'))
    except FileNotFoundError: print('missing', f)
print('others', len(others))
print('id collisions:', [r['id'] for r in recs if r['id'] in ids])
pool = [('self', r['id'], r['text'], clean(r)) for r in recs]
for i, r in enumerate(recs):
    c = clean(r); g = ng(c); hits = []
    for (f, oid, ot, oc) in others + pool[:i] + pool[i+1:]:
        if oid == r['id'] and f == 'self': continue
        if not oc: continue
        go = ng(oc); j = len(g & go) / max(1, len(g | go))
        if j >= 0.3 or (abs(len(oc)-len(c)) < 0.5*len(c) and difflib.SequenceMatcher(None, c, oc, autojunk=False).quick_ratio() > 0.8 and difflib.SequenceMatcher(None, c, oc, autojunk=False).ratio() >= 0.6):
            ratio = difflib.SequenceMatcher(None, c, oc, autojunk=False).ratio()
            hits.append((f, oid, round(j, 2), round(ratio, 2)))
    if hits: print(r['id'], hits)
