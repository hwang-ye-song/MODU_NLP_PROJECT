import json, sys, os, re
sys.path.insert(0, os.path.dirname(__file__))
from common import visible
lab, n = sys.argv[2], int(sys.argv[3])
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    if r["label"] != lab:
        continue
    o = r["origin"]
    v = visible(r["text"])
    print(f"## {r['id']} row={o['row_index']} len={len(r['text'])} {o['site_brand']} m={o.get('length_matched_to_row','')} | {v[:n]}")
