import json, sys, re
wd = sys.argv[1]
en = {}
for l in open(wd + "/parts_v2/bipia.jsonl", encoding="utf-8"):
    r = json.loads(l)
    if r.get("core") is False and r.get("subset") == "email":
        en[r["id"]] = r
ko = [json.loads(l) for l in open(wd + "/ko_parts/bipia_email_new.jsonl", encoding="utf-8")]
errs = []
print("count", len(ko), "inj", sum(r["label"] == "injection" for r in ko), "ben", sum(r["label"] == "benign" for r in ko))
ids = [r["id"] for r in ko]
if len(set(ids)) != len(ids): errs.append("dup ids")
if [r["pair_id"] for r in ko] != list(en.keys()): errs.append("order/pair mismatch")
# existing KO ids collision
import glob
for fn in glob.glob(wd + "/ko_parts/*.jsonl"):
    if fn.endswith("bipia_email_new.jsonl"): continue
    for l in open(fn, encoding="utf-8"):
        if json.loads(l)["id"] in ids: errs.append("id collision " + fn)
for r in ko:
    e = en[r["pair_id"]]
    t = r["text"]
    for k in ["label", "source", "subset", "origin", "core", "notes"]:
        if r[k] != e[k]: errs.append(r["id"] + " field " + k)
    if r["id"] != r["pair_id"] + "-ko": errs.append(r["id"] + " id fmt")
    if e["label"] == "injection":
        if not r["injected_instruction"] or r["injected_instruction"] not in t: errs.append(r["id"] + " inj not substring")
        if t.count(r["injected_instruction"]) != 1: errs.append(r["id"] + " inj count")
        # position check: start/middle/end
        pos = e["origin"]["position"]
        i = t.index(r["injected_instruction"])
        p = "start" if i == 0 else ("end" if i + len(r["injected_instruction"]) == len(t) else "middle")
        if p != pos: errs.append(r["id"] + f" position {p} vs {pos}")
    else:
        if r["injected_instruction"] is not None: errs.append(r["id"] + " benign inj not null")
    # structure
    if e["text"].count("\n") != t.count("\n"): errs.append(r["id"] + f" newline {e['text'].count(chr(10))} vs {t.count(chr(10))}")
    if e["text"].count("|") != t.count("|"): errs.append(r["id"] + f" pipes {e['text'].count('|')} vs {t.count('|')}")
    for m in ["SUBJECT:", "EMAIL_FROM:", "RECEIVED DATE:", "CONTENT:", "Subject:", "To:"]:
        if e["text"].count(m) != t.count(m): errs.append(r["id"] + " marker " + m)
    # preserved tokens: emails, urls, amounts, card digits, ids
    toks = set(re.findall(r"[\w.+-]+@[\w.-]+|www\.[\w.]+|\$[\d, ]*\d[\d.]*|••\d{4}|\*\*\*\d{4}|\b\d{6,}\w*|in_\w+|\d{2}:\d{2}:\d{2}", e["text"]))
    for tok in toks:
        tok = tok.strip()
        if tok not in t: errs.append(r["id"] + " missing token " + repr(tok))
    # hangul ratio among letters
    letters = [c for c in t if c.isalpha()]
    hang = sum('가' <= c <= '힣' for c in letters)
    r["_hr"] = hang / max(1, len(letters))
print("errors:", errs if errs else "none")
print("hangul ratio min", min(r["_hr"] for r in ko), [ (r["id"], round(r["_hr"],2)) for r in ko if r["_hr"] < 0.5])
# leftover english words
allow = set()
words = {}
for r in ko:
    for w in re.findall(r"[A-Za-z]{3,}", r["text"]):
        words[w] = words.get(w, 0) + 1
print(sorted(words.items(), key=lambda x: -x[1]))
