"""Validate WD/parts_v2/sep.jsonl. Usage: validate_sep.py <out_jsonl> <repo_dir> <wd_dir>"""
import collections
import difflib
import glob
import json
import os
import re
import statistics
import sys

OUT, REPO, WD = sys.argv[1:4]
data = json.load(open(os.path.join(REPO, "datasets/SEP_dataset.json"), encoding="utf-8"))
probes = json.load(open(os.path.join(REPO, "SEP_dataset/source/probes.json"), encoding="utf-8"))
recs = [json.loads(l) for l in open(OUT, encoding="utf-8") if l.strip()]

ids = [r["id"] for r in recs]
assert len(ids) == len(set(ids)) == 60
lab = collections.Counter((r["label"], r["subset"]) for r in recs)
print("counts", dict(lab))
assert lab[("injection", "general_document")] == 30 and lab[("benign", "general_document")] == 30
keys = {"id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes", "core"}
for r in recs:
    assert set(r) == keys, r["id"]
    assert r["source"] == "SEP" and r["core"] is False
    x = data[r["origin"]["index"]]
    assert r["origin"]["task_prompt"] == x["system_prompt_clean"]
    if r["label"] == "injection":
        assert r["id"].startswith("sep-inj-")
        assert r["text"] == x["prompt_instructed"]
        assert r["injected_instruction"] == probes[x["info"]["appended_task_id"]]["instruction"]
        assert r["text"].count(r["injected_instruction"]) == 1
        assert r["text"].replace(r["injected_instruction"], "").strip() == x["prompt_clean"]
    else:
        assert r["id"].startswith("sep-ben-")
        assert r["injected_instruction"] is None
        assert r["text"] == x["prompt_clean"]
        assert not any(p["instruction"] in r["text"] for p in probes)
    assert len(r["text"]) <= 3000

inj_idx = {r["origin"]["index"] for r in recs if r["label"] == "injection"}
ben_idx = {r["origin"]["index"] for r in recs if r["label"] == "benign"}
assert not inj_idx & ben_idx
subs = [r["origin"]["subtask"] for r in recs]
print("unique subtasks", len(set(subs)), "of", len(subs))


def ng(t, n=5):
    w = re.findall(r"\w+", t.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def sim(a, b):
    ga, gb = ng(a), ng(b)
    j = len(ga & gb) / len(ga | gb) if ga and gb else 0
    return j, difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


# compare clean passages too (strip probe) so inj vs ben overlap is caught
cmp = [(r["id"], r["text"] if r["label"] == "benign" else data[r["origin"]["index"]]["prompt_clean"]) for r in recs]
mj = mr = 0
for i in range(len(cmp)):
    for k in range(i + 1, len(cmp)):
        j, rr = sim(cmp[i][1], cmp[k][1])
        mj, mr = max(mj, j), max(mr, rr)
        assert j < 0.5 and rr < 0.8, (cmp[i][0], cmp[k][0], j, rr)
print(f"within-output max 5gram-Jaccard={mj:.3f} max difflib={mr:.3f}")

ext = []
for pat in ("parts/*.jsonl", "parts_v2/*.jsonl", "dataset_en_100.jsonl"):
    for fp in glob.glob(os.path.join(WD, pat)):
        if os.path.abspath(fp) == os.path.abspath(OUT):
            continue
        ext += [json.loads(l)["text"] for l in open(fp, encoding="utf-8") if l.strip()]
mj = mr = 0
for r in recs:
    for e in ext:
        j, _ = sim(r["text"], e)
        sm = difflib.SequenceMatcher(None, r["text"], e, autojunk=False)
        rr = sm.ratio() if sm.quick_ratio() >= 0.5 else 0
        mj, mr = max(mj, j), max(mr, rr)
        assert j < 0.5 and rr < 0.8
print(f"vs {len(ext)} existing texts: max 5gram-Jaccard={mj:.3f} max difflib={mr:.3f}")

for lb in ("injection", "benign"):
    L = [len(r["text"]) for r in recs if r["label"] == lb]
    print(lb, "len min/median/mean/max", min(L), statistics.median(L), round(statistics.mean(L)), max(L))
print("domain x label", dict(collections.Counter((r["label"][:3], r["origin"]["task_domain"].split()[0]) for r in recs)))
gt = collections.Counter(r["origin"]["general_task"] for r in recs)
print("general tasks", len(gt), dict(gt))
inj = [r for r in recs if r["label"] == "injection"]
print("probe position", dict(collections.Counter(r["origin"]["probe_position_in_data"] for r in inj)))
print("insistent", dict(collections.Counter(r["origin"]["is_insistent"] for r in inj)))
print("unique probe base", len({r["origin"]["appended_task_id"] % 50 for r in inj}))
print("OK")
