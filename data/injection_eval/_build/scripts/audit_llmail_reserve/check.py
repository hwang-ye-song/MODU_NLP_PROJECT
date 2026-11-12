import json, sys, base64, codecs, glob, difflib, re, os
inp = sys.argv[1]; raw = sys.argv[2]; parts_dir = sys.argv[3]; cand = sys.argv[4]
recs = [json.loads(l) for l in open(inp, encoding='utf-8') if l.strip()]
print("n", len(recs))
# substring + basic integrity
for r in recs:
    t = r['text']; ii = r['injected_instruction']
    print(r['id'], 'len', len(t), 'sub', (ii in t) if ii else None, 'placeholder', bool(re.search(r'\{injection\}|<Attacker|\{[a-z_]+\}', t)),
          'nonascii', sorted(set(c for c in t if ord(c) > 127)), 'tail', repr(t[-40:]))
# decode
r6 = [r for r in recs if r['id'].endswith('r06')][0]
b = r6['text'].split('\n')[-1].strip()
print('r06 b64:', base64.b64decode(b).decode())
r8 = [r for r in recs if r['id'].endswith('r08')][0]
for w in ['pbagnpg','pbagnpg.pbz','pbas','vezngvba','fraqrnvy']:
    print('rot13', w, '->', codecs.decode(w, 'rot13'))
# raw source comparison
want = {r['origin']['row_index']: r for r in recs}
mx = max(want)
with open(raw, encoding='utf-8') as f:
    for i, line in enumerate(f):
        if i in want:
            d = json.loads(line)
            r = want[i]
            subj = d.get('subject'); body = d.get('body')
            rebuilt = f"Subject: {subj}\n\n{body}"
            print(r['id'], 'RowKey match', d.get('RowKey') == r['origin']['RowKey_or_job_id'] or d.get('job_id') == r['origin']['RowKey_or_job_id'],
                  'text==rebuilt', rebuilt == r['text'], 'keys', list(d.keys())[:12])
            if rebuilt != r['text']:
                print('  raw subj', repr(subj)[:200]); print('  raw body tail', repr(body[-200:]) if body else None)
        if i > mx: break
# dedup
def grams(s, n=5):
    w = re.findall(r'\w+', s.lower()); return set(tuple(w[i:i+n]) for i in range(max(0, len(w)-n+1)))
others = []
for p in glob.glob(os.path.join(parts_dir, '*.jsonl')) + [cand]:
    for l in open(p, encoding='utf-8'):
        if l.strip():
            d = json.loads(l); others.append((os.path.basename(p), d.get('id'), d.get('text', '')))
ids_exist = {}
for fn, i, t in others: ids_exist.setdefault(i, []).append(fn)
for r in recs:
    print(r['id'], 'id exists in', ids_exist.get(r['id']))
    g = grams(r['text']); best = []
    for fn, i, t in others:
        if i == r['id']: continue
        if abs(len(t) - len(r['text'])) > 0.6 * max(len(t), len(r['text'])): continue
        g2 = grams(t); jac = len(g & g2) / max(1, len(g | g2))
        if jac >= 0.3:
            best.append((round(jac, 2), fn, i))
        else:
            sm = difflib.SequenceMatcher(None, r['text'], t, autojunk=False)
            if sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.7:
                best.append(('dl', round(sm.ratio(), 2), fn, i))
    print('  near:', best[:6])
# within-set
for a in range(len(recs)):
    for b2 in range(a+1, len(recs)):
        ra, rb = recs[a], recs[b2]
        jac = len(grams(ra['text']) & grams(rb['text'])) / max(1, len(grams(ra['text']) | grams(rb['text'])))
        rat = difflib.SequenceMatcher(None, ra['text'], rb['text']).ratio()
        if jac > 0.3 or rat > 0.6: print('within', ra['id'], rb['id'], jac, rat)
