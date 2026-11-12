import json, sys, collections
sys.path.insert(0, '.')
from lib import *
en = {json.loads(l)['id']: json.loads(l) for l in open('<DATASET_ROOT>/_build/parts_v2/webpage.jsonl', encoding='utf-8')}
M = collections.defaultdict(set)
for fn in ['webpage_ben', 'webpage_inj']:
    for l in open(f'<DATASET_ROOT>/_build/ko_parts/{fn}.jsonl', encoding='utf-8'):
        k = json.loads(l)
        e = en.get(k['pair_id'])
        if not e: continue
        a = TOK.split(e['text']); b = TOK.split(k['text'])
        if len(a) != len(b):
            continue
        for i in range(0, len(a), 2):
            s, t = a[i].strip(), b[i].strip()
            if s and s != t and LATIN_WORD.search(s):
                M[s].add(t)
json.dump({k: sorted(v) for k, v in M.items()}, open('old_map.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print(len(M))
for k, v in M.items():
    if len(k) < 60: print(repr(k), '=>', v)
