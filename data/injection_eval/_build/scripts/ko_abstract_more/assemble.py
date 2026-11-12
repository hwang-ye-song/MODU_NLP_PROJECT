import json, glob, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
EN = '<DATASET_ROOT>/_build/parts_v2/bipia_abstract_more.jsonl'
OUT = '<DATASET_ROOT>/_build/ko_parts/abstract_more_inj.jsonl'

BASE_NOTE = ("Translated into Korean news-article prose (기사체); line breaks and blank lines preserved 1:1; "
             "inserted BIPIA attack sentence translated as a natural Korean instruction to the AI at the same position ({pos}, same line). "
             "People, clubs, companies and most organisations/places kept in Latin script; well-known countries/cities and institutions "
             "in standard Korean form; numbers, dates and amounts kept (digits preserved).")


def parse_chunks():
    recs = {}
    order = []
    for p in sorted(glob.glob(os.path.join(HERE, 'chunk*.txt'))):
        lines = open(p, encoding='utf-8').read().split('\n')
        i = 0
        while i < len(lines):
            ln = lines[i]
            if ln.startswith('@@@ID '):
                rid = ln[6:].strip()
                inj = note = None
                i += 1
                while not lines[i].startswith('@@@TEXT'):
                    if lines[i].startswith('@@@INJ '):
                        inj = lines[i][7:]
                    elif lines[i].startswith('@@@NOTE '):
                        note = lines[i][8:]
                    i += 1
                i += 1
                body = []
                while lines[i] != '@@@END':
                    body.append(lines[i])
                    i += 1
                assert rid not in recs, rid
                recs[rid] = dict(text='\n'.join(body), inj=inj, note=note)
                order.append(rid)
            i += 1
    return recs


def main():
    en = [json.loads(l) for l in open(EN, encoding='utf-8')]
    en_inj = [r for r in en if r['label'] == 'injection']
    ko = parse_chunks()
    out = []
    problems = []
    for r in en_inj:
        rid = r['id']
        if rid not in ko:
            continue
        k = ko[rid]
        en_lines = r['text'].split('\n')
        ko_lines = k['text'].split('\n')
        if len(en_lines) != len(ko_lines):
            problems.append(f'{rid}: line count EN {len(en_lines)} KO {len(ko_lines)}')
            continue
        # restore trailing whitespace stripped by the editor, and blank-line parity
        fixed = []
        for el, kl in zip(en_lines, ko_lines):
            if (el.strip() == '') != (kl.strip() == ''):
                problems.append(f'{rid}: blank-line mismatch EN {el[:30]!r} KO {kl[:30]!r}')
            m = re.search(r'[ \t]+$', el)
            if m and not kl.endswith(m.group(0)):
                kl = kl.rstrip() + m.group(0)
            fixed.append(kl)
        text = '\n'.join(fixed)
        inj = k['inj']
        if inj is None or inj not in text:
            problems.append(f'{rid}: injected_instruction not substring')
        # same line index for the payload
        en_idx = [i for i, l in enumerate(en_lines) if r['injected_instruction'] in l]
        ko_idx = [i for i, l in enumerate(fixed) if inj and inj in l]
        if en_idx != ko_idx:
            problems.append(f'{rid}: payload line EN {en_idx} KO {ko_idx}')
        # leftover English prose check: Latin words outside the payload
        note = BASE_NOTE.format(pos=r['origin']['position'])
        if k['note']:
            note += ' ' + k['note']
        rec = {
            'id': rid + '-ko', 'pair_id': rid, 'lang': 'ko',
            'label': r['label'], 'source': r['source'], 'subset': r['subset'], 'doc_type': r['doc_type'],
            'text': text, 'injected_instruction': inj,
            'origin': r['origin'], 'notes': r['notes'], 'core': r['core'],
            'translation_notes': note,
        }
        out.append(rec)
    print('translated', len(out), 'of', len(en_inj))
    for p in problems:
        print('PROBLEM', p)
    if '--write' in sys.argv:
        assert len(out) == len(en_inj) and not problems
        with open(OUT, 'w', encoding='utf-8', newline='\n') as f:
            for rec in out:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
        print('wrote', OUT)
    for rec in out:
        t = rec['text'].replace(rec['injected_instruction'], '')
        hang = len(re.findall(r'[\uac00-\ud7a3]', t))
        lat = len(re.findall(r'[A-Za-z]', t))
        print(rec['id'], len(rec['text']), 'hangul', hang, 'latin', lat, round(hang / max(1, hang + lat), 2))


if __name__ == '__main__':
    main()
