"""Print full pool texts. Usage: show.py <pool.jsonl> <excl.json> <rows,comma>"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
want = [int(x) for x in sys.argv[3].split(",")]
t80 = json.load(open(sys.argv[2], encoding="utf-8"))["teams80"]
pool = {}
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    if r["row_index"] in want:
        pool[r["row_index"]] = r
for w in want:
    r = pool[w]
    ob = "".join(str(int(r["objectives"][k])) for k in KEYS)
    print(f"=== row={w} {r['scenario']} {r['stratum']} obj={ob} team={r['team_id'][:8]} use80={t80.get(r['team_id'], 0)} len={r['len']}")
    print(r["text"])
