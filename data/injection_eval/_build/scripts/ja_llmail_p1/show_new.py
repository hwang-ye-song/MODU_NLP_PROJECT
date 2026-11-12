"""Print review records whose row_index is not in the reviewed-rows files.

Usage: python -X utf8 -I show_new.py <review.jsonl> <max_pos> <head> <tail> <reviewed.txt> [<reviewed.txt> ...]
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
p, maxpos, h, t = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4])
seen = set()
for f in sys.argv[5:]:
    seen |= {int(x) for x in open(f).read().split()}
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
for n, l in enumerate(open(p, encoding="utf-8"), 1):
    if n > maxpos:
        break
    r = json.loads(l)
    o = r["origin"]
    if o["row_index"] in seen:
        continue
    tx = r["text"]
    vis = "".join(c if (c.isprintable() or c == "\n") and not (0xE0000 <= ord(c) <= 0xE007F)
                  else ("·" if 0xE0000 <= ord(c) <= 0xE007F else "¤") for c in tx)
    vis = re.sub(r"\n+", " ⏎ ", vis)
    vis = re.sub(r"·{3,}", lambda m: f"[TAGCH×{len(m.group(0))}]", vis)
    shown = vis if len(vis) <= h + t + 40 else vis[:h] + f" […{len(vis) - h - t}…] " + vis[-t:]
    ob = "".join(str(int(o["objectives"][k])) for k in KEYS)
    print(f"#{n} r{o['row_index']} {o['level']} {ob} t={o['team_id'][:6]} L={len(tx)} [{','.join(r['technique_tags'])}]")
    print(f"  I: {r['injected_instruction']!r}"[:300])
    print(f"  T: {shown}")
