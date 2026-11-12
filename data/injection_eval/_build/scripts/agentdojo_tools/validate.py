"""Validate agentdojo_tools.jsonl: JSON, counts, ids, substring, dedup (within + vs existing), length stats.
usage: python validate.py <jsonl> <WD>
"""
import collections, difflib, glob, json, os, re, statistics, sys

path, WD = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
print("records", len(recs))
ids = [r["id"] for r in recs]
assert len(ids) == len(set(ids)), "dup ids"
lab = collections.Counter(r["label"] for r in recs)
print("labels", dict(lab))
for r in recs:
    assert set(r) == {"id", "label", "source", "subset", "doc_type", "text", "injected_instruction", "origin", "notes", "core"}, r["id"]
    if r["label"] == "injection":
        assert r["injected_instruction"] and r["injected_instruction"] in r["text"], r["id"]
    else:
        assert r["injected_instruction"] is None
    assert len(r["text"]) <= 3000, r["id"]
print("doc_type x label", sorted(collections.Counter((r["doc_type"], r["label"]) for r in recs).items()))
print("subset x label", sorted(collections.Counter((r["subset"], r["label"]) for r in recs).items()))
print("attack templates", sorted(collections.Counter(r["origin"]["attack_template"] for r in recs if r["label"] == "injection").items()))
combo = [(r["origin"]["suite"], r["origin"]["injection_vector"], r["origin"]["injection_task_id"], r["origin"]["attack_template"]) for r in recs if r["label"] == "injection"]
assert len(combo) == len(set(combo)), "repeated combo"
print("distinct vectors used", len({c[:2] for c in combo}), "distinct (suite,task)", len({(c[0], c[2]) for c in combo}))
L = {k: sorted(len(r["text"]) for r in recs if r["label"] == k) for k in lab}
for k, v in L.items():
    print(k, "median", statistics.median(v), "q1", v[len(v) // 4], "q3", v[3 * len(v) // 4], "min", v[0], "max", v[-1])
inj, ben = L["injection"], L["benign"]
auc = sum((a > b) + 0.5 * (a == b) for a in inj for b in ben) / (len(inj) * len(ben))
print("length-only AUC (injection longer)", round(auc, 3))


def toks(t):
    return re.findall(r"\w+", t.lower())


def grams(t, n=5):
    w = toks(t)
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


ex = []
for f in glob.glob(os.path.join(WD, "_build", "parts_v2", "*.jsonl")) + [os.path.join(WD, "_build", "ja_llmail_candidates.jsonl")]:
    if os.path.abspath(f) == os.path.abspath(path):
        continue
    for l in open(f, encoding="utf-8"):
        if l.strip():
            ex.append(json.loads(l)["text"])
G = [grams(r["text"]) for r in recs]
EG = [grams(t) for t in ex]
worst_j, worst_r = 0, 0
for i in range(len(recs)):
    for j in list(range(i + 1, len(recs))):
        jj = jacc(G[i], G[j]); worst_j = max(worst_j, jj)
        rr = difflib.SequenceMatcher(None, recs[i]["text"], recs[j]["text"], autojunk=False)
        if rr.real_quick_ratio() >= 0.8 and rr.quick_ratio() >= 0.8:
            worst_r = max(worst_r, rr.ratio(), difflib.SequenceMatcher(None, recs[j]["text"], recs[i]["text"], autojunk=False).ratio())
    for k in range(len(ex)):
        jj = jacc(G[i], EG[k]); worst_j = max(worst_j, jj)
        rr = difflib.SequenceMatcher(None, recs[i]["text"], ex[k], autojunk=False)
        if rr.real_quick_ratio() >= 0.8 and rr.quick_ratio() >= 0.8:
            worst_r = max(worst_r, rr.ratio(), difflib.SequenceMatcher(None, ex[k], recs[i]["text"], autojunk=False).ratio())
print("max 5-gram Jaccard", round(worst_j, 3), "max difflib ratio (among quick>=0.8)", round(worst_r, 3), "existing texts", len(ex))
assert worst_j < 0.5 and worst_r < 0.8
print("OK")
