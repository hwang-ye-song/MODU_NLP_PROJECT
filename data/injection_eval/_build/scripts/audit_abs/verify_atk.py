import json, sys
OLD = "<SCRATCH>/dl/bipia/benchmark"
atk = json.load(open(f"{OLD}/text_attack_train.json", encoding='utf-8'))
recs = [json.loads(l) for l in open(sys.argv[1], encoding='utf-8')]
seen = {}
for r in recs:
    if r['label'] != 'injection': continue
    o = r['origin']
    a = atk[o['attack_category']][o['attack_index']]
    ok = a == r['injected_instruction']
    key = r['injected_instruction']
    dup = seen.get(key); seen[key] = r['id']
    print(r['id'], 'ATK_OK' if ok else 'ATK_MISMATCH', 'DUP_OF ' + dup if dup else '', '|', o['attack_category'], o['attack_index'], '|', key[:110])
