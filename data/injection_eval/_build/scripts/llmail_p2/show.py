import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
path, start, end, maxc = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
with open(path, encoding="utf-8") as f:
    rows = [json.loads(l) for l in f if l.strip()]
for n, r in enumerate(rows[start:end], start):
    t = r["text"]
    print(f"=== #{n} row={r['row_index']} {r['scenario']} {r['stratum']} team={r['team_id'][:8]} len={len(t)} tags={r['tags']}")
    print(t[:maxc] + (" [...]" if len(t) > maxc else ""))
