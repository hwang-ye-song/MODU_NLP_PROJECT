"""Pairwise difflib ratios. Usage: python -I sim.py <pool.jsonl> <core.jsonl> <rows,comma> [thr]
Prints pairs among given rows and vs core with ratio >= thr (default 0.45)."""
import json, re, sys
from difflib import SequenceMatcher
sys.stdout.reconfigure(encoding="utf-8")
norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()


def ratio(a, b):
    """max of char-level and word-level difflib ratios, autojunk disabled."""
    c = SequenceMatcher(None, a, b, autojunk=False).ratio()
    w = SequenceMatcher(None, a.split(), b.split(), autojunk=False).ratio()
    return max(c, w)
want = [int(x) for x in sys.argv[3].split(",")]
thr = float(sys.argv[4]) if len(sys.argv) > 4 else 0.45
pool = {}
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    if r["row_index"] in want: pool[r["row_index"]] = norm(r["text"])
core = [(json.loads(l)["id"], norm(json.loads(l)["text"])) for l in open(sys.argv[2], encoding="utf-8")]
items = [(str(w), pool[w]) for w in want]
for i, (a, ta) in enumerate(items):
    mx = max(((ratio(ta, tc), cid) for cid, tc in core))
    flag = "  <-- CORE NEAR" if mx[0] >= 0.6 else ""
    print(f"{a}: max vs core {mx[0]:.3f} ({mx[1]}){flag}")
    for b, tb in items[i + 1:]:
        r = ratio(ta, tb)
        if r >= thr: print(f"   {a} ~ {b}: {r:.3f}" + ("  <-- NEAR" if r >= 0.6 else ""))
