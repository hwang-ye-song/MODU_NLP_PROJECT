import json, glob, re, difflib, os
P = "<DATASET_ROOT>/_build/parts_v2"
mine_p = f"{P}/bipia_abstract_more.jsonl"
mine = [json.loads(l) for l in open(mine_p, encoding='utf-8')]
others = []
for f in glob.glob(f"{P}/*.jsonl") + ["<DATASET_ROOT>/_build/ja_llmail_candidates.jsonl"]:
    if os.path.basename(f) == 'bipia_abstract_more.jsonl' or not os.path.exists(f): continue
    for l in open(f, encoding='utf-8'):
        try: others.append((os.path.basename(f), json.loads(l)))
        except Exception: pass
def toks(t): return re.findall(r"\w+", t.lower())
def ng(t, n=5):
    w = toks(t); return set(tuple(w[i:i+n]) for i in range(len(w)-n+1))
mine_ng = [ng(r['text']) for r in mine]
oth_ng = [ng(r.get('text','')) for _, r in others]
# xsum id overlap
oth_x = {}
for f, r in others:
    o = r.get('origin') or {}
    if isinstance(o, dict) and o.get('xsum_id'): oth_x.setdefault(str(o['xsum_id']), []).append(r['id'])
iis = {}
for f, r in others:
    if r.get('injected_instruction'): iis.setdefault(r['injected_instruction'], []).append(r['id'])
for i, r in enumerate(mine):
    best = (0, None)
    for j, (f, o) in enumerate(others):
        a, b = mine_ng[i], oth_ng[j]
        if not a or not b: continue
        jac = len(a & b) / len(a | b)
        if jac > best[0]: best = (jac, o['id'])
    bw = (0, None)
    for k, r2 in enumerate(mine):
        if k == i: continue
        a, b = mine_ng[i], mine_ng[k]
        jac = len(a & b) / len(a | b) if a and b else 0
        if jac > bw[0]: bw = (jac, r2['id'])
    flags = []
    x = str(r['origin'].get('xsum_id'))
    if x in oth_x: flags.append('XSUM_REUSED:' + ','.join(oth_x[x]))
    if r.get('injected_instruction') in iis: flags.append('II_REUSED:' + ','.join(iis[r['injected_instruction']][:3]))
    print(r['id'], 'ext %.3f %s' % best, '| within %.3f %s' % bw, flags)
print('others', len(others))
