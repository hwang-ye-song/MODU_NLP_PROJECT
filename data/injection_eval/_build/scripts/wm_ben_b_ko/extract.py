"""List translatable segments per page. usage: extract.py <src_dir> <out_dir>"""
import os, re, sys, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import tokens, ATTR, prose_attr, LATIN, esc_tokens

src, out = sys.argv[1:3]
os.makedirs(out, exist_ok=True)
for fn in sorted(os.listdir(src)):
    text = open(os.path.join(src, fn), encoding='utf-8', newline='').read()
    segs = []
    seen = set()

    def add(kind, s):
        if (kind, s) in seen:
            return
        seen.add((kind, s))
        segs.append((kind, s))

    for kind, p in tokens(text):
        if kind == 'text' and '&lt;' in p:
            for k2, q in esc_tokens(p):
                if k2 == 'text':
                    if q.strip() and LATIN.search(q):
                        add('ET', q.strip())
                elif k2 == 'ecomment':
                    if LATIN.search(q[7:-6]):
                        add('EC', q[7:-6].strip())
                else:
                    for m in ATTR.finditer(q):
                        val = m.group(5) if m.group(5) is not None else m.group(6)
                        pa = prose_attr(m.group(2), q)
                        if pa and val and LATIN.search(val):
                            add('EA:' + m.group(2) + ('?' if pa == 'maybe' else ''), val)
        elif kind == 'text':
            s = p.strip()
            if s and LATIN.search(s):
                add('T', s)
        elif kind == 'comment':
            inner = p[4:-3].strip()
            if LATIN.search(inner):
                add('C', inner)
        elif kind == 'code':
            if LATIN.search(p) and re.search(r'/\*|//|["\'][A-Z][a-z]+ [a-z]', p):
                add('X', p)
        else:
            for m in ATTR.finditer(p):
                val = m.group(5) if m.group(5) is not None else m.group(6)
                pa = prose_attr(m.group(2), p)
                if pa and val and LATIN.search(val):
                    add('A:' + m.group(2) + ('?' if pa == 'maybe' else ''), val)
    with open(os.path.join(out, fn.replace('.html', '.txt')), 'w', encoding='utf-8') as f:
        for k, s in segs:
            f.write(f'[{k}] {s}\n')
    print(fn, len(text), 'segs', len(segs), 'chars', sum(len(s) for k, s in segs))
