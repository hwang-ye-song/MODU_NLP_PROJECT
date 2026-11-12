"""Show the context around the template payload of given rows."""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from templates import classify
from common import site_of
bs = json.load(open(sys.argv[1], encoding="utf-8"))
for r in map(int, sys.argv[2].split(",")):
    h = bs[r]["content"]
    hits, weak = classify(h)
    for k, t, s in hits:
        i = h.find(s)
        print(f"## {r} len={len(h)} site={site_of(h)} {k} @{i} | " + re.sub(r"\s+", " ", h[max(0, i - 160):i]) + " [[P]] " + re.sub(r"\s+", " ", h[i + len(s):i + len(s) + 60]))
