import json, sys, difflib, os
OUT, REPO = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(OUT, encoding="utf-8")]
def ctx(r):
    row = json.loads(open(os.path.join(REPO, r["origin"]["file"]), encoding="utf-8").read().split("\n")[r["origin"]["index"]])
    c = row["context"]; return "\n".join(c) if isinstance(c, list) else c
C = {r["id"]: ctx(r) for r in recs}
ids = list(C)
for i in range(len(ids)):
    for j in range(i+1, len(ids)):
        a, b = ids[i], ids[j]
        ra = difflib.SequenceMatcher(None, C[a], C[b], autojunk=False).ratio()
        if ra > 0.7:
            print(a, b, round(ra, 3))
