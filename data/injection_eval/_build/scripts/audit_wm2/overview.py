import json, sys
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
print(len(recs))
print(recs[0].keys())
for r in recs:
    ii=r.get('injected_instruction')
    print(r['id'], r['label'], r['subset'], r['doc_type'], len(r['text']), 'II_sub' if ii and ii in r['text'] else ('II_none' if ii is None else 'II_MISSING'), json.dumps(r.get('origin'))[:150], (r.get('notes') or '')[:100])
