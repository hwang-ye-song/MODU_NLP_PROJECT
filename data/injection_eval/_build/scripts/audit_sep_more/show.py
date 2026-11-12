import json, sys
a, b = int(sys.argv[1]), int(sys.argv[2])
recs = [json.loads(l) for l in open('<DATASET_ROOT>/_build/parts_v2/sep_more.jsonl', encoding='utf-8')]
for i, r in enumerate(recs[a:b], a):
    ii = r.get('injected_instruction')
    sub = (ii in r['text']) if ii else None
    o = r['origin']
    print(f"=== [{i}] {r['id']} | {r['label']} | {r['subset']} | {r.get('doc_type')} | core={r['core']} | len={len(r['text'])} | sub={sub} | pos={o.get('probe_position_in_data')} | witness={o.get('witness')}")
    print("TASK:", o.get('task_prompt'))
    print("II:", ii)
    print("TEXT:", r['text'])
