"""Align EN/KO pairs of existing webpage translations into a segment glossary."""
import json, re, sys, collections
B='<DATASET_ROOT>/_build/'
TOK = re.compile(r'(<!--.*?-->|<[^>]*>|&lt;.*?&gt;)', re.S)
en={}
for f in ['parts_v2/webpage.jsonl','parts_v2/webpage_more.jsonl']:
    for l in open(B+f,encoding='utf-8'):
        r=json.loads(l); en[r['id']]=r
gl=collections.defaultdict(collections.Counter)
import glob
for f in glob.glob(B+'ko_parts/webpage*.jsonl'):
    for l in open(f,encoding='utf-8'):
        k=json.loads(l)
        e=en.get(k['pair_id'])
        if not e: continue
        a=TOK.split(e['text']); b=TOK.split(k['text'])
        if len(a)!=len(b):
            print('len mismatch',k['pair_id'],file=sys.stderr); continue
        for x,y in zip(a,b):
            if x!=y and x.strip():
                gl[x.strip()][y.strip()]+=1
out={k:dict(v) for k,v in gl.items()}
json.dump(out,open(sys.argv[1],'w',encoding='utf-8'),ensure_ascii=False,indent=0)
print(len(out))
