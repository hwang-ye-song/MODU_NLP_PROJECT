"""Validate the BIPIA abstract slice.
Usage: python -X utf8 -I validate.py <out_jsonl> <bipia_repo_dir> <abstract_ctx_dir> <used_bipia_jsonl> <parts_dir>[,...]"""
import difflib
import glob
import json
import os
import random
import re
import statistics
import sys
from collections import Counter

from nltk.tokenize.punkt import PunktSentenceTokenizer

OUT, REPO, CTX, USED, PARTS = sys.argv[1:6]
errs, info = [], []


def norm(t):
    return re.sub(r"\s+", " ", t).strip().lower()


def grams(t, n=5):
    w = norm(t).split()
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def jac(a, b):
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb))


def wratio(a, b):
    sm = difflib.SequenceMatcher(None, norm(a).split(), norm(b).split(), autojunk=False)
    return sm.ratio() if sm.real_quick_ratio() >= 0.5 and sm.quick_ratio() >= 0.5 else 0.0


def cratio(a, b):
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


def check_pair(tag, a, b):
    j, w = jac(a, b), wratio(a, b)
    c = cratio(a, b) if w >= 0.5 else None
    if j >= 0.5 or w >= 0.8 or (c is not None and c >= 0.8):
        errs.append(f"near-dup {tag}: jac={j:.2f} wratio={w:.2f} cratio={c}")
    return j, w, c


def insert(ctx, atk, pos):
    if pos == "end":
        return "\n".join([ctx, atk])
    if pos == "start":
        return "\n".join([atk, ctx])
    rng = random.Random(2023)
    spans = list(PunktSentenceTokenizer().span_tokenize(ctx))
    s, _ = rng.sample(spans, k=1)[0]
    if s == 0:
        errs.append("middle insertion at char 0")
    return "\n".join([ctx[:s], atk, ctx[s:]])


raw = open(OUT, encoding="utf-8").read()
assert raw.endswith("\n") and "\r" not in raw
recs = [json.loads(l) for l in raw.split("\n")[:-1]]
ids = [r["id"] for r in recs]
exp = [f"bipia-abs-inj-{i:02d}" for i in range(1, 41)] + [f"bipia-abs-ben-{i:02d}" for i in range(1, 41)]
if ids != exp:
    errs.append("ids")
keys = ["id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes", "core"]
ctx_rows = {s: [json.loads(l) for l in open(os.path.join(CTX, f"{s}.jsonl"), encoding="utf-8")] for s in ["test", "train"]}
meta = {s: [json.loads(l) for l in open(os.path.join(CTX, f"{s}_meta.jsonl"), encoding="utf-8")] for s in ["test", "train"]}
atk = {f: json.load(open(os.path.join(REPO, f), encoding="utf-8"))
       for f in ["benchmark/text_attack_test.json", "benchmark/text_attack_train.json"]}
used = {json.loads(l).get("injected_instruction") for l in open(USED, encoding="utf-8") if l.strip()}
contexts = {}
for r in recs:
    if list(r.keys()) != keys:
        errs.append(f"{r['id']} keys")
    if r["source"] != "BIPIA" or r["subset"] != "abstract" or r["core"] is not False:
        errs.append(f"{r['id']} fields")
    o = r["origin"]
    ctx = ctx_rows[o["split"]][o["index"]]["context"]
    m = meta[o["split"]][o["index"]]
    if (m["row_index"], m["xsum_id"], m["xsum_split"]) != (o["row_index"], o["xsum_id"], o["dataset_split"]):
        errs.append(f"{r['id']} meta")
    if len(r["text"]) > 3000:
        errs.append(f"{r['id']} too long")
    contexts[r["id"]] = ctx
    if r["label"] == "injection":
        a = r["injected_instruction"]
        if a not in r["text"] or r["text"].count(a) != 1:
            errs.append(f"{r['id']} instruction not a unique substring")
        if atk[o["attack_file"]][o["attack_category"]][o["attack_index"]] != a:
            errs.append(f"{r['id']} attack mismatch")
        if a in used:
            errs.append(f"{r['id']} attack string already used in bipia.jsonl")
        if insert(ctx, a, o["position"]) != r["text"]:
            errs.append(f"{r['id']} insertion not reproducible")
    else:
        if r["injected_instruction"] is not None or r["text"] != ctx or o["attack_file"] is not None:
            errs.append(f"{r['id']} benign fields")
        for f in atk.values():
            for items in f.values():
                for s in items:
                    if s in r["text"]:
                        errs.append(f"{r['id']} contains an attack string")
if len({(r["origin"]["split"], r["origin"]["index"]) for r in recs}) != 80:
    errs.append("an article is used twice")
inj = [r for r in recs if r["label"] == "injection"]
ben = [r for r in recs if r["label"] == "benign"]
attacks = [r["injected_instruction"] for r in inj]
if len(set(attacks)) != len(attacks):
    errs.append("attack string repeated")
# near-dups within slice (contexts) and against all part files
ctx_list = list(contexts.items())
mx = (0, 0, 0)
for i in range(len(ctx_list)):
    for j in range(i + 1, len(ctx_list)):
        jj, w, c = check_pair(f"{ctx_list[i][0]}~{ctx_list[j][0]}", ctx_list[i][1], ctx_list[j][1])
        mx = (max(mx[0], jj), max(mx[1], w), max(mx[2], c or 0))
info.append(f"within-slice max jac={mx[0]:.3f} wratio={mx[1]:.3f} cratio={mx[2]:.3f}")
ext = []
for d in PARTS.split(","):
    for f in sorted(glob.glob(os.path.join(d, "*.jsonl"))):
        if os.path.abspath(f) == os.path.abspath(OUT):
            continue
        for line in open(f, encoding="utf-8"):
            if line.strip():
                ext.append((os.path.basename(f), json.loads(line)))
mx = (0, 0, 0)
for r in recs:
    for fn, e in ext:
        jj, w, c = check_pair(f"{r['id']}~{fn}:{e['id']}", r["text"], e["text"])
        mx = (max(mx[0], jj), max(mx[1], w), max(mx[2], c or 0))
info.append(f"vs {len(ext)} part records max jac={mx[0]:.3f} wratio={mx[1]:.3f} cratio={mx[2]:.3f}")

info.append(f"labels {Counter(r['label'] for r in recs)}")
info.append(f"attack files {Counter(r['origin']['attack_file'] for r in inj)}")
info.append(f"categories {sorted(Counter(r['origin']['attack_category'] for r in inj).values())}")
info.append(f"positions {Counter(r['origin']['position'] for r in inj)}")
info.append(f"positions test-file {Counter(r['origin']['position'] for r in inj if 'test' in r['origin']['attack_file'])}")
for c, n in Counter(r["origin"]["attack_category"] for r in inj).items():
    ps = [r["origin"]["position"] for r in inj if r["origin"]["attack_category"] == c]
    if len(set(ps)) != len(ps):
        errs.append(f"category {c} repeats a position")
info.append(f"context splits inj {Counter(r['origin']['split'] for r in inj)} ben {Counter(r['origin']['split'] for r in ben)}")
for lab, rs in [("inj", inj), ("ben", ben)]:
    L = [len(r["text"]) for r in rs]
    info.append(f"{lab} text len min {min(L)} median {statistics.median(L)} mean {statistics.mean(L):.0f} max {max(L)}")
print("\n".join(info))
print("ERRORS:" if errs else "OK, no errors", *errs, sep="\n")
