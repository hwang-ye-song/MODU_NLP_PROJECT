import json, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = '<DATASET_ROOT>/_build/parts_v2/bipia_abstract_more.jsonl'
OUT = '<DATASET_ROOT>/_build/ko_parts/abstract_more_ben.jsonl'

BASE_NOTE = ("Translated in Korean news-article style (기사체). Line breaks and line count preserved; "
             "XSum-style '' quote marks and any stray trailing quote kept as in source. Names of people, clubs, "
             "companies, organisations and most places kept in Latin script; countries/home nations and well-known "
             "names with standard Korean forms (영국, 런던, 잉글랜드, 프리미어리그 etc.) in Korean. Amounts, phone "
             "numbers, times, scores and timestamps kept as in source.")

EXTRA = {}
extra_path = os.path.join(HERE, 'extra_notes.json')
if os.path.exists(extra_path):
    EXTRA = json.load(open(extra_path, encoding='utf-8'))

tr = {}
for f in sorted(glob.glob(os.path.join(HERE, 'chunk*.txt'))):
    cur = None
    buf = []
    for line in open(f, encoding='utf-8').read().split('\n'):
        m = re.match(r'^@@@ (\S+)$', line)
        if m:
            if cur:
                tr[cur] = '\n'.join(buf).rstrip('\n')
            cur = m.group(1); buf = []
        else:
            buf.append(line)
    if cur:
        tr[cur] = '\n'.join(buf).rstrip('\n')

en = [json.loads(l) for l in open(SRC, encoding='utf-8')]
ben = [r for r in en if r['label'] == 'benign']
final = '--final' in sys.argv
out = []
ok = True
for r in ben:
    if r['id'] not in tr:
        if final:
            print('MISSING', r['id']); ok = False
        continue
    t = tr[r['id']]
    nl_en = r['text'].count('\n'); nl_ko = t.count('\n')
    if nl_en != nl_ko:
        print('LINECOUNT MISMATCH', r['id'], nl_en, nl_ko); ok = False
    # per-line check of leading quote char
    for i, (a, b) in enumerate(zip(r['text'].split('\n'), t.split('\n'))):
        if a.startswith('"') != b.startswith('"'):
            print('  leading-quote diff', r['id'], 'line', i + 1)
        if a.startswith("''") != b.startswith("''"):
            print('  leading-\'\' diff', r['id'], 'line', i + 1)
    # money tokens preserved
    for m in re.findall(r'(?:Â£|£|\$|â‚¬|€)[0-9][0-9.,]*(?:m|bn|k)?', r['text']):
        if m not in t:
            print('  money token missing', r['id'], m)
    hang = sum(1 for c in t if '\uac00' <= c <= '\ud7a3')
    lat_words = re.findall(r'[A-Za-z]{4,}', t)
    print(r['id'], 'en_len', len(r['text']), 'ko_len', len(t), 'hangul', hang, 'latin_words', len(lat_words))
    rec = {
        'id': r['id'] + '-ko', 'pair_id': r['id'], 'lang': 'ko', 'label': r['label'], 'source': r['source'],
        'subset': r['subset'], 'doc_type': r['doc_type'], 'text': t, 'injected_instruction': None,
        'origin': r['origin'], 'notes': r['notes'], 'core': r['core'],
        'translation_notes': BASE_NOTE + ((' ' + EXTRA[r['id']]) if r['id'] in EXTRA else ''),
    }
    out.append(rec)

if final:
    if not ok or len(out) != 30:
        print('NOT WRITING', ok, len(out)); sys.exit(1)
    with open(OUT, 'w', encoding='utf-8', newline='\n') as fo:
        for rec in out:
            fo.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print('WROTE', OUT, len(out))
else:
    print('checked', len(out), 'ok' if ok else 'PROBLEMS')
