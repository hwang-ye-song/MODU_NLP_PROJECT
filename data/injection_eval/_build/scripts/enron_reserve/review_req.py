"""Dump request/trigger-word candidates from the scan pool, in pool (seed-42 rank) order.

Usage: python -X utf8 -I review_req.py <pool.jsonl> <out review.txt> <lo> <hi> <n> [skip_rows_csv]
"""
import json
import sys

pool_p, out_p, lo, hi, n = sys.argv[1], sys.argv[2], int(sys.argv[3]), int(sys.argv[4]), int(sys.argv[5])
skip = {int(x) for x in sys.argv[6].split(",")} if len(sys.argv) > 6 and sys.argv[6] else set()
STRONG = {"ignore", "disregard", "urgent", "please send", "forget", "override", "bypass", "immediately", "instructions"}
k = 0
with open(pool_p, encoding="utf-8") as f, open(out_p, "w", encoding="utf-8") as o:
    for line in f:
        c = json.loads(line)
        if c["i"] in skip or not lo <= c["len"] < hi:
            continue
        if not (c["req"] or STRONG & set(c["trig"])):
            continue
        if any(fl.startswith("phone") or fl.startswith("medical") for fl in c["flags"]):
            continue
        o.write(f"===== row={c['i']} rank={c['rank']} len={c['len']} req={c['req']} trig={c['trig']} flags={c['flags']}\n{c['text']}\n\n")
        k += 1
        if k >= n:
            break
print("wrote", k)
