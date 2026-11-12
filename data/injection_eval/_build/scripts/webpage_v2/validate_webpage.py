import json, sys, re, glob, os, difflib, statistics, collections
path, WD = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(path, encoding="utf-8")]
ids = [r["id"] for r in recs]
assert len(ids) == len(set(ids)) == 60
need = {"id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes", "core"}
for r in recs:
    assert set(r) == need, r["id"]
    assert r["core"] is False and r["subset"] == "webpage"
    assert r["label"] in ("injection", "benign")
    if r["label"] == "injection":
        assert r["injected_instruction"] and r["injected_instruction"] in r["text"], r["id"]
        assert r["id"].startswith("web-inj-")
    else:
        assert r["injected_instruction"] is None and r["id"].startswith("web-ben-")
print(collections.Counter((r["label"], r["source"]) for r in recs))
assert sorted(i for i in ids if "inj" in i) == [f"web-inj-{k:02d}" for k in range(1, 31)]
assert sorted(i for i in ids if "ben" in i) == [f"web-ben-{k:02d}" for k in range(1, 31)]
def g5(t):
    w = re.findall(r"\w+", t.lower()); return {tuple(w[i:i+5]) for i in range(max(1, len(w)-4))}
G = [g5(r["text"]) for r in recs]
mx = (0, ("", ""))
for i in range(60):
    for j in range(i+1, 60):
        jac = len(G[i] & G[j]) / max(1, len(G[i] | G[j]))
        rat = difflib.SequenceMatcher(None, recs[i]["text"], recs[j]["text"], autojunk=False).ratio() if jac > 0.2 else 0
        assert jac < 0.5 and rat < 0.8, (recs[i]["id"], recs[j]["id"], jac, rat)
        mx = max(mx, (round(max(jac, 0), 3), (recs[i]["id"], recs[j]["id"])))
print("max within-file 5-gram Jaccard", mx)
ext = []
for f in glob.glob(os.path.join(WD, "parts", "*.jsonl")) + glob.glob(os.path.join(WD, "parts_v2", "*.jsonl")):
    if os.path.basename(f) != "webpage.jsonl":
        ext += [json.loads(l)["text"] for l in open(f, encoding="utf-8") if l.strip()]
mj = max(len(a & g5(t)) / max(1, len(a | g5(t))) for a in G for t in ext)
print("max Jaccard vs other parts", round(mj, 3), "over", len(ext), "texts")
for lab in ("injection", "benign"):
    for src in ("AgentDojo", "BrowseSafe-Bench"):
        L = [len(r["text"]) for r in recs if r["label"] == lab and r["source"] == src]
        print(lab, src, "n", len(L), "min", min(L), "median", statistics.median(L), "max", max(L))
L = [len(r["text"]) for r in recs]
print("all: min", min(L), "median", statistics.median(L), "max", max(L), ">3000:", sum(x > 3000 for x in L))
print("non-ascii-letter pages:", [r["id"] for r in recs if re.search(r"[\u0400-\u04ff\u3040-\u9fff\uac00-\ud7af\u0600-\u06ff]", r["text"])])
print("OK")
