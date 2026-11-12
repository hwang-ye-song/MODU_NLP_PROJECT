"""List review candidates for (scenario, stratum) cells.

Usage: python -X utf8 -I cand.py <pool.jsonl> <core.jsonl> <chosen_rows.txt> <cells> <n_random> <n_rare> <maxchars> <out.txt> [allow_team_reuse]
  cells: comma list like level1m:full,level1m:detected
  chosen_rows.txt: one row_index per line (already picked new items; may be empty)
Candidates come from a single random.seed(42) shuffle of the pool; teams already used
(core + chosen) are skipped unless allow_team_reuse=1 (then teams used < 2 are allowed);
anything with difflib ratio >= 0.6 to a selected text is skipped.
"""
import json
import random
import re
import sys
from collections import Counter
from difflib import SequenceMatcher

sys.stdout.reconfigure(encoding="utf-8")
pool_p, core_p, chosen_p, cells_s, n_rand, n_rare, maxc, out_p = sys.argv[1:9]
reuse = len(sys.argv) > 9 and sys.argv[9] == "1"
n_rand, n_rare, maxc = int(n_rand), int(n_rare), int(maxc)
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
RARE = {"base64", "hex", "encoding_kw", "tag_chars", "zero_width", "fullwidth", "cyrillic", "math_alpha",
        "combining", "judge", "split", "html", "roleplay", "non_latin_script", "tool_call", "code", "leet",
        "spaced_or_obf", "authority", "fake_summary"}


def norm(t):
    return re.sub(r"\s+", " ", t.lower()).strip()


pool = [json.loads(l) for l in open(pool_p, encoding="utf-8")]
core = [json.loads(l) for l in open(core_p, encoding="utf-8")]
chosen = {int(x) for x in open(chosen_p, encoding="utf-8").read().split()} if chosen_p != "-" else set()
by_row = {r["row_index"]: r for r in pool}
missing = [c for c in chosen if c not in by_row]
assert not missing, missing

teams = Counter(r["origin"]["team_id"] for r in core)
sel_texts = [norm(r["text"]) for r in core]
for c in chosen:
    teams[by_row[c]["team_id"]] += 1
    sel_texts.append(norm(by_row[c]["text"]))


def near(t):
    """True if char- or word-level difflib ratio (autojunk off) >= 0.6 vs any selected text."""
    nt = norm(t)
    for s in sel_texts:
        for a, b in ((nt, s), (nt.split(), s.split())):
            sm = SequenceMatcher(None, a, b, autojunk=False)
            if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6 and sm.ratio() >= 0.6:
                return True
    return False


random.seed(42)
order = list(range(len(pool)))
random.shuffle(order)

lines = []
for cell in cells_s.split(","):
    sc, st = cell.split(":")
    rows = [pool[i] for i in order if pool[i]["scenario"] == sc and pool[i]["stratum"] == st]
    rand_l, rare_l, seen_teams = [], [], set()
    for r in rows:
        if r["team_id"] in seen_teams or r["row_index"] in chosen:
            continue
        if teams[r["team_id"]] >= (2 if reuse else 1):
            continue
        if len(rand_l) < n_rand:
            target = rand_l
        elif len(rare_l) < n_rare and RARE & set(r["tags"]):
            target = rare_l
        else:
            continue
        if near(r["text"]):
            continue
        seen_teams.add(r["team_id"])
        target.append(r)
        if len(rand_l) >= n_rand and len(rare_l) >= n_rare:
            break
    shown = rand_l + rare_l
    lines.append(f"########## CELL {sc} {st}: {len(rows)} rows, showing {len(shown)}")
    for r in shown:
        ob = "".join(str(int(r["objectives"][k])) for k in KEYS)
        t = r["text"]
        lines.append(f"=== row={r['row_index']} {sc} {st} obj={ob} team={r['team_id'][:8]} used={teams[r['team_id']]} len={r['len']} en={int(r['english'])} tags={','.join(r['tags'])}")
        lines.append(t[:maxc] + (" [...]" if len(t) > maxc else ""))
open(out_p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote", out_p, len(lines))
