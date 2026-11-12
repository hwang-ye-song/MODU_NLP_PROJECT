import json
import sys
from collections import Counter

path = sys.argv[1]
rows = []
with open(path, encoding="utf-8") as f:
    for i, line in enumerate(f):
        line = line.strip()
        if not line:
            continue
        rows.append((i, json.loads(line)))

print("n rows:", len(rows))
print("keys:", Counter(tuple(sorted(r.keys())) for _, r in rows).most_common(3))
print("scenario:", sorted(Counter(r.get("scenario") for _, r in rows).items()))

def objs(r):
    o = r.get("objectives")
    if isinstance(o, str):
        try:
            return json.loads(o)
        except Exception:
            return None
    return o

oc = Counter()
for _, r in rows:
    o = objs(r)
    if o is None:
        oc["NONE"] += 1
        continue
    oc[tuple(o.get(k) for k in ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"])] += 1
for k, v in oc.most_common(40):
    print(k, v)

print("teams:", len(set(r.get("team_id") for _, r in rows)))
print("example:", json.dumps(rows[0][1], ensure_ascii=False)[:1500])
# success per scenario
succ = Counter()
for _, r in rows:
    o = objs(r) or {}
    if all(o.get(k) for k in ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]):
        succ[r.get("scenario")] += 1
print("full success per scenario:", sorted(succ.items()))
