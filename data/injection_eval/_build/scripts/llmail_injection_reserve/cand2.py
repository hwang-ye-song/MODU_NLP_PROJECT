"""List reserve candidates per Phase 2 level, from a single random.seed(42) shuffle of the pool.

Usage: python -X utf8 -I cand2.py <pool.jsonl> <excl.json> <per_stratum> <maxchars> <out.txt> <max_team_use_in_80> [levels,comma]
Skips rows already used (excl rows), teams used more than max_use times in the existing 80
(least-used teams listed first), near-duplicates
(char- or word-level difflib ratio >= 0.6, autojunk off, normalised text) of any excluded text
or of an earlier listed candidate. One candidate per team per level.
"""
import json, random, re, sys
from difflib import SequenceMatcher
sys.stdout.reconfigure(encoding="utf-8")
pool_p, excl_p, per, maxc, out_p, max_use = sys.argv[1:7]
per, maxc, max_use = int(per), int(maxc), int(max_use)
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()
pool = [json.loads(l) for l in open(pool_p, encoding="utf-8")]
ex = json.load(open(excl_p, encoding="utf-8"))
rows_ex, teams80 = set(ex["rows"]), ex["teams80"]
sel = [norm(t) for _, t in ex["texts"]]
levels = sys.argv[7].split(",") if len(sys.argv) > 7 else sorted({r["scenario"] for r in pool})


def near(t, others):
    nt = norm(t)
    for s in others:
        for a, b in ((nt, s), (nt.split(), s.split())):
            sm = SequenceMatcher(None, a, b, autojunk=False)
            if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6 and sm.ratio() >= 0.6:
                return True
    return False


random.seed(42)
order = list(range(len(pool)))
random.shuffle(order)
order.sort(key=lambda i: teams80.get(pool[i]["team_id"], 0))  # stable: least-used teams first
shown, lines = [], []
for lv in levels:
    used_t = set()
    for st in ["full", "undetected_partial", "detected"]:
        got = 0
        for i in order:
            r = pool[i]
            if r["scenario"] != lv or r["stratum"] != st or r["row_index"] in rows_ex:
                continue
            if teams80.get(r["team_id"], 0) > max_use or r["team_id"] in used_t or not r["english"]:
                continue
            if near(r["text"], sel + shown):
                continue
            used_t.add(r["team_id"]); shown.append(norm(r["text"])); got += 1
            ob = "".join(str(int(r["objectives"][k])) for k in KEYS)
            lines.append(f"=== row={r['row_index']} {lv} {st} obj={ob} team={r['team_id'][:8]} use80={teams80.get(r['team_id'], 0)} len={r['len']} tags={','.join(r['tags'])}")
            t = r["text"]
            lines.append(t[:maxc] + (f" [...+{len(t)-maxc}]" if len(t) > maxc else ""))
            if got >= per:
                break
open(out_p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote", out_p, sum(l.startswith("===") for l in lines))
