import json, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from common import visible
bs = json.load(open(sys.argv[1], encoding="utf-8"))
n = int(sys.argv[3]) if len(sys.argv) > 3 else 350
for r in map(int, sys.argv[2].split(",")):
    v = visible(bs[r]["content"])
    print(f"## {r} html={len(bs[r]['content'])} vis={len(v)} | {v[:n]}")
