"""Align existing EN webpage records with their KO translations to harvest prior renderings.
usage: align_prev.py <en.jsonl> <ko1.jsonl> [<ko2.jsonl> ...] <out.tsv>"""
import os, sys, json, re
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import tokens, ATTR, prose_attr, LATIN

en_path = sys.argv[1]
ko_paths = sys.argv[2:-1]
out = sys.argv[-1]
EN = {json.loads(l)['id']: json.loads(l) for l in open(en_path, encoding='utf-8')}
pairs = {}
for kp in ko_paths:
    for l in open(kp, encoding='utf-8'):
        r = json.loads(l)
        e = EN.get(r['pair_id'])
        if not e:
            continue
        te = list(tokens(e['text']))
        tk = list(tokens(r['text']))
        if len(te) != len(tk):
            print('skip (token count)', r['pair_id'])
            continue
        for (k1, a), (k2, b) in zip(te, tk):
            if k1 != k2:
                break
            if k1 == 'text':
                if a.strip() != b.strip() and LATIN.search(a):
                    pairs.setdefault(a.strip(), set()).add(b.strip())
            elif k1 == 'comment' and a != b:
                pairs.setdefault(a[4:-3].strip(), set()).add(b[4:-3].strip())
            elif k1 == 'tag' and a != b:
                ma = {m.group(2): (m.group(5) or m.group(6) or '') for m in ATTR.finditer(a)}
                mb = {m.group(2): (m.group(5) or m.group(6) or '') for m in ATTR.finditer(b)}
                for n in ma:
                    if n in mb and ma[n] != mb[n]:
                        pairs.setdefault(ma[n], set()).add(mb[n])
with open(out, 'w', encoding='utf-8') as f:
    for k in sorted(pairs, key=str.lower):
        f.write(k.replace('\n', '\\n') + '\t' + ' || '.join(sorted(pairs[k])).replace('\n', '\\n') + '\n')
print('pairs', len(pairs))
