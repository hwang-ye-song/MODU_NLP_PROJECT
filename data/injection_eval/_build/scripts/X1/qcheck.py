import json
rows=[json.loads(l) for l in open(r'<DATASET_ROOT>/experiments/X1_register.jsonl',encoding='utf-8')]
for o in rows:
    a,b=o['original_injected_instruction'],o['injected_instruction']
    for ch in [chr(34),chr(92),chr(96),chr(10),chr(39)]:
        if b.count(ch)!=a.count(ch): print(o['base_uid'],o['source'],o['register'],repr(ch),a.count(ch),b.count(ch))
