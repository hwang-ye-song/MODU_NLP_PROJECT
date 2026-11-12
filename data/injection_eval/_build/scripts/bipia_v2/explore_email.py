"""Email pool under the core build's grouping vs strict families.
Usage: python -X utf8 -I explore_email.py <bipia_repo_dir> <core_bipia_jsonl> <task>"""
import difflib
import json
import os
import re
import sys

REPO, CORE, TASK = sys.argv[1], sys.argv[2], sys.argv[3]


def norm(t):
    return re.sub(r"\s+", " ", t).strip().lower()


def grams(t, n=5):
    w = norm(t).split()
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def email_keys(text):
    m = re.search(r"RECEIVED DATE:\s*([^|]+)", text)
    date = m.group(1).strip() if m else None
    amounts = {re.sub(r"\D", "", a) for a in re.findall(r"\$\s?(\d[\d,\s]*\.\d\d)", text)}
    amounts.discard("10000")
    return date, frozenset(amounts)


def same_source(task, a, b):
    if norm(a) == norm(b):
        return True
    if task == "email":
        da, aa = email_keys(a)
        db, ab = email_keys(b)
        if da and da == db:
            return True
        if aa and aa == ab:
            return True
    sm = difflib.SequenceMatcher(None, a, b)
    return sm.real_quick_ratio() >= 0.95 and sm.quick_ratio() >= 0.95 and sm.ratio() >= 0.95


def strict(a, b):
    ga, gb = grams(a), grams(b)
    if len(ga & gb) / max(1, len(ga | gb)) >= 0.5:
        return True
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    return sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8


def load(split, limit=None):
    rel = f"benchmark/{TASK}/{split}.jsonl"
    out = []
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if limit is not None and i >= limit:
                break
            if not line.strip():
                continue
            r = json.loads(line)
            c = r["context"]
            if isinstance(c, list):
                c = "\n".join(c)
            out.append((split, i, c))
    return out


core = [json.loads(l) for l in open(CORE, encoding="utf-8")]
core_lab = {r["origin"]["index"]: r["label"] for r in core if r["subset"] == TASK}
lim = 0 if TASK == "table" else None
rows = load("test") + load("train", lim)
# core-style grouping
groups = []
for sp, i, c in rows:
    for g in groups:
        if same_source(TASK, g[0][2], c):
            g.append((sp, i, c)); break
    else:
        groups.append([(sp, i, c)])
reps = [g[0] for g in groups]
print("core-style groups", len(groups), "test-first", sum(1 for g in reps if g[0] == "test"),
      "<=2700", sum(1 for g in reps if len(g[2]) <= 2700))
# groups touched by core
core_g = [k for k, g in enumerate(groups) if any(m[0] == "test" and m[1] in core_lab for m in g)]
print("core-touched groups", len(core_g))
# strict families over the representatives
fam = []
for k, rep in enumerate(reps):
    for f in fam:
        if any(strict(reps[j][2], rep[2]) for j in f):
            f.append(k); break
    else:
        fam.append([k])
print("strict families over reps", len(fam))
for f in fam:
    labs = set()
    for k in f:
        for m in groups[k]:
            if m[0] == "test" and m[1] in core_lab:
                labs.add(core_lab[m[1]])
    print(len(f), "reps; test reps", sum(1 for k in f if reps[k][0] == "test"), "core labels", sorted(labs),
          "|", reps[f[0]][2][:70].replace(chr(10), " ").encode("ascii", "replace").decode())
