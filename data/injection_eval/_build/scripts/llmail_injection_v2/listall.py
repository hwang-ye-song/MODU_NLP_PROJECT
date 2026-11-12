"""Per cell, per team with remaining capacity, list up to K distinct non-near-dup texts.
Usage: python -X utf8 -I listall.py <pool> <core> <chosen> <cells> <K> <maxc> <out> [skip_teams]"""
import json, random, re, sys
from collections import Counter, defaultdict
from difflib import SequenceMatcher
sys.stdout.reconfigure(encoding="utf-8")
pool_p, core_p, chosen_p, cells, K, maxc, out = sys.argv[1:8]
skip = set(sys.argv[8].split(",")) if len(sys.argv) > 8 else set()
K, maxc = int(K), int(maxc)
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()
pool = [json.loads(l) for l in open(pool_p, encoding="utf-8")]
core = [json.loads(l) for l in open(core_p, encoding="utf-8")]
chosen = {int(x) for x in open(chosen_p, encoding="utf-8").read().split()}
by_row = {r["row_index"]: r for r in pool}
used = Counter(r["origin"]["team_id"] for r in core)
sel = [norm(r["text"]) for r in core]
for c in chosen:
    used[by_row[c]["team_id"]] += 1; sel.append(norm(by_row[c]["text"]))
def near(t, others):
    nt = norm(t)
    for s in others:
        for a, b in ((nt, s), (nt.split(), s.split())):
            sm = SequenceMatcher(None, a, b, autojunk=False)
            if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6 and sm.ratio() >= 0.6:
                return True
    return False
random.seed(42)
order = list(range(len(pool))); random.shuffle(order)
lines = []
for cell in cells.split(","):
    sc, st = cell.split(":")
    per_team = defaultdict(list)
    for i in order:
        r = pool[i]
        if r["scenario"] != sc or r["stratum"] != st or r["row_index"] in chosen: continue
        if used[r["team_id"]] >= 2 or r["team_id"][:8] in skip: continue
        lst = per_team[r["team_id"]]
        if len(lst) >= K: continue
        if near(r["text"], sel + [norm(x["text"]) for x in lst]): continue
        lst.append(r)
    lines.append(f"########## CELL {sc} {st}: teams {len(per_team)}")
    for t, lst in per_team.items():
        for r in lst:
            ob = "".join(str(int(r["objectives"][k])) for k in KEYS)
            lines.append(f"=== row={r['row_index']} {sc} {st} obj={ob} team={t[:8]} used={used[t]} len={r['len']} tags={','.join(r['tags'])}")
            tx = r["text"]; lines.append(tx[:maxc] + (" [...]" if len(tx) > maxc else ""))
open(out, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote", out, len(lines))
