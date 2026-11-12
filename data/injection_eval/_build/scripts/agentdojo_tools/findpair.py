import difflib, glob, json, os, sys
path, WD = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
ex = []
for f in glob.glob(os.path.join(WD, "_build", "parts_v2", "*.jsonl")) + [os.path.join(WD, "_build", "ja_llmail_candidates.jsonl")]:
    if os.path.abspath(f) == os.path.abspath(path):
        continue
    for l in open(f, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); ex.append((os.path.basename(f), r["id"], r["text"]))
pool = [("self", r["id"], r["text"]) for r in recs]
for i, r in enumerate(recs):
    for (fn, rid, t) in pool[i + 1:] + ex:
        sm = difflib.SequenceMatcher(None, r["text"], t, autojunk=False)
        if sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.78:
            print(r["id"], fn, rid, round(sm.ratio(), 3))
