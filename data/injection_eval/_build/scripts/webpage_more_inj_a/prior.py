import re
"""Align existing EN webpage records with their KO translations segment-by-segment -> prior.json {en: [ko variants]}."""
import json, sys, collections
sys.path.insert(0, '.')
import seg
seg.LETTER = re.compile(r'[A-Za-z가-힣]')
segments = seg.segments
import re
W = '<DATASET_ROOT>/_build/'
en = {}
for f in ['parts_v2/webpage.jsonl']:
    for l in open(W + f, encoding='utf-8'):
        r = json.loads(l); en[r['id']] = r['text']
prior = collections.defaultdict(collections.Counter)
nal = 0; bad = 0
for f in ['ko_parts/webpage_inj.jsonl', 'ko_parts/webpage_ben.jsonl']:
    for l in open(W + f, encoding='utf-8'):
        r = json.loads(l)
        if r['source'] != 'BrowseSafe-Bench':
            continue
        a = [p for p in segments(en[r['pair_id']]) if p[0] == 'seg']
        b = [p for p in segments(r['text']) if p[0] == 'seg']
        if len(a) != len(b):
            bad += 1; continue
        nal += 1
        for x, y in zip(a, b):
            prior[x[3]][y[3]] += 1
json.dump({k: dict(v) for k, v in prior.items()}, open('prior.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=0)
print('aligned', nal, 'unaligned', bad, 'segments', len(prior))
