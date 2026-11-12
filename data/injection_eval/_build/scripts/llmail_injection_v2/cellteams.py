"""Team composition of cells with current team usage. Usage: python -I cellteams.py <pool> <core> <chosen> <cells>"""
import json, sys
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding="utf-8")
pool = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
core = [json.loads(l) for l in open(sys.argv[2], encoding="utf-8")]
chosen = {int(x) for x in open(sys.argv[3], encoding="utf-8").read().split()}
by_row = {r["row_index"]: r for r in pool}
used = Counter(r["origin"]["team_id"][:8] for r in core)
for c in chosen: used[by_row[c]["team_id"][:8]] += 1
for cell in sys.argv[4].split(","):
    sc, st = cell.split(":")
    c = Counter(r["team_id"][:8] for r in pool if r["scenario"] == sc and r["stratum"] == st)
    print(cell, " ".join(f"{t}({n},u{used[t]})" for t, n in c.most_common()))
