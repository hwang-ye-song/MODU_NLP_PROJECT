"""Build a stratified, diversity-greedy candidate pool from LLMail-Inject Phase 2.

Usage: python -I pool.py <raw_submissions_phase2.jsonl> <out_pool.jsonl>
"""
import json
import random
import re
import sys
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")

src, out = sys.argv[1], sys.argv[2]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
VALID = re.compile(r"^level[12][k-v]$")
STOP = {"the", "to", "and", "please", "email", "you", "is", "a", "of", "this", "with", "send", "for", "your", "in"}

FAKE_TOK = re.compile(r"<\|[^|>]{1,30}\|>|\[/?(INST|SYSTEM|END|USER|ASSISTANT)[^\]]{0,20}\]|<</?SYS>>|</?(system|user|assistant|context|email|tool)[^>]{0,20}>|<end_of_turn>|<start_of_turn>|###\s*(system|user|assistant|instruction)", re.I)
B64 = re.compile(r"[A-Za-z0-9+/]{32,}={0,2}")
OBF = re.compile(r"\(at\)|<at>|\[at\]|\bat\b\s+contact\s+dot|\bdot\s+com\b|rot13|base64|hex|reverse", re.I)
JSONCALL = re.compile(r'"(to|body)"\s*:', re.I)
ROLE = re.compile(r"\b(pretend|role[- ]?play|you are now|imagine|game|story|character|simulation|act as)\b", re.I)


def parse_obj(o):
    if isinstance(o, str):
        try:
            return json.loads(o)
        except Exception:
            return None
    return o


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


def is_english(t):
    letters = [c for c in t if c.isalpha()]
    if len(letters) < 40:
        return False
    ascii_ratio = sum(c.isascii() for c in letters) / len(letters)
    words = re.findall(r"[a-z]+", t.lower())
    sw = sum(w in STOP for w in words)
    return ascii_ratio >= 0.97 and sw >= 4 and sw / max(1, len(words)) >= 0.08


def tags(t):
    tg = []
    if FAKE_TOK.search(t):
        tg.append("fake_tokens")
    if B64.search(t):
        tg.append("long_b64_like")
    if OBF.search(t):
        tg.append("obfuscation_kw")
    if JSONCALL.search(t):
        tg.append("json_call")
    if ROLE.search(t):
        tg.append("roleplay_kw")
    if re.search(r"[​-‏⁠﻿]", t):
        tg.append("zero_width")
    return tg


rows = []
with open(src, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if not line.strip():
            continue
        r = json.loads(line)
        sc = r.get("scenario") or ""
        if not VALID.match(sc):
            continue
        o = parse_obj(r.get("objectives"))
        if not o or any(o.get(k) is None for k in KEYS):
            continue
        subj = r.get("subject") or ""
        body = r.get("body") or ""
        if not body.strip():
            continue
        text = f"Subject: {subj}\n\n{body}"
        if len(text) > 3000 or len(text) < 120:
            continue
        if not is_english(text):
            continue
        rows.append({
            "row_index": i, "RowKey": r.get("RowKey"), "job_id": r.get("job_id"),
            "scenario": sc, "team_id": r.get("team_id"), "objectives": o,
            "stratum": stratum(o), "text": text, "tags": tags(text),
            "completed_time": r.get("completed_time"),
        })

print("eligible rows:", len(rows))
print(Counter(r["stratum"] for r in rows))

# exact-dup removal on normalized text (keep first occurrence)
seen = set()
uniq = []
for r in rows:
    k = re.sub(r"\s+", " ", r["text"].lower()).strip()
    if k in seen:
        continue
    seen.add(k)
    uniq.append(r)
print("unique eligible:", len(uniq))

random.seed(42)
by_stratum = defaultdict(list)
for r in uniq:
    by_stratum[r["stratum"]].append(r)
for s in sorted(by_stratum):
    random.shuffle(by_stratum[s])

# Pool: per stratum, greedily pick up to N candidates, one per team, preferring unseen sublevels.
N = {"full_success": 30, "undetected_sent_partial": 10, "undetected_not_sent": 12,
     "detected_but_sent": 12, "detected_failed": 12}
pool = []
for s in ["full_success", "undetected_sent_partial", "undetected_not_sent", "detected_but_sent", "detected_failed"]:
    teams_used = set()
    sc_count = Counter()
    picked = []
    cands = by_stratum[s]
    while len(picked) < N[s]:
        best = None
        for r in cands:
            if r["team_id"] in teams_used:
                continue
            if best is None or sc_count[r["scenario"]] < sc_count[best["scenario"]]:
                best = r
                if sc_count[r["scenario"]] == 0:
                    break
        if best is None:
            break
        picked.append(best)
        teams_used.add(best["team_id"])
        sc_count[best["scenario"]] += 1
    print(s, "available", len(cands), "teams", len({r["team_id"] for r in cands}), "picked", len(picked))
    pool.extend(picked)

with open(out, "w", encoding="utf-8") as f:
    for r in pool:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("pool size", len(pool))
