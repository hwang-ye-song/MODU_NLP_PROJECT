"""Explore BIPIA context pools (test+train) for the v2 expansion.
Usage: python -X utf8 -I explore.py <bipia_repo_dir> <core_bipia_jsonl>"""
import difflib
import json
import os
import re
import sys

REPO, CORE = sys.argv[1], sys.argv[2]


def norm(t):
    return re.sub(r"\s+", " ", t).strip().lower()


def grams(t, n=5):
    w = norm(t).split()
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def email_keys(text):
    m = re.search(r"RECEIVED DATE:\s*([^|]+)", text)
    date = m.group(1).strip() if m else None
    amounts = {re.sub(r"\D", "", a) for a in re.findall(r"\$\s?(\d[\d,\s]*\.\d\d)", text)}
    amounts.discard("10000")
    return date, frozenset(amounts)


def is_english(text):
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    return sum(1 for ch in letters if ord(ch) > 127) / len(letters) <= 0.02


def load(task, split):
    rel = f"benchmark/{task}/{split}.jsonl"
    out = []
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            r = json.loads(line)
            c = r["context"]
            if isinstance(c, list):
                c = "\n".join(c)
            out.append((split, i, c, r))
    return out


core = [json.loads(l) for l in open(CORE, encoding="utf-8")]
for task in ["email", "table", "code"]:
    rows = load(task, "test") + load(task, "train")[: (150 if task == "table" else None)]
    core_idx = {r["origin"]["index"] for r in core if r["subset"] == task}
    # greedy grouping
    groups = []  # list of (rep_text, grams, members)
    for sp, i, c, r in rows:
        g = grams(c)
        hit = None
        for k, (rep, rg, mem) in enumerate(groups):
            if norm(rep) == norm(c):
                hit = k; break
            if task == "email":
                da, aa = email_keys(rep); db, ab = email_keys(c)
                if (da and da == db) or (aa and aa == ab):
                    hit = k; break
            if jacc(g, rg) >= 0.5:
                hit = k; break
            sm = difflib.SequenceMatcher(None, rep, c, autojunk=False)
            if sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8:
                hit = k; break
        if hit is None:
            groups.append((c, g, [(sp, i, len(c), is_english(c))]))
        else:
            groups[hit][2].append((sp, i, len(c), is_english(c)))
    ntest = sum(1 for g in groups if g[2][0][0] == "test")
    elig = [g for g in groups if g[2][0][3] and g[2][0][2] <= 2700]
    print(task, "rows", len(rows), "groups", len(groups), "groups starting in test", ntest,
          "eligible(len<=2700, en)", len(elig),
          "eligible test-first", sum(1 for g in elig if g[2][0][0] == "test"))
    multi = [g[2] for g in groups if len(g[2]) > 1]
    print("  multi-member groups:", len(multi), multi[:8])
    core_groups = [k for k, g in enumerate(groups) if any(m[0] == "test" and m[1] in core_idx for m in g[2])]
    print("  core groups", len(core_groups))
    if task == "email":
        for g in groups:
            print("   ", g[2], g[0][:90].replace(chr(10), " ").encode("ascii", "replace").decode())
    sys.stdout.flush()
