import json
import sys

sys.stdout.reconfigure(encoding="utf-8")
src = sys.argv[1]
want = [int(x) for x in sys.argv[2].split(",")]
ws = set(want)
found = {}
with open(src, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if i in ws:
            found[i] = json.loads(line)
for i in want:
    r = found[i]
    text = f"Subject: {r.get('subject') or ''}\n\n{r.get('body') or ''}"
    print(f"=== row={i} {r['scenario']} team={r['team_id'][:8]} len={len(text)} obj={r['objectives']}")
    print(ascii(text) if "--ascii" in sys.argv else text)
