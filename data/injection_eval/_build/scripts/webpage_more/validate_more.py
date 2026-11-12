"""Validate webpage_more.jsonl. usage: python validate_more.py <jsonl> <WD>"""
import collections, difflib, glob, json, os, re, statistics, sys

path, WD = sys.argv[1], sys.argv[2]
lines = open(path, encoding="utf-8").read().splitlines()
recs = [json.loads(l) for l in lines]  # valid JSON on every line
ids = [r["id"] for r in recs]
assert len(ids) == len(set(ids)) == 80
need = {"id", "label", "source", "subset", "doc_type", "text", "injected_instruction", "origin", "notes", "core"}
for r in recs:
    assert set(r) == need, r["id"]
    assert r["core"] is False and r["subset"] == "webpage" and r["doc_type"] == "webpage" and r["source"] == "BrowseSafe-Bench"
    assert r["origin"]["revision"] == "b506fb5bc7fd4472c8738055a67a0ef6406afdc9"
    if r["label"] == "injection":
        assert r["injected_instruction"] and r["injected_instruction"] in r["text"], r["id"]
        assert r["id"].startswith("web-inj-") and r["origin"]["dataset_label"] == "yes"
    else:
        assert r["label"] == "benign" and r["injected_instruction"] is None and r["id"].startswith("web-ben-")
        assert r["origin"]["dataset_label"] == "no"
assert sorted(i for i in ids if "inj" in i) == [f"web-inj-{k:02d}" for k in range(31, 71)]
assert sorted(i for i in ids if "ben" in i) == [f"web-ben-{k:02d}" for k in range(31, 71)]
print(collections.Counter((r["label"], r["subset"]) for r in recs))
rows = [r["origin"]["row_index"] for r in recs]
assert len(rows) == len(set(rows))

# against every other part file
others, other_ids = [], set()
for f in glob.glob(os.path.join(WD, "_build", "parts_v2", "*.jsonl")) + glob.glob(os.path.join(WD, "_build", "parts_v1", "*.jsonl")) + [os.path.join(WD, "_build", "ja_llmail_candidates.jsonl")]:
    if os.path.abspath(f) == os.path.abspath(path) or os.path.basename(f) == "webpage_more.jsonl":
        continue
    for l in open(f, encoding="utf-8"):
        if l.strip():
            o = json.loads(l)
            others.append(o)
            other_ids.add(o["id"])
            if o.get("source") == "BrowseSafe-Bench":
                assert o["origin"]["row_index"] not in rows, ("row reused", o["id"])
assert not (set(ids) & other_ids), set(ids) & other_ids


def g5(t):
    w = re.findall(r"\w+", t.lower())
    return {tuple(w[i:i + 5]) for i in range(max(1, len(w) - 4))}


def ratio(a, b):
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < 0.8 or sm.quick_ratio() < 0.8:
        return 0.0
    return sm.ratio()


G = [g5(r["text"]) for r in recs]
mj, mr, lowj = (0, ("", "")), (0, ("", "")), (0, ("", ""))
for i in range(80):
    for j in range(i + 1, 80):
        jac = len(G[i] & G[j]) / max(1, len(G[i] | G[j]))
        short = len(recs[i]["text"]) <= 3500 and len(recs[j]["text"]) <= 3500
        # difflib on pairs sharing >10% word 5-grams; short pairs always (doubles as a check of that prefilter)
        rat = ratio(recs[i]["text"], recs[j]["text"]) if (jac > 0.1 or short) else 0
        assert jac < 0.5 and rat < 0.8, (ids[i], ids[j], jac, rat)
        mj = max(mj, (round(jac, 3), (ids[i], ids[j])))
        mr = max(mr, (round(rat, 3), (ids[i], ids[j])))
        if jac <= 0.1:
            lowj = max(lowj, (round(rat, 3), (ids[i], ids[j])))
print("within-file max 5-gram Jaccard", mj, "max difflib ratio", mr, "| max ratio among short pairs with Jaccard<=0.1", lowj)
mj, mr = (0, ("", "")), (0, ("", ""))
for a, r in zip(G, recs):
    for o in others:
        go = g5(o["text"])
        jac = len(a & go) / max(1, len(a | go))
        full = o.get("subset") == "webpage"  # other web pages: full check; other subsets: Jaccard>0.1 prefilter
        rat = ratio(r["text"], o["text"]) if (full or jac > 0.1) else 0
        assert jac < 0.5 and rat < 0.8, (r["id"], o["id"], jac, rat)
        mj = max(mj, (round(jac, 3), (r["id"], o["id"])))
        mr = max(mr, (round(rat, 3), (r["id"], o["id"])))
print("vs", len(others), "other texts: max Jaccard", mj, "max ratio", mr)
for lab in ("injection", "benign"):
    L = [len(r["text"]) for r in recs if r["label"] == lab]
    print(lab, "n", len(L), "min", min(L), "median", statistics.median(L), "max", max(L), ">3000:", sum(x > 3000 for x in L))
# length-only AUC (prob. a random injection is longer than a random benign)
Li = [len(r["text"]) for r in recs if r["label"] == "injection"]
Lb = [len(r["text"]) for r in recs if r["label"] == "benign"]
auc = sum((a > b) + 0.5 * (a == b) for a in Li for b in Lb) / (len(Li) * len(Lb))
print("length-only AUC", round(auc, 3))
t = collections.Counter(r["origin"]["attack_template"] for r in recs if r["label"] == "injection")
print("max uses of one template", max(t.values()), t.most_common(6))
print("attack types", collections.Counter(r["origin"]["attack_type"].split(" ")[0] for r in recs if r["label"] == "injection"))
print("placements", collections.Counter(r["origin"]["payload_placement"] for r in recs if r["label"] == "injection"))
for lab in ("injection", "benign"):
    print(lab, "sites", collections.Counter(r["origin"]["site_brand"] for r in recs if r["label"] == lab).most_common())
print("non-latin pages:", [r["id"] for r in recs if re.search(r"[Ѐ-ӿ぀-鿿가-힯؀-ۿ]", r["text"])])
print("OK")
