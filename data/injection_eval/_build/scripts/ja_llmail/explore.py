"""Explore Phase 2 raw submissions: scenario x objective counts, retrieval flag, keywords.
Usage: python -X utf8 -I explore.py <raw_submissions_phase2.jsonl>
"""
import json, sys, re
from collections import Counter, defaultdict
src = sys.argv[1]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
sc_c = Counter(); obj_c = defaultdict(Counter); kw = defaultdict(Counter)
keys_c = Counter()
for i, line in enumerate(open(src, encoding="utf-8")):
    r = json.loads(line)
    keys_c[tuple(sorted(r.keys()))] += 1
    sc = r.get("scenario")
    sc_c[sc] += 1
    o = r.get("objectives")
    try:
        o = json.loads(o) if isinstance(o, str) else o
    except Exception:
        o = None
    if not o:
        obj_c[sc]["noobj"] += 1; continue
    obj_c[sc]["".join(str(int(bool(o.get(k)))) for k in KEYS)] += 1
    t = ((r.get("subject") or "") + " " + (r.get("body") or "")).lower()
    for w in ["zenith", "q2", "budget", "million", "profit"]:
        if w in t: kw[sc][w] += 1
print(keys_c.most_common(3))
for sc in sorted(sc_c, key=str):
    print(sc, sc_c[sc], dict(obj_c[sc].most_common(8)), dict(kw[sc]))
