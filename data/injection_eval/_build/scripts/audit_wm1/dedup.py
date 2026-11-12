import json, re, glob, difflib, os, collections

AUD = '<DATASET_ROOT>/_build/audit/'
inp = [json.loads(l) for l in open(AUD + 'input_webpage_more_1.jsonl', encoding='utf-8')]
ids = {r['id'] for r in inp}

others = []
for f in glob.glob('<DATASET_ROOT>/_build/parts_v2/*.jsonl') + [AUD + 'input_webpage_more_2.jsonl', '<DATASET_ROOT>/_build/ja_llmail_candidates.jsonl']:
    if not os.path.exists(f):
        continue
    for l in open(f, encoding='utf-8'):
        if l.strip():
            r = json.loads(l)
            others.append((os.path.basename(f), r))

in_more = [(f, r['id']) for f, r in others if r['id'] in ids]
print('input ids also present in other files:', collections.Counter(f for f, _ in in_more))

def toks(t):
    return re.findall(r'\w+', t.lower())

def grams(t, n=5):
    w = toks(t)
    return set(tuple(w[i:i+n]) for i in range(len(w) - n + 1))

G = {r['id']: grams(r['text']) for r in inp}
OG = [(f, r['id'], r['text'], grams(r['text'])) for f, r in others if r['id'] not in ids and r.get('source', '').lower().find('browse') >= 0 or (r['id'] not in ids and 'web' in r['id'])]
print('comparison pool size', len(OG))

def jac(a, b):
    return len(a & b) / max(1, len(a | b))

# within
for i, a in enumerate(inp):
    for b in inp[i+1:]:
        j = jac(G[a['id']], G[b['id']])
        sm = difflib.SequenceMatcher(None, a['text'], b['text'], autojunk=False)
        if j >= 0.3 or sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.6:
            print('WITHIN', a['id'], b['id'], 'jac %.2f' % j, 'ratio %.2f' % sm.ratio())
# against others
for a in inp:
    best = []
    for f, oid, ot, og in OG:
        j = jac(G[a['id']], og)
        if j >= 0.3:
            best.append((j, f, oid, ot))
    for j, f, oid, ot in sorted(best, reverse=True)[:3]:
        sm = difflib.SequenceMatcher(None, a['text'], ot, autojunk=False)
        print('CROSS', a['id'], f, oid, 'jac %.2f' % j, 'ratio %.2f' % sm.ratio())
# payload reuse vs others
spans = collections.defaultdict(list)
for f, r in others:
    ii = r.get('injected_instruction')
    if ii and r['id'] not in ids:
        spans[ii.strip()].append(r['id'])
for a in inp:
    ii = a.get('injected_instruction')
    if ii:
        within = [b['id'] for b in inp if b['id'] != a['id'] and b.get('injected_instruction') == ii]
        print('SPAN', a['id'], 'same-span within:', within, 'elsewhere:', spans.get(ii.strip(), [])[:6])
