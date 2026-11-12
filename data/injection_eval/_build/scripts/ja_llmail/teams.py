"""Team stats in pool. Usage: python -X utf8 -I teams.py <pool.jsonl> <raw.jsonl>"""
import json, sys
from collections import Counter, defaultdict
pool = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
allteams = Counter()
for l in open(sys.argv[2], encoding="utf-8"):
    r = json.loads(l)
    if r.get("scenario","").startswith("level") and r["scenario"][-1] in "klmnopqrstuv":
        allteams[r["team_id"]] += 1
print("phase2 teams total", len(allteams))
t = defaultdict(Counter)
for r in pool:
    t[r["team_id"]][r["tier"]] += 1
    t[r["team_id"]]["goal"] += int(r["f"]["goal_addr"] or r["f"]["goal_body"])
dist = Counter()
for k, c in t.items():
    n = c["full"] + c["partial"]
    dist[min(n, 10)] += 1
print("pool rows per team (capped 10):", sorted(dist.items()))
print("teams with >=3 rows:", sum(1 for c in t.values() if c['full']+c['partial'] >= 3))
print("teams with >=1 full:", sum(1 for c in t.values() if c['full']))
for k, c in sorted(t.items(), key=lambda kv: -kv[1]["full"])[:30]:
    print(k[:8], dict(c))
