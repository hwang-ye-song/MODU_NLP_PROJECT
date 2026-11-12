import json
import sys
import re
from collections import Counter, defaultdict

path = sys.argv[1]
rows = []
with open(path, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if line.strip():
            rows.append((i, json.loads(line)))

kw = ["zenith", "q2", "budget", "million", "confirmation", "contact@contact.com", "profit"]
cnt = defaultdict(Counter)
tot = Counter()
for i, r in rows:
    sc = r.get("scenario") or ""
    pre = sc[:6]
    tot[pre] += 1
    t = ((r.get("subject") or "") + " " + (r.get("body") or "")).lower()
    for k in kw:
        if k in t:
            cnt[pre][k] += 1
for pre in sorted(tot):
    print(pre, tot[pre], {k: round(cnt[pre][k] / tot[pre], 2) for k in kw})

# successful level2 examples: show a few bodies briefly
n = 0
for i, r in rows:
    sc = r.get("scenario") or ""
    o = r.get("objectives")
    o = json.loads(o) if isinstance(o, str) else (o or {})
    if sc.startswith("level2") and o.get("exfil.sent") and o.get("exfil.content"):
        print("----", i, sc, o)
        print(repr((r.get("subject") or "")[:200]), repr((r.get("body") or "")[:400]))
        n += 1
        if n >= 4:
            break
# output field: does it vary?
oc = Counter((r.get("output") or "")[:40] for _, r in rows)
print(oc.most_common(5))
