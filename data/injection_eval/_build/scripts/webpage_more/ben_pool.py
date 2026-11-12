"""Benign candidate pool: label 'no', unused, english_ok, no artifact, no AI_CUE (same filter as build_webpage.py)."""
import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import english_ok, ARTIFACT, site_of
bs = json.load(open(sys.argv[1], encoding="utf-8"))
used = {json.loads(l)["origin"].get("row_index") for l in open(sys.argv[2], encoding="utf-8")}
hi = int(sys.argv[3])
AI_CUE = re.compile(r"ignore (all )?previous|disregard|system (prompt|instruction)|you are now|override|admin mode|\bAI\b|language model", re.I)
rej = collections.Counter(); out = []
for x in bs:
    h = x["content"]
    if x["label"] != "no" or len(h) > hi or x["row_index"] in used:
        continue
    if not english_ok(h): rej["nonen/stub"] += 1; continue
    if ARTIFACT.search(h): rej["artifact"] += 1; continue
    if AI_CUE.search(h): rej["ai_cue"] += 1; continue
    out.append((x["row_index"], len(h), site_of(h)))
print(rej, len(out))
for b in (3000, 5000, 8000, 10000, 12000, 15000):
    print(b, sum(1 for o in out if o[1] <= b))
print(collections.Counter(o[2] for o in out).most_common(40))
for o in out: print(o)
