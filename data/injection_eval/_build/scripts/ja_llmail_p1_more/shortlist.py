"""Shortlist new Phase-1 detector-evasion candidates (not yet read). Usage: shortlist.py pool.jsonl out.jsonl"""
import json, sys, re, glob, difflib, random
from collections import Counter, defaultdict
random.seed(42)
sys.stdout.reconfigure(encoding="utf-8")
WD = "<DATASET_ROOT>/_build/"
ex_files = [WD + "ja_llmail_phase1_candidates.jsonl", WD + "ja_llmail_candidates.jsonl"] + glob.glob(WD + "parts_v2/llmail_injection*.jsonl")
ex_texts, ex_keys = [], set()
for f in ex_files:
    for l in open(f, encoding="utf-8"):
        if l.strip():
            r = json.loads(l); ex_texts.append(r["text"])
            o = r.get("origin", {})
            for k in ("RowKey", "row_key", "rowkey"):
                if o.get(k): ex_keys.add(o[k])
print("existing", len(ex_texts), "keys", len(ex_keys))
PRI = {"all": 0, "llm_judge": 1, "task_tracker": 2, "prompt_shield": 3}
GOAL = re.compile(r"contact@contact\.com", re.I)
rows = []
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    if r["RowKey"] in ex_keys or not r["english_strict"] or r["len"] > 3000 or r["len"] < 120: continue
    f = r["f"]
    if not (f["send_verb"] and (GOAL.search(r["text"]) or f["b64"])): continue
    if f["non_latin"] > 0: continue
    rows.append(r)
print("prefiltered", len(rows))
rows.sort(key=lambda r: (PRI[r["detector"]], r["subrank"], -(r["f"]["ai_address"] > 0), r["row_index"]))
def near(t, pool):
    for p in pool:
        sm = difflib.SequenceMatcher(None, t, p, autojunk=False)
        if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6 and sm.ratio() >= 0.6: return True
    return False
out, team = [], Counter()
LIMIT = int(sys.argv[3]) if len(sys.argv) > 3 else 400
for r in rows:
    if team[r["team_id"]] >= 5: continue
    if near(r["text"], ex_texts) or near(r["text"], [x["text"] for x in out]): continue
    out.append(r); team[r["team_id"]] += 1
    if len(out) >= LIMIT: break
print("short", len(out), Counter(x["detector"] for x in out), Counter(x["subrank"] for x in out))
with open(sys.argv[2], "w", encoding="utf-8", newline="\n") as fh:
    for i, r in enumerate(out):
        r["_s"] = i; fh.write(json.dumps(r, ensure_ascii=False) + "\n")
