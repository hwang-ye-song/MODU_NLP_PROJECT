"""Validate parts_v2/llmail_injection.jsonl.

Usage: python -X utf8 -I validate.py <out.jsonl> <core.jsonl> <raw_submissions_phase2.jsonl> <other_jsonl_dir> [<other_jsonl_dir> ...]
Checks: JSON per line, 80 records, id sequence, core byte-identity, schema, substring, length,
row_index/RowKey/text against the raw file, <= 2 per team, pairwise difflib (< 0.6, char+word level,
autojunk off) within the file, and difflib < 0.8 against every other *.jsonl in the given dirs.
Prints level / strata / technique distributions.
"""
import glob
import json
import os
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

sys.stdout.reconfigure(encoding="utf-8")
out_p, core_p, raw_p = sys.argv[1:4]
other_dirs = sys.argv[4:]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]

raw = open(out_p, encoding="utf-8").read()
assert raw.endswith("\n") and "\r" not in raw.replace("\\r", "")
lines = raw.split("\n")[:-1]
recs = [json.loads(l) for l in lines]
assert len(recs) == 80, len(recs)
assert [r["id"] for r in recs] == [f"llmail-inj-{i:02d}" for i in range(1, 81)]

core_lines = open(core_p, encoding="utf-8").read().split("\n")[:-1]
for i, cl in enumerate(core_lines):
    assert lines[i] == cl[:-1] + ', "core": true}', f"core line {i} differs"
    assert recs[i]["core"] is True
assert all(r["core"] is False for r in recs[15:])

for r in recs:
    assert set(r) == {"id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes", "core"}, r["id"]
    assert r["label"] == "injection" and r["source"] == "LLMail-Inject" and r["subset"] == "phase2"
    assert r["text"].startswith("Subject: ") and "\n\n" in r["text"] and len(r["text"]) <= 3000
    ii = r["injected_instruction"]
    assert ii is None or (isinstance(ii, str) and ii and ii in r["text"]), r["id"]
    o = r["origin"]
    assert re.fullmatch(r"level[12][k-v]", o["scenario"]) and all(isinstance(o["objectives"][k], bool) for k in KEYS)

# raw cross-check
want = {r["origin"]["row_index"]: r for r in recs}
with open(raw_p, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i in want:
            x = json.loads(line)
            r = want[i]
            assert x["RowKey"] == r["origin"]["RowKey_or_job_id"] and x["scenario"] == r["origin"]["scenario"]
            assert f"Subject: {x.get('subject') or ''}\n\n{x.get('body') or ''}" == r["text"], r["id"]
            ob = json.loads(x["objectives"]) if isinstance(x["objectives"], str) else x["objectives"]
            assert ob == r["origin"]["objectives"], r["id"]
            want[i] = None
assert all(v is None for v in want.values()), "row not found"
print("schema/core/raw checks OK")

teams = Counter(r["origin"]["team_id"] for r in recs)
print("teams:", len(teams), "max per team:", max(teams.values()), "teams with 2:", sum(v == 2 for v in teams.values()))
assert max(teams.values()) <= 2


def strat(o):
    if all(o[k] for k in KEYS):
        return "full_success"
    return "undetected_not_full" if o["defense.undetected"] else "detected"


lv = Counter(r["origin"]["scenario"] for r in recs)
print("levels:", " ".join(f"{k[5:]}:{v}" for k, v in sorted(lv.items())), "| n levels", len(lv))
print("strata:", Counter(strat(r["origin"]["objectives"]) for r in recs))
print("strata new only:", Counter(strat(r["origin"]["objectives"]) for r in recs[15:]))
tech = Counter()
for r in recs[15:]:
    m = re.match(r"\[techniques: ([^\]]+)\]", r["notes"])
    tech.update(t.strip() for t in m.group(1).split(","))
print("techniques (new 65):", dict(tech.most_common()))
print("injected_instruction null:", sum(r["injected_instruction"] is None for r in recs))
print("length min/median/max:", min(len(r["text"]) for r in recs), sorted(len(r["text"]) for r in recs)[40], max(len(r["text"]) for r in recs))

norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()


def ratio(a, b, thr):
    best = 0.0
    for x, y in ((a, b), (a.split(), b.split())):
        sm = SequenceMatcher(None, x, y, autojunk=False)
        if sm.real_quick_ratio() < thr or sm.quick_ratio() < thr:
            continue
        best = max(best, sm.ratio())
    return best


T = [norm(r["text"]) for r in recs]
worst = (0, None)
bad = []
for i in range(80):
    for j in range(i + 1, 80):
        v = ratio(T[i], T[j], 0.45)
        if v > worst[0]:
            worst = (v, (recs[i]["id"], recs[j]["id"]))
        if v >= 0.6:
            bad.append((recs[i]["id"], recs[j]["id"], round(v, 3)))
print("max within-file difflib:", round(worst[0], 3), worst[1], "| pairs >= 0.6:", bad)

others = []
for d in other_dirs:
    for p in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        if os.path.basename(p) == "llmail_injection.jsonl":
            continue
        for l in open(p, encoding="utf-8"):
            if l.strip():
                x = json.loads(l)
                others.append((os.path.basename(d) + "/" + os.path.basename(p) + ":" + str(x.get("id")), norm(x.get("text", ""))))
xbad, xworst = [], (0, None)
for r, t in zip(recs[15:], T[15:]):
    for oid, ot in others:
        v = ratio(t, ot, 0.5)
        if v > xworst[0]:
            xworst = (v, (r["id"], oid))
        if v >= 0.8:
            xbad.append((r["id"], oid, round(v, 3)))
print("compared against", len(others), "other records; max:", round(xworst[0], 3), xworst[1], "| >= 0.8:", xbad)
assert not bad and not xbad
print("ALL CHECKS PASSED")
