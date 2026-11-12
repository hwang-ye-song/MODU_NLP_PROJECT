"""Inventory of hidden strings (comments, attributes, hidden elements) in yes/no rows; counts per string
and how many 'no' rows also contain the same string (to separate payloads from benign distractors)."""
import json, re, sys, collections, os
sys.path.insert(0, os.path.dirname(__file__))
from common import english_ok, ARTIFACT
bs = json.load(open(sys.argv[1], encoding="utf-8"))
used = {json.loads(l)["origin"].get("row_index") for l in open(sys.argv[2], encoding="utf-8")}
maxlen = int(sys.argv[3])
HID = [re.compile(r"<!--(.*?)-->", re.S),
       re.compile(r'\b(?:title|data-[\w-]+|aria-label|alt|value|content|placeholder)="([^"]{25,})"'),
       re.compile(r'<(?:div|span|p)[^>]*style="[^"]*(?:display:\s*none|opacity:\s*0|left:\s*-9999px|font-size:\s*0|visibility:\s*hidden|color:\s*(?:white|#fff(?:fff)?)\b)[^"]*"[^>]*>(.*?)</(?:div|span|p)>', re.S)]
def strings(h):
    out = []
    for p in HID:
        for m in p.finditer(h):
            s = re.sub(r"\s+", " ", m.group(1)).strip()
            if len(s.split()) >= 5 and not s.startswith(("<", "{", ".")) and "{" not in s[:40]:
                out.append(s)
    return out
cnt = {"yes": collections.Counter(), "no": collections.Counter()}
rows = collections.defaultdict(list)
for x in bs:
    h = x["content"]
    if len(h) > maxlen or not english_ok(h) or ARTIFACT.search(h):
        continue
    for s in set(strings(h)):
        cnt[x["label"]][s] += 1
        if x["label"] == "yes" and x["row_index"] not in used:
            rows[s].append(x["row_index"])
for s, c in cnt["yes"].most_common():
    print(f"{c:3d} no={cnt['no'][s]:3d} new={len(rows[s]):3d} | {s[:230]} | {rows[s][:8]}")
