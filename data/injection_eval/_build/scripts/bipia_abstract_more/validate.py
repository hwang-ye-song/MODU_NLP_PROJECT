"""Validate bipia_abstract_more.jsonl.
Usage: python -X utf8 -I validate.py <out_jsonl> <bipia_repo_dir> <abstract_ctx_dir> <parts_dir> <extra_jsonl>"""
import difflib
import glob
import json
import os
import random
import re
import statistics
import sys
from collections import Counter, defaultdict

from nltk.tokenize.punkt import PunktSentenceTokenizer

OUT, REPO, CTX, PARTS, EXTRA = sys.argv[1:6]
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


def read_jsonl(p):
    return [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]


raw = open(OUT, encoding="utf-8").read()
assert raw.endswith("\n") and "\r" not in raw
recs = [json.loads(l) for l in raw.split("\n")[:-1]]
ids = [r["id"] for r in recs]
exp = [f"bipia-abs-inj-{i:02d}" for i in range(41, 71)] + [f"bipia-abs-ben-{i:02d}" for i in range(41, 71)]
if ids != exp:
    errs.append("ids")
keys = ["id", "label", "source", "subset", "doc_type", "text", "injected_instruction", "origin", "notes", "core"]
ctx_rows = {s: read_jsonl(os.path.join(CTX, f"{s}.jsonl")) for s in ["test", "train"]}
meta = {s: read_jsonl(os.path.join(CTX, f"{s}_meta.jsonl")) for s in ["test", "train"]}
atk = {f: json.load(open(os.path.join(REPO, f), encoding="utf-8"))
       for f in ["benchmark/text_attack_test.json", "benchmark/text_attack_train.json"]}
prev = read_jsonl(os.path.join(PARTS, "bipia_abstract.jsonl"))
prev_keys = {(r["origin"]["split"], r["origin"]["index"]) for r in prev}
prev_xsum = {r["origin"]["xsum_id"] for r in prev}
used = set()
all_ids = set()
for f in sorted(glob.glob(os.path.join(PARTS, "*.jsonl"))):
    if os.path.abspath(f) == os.path.abspath(OUT):
        continue
    for r in read_jsonl(f):
        all_ids.add(r["id"])
        if os.path.basename(f).startswith("bipia") and r.get("injected_instruction"):
            used.add(r["injected_instruction"])
if set(ids) & all_ids:
    errs.append(f"id collision {set(ids) & all_ids}")
contexts = {}
for r in recs:
    if list(r.keys()) != keys:
        errs.append(f"{r['id']} keys")
    if (r["source"], r["subset"], r["doc_type"], r["core"]) != ("BIPIA", "abstract", "news_article", False):
        errs.append(f"{r['id']} fields")
    o = r["origin"]
    ctx = ctx_rows[o["split"]][o["index"]]["context"]
    m = meta[o["split"]][o["index"]]
    if (m["row_index"], m["xsum_id"], m["xsum_split"]) != (o["row_index"], o["xsum_id"], o["dataset_split"]):
        errs.append(f"{r['id']} meta")
    if (o["split"], o["index"]) in prev_keys or o["xsum_id"] in prev_xsum:
        errs.append(f"{r['id']} article already used in bipia_abstract.jsonl")
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
            errs.append(f"{r['id']} attack string already used in a bipia part file")
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
if len({(r["origin"]["split"], r["origin"]["index"]) for r in recs}) != 60:
    errs.append("an article is used twice")
if len({r["origin"]["xsum_id"] for r in recs}) != 60:
    errs.append("an xsum id is used twice")
inj = [r for r in recs if r["label"] == "injection"]
ben = [r for r in recs if r["label"] == "benign"]
attacks = [r["injected_instruction"] for r in inj]
if len(set(attacks)) != len(attacks):
    errs.append("attack string repeated")
ctx_list = list(contexts.items())
mx = (0, 0, 0)
for i in range(len(ctx_list)):
    for j in range(i + 1, len(ctx_list)):
        jj, w, c = check_pair(f"{ctx_list[i][0]}~{ctx_list[j][0]}", ctx_list[i][1], ctx_list[j][1])
        mx = (max(mx[0], jj), max(mx[1], w), max(mx[2], c or 0))
info.append(f"within-slice max jac={mx[0]:.3f} wratio={mx[1]:.3f} cratio={mx[2]:.3f}")
ext = []
for f in sorted(glob.glob(os.path.join(PARTS, "*.jsonl"))) + [EXTRA]:
    if os.path.abspath(f) == os.path.abspath(OUT):
        continue
    for e in read_jsonl(f):
        ext.append((os.path.basename(f), e))
mx = (0, 0, 0)
for r in recs:
    for fn, e in ext:
        jj, w, c = check_pair(f"{r['id']}~{fn}:{e['id']}", r["text"], e["text"])
        mx = (max(mx[0], jj), max(mx[1], w), max(mx[2], c or 0))
info.append(f"vs {len(ext)} external records max jac={mx[0]:.3f} wratio={mx[1]:.3f} cratio={mx[2]:.3f}")
info.append(f"labels {Counter(r['label'] for r in recs)}")
info.append(f"attack files {Counter(r['origin']['attack_file'] for r in inj)}")
info.append(f"categories {sorted(Counter(r['origin']['attack_category'] for r in inj).values())}")
info.append(f"positions {Counter(r['origin']['position'] for r in inj)}")
old_pos = defaultdict(set)
for r in prev:
    if r["label"] == "injection":
        old_pos[r["origin"]["attack_category"]].add(r["origin"]["position"])
for c, n in Counter(r["origin"]["attack_category"] for r in inj).items():
    ps = [r["origin"]["position"] for r in inj if r["origin"]["attack_category"] == c]
    if len(set(ps)) != len(ps):
        errs.append(f"category {c} repeats a position")
    if old_pos[c] | set(ps) != {"start", "middle", "end"}:
        errs.append(f"category {c} does not cover all positions with the earlier slice")
info.append(f"context splits inj {Counter(r['origin']['split'] for r in inj)} ben {Counter(r['origin']['split'] for r in ben)}")
for lab, rs in [("inj", inj), ("ben", ben)]:
    L = [len(r["text"]) for r in rs]
    info.append(f"{lab} text len min {min(L)} median {statistics.median(L)} mean {statistics.mean(L):.0f} max {max(L)}")
print("\n".join(info))
print("ERRORS:" if errs else "OK, no errors", *errs, sep="\n")
