"""List translatable units of the slice, with existing-glossary hits."""
import json, re, sys
B='<DATASET_ROOT>/_build/'
W='<SCRATCH>/work/webpage_more_ben_ko_a/'
TOK = re.compile(r'(<!--.*?-->|<[^>]*>|&lt;.*?&gt;)', re.S)
LATIN = re.compile(r'[A-Za-z]{2,}')
URLISH = re.compile(r'^(\S*[.@/]\S*|\||•)$')
ATTR = re.compile(r'\b(title|alt|placeholder|aria-label|data-[\w-]+|value)="([^"]*)"')
TR = json.load(open(B+'scripts/webpage_inj_ko_v2/tr_data.json',encoding='utf-8'))
AL = json.load(open(W+'aligned_gloss.json',encoding='utf-8'))
def lookup(s):
    if s in TR['segments']: return 'TR', TR['segments'][s]
    if s in AL: return 'AL', list(AL[s].keys())[0]
    return None, None
recs=[json.loads(l) for l in open(B+'parts_v2/webpage_more.jsonl',encoding='utf-8')]
ids=['web-ben-%d'%i for i in range(32,51)]
inj_text=' '.join(r['text'] for r in recs if r['label']=='injection')
units=set()
for r in recs:
    if r['id'] not in ids: continue
    print('=====', r['id'])
    for i,p in enumerate(TOK.split(r['text'])):
        if i%2==1:
            if p.startswith('<!--') or p.startswith('&lt;!--'):
                src,ko=lookup(p); print('  CMT', src, repr(p)[:150]); units.add(p)
            elif p.startswith('<'):
                for a,v in ATTR.findall(p):
                    if LATIN.search(v) and ' ' in v:
                        print('  ATTR', a, repr(v), lookup(v)[0])
            continue
        s=p.strip()
        if not s or not LATIN.search(s) or all(URLISH.match(w) for w in s.split()): continue
        src,ko=lookup(s)
        units.add(s)
        print('  TXT', src, 'INJ' if s in inj_text else '-', repr(s)[:160])
