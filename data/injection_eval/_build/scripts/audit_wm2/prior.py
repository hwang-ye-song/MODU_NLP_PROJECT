import json,glob,os
for f in glob.glob('<DATASET_ROOT>/_build/parts_v2/webpage*.jsonl')+['<DATASET_ROOT>/en/dataset_en_700.jsonl']:
    for l in open(f,encoding='utf-8'):
        r=json.loads(l); o=r.get('origin') or {}
        if r.get('label')=='injection' and 'browsesafe' in str(o) :
            print(os.path.basename(f), r['id'], o.get('payload_placement'), o.get('attack_template'), (r.get('injected_instruction') or '')[:80])
