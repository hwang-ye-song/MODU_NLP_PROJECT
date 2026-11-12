import json, re, sys
sys.path.insert(0, '.')
from lib import TOK
ids = sys.argv[1:]
for l in open('out_tmp.jsonl', encoding='utf-8'):
    o = json.loads(l)
    if o['pair_id'].split('-')[-1] in ids:
        parts = TOK.split(o['text'])
        vis = ' ¦ '.join(p.strip() for p in parts[0::2] if p.strip())
        print('=====', o['id']); print(vis); print()
