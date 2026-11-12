"""For given rows, list every pool row with the same normalised text (other levels/strata).
Usage: python -I variants.py <pool.jsonl> <rows,comma>"""
import json, re, sys
from collections import defaultdict
sys.stdout.reconfigure(encoding="utf-8")
norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()
want = [int(x) for x in sys.argv[2].split(",")]
pool = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
by_text = defaultdict(list)
for r in pool:
    by_text[norm(r["text"])].append(r)
by_row = {r["row_index"]: r for r in pool}
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
for w in want:
    vs = by_text[norm(by_row[w]["text"])]
    print(w, by_row[w]["team_id"][:8], "->", ", ".join(f"{v['row_index']}:{v['scenario'][5:]}:{''.join(str(int(v['objectives'][k])) for k in KEYS)}" for v in vs))
