"""usage: python -X utf8 -I validate_01_25.py <en_jsonl> <ko_jsonl>"""
import json
import re
import sys

en_path, ko_path = sys.argv[1:3]
en = {json.loads(l)["id"]: json.loads(l) for l in open(en_path, encoding="utf-8") if l.strip()}
ko = [json.loads(l) for l in open(ko_path, encoding="utf-8") if l.strip()]
print("records:", len(ko))
ids = [r["id"] for r in ko]
assert len(set(ids)) == len(ids), "dup ids"
problems = []
for r in ko:
    e = en.get(r["pair_id"])
    if e is None:
        problems.append((r["id"], "pair missing")); continue
    if r["id"] != r["pair_id"] + "-ko": problems.append((r["id"], "id form"))
    for k in ("label", "source", "subset", "origin", "core", "notes"):
        if r[k] != e[k]: problems.append((r["id"], "field " + k))
    if r["lang"] != "ko": problems.append((r["id"], "lang"))
    if r["injected_instruction"] is not None: problems.append((r["id"], "inj not null"))
    t = r["text"]
    if t.count("\n") != e["text"].count("\n"): problems.append((r["id"], "line count"))
    if not t.startswith("Subject: "): problems.append((r["id"], "subject marker"))
    # Hangul share among letters
    hang = len(re.findall(r"[가-힣]", t))
    lat = len(re.findall(r"[A-Za-z]", t))
    ratio = hang / max(1, hang + lat)
    # preserved tokens: emails, digit-bearing tokens
    toks = set(re.findall(r"[\w.+-]+@[\w.-]+", e["text"]))
    toks |= set(re.findall(r"\(?\d[\d/().:,x$KkmM-]*\d\)?|\d", e["text"]))
    missing = [tk for tk in toks if tk.strip("().,:") not in t]
    # long English runs (>=4 consecutive Latin words)
    runs = re.findall(r"(?:[A-Za-z][A-Za-z'.&,-]*\s+){4,}[A-Za-z][A-Za-z'.&-]*", t.split("\n", 1)[1])
    print(f"{r['id']:16s} hangul_ratio={ratio:.2f} missing_tokens={missing} english_runs={runs}")
print("problems:", problems)
