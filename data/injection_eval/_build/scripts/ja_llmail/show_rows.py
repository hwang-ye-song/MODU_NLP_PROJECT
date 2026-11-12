"""Compact review of selected rows.

Usage: python -X utf8 -I show_rows.py <review.jsonl> <rows_file_comma_separated> <from> <to> <head> <tail>
(from/to index into the rows list, 0-based, end exclusive)
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
p, rows_p, a, b, h, t = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5]), int(sys.argv[6])
want = [int(x) for x in open(rows_p).read().split(",") if x.strip()][a:b]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
idx = {}
for n, l in enumerate(open(p, encoding="utf-8"), 1):
    r = json.loads(l)
    idx[r["origin"]["row_index"]] = (n, r)
for ri in want:
    n, r = idx[ri]
    o = r["origin"]
    tx = r["text"]
    vis = "".join(c if (c.isprintable() or c == "\n") and not (0xE0000 <= ord(c) <= 0xE007F)
                  else ("·" if 0xE0000 <= ord(c) <= 0xE007F else "¤") for c in tx)
    vis = re.sub(r"\n+", " ⏎ ", vis)
    vis = re.sub(r"·{3,}", lambda m: f"[TAGCH×{len(m.group(0))}]", vis)
    shown = vis if len(vis) <= h + t + 40 else vis[:h] + f" […{len(vis) - h - t}…] " + vis[-t:]
    ob = "".join(str(int(o["objectives"][k])) for k in KEYS)
    print(f"#{n} r{ri} {o['level']} {ob} t={o['team_id'][:6]} L={len(tx)} [{','.join(r['technique_tags'])}]")
    print(f"  I: {r['injected_instruction']!r}"[:300])
    print(f"  T: {shown}")
