"""Print candidates having a given trigger. Usage: show.py <cands.jsonl> <trigger> [max] [maxlen]"""
import json
import sys

path, trig = sys.argv[1], sys.argv[2]
mx = int(sys.argv[3]) if len(sys.argv) > 3 else 50
maxlen = int(sys.argv[4]) if len(sys.argv) > 4 else 3000
n = 0
for line in open(path, encoding="utf-8"):
    c = json.loads(line)
    if trig != "*" and trig not in c["triggers"]:
        continue
    if c["len"] > maxlen:
        continue
    n += 1
    if n > mx:
        break
    print(f"===== {c['split']}:{c['row_index']} score={c['score']} len={c['len']} trig={c['triggers']} imper={c['imper']}")
    print(c["text"])
    print()
