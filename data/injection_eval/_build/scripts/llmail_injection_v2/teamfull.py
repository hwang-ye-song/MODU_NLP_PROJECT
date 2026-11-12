"""Team x level matrix of full-success rows. Usage: python -I teamfull.py <pool.jsonl> <core.jsonl>"""
import json, sys
from collections import defaultdict, Counter
sys.stdout.reconfigure(encoding="utf-8")
pool = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
core = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8")]
ct = Counter(r["origin"]["team_id"][:8] for r in core)
m = defaultdict(Counter)
for r in pool:
    if r["stratum"] == "full":
        m[r["team_id"][:8]][r["scenario"][5:]] += 1
for t in sorted(m, key=lambda t: -len(m[t])):
    print(t, "core_used=%d" % ct[t], dict(sorted(m[t].items())))
print("teams with full:", len(m))
