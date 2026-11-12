"""Compact review printer. Usage: python -X utf8 -I show.py <review.jsonl> <from> <to> <head> <tail> [only_null]"""
import json, sys, re
sys.stdout.reconfigure(encoding="utf-8")
p, a, b, h, t = sys.argv[1], int(sys.argv[2]), int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
only_null = len(sys.argv) > 6 and sys.argv[6] == "1"
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
for n, l in enumerate(open(p, encoding="utf-8"), 1):
    if n < a or n > b:
        continue
    r = json.loads(l)
    if only_null and r["injected_instruction"] is not None:
        continue
    o = r["origin"]
    tx = r["text"]
    vis = "".join(c if (c.isprintable() or c == "\n") and not (0xE0000 <= ord(c) <= 0xE007F) else ("·" if 0xE0000 <= ord(c) <= 0xE007F else "¤") for c in tx)
    vis = re.sub(r"\n+", " ⏎ ", vis)
    vis = re.sub(r"·{3,}", lambda m: f"[TAGCH×{len(m.group(0))}]", vis)
    shown = vis if len(vis) <= h + t + 40 else vis[:h] + f" […{len(vis)-h-t}…] " + vis[-t:]
    ob = "".join(str(int(o["objectives"][k])) for k in KEYS)
    print(f"#{n} r{o['row_index']} {o['level']} {ob} t={o['team_id'][:6]} L={len(tx)} [{','.join(r['technique_tags'])}]")
    print(f"  I: {r['injected_instruction']!r}")
    print(f"  T: {shown}")
