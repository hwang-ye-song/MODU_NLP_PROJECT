import json, sys
OLD = "<SCRATCH>/dl/bipia_abstract/ctx"
ctx = {}
for sp in ('test', 'train'):
    lines = [json.loads(l) for l in open(f"{OLD}/{sp}.jsonl", encoding='utf-8')]
    meta = [json.loads(l) for l in open(f"{OLD}/{sp}_meta.jsonl", encoding='utf-8')]
    ctx[sp] = (lines, meta)
print('ctx keys sample', list(ctx['test'][0][0].keys()))
recs = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
for r in recs:
    o = r['origin']; sp = o['split']; i = o['index']
    lines, meta = ctx[sp]
    c = lines[i]; c = c.get('context', c.get('document', c))
    m = meta[i]
    metaok = (m['row_index'] == o['row_index'] and str(m['xsum_id']) == str(o['xsum_id']))
    t = r['text']; ii = r.get('injected_instruction')
    if r['label'] == 'benign':
        res = 'EXACT' if t == c else 'DIFF'
    else:
        pos = o['position']
        if pos == 'start': cand = ii + '\n' + c
        elif pos == 'end': cand = c + '\n' + ii
        else:
            k = t.find('\n' + ii + '\n')
            cand = None
            if k >= 0:
                rebuilt = t[:k] + t[k + len(ii) + 2:]
                res0 = rebuilt == c
                cand = t if res0 else None
        res = 'EXACT' if cand == t else 'DIFF'
    print(r['id'], sp, i, 'meta_ok' if metaok else 'META_MISMATCH', res, o.get('position'), o.get('attack_category'), o.get('attack_index'), 'ctxlen', len(c))
