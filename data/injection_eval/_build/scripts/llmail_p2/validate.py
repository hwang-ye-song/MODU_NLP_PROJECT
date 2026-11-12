"""Validate the output JSONL and cross-check row indices against the HF datasets-server rows API.

Usage: python -I validate.py <out.jsonl> [--remote]
"""
import json
import re
import sys
import urllib.request
from collections import Counter
from difflib import SequenceMatcher

sys.stdout.reconfigure(encoding="utf-8")
path = sys.argv[1]
raw = open(path, encoding="utf-8").read()
lines = raw.split("\n")
assert lines[-1] == "", "file should end with newline"
lines = lines[:-1]
print("lines:", len(lines))
recs = [json.loads(l) for l in lines]
assert len(recs) == 15
ids = [r["id"] for r in recs]
assert len(set(ids)) == 15, "dup ids"
req = ["id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes"]
for r in recs:
    assert all(k in r for k in req), r["id"]
    assert r["label"] == "injection" and r["source"] == "LLMail-Inject" and r["subset"] == "phase2"
    assert r["text"].startswith("Subject: ") and "\n\n" in r["text"]
    assert len(r["text"]) <= 3000

def norm(t):
    return re.sub(r"\s+", " ", t.lower()).strip()

def shingles(t, k=5):
    w = re.findall(r"\w+", t.lower())
    return {tuple(w[i:i + k]) for i in range(max(1, len(w) - k + 1))}

texts = [r["text"] for r in recs]
assert len({norm(t) for t in texts}) == 15, "exact dup"
mx = (0, None)
for i in range(15):
    for j in range(i + 1, 15):
        a, b = shingles(texts[i]), shingles(texts[j])
        jac = len(a & b) / max(1, len(a | b))
        sm = SequenceMatcher(None, norm(texts[i]), norm(texts[j])).ratio()
        if max(jac, sm) > mx[0]:
            mx = (max(jac, sm), (ids[i], ids[j], round(jac, 3), round(sm, 3)))
print("max pairwise similarity:", mx)
print("teams distinct:", len({r["origin"]["team_id"] for r in recs}))
print("scenarios:", sorted(Counter(r["origin"]["scenario"] for r in recs).items()))
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
print("objective patterns:", Counter(tuple(int(r["origin"]["objectives"][k]) for k in KEYS) for r in recs))
print("lengths:", [len(t) for t in texts])

if "--remote" in sys.argv:
    bad = 0
    for r in recs:
        o = r["origin"]
        url = ("https://datasets-server.huggingface.co/rows?dataset=microsoft/llmail-inject-challenge"
               f"&config=default&split=Phase2&offset={o['row_index']}&length=1")
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "dataset-builder"}), timeout=60) as resp:
            d = json.load(resp)
        row = d["rows"][0]["row"]
        ok = row["RowKey"] == o["RowKey_or_job_id"] and f"Subject: {row['subject']}\n\n{row['body']}" == r["text"]
        bad += not ok
        print(r["id"], o["row_index"], "remote match" if ok else "MISMATCH")
    print("remote mismatches:", bad)
