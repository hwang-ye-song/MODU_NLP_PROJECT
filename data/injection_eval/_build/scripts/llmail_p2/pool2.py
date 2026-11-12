"""Targeted candidate listing for under-covered sublevels.

Usage: python -I pool2.py <raw.jsonl> <sublevels,comma> <exclude_team_prefixes,comma> <per_cell> <maxchars>
Reuses filtering logic from pool.py (imported by path-free copy to stay -I safe).
"""
import json
import random
import re
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8")
src = sys.argv[1]
subs = sys.argv[2].split(",")
excl = [t for t in sys.argv[3].split(",") if t]
per = int(sys.argv[4])
maxc = int(sys.argv[5])
mode = sys.argv[6] if len(sys.argv) > 6 else "all"

KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
STOP = {"the", "to", "and", "please", "email", "you", "is", "a", "of", "this", "with", "send", "for", "your", "in"}


def is_english(t):
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 40:
        return False
    ascii_ratio = sum(c.isascii() for c in letters) / len(letters)
    words = re.findall(r"[a-z]+", t.lower())
    sw = sum(w in STOP for w in words)
    return ascii_ratio >= 0.97 and sw >= 4 and sw / max(1, len(words)) >= 0.08


def stratum(o):
    if all(o.get(k) for k in KEYS):
        return "full_success"
    if o.get("defense.undetected") and o.get("exfil.sent"):
        return "undetected_sent_partial"
    if o.get("defense.undetected"):
        return "undetected_not_sent"
    if o.get("exfil.sent"):
        return "detected_but_sent"
    return "detected_failed"


cells = defaultdict(list)
seen = set()
with open(src, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if not line.strip():
            continue
        r = json.loads(line)
        sc = r.get("scenario") or ""
        o = r.get("objectives")
        o = json.loads(o) if isinstance(o, str) else o
        if not o or any(o.get(k) is None for k in KEYS):
            continue
        text = f"Subject: {r.get('subject') or ''}\n\n{r.get('body') or ''}"
        k = re.sub(r"\s+", " ", text.lower()).strip()
        if k in seen:
            continue
        seen.add(k)
        if sc not in subs:
            continue
        if any((r.get("team_id") or "").startswith(e) for e in excl):
            continue
        if len(text) > 3000 or len(text) < 120 or not is_english(text):
            continue
        st = stratum(o)
        if mode == "success" and st.startswith("detected"):
            continue
        if mode == "detected" and not st.startswith("detected"):
            continue
        if mode == "encoded" and not re.search(r"(\b[0-9A-Fa-f]{2}(\s+[0-9A-Fa-f]{2}){15,})|([A-Za-z0-9+/]{40,}={0,2})", text):
            continue
        cells[(sc, st)].append((i, r, o, text))

random.seed(42)
for key in sorted(cells):
    lst = cells[key]
    random.shuffle(lst)
    teams = set()
    shown = 0
    for i, r, o, text in lst:
        if r["team_id"] in teams:
            continue
        teams.add(r["team_id"])
        print(f"=== row={i} {key[0]} {key[1]} team={r['team_id'][:8]} len={len(text)} (cell size {len(lst)})")
        print(text[:maxc] + (" [...]" if len(text) > maxc else ""))
        shown += 1
        if shown >= per:
            break
