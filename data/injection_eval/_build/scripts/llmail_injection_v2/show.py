"""Show pool rows. Usage: python -I show.py <pool.jsonl> <scenarios|*> <stratum|*> <team_prefixes|*> <maxc> [rows]"""
import json, sys
sys.stdout.reconfigure(encoding="utf-8")
p, scs, st, tps, maxc = sys.argv[1:6]
rows_f = set(int(x) for x in sys.argv[6].split(",")) if len(sys.argv) > 6 else None
scs = None if scs == "*" else set("level" + s if not s.startswith("level") else s for s in scs.split(","))
tps = None if tps == "*" else tps.split(",")
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
for l in open(p, encoding="utf-8"):
    r = json.loads(l)
    if rows_f is not None and r["row_index"] not in rows_f: continue
    if scs and r["scenario"] not in scs: continue
    if st != "*" and r["stratum"] != st: continue
    if tps and not any(r["team_id"].startswith(t) for t in tps): continue
    ob = "".join(str(int(r["objectives"][k])) for k in KEYS)
    print(f"=== row={r['row_index']} {r['scenario']} {r['stratum']} obj={ob} team={r['team_id'][:8]} len={r['len']} tags={','.join(r['tags'])}")
    t = r["text"]; m = int(maxc)
    print(t[:m] + (" [...]" if len(t) > m else ""))
