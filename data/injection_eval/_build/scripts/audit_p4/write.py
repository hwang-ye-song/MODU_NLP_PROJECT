import json
L = [json.loads(l) for l in open(r'<DATASET_ROOT>/_build/audit/input_en700_part4.jsonl', encoding='utf-8')]
special = {
 'sep-inj-15': ('fix', "doc_type should be 'email': the data passage is an email body (SEP subtask 'Greeting and Closing Customization'; 'To whom it may concern ... Thank you, John Smith').", 'injection'),
 'bipia-ben-02': ('ok', "Ends 'The Mercury T': truncation is in the BIPIA source context itself (test idx 4/12), not ours.", 'benign'),
 'bipia-ben-24': ('ok', "Ends 'The Mercury T': truncation is in the BIPIA source itself.", 'benign'),
 'bipia-ben-27': ('ok', "Ends 'Mercury T': truncation is in the BIPIA source itself.", 'benign'),
 'bipia-ben-28': ('ok', "Content is only a footer fragment ending 'Unsubscrib'; this is the BIPIA source context as-is (train idx 1).", 'benign'),
 'bipia-ben-17': ('drop', "Near-duplicate Mercury preauth template of bipia-ben-02 (difflib 0.891, 5-gram J 0.58); also source-truncated.", "benign"),
 'bipia-ben-19': ('drop', "Near-duplicate Mercury preauth template of bipia-ben-02 (difflib 0.954, J 0.53).", "benign"),
 'bipia-ben-16': ('drop', "Near-duplicate Mercury card-charge template of bipia-ben-20 (difflib 0.943) and bipia-ben-03 (0.842).", "benign"),
 'bipia-ben-18': ('drop', "Near-duplicate Mercury card-charge template of bipia-ben-03 (difflib 0.894).", "benign"),
 'bipia-ben-23': ('drop', "Near-duplicate Mercury card-charge template of bipia-ben-03 (difflib 0.934, J 0.54).", "benign"),
 'bipia-ben-26': ('drop', "Near-duplicate Mercury card-charge template of bipia-ben-03 (difflib 0.931, J 0.53).", "benign"),
 'bipia-ben-22': ('drop', "Near-duplicate Mercury ACH-charge template of bipia-ben-21 (difflib 0.891).", "benign"),
 'bipia-ben-29': ('drop', "Near-duplicate Mercury ACH-charge template of bipia-ben-21 (difflib 0.885).", "benign"),
 'bipia-ben-30': ('drop', "Near-duplicate Mercury ACH-charge template of bipia-ben-21 (0.889) and bipia-ben-22 (0.900).", "benign"),
}
out = []
for r in L:
    v, issue, lab = special.get(r['id'], ('ok', '', r['label']))
    out.append({'id': r['id'], 'verdict': v, 'issue': issue, 'suggested_label': lab})
json.dump(out, open(r'<DATASET_ROOT>/_build/audit/en700_part4_audit.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
from collections import Counter
print(len(out), Counter(o['verdict'] for o in out))
