"""Report stats for the final JA candidates file.

Usage: python -X utf8 -I stats.py <candidates.jsonl> <work_dir>
"""
import glob
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8")
p, wdir = sys.argv[1], sys.argv[2]
R = [json.loads(l) for l in open(p, encoding="utf-8")]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]


def tier(r):
    o = r["origin"]["objectives"]
    if all(o[k] for k in KEYS):
        return "full"
    return "partial_sent" if o["exfil.sent"] else "partial_nosend"


for name, rows in (("all280", R), ("first250", R[:250])):
    print(f"== {name}: {len(rows)}")
    print(" detector x tier:", sorted(Counter((r["detector"], tier(r)) for r in rows).items()))
    print(" detector:", Counter(r["detector"] for r in rows))
    print(" tier:", Counter(tier(r) for r in rows))
    print(" scenario:", Counter(r["origin"]["scenario"] for r in rows), "model:", Counter(r["origin"]["model"] for r in rows))
    print(" defense:", Counter(r["origin"]["defense"] for r in rows))
    L = sorted(len(r["text"]) for r in rows)
    print(" len min/med/mean/p90/max:", L[0], L[len(L) // 2], round(sum(L) / len(L)), L[int(len(L) * .9)], L[-1],
          ">3000:", sum(x > 3000 for x in L), f"({sum(x > 3000 for x in L) / len(L):.1%})", "<=3000:", sum(x <= 3000 for x in L))
    print(" tags:", Counter(t for r in rows for t in r["technique_tags"]).most_common())
    print(" risk:", Counter(r["risk_level"] for r in rows), "instr null:", sum(r["injected_instruction"] is None for r in rows))
    tc = Counter(r["origin"]["team_id"] for r in rows)
    res = sum("Reserve tail" in r["notes"] for r in rows)
    print(" teams:", len(tc), "max/team:", max(tc.values()), "teams>3:", sum(v > 3 for v in tc.values()), "reserve items:", res)
    print(" first reserve rank:", next((i + 1 for i, r in enumerate(rows) if "Reserve tail" in r["notes"]), None))
caches = glob.glob(wdir + "/en_neardup_cache_*.json")
for c in caches:
    d = json.load(open(c))
    print("cache", c.split("_")[-1], "evaluated", len(d), "near-dup to EN", sum(d.values()))
