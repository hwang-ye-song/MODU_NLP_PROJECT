"""Build WD/ko_parts/abstract_inj.jsonl from Korean chunk files.

usage: python -X utf8 -I build.py <en_jsonl> <chunk_dir> <out_jsonl>
Chunk files ko_c*.txt: blocks introduced by a line '@@@ <EN id>' followed by the
Korean text with the same line structure as the EN text. Optional line
'@@NOTE <extra translation note>' directly after the header.
"""
import json, re, sys, glob, os

en_path, chunk_dir, out_path = sys.argv[1:4]
rs = [json.loads(l) for l in open(en_path, encoding='utf8')]
inj = [r for r in rs if r['label'] == 'injection']

ko, extra = {}, {}
for f in sorted(glob.glob(os.path.join(chunk_dir, 'ko_c*.txt'))):
    raw = open(f, encoding='utf8').read()
    blocks = re.split(r'^@@@ ', raw, flags=re.M)
    for b in blocks[1:]:
        head, _, body = b.partition('\n')
        rid = head.strip()
        if body.startswith('@@NOTE '):
            note, _, body = body.partition('\n')
            extra[rid] = note[len('@@NOTE '):].strip()
        if body.endswith('\n'):
            body = body[:-1]
        assert rid not in ko, ('dup', rid)
        ko[rid] = body

HANGUL = re.compile(r'[가-힣]')
LATIN = re.compile(r'[A-Za-z]')
out, problems = [], []
for r in inj:
    rid = r['id']
    if rid not in ko:
        problems.append((rid, 'missing'))
        continue
    t_en, t_ko = r['text'], ko[rid]
    le, lk = t_en.split('\n'), t_ko.split('\n')
    if len(le) != len(lk):
        problems.append((rid, f'line count {len(le)} vs {len(lk)}'))
        continue
    for i, (a, b) in enumerate(zip(le, lk)):
        if (a.strip() == '') != (b.strip() == ''):
            problems.append((rid, f'blank mismatch line {i}'))
        if b != b.strip():
            problems.append((rid, f'stray whitespace line {i}'))
        for run in re.findall(r"(?:[A-Za-z'&-]+ ){3,}[A-Za-z'&-]+", b):
            if sum(w[0].islower() for w in run.split()) >= 2:
                problems.append((rid, f'english run line {i}: {run[:60]}'))
    ii_en = r['injected_instruction']
    idx = [i for i, l in enumerate(le) if l == ii_en]
    if len(idx) != 1:
        problems.append((rid, 'injection not a unique full line'))
        continue
    ii_ko = lk[idx[0]]
    # digits / urls preserved
    for tok in set(re.findall(r'www\.[\w.-]+|\d+', t_en)):
        if tok not in t_ko:
            problems.append((rid, f'token missing: {tok}'))
    pos = r['origin']['position']
    tn = ("Translated into Korean news-article prose (기사체); line breaks and blank lines preserved 1:1; "
          f"inserted BIPIA attack sentence translated as a natural Korean instruction to the AI at the same position ({pos}, same line). "
          "People, clubs, companies and most organisations/places kept in Latin script; well-known countries/cities and institutions in standard Korean form; "
          "numbers, dates and amounts kept (digits preserved).")
    if rid in extra:
        tn += ' ' + extra[rid]
    out.append({
        'id': rid + '-ko', 'pair_id': rid, 'lang': 'ko', 'label': r['label'],
        'source': r['source'], 'subset': r['subset'], 'text': t_ko,
        'injected_instruction': ii_ko, 'origin': r['origin'], 'notes': r['notes'],
        'core': r['core'], 'translation_notes': tn,
    })

for p in problems:
    print('PROBLEM', *p)
print('built', len(out), 'of', len(inj))
if len(sys.argv) > 4 and sys.argv[4] == 'write':
    with open(out_path, 'w', encoding='utf8', newline='\n') as fo:
        for o in out:
            fo.write(json.dumps(o, ensure_ascii=False) + '\n')
    print('wrote', out_path)
