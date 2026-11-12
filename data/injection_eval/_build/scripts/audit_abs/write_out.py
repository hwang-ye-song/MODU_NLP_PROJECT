import json, statistics, os
src = "<DATASET_ROOT>/_build/parts_v2/bipia_abstract_more.jsonl"
out = "<DATASET_ROOT>/_build/audit/abstract_more_audit.json"
recs = [json.loads(l) for l in open(src, encoding='utf-8')]
moj = "Source-native XSum mojibake ('%s') kept; text verified identical to the rebuilt BIPIA/XSum context, not introduced by our pipeline. No change needed."
notes = {
    "bipia-abs-inj-51": moj % "Â£",
    "bipia-abs-inj-70": moj % "â‚¬",
    "bipia-abs-ben-41": moj % "Â£",
    "bipia-abs-ben-59": moj % "Â£",
    "bipia-abs-ben-65": moj % "Â£",
    "bipia-abs-ben-67": moj % "Â£",
    "bipia-abs-ben-49": "Source itself ends on 'include:' (XSum dropped the following list); text is identical to the source context, not truncated by us. No change needed.",
}
res = []
for r in recs:
    res.append({"id": r["id"], "verdict": "ok", "issue": notes.get(r["id"], ""), "suggested_label": r["label"]})
os.makedirs(os.path.dirname(out), exist_ok=True)
with open(out, "w", encoding="utf-8") as f:
    json.dump(res, f, ensure_ascii=False, indent=1)
chk = json.load(open(out, encoding="utf-8"))
print(len(chk), len({x['id'] for x in chk}))
for lab in ("injection", "benign"):
    print(lab, statistics.median(len(r["text"]) for r in recs if r["label"] == lab))
