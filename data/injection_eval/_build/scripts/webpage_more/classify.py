import json, re, sys, os, collections
sys.path.insert(0, os.path.dirname(__file__))
from common import english_ok, ARTIFACT, site_of
from templates import classify
bs = json.load(open(sys.argv[1], encoding="utf-8"))
used = {json.loads(l)["origin"].get("row_index") for l in open(sys.argv[2], encoding="utf-8")}
hi = int(sys.argv[3])
C = collections.defaultdict(list); unk = []
for x in bs:
    h = x["content"]
    if x["label"] != "yes" or len(h) > hi or x["row_index"] in used or not english_ok(h) or ARTIFACT.search(h):
        continue
    hits, weak = classify(h)
    if len(hits) > 1:
        print("MULTI", x["row_index"], [k for k, _, _ in hits])
    if hits:
        C[hits[0][0]].append((x["row_index"], len(h), site_of(h), "+weak" if weak else ""))
    else:
        unk.append((x["row_index"], len(h), site_of(h), ",".join(weak)))
for k, v in sorted(C.items()):
    print(k, len(v), sorted(v, key=lambda z: z[1]))
print("UNCLASSIFIED", len(unk))
for u in sorted(unk, key=lambda z: z[1]): print("  ", u)
