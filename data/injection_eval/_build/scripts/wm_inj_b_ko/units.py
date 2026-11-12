import json, sys
sys.path.insert(0, '.')
from lib import *
TR = json.load(open('<DATASET_ROOT>/_build/scripts/webpage_inj_ko_v2/tr_data.json', encoding='utf-8'))
G = {**TR['segments'], **TR['payloads']}
lo, hi = int(sys.argv[1]), int(sys.argv[2])
for n in range(lo, hi + 1):
    rid = f'web-inj-{n}'
    t = open(f'src/{rid}.html', encoding='utf-8').read()
    print('=====', rid)
    seen = set()
    for kind, s in text_nodes(t):
        if kind == 'code':
            print('  [CODE]', s[:200].replace('\n', ' '))
            continue
        if kind.startswith('attr') and not is_prose(s):
            continue
        if kind == 'text' and (url_like(s) or not LATIN_WORD.search(s)):
            continue
        if (kind, s) in seen:
            continue
        seen.add((kind, s))
        tag = 'G ' if s in G else ''
        print(f'  [{kind}] {tag}{s!r}')
