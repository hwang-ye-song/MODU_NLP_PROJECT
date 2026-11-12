import json, re, sys
en = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
ko = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8") if l.strip()]
assert len(en) == len(ko) == 12, (len(en), len(ko))
ids = [r["id"] for r in ko]; assert len(set(ids)) == len(ids)
en_ids = [r["id"] for r in en]
assert [r["pair_id"] for r in ko] == en_ids
keys = ['id','pair_id','lang','label','source','subset','doc_type','text','injected_instruction','origin','notes','core','translation_notes']
for e, k in zip(en, ko):
    assert list(k.keys()) == keys, k["id"]
    for f in ["label","source","subset","origin","core","doc_type","notes"]:
        assert e[f] == k[f], (k["id"], f)
    assert k["injected_instruction"] is None and k["label"] == "benign" and k["lang"] == "ko"
    t = k["text"]
    body = t.split("\n", 1)[1]
    hangul = len(re.findall(r"[\uac00-\ud7a3]", body)); latin = len(re.findall(r"[A-Za-z]", body))
    # leftover English prose: 4+ consecutive lower-case English words
    eng = re.findall(r"\b[a-z]+(?: [a-z]+){3,}\b", body)
    nums_en = sorted(re.findall(r"\d+", e["text"])); nums_ko = sorted(re.findall(r"\d+", t))
    print(f'{k["id"]:18s} lines {t.count(chr(10))}/{e["text"].count(chr(10))} len {len(t)}/{len(e["text"])} hangul {hangul} latin {latin} ratio {hangul/(hangul+latin):.2f} eng={eng} nums_missing={sorted(set(nums_en)-set(nums_ko))} nums_extra={sorted(set(nums_ko)-set(nums_en))}')
print("OK")
