import json
rows=[json.loads(l) for l in open('<DATASET_ROOT>/_build/audit/input_en700_part1.jsonl',encoding='utf-8')]
TR="ok; email body truncated mid-word in BIPIA source (context verified verbatim), not by our pipeline"
trunc={f'bipia-inj-{i:02d}' for i in [1,2,3,4,5,7,21,22,28,29,33,34,35,40,41]}
def nd(other, ratio, idx):
    return (f"near-duplicate of {other}: identical BIPIA email context (email/test.jsonl #{idx}) with a different attack; "
            f"full-text difflib ratio {ratio} >= 0.8 (documented 2-use context reuse in bipia_v2/build_v2.py). Keep {other}, drop this one.")
drops={
 'bipia-inj-24': nd('bipia-inj-21','0.91',14),
 'bipia-inj-25': nd('bipia-inj-22','0.81',2),
 'bipia-inj-26': ("near-duplicate of bipia-inj-33 (identical email/test.jsonl #19 context, difflib 0.87) and doubtful label: "
                  "'Can you reply in German?' sits mid-body of a person-to-person email and reads as the sender's own request to David. Keep bipia-inj-33."),
 'bipia-inj-31': nd('bipia-inj-27','0.94',36),
 'bipia-inj-32': nd('bipia-inj-29','0.81',21),
 'bipia-inj-38': nd('bipia-inj-37','0.89',29),
 'bipia-inj-39': nd('bipia-inj-30','0.90',31),
 'bipia-inj-42': nd('bipia-inj-28','0.85',39),
 'bipia-inj-43': nd('bipia-inj-35','0.81',37),
}
out=[]
for r in rows:
    i=r['id']
    if i in drops:
        out.append({"id":i,"verdict":"drop","issue":drops[i],"suggested_label":"injection" if i!='bipia-inj-26' else None})
    else:
        issue=""
        if i in trunc: issue=TR
        if i=='bipia-inj-73': issue="ok; Stack Overflow answer ends mid-sentence ('...plotted them with these modifications to give') in BIPIA source, not by our pipeline"
        out.append({"id":i,"verdict":"ok","issue":issue,"suggested_label":"injection"})
json.dump(out,open('<DATASET_ROOT>/_build/audit/en700_part1_audit.json','w',encoding='utf-8'),ensure_ascii=False,indent=1)
from collections import Counter
print(len(out),Counter(o['verdict'] for o in out))
