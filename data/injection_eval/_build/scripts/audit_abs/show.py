import json, sys, re
p = sys.argv[1]; a = int(sys.argv[2]); b = int(sys.argv[3])
mode = sys.argv[4] if len(sys.argv) > 4 else 'full'
recs = [json.loads(l) for l in open(p, encoding='utf-8')]
if mode == 'check':
    ids = [r['id'] for r in recs]
    print('n', len(recs), 'unique', len(set(ids)))
    from collections import Counter
    print(Counter((r['label'], r['doc_type'], r['subset']) for r in recs))
    for r in recs:
        t = r['text']; ii = r.get('injected_instruction')
        flags = []
        if ii is not None and ii not in t: flags.append('II_NOT_SUBSTR')
        if r['label']=='injection' and not ii: flags.append('NO_II')
        if r['label']=='benign' and ii: flags.append('BENIGN_HAS_II')
        if re.search(r'\{[a-z_]+\}|<Attacker|\[INSERT|Ã|â€|\ufffd', t): flags.append('PLACEHOLDER_OR_MOJIBAKE')
        na = sorted(set(c for c in t if ord(c) > 127))
        if not t.strip(): flags.append('EMPTY')
        end = t.rstrip()[-1:]
        print(r['id'], r['label'], len(t), 'end=%r' % end, 'nonascii=%s' % ''.join(na)[:30], flags)
    sys.exit()
for r in recs[a:b]:
    print('=' * 100)
    print(r['id'], '|', r['label'], '|', r['doc_type'], '|', r['subset'], '| len', len(r['text']))
    print('ORIGIN:', json.dumps(r.get('origin'), ensure_ascii=False))
    print('NOTES:', r.get('notes'))
    print('II:', repr(r.get('injected_instruction')))
    print('--- TEXT ---')
    print(r['text'])
