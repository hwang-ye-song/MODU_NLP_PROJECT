"""Technique-first candidate listing for the undetected/detected strata.

Usage: python -X utf8 -I techlist.py <pool.jsonl> <core.jsonl> <chosen_rows.txt> <per_tag> <maxc> <out.txt>
Only cells still needed (NEED below) are considered; teams already used are skipped;
near-duplicates (difflib >= 0.6 char or word level) of selected texts are skipped.
"""
import json, random, re, sys
from collections import Counter
from difflib import SequenceMatcher
sys.stdout.reconfigure(encoding="utf-8")
pool_p, core_p, chosen_p, per, maxc, out_p = sys.argv[1:7]
per, maxc = int(per), int(maxc)
NEED_U = "1l 1m 1o 1p 1q 1r 1s 1t 1u 1v 2k 2l 2m 2n 2o 2p 2s 2t 2u 2v".split()
NEED_D = "1k 1l 1m 1n 1o 1p 1q 1s 1t 1v 2k 2m 2n 2o 2p 2q 2r 2t 2u 2v".split()
NEED = {("level" + l, "undetected_partial") for l in NEED_U} | {("level" + l, "detected") for l in NEED_D}
ORDER = ["math_alpha", "combining", "hex", "cyrillic", "tag_chars", "zero_width", "fullwidth", "encoding_kw", "base64",
         "non_latin_script", "roleplay", "leet", "html", "judge", "split", "spaced_or_obf", "tool_call", "code", "authority", "fake_summary"]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()
pool = [json.loads(l) for l in open(pool_p, encoding="utf-8")]
core = [json.loads(l) for l in open(core_p, encoding="utf-8")]
chosen = {int(x) for x in open(chosen_p, encoding="utf-8").read().split()}
by_row = {r["row_index"]: r for r in pool}
teams = Counter(r["origin"]["team_id"] for r in core)
sel = [norm(r["text"]) for r in core]
for c in chosen:
    teams[by_row[c]["team_id"]] += 1
    sel.append(norm(by_row[c]["text"]))

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
cands = [pool[i] for i in order if (pool[i]["scenario"], pool[i]["stratum"]) in NEED and teams[pool[i]["team_id"]] == 0 and pool[i]["row_index"] not in chosen]
print("candidate rows:", len(cands), "unused teams:", len({r["team_id"] for r in cands}))
lines, shown_rows, shown_texts = [], set(), []
for tag in ORDER:
    got, tteams = [], set()
    for r in cands:
        if tag not in r["tags"] or r["row_index"] in shown_rows or r["team_id"] in tteams:
            continue
        if near(r["text"], sel + shown_texts):
            continue
        got.append(r); tteams.add(r["team_id"]); shown_rows.add(r["row_index"]); shown_texts.append(norm(r["text"]))
        if len(got) >= per:
            break
    lines.append(f"########## TAG {tag}: {len(got)}")
    for r in got:
        ob = "".join(str(int(r["objectives"][k])) for k in KEYS)
        lines.append(f"=== row={r['row_index']} {r['scenario']} {r['stratum']} obj={ob} team={r['team_id'][:8]} len={r['len']} tags={','.join(r['tags'])}")
        t = r["text"]
        lines.append(t[:maxc] + (" [...]" if len(t) > maxc else ""))
open(out_p, "w", encoding="utf-8").write("\n".join(lines) + "\n")
print("wrote", out_p)
