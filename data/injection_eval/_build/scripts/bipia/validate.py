"""Validate bipia.jsonl. Usage: python -I validate.py <out_jsonl> <bipia_repo_dir>"""
import json
import os
import re
import sys
from collections import Counter

OUT, REPO = sys.argv[1], sys.argv[2]
errs = []
with open(OUT, encoding="utf-8") as f:
    raw = f.read()
lines = raw.split("\n")
if lines and lines[-1] == "":
    lines = lines[:-1]
if len(lines) != 35:
    errs.append(f"expected 35 lines, got {len(lines)}")
recs = [json.loads(l) for l in lines]

keys = ["id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes"]
okeys = ["url", "commit", "file", "index", "attack_file", "attack_category", "position", "question"]
for r in recs:
    if list(r.keys()) != keys:
        errs.append(f"{r.get('id')}: keys {list(r.keys())}")
    if list(r["origin"].keys()) != okeys:
        errs.append(f"{r['id']}: origin keys {list(r['origin'].keys())}")
    if r["source"] != "BIPIA":
        errs.append(f"{r['id']}: source")

cnt = Counter((r["label"], r["subset"]) for r in recs)
print("counts", dict(cnt))
want = {("injection", "email"): 7, ("injection", "table"): 7, ("injection", "code"): 6,
        ("benign", "email"): 5, ("benign", "table"): 5, ("benign", "code"): 5}
if dict(cnt) != want:
    errs.append(f"counts {dict(cnt)}")

ids = [r["id"] for r in recs]
if len(set(ids)) != len(ids):
    errs.append("dup ids")
texts = [re.sub(r"\s+", " ", r["text"]).strip().lower() for r in recs]
if len(set(texts)) != len(texts):
    errs.append("dup texts")

# Reconstruct original contexts from source files and check.
def ctx_of(file, idx):
    with open(os.path.join(REPO, file), encoding="utf-8") as f:
        row = json.loads(f.read().split("\n")[idx])
    c = row["context"]
    return "\n".join(c) if isinstance(c, list) else c, row

inj_ctx, ben_ctx = set(), set()
for r in recs:
    o = r["origin"]
    ctx, row = ctx_of(o["file"], o["index"])
    if r["subset"] != "code" and o["question"] != row["question"]:
        errs.append(f"{r['id']}: question mismatch")
    if r["label"] == "injection":
        a = r["injected_instruction"]
        if not a or a not in r["text"]:
            errs.append(f"{r['id']}: injected_instruction not in text")
        attacks = json.load(open(os.path.join(REPO, o["attack_file"]), encoding="utf-8"))
        if a not in attacks[o["attack_category"]]:
            errs.append(f"{r['id']}: attack not in category")
        if o["position"] == "start" and r["text"] != a + "\n" + ctx:
            errs.append(f"{r['id']}: start mismatch")
        if o["position"] == "end" and r["text"] != ctx + "\n" + a:
            errs.append(f"{r['id']}: end mismatch")
        if o["position"] == "middle":
            rebuilt = r["text"].replace("\n" + a + "\n", "", 1)
            if rebuilt != ctx:
                errs.append(f"{r['id']}: middle mismatch")
        inj_ctx.add(ctx)
    else:
        if r["injected_instruction"] is not None or o["attack_file"] or o["position"]:
            errs.append(f"{r['id']}: benign has attack fields")
        if r["text"] != ctx:
            errs.append(f"{r['id']}: benign text != original context")
        ben_ctx.add(ctx)
    if len(r["text"]) > 3000:
        errs.append(f"{r['id']}: len {len(r['text'])}")
if inj_ctx & ben_ctx:
    errs.append("context shared between labels")
if len(ben_ctx) != 15 or len(inj_ctx) != 20:
    errs.append(f"distinct ctx inj={len(inj_ctx)} ben={len(ben_ctx)}")

for r in recs:
    o = r["origin"]
    print(r["id"], r["subset"], o["file"].split("/")[1], o["index"], len(r["text"]),
          o["position"], o["attack_category"], "|", (o["question"] or "")[:60])
print("positions", Counter(r["origin"]["position"] for r in recs if r["label"] == "injection"))
print("ERRORS:" if errs else "OK: all checks passed")
for e in errs:
    print("  ", e)
