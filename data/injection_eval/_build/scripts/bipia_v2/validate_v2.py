"""Validate the BIPIA v2 slice.
Usage: python -X utf8 -I validate_v2.py <out_jsonl> <core_bipia_jsonl> <bipia_repo_dir> <parts_dir>"""
import difflib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

from nltk.tokenize.punkt import PunktSentenceTokenizer

OUT, CORE, REPO, PARTS = sys.argv[1:5]
errs, warn = [], []


def norm(t):
    return re.sub(r"\s+", " ", t).strip().lower()


def grams(t, n=5):
    w = norm(t).split()
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def sim(a, b):
    ga, gb = grams(a), grams(b)
    j = len(ga & gb) / max(1, len(ga | gb))
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    r = sm.ratio() if (sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8) else 0.0
    return j, r


def is_dup(a, b):
    j, r = sim(a, b)
    return j >= 0.5 or r >= 0.8, j, r


raw = open(OUT, encoding="utf-8").read()
lines = raw.split("\n")
if lines[-1] == "":
    lines = lines[:-1]
recs = [json.loads(l) for l in lines]
if len(recs) != 160:
    errs.append(f"expected 160 lines, got {len(recs)}")

core_lines = [l for l in open(CORE, encoding="utf-8").read().split("\n") if l.strip()]
for k, cl in enumerate(core_lines):
    r = dict(recs[k])
    if r.pop("core", None) is not True:
        errs.append(f"line {k}: core flag")
    if json.dumps(r, ensure_ascii=False) != cl:
        errs.append(f"line {k}: core record changed")
for r in recs[len(core_lines):]:
    if r.get("core") is not False:
        errs.append(f"{r['id']}: core flag should be false")
    if list(r.keys()) != ["id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes", "core"]:
        errs.append(f"{r['id']}: keys")
    if list(r["origin"].keys()) != ["url", "commit", "file", "index", "split", "attack_file", "attack_category",
                                    "position", "question"]:
        errs.append(f"{r['id']}: origin keys")

cnt = Counter((r["label"], r["subset"]) for r in recs)
want = {("injection", "email"): 30, ("injection", "table"): 30, ("injection", "code"): 30,
        ("benign", "email"): 20, ("benign", "table"): 25, ("benign", "code"): 25}
if dict(cnt) != want:
    errs.append(f"counts {dict(cnt)}")
ids = [r["id"] for r in recs]
if len(set(ids)) != len(ids):
    errs.append("dup ids")
exp_ids = [f"bipia-inj-{i:02d}" for i in range(1, 91)] + [f"bipia-ben-{i:02d}" for i in range(1, 71)]
if sorted(ids) != sorted(exp_ids):
    errs.append("id numbering")
if len({norm(r["text"]) for r in recs}) != len(recs):
    errs.append("dup texts (normalised)")


def row_of(file, idx):
    with open(os.path.join(REPO, file), encoding="utf-8") as f:
        return json.loads(f.read().split("\n")[idx])


def ctx_of(row):
    c = row["context"]
    return "\n".join(c) if isinstance(c, list) else c


def ins(pos, ctx, a):
    if pos == "start":
        return a + "\n" + ctx
    if pos == "end":
        return ctx + "\n" + a
    rng = random.Random(2023)
    st, _ = rng.sample(list(PunktSentenceTokenizer().span_tokenize(ctx)), k=1)[0]
    if st == 0:
        errs.append("middle at 0")
    return "\n".join([ctx[:st], a, ctx[st:]])


attack_cache = {}
ctx_uses = defaultdict(list)
inj_ctx, ben_ctx = {}, {}
attack_strings = Counter()
for r in recs:
    o = r["origin"]
    row = row_of(o["file"], o["index"])
    ctx = ctx_of(row)
    split = o.get("split") or o["file"].split("/")[-1].split(".")[0]
    if o["file"] != f"benchmark/{r['subset']}/{split}.jsonl":
        errs.append(f"{r['id']}: file/split")
    if r["subset"] != "code" and o["question"] != row["question"]:
        errs.append(f"{r['id']}: question mismatch")
    if r["subset"] == "code" and o["question"] is not None:
        errs.append(f"{r['id']}: code question")
    if len(r["text"]) > 3000:
        errs.append(f"{r['id']}: len {len(r['text'])}")
    if r["label"] == "injection":
        a = r["injected_instruction"]
        if not a or a not in r["text"]:
            errs.append(f"{r['id']}: injected_instruction not in text")
        want_file = "benchmark/code_attack_test.json" if r["subset"] == "code" else "benchmark/text_attack_test.json"
        if o["attack_file"] != want_file:
            warn.append(f"{r['id']}: attack file {o['attack_file']}")
        if o["attack_file"] not in attack_cache:
            attack_cache[o["attack_file"]] = json.load(open(os.path.join(REPO, o["attack_file"]), encoding="utf-8"))
        if a not in attack_cache[o["attack_file"]][o["attack_category"]]:
            errs.append(f"{r['id']}: attack not in category")
        if r["text"] != ins(o["position"], ctx, a):
            errs.append(f"{r['id']}: insertion mismatch ({o['position']})")
        attack_strings[a] += 1
        ctx_uses[(r["subset"], split, o["index"])].append(r)
        inj_ctx[(r["subset"], split, o["index"])] = ctx
    else:
        if r["injected_instruction"] is not None or o["attack_file"] or o["position"] or o["attack_category"]:
            errs.append(f"{r['id']}: benign has attack fields")
        if r["text"] != ctx:
            errs.append(f"{r['id']}: benign text != original context")
        if (r["subset"], split, o["index"]) in ben_ctx:
            errs.append(f"{r['id']}: benign context repeated")
        ben_ctx[(r["subset"], split, o["index"])] = ctx

# context sharing / reuse
if set(inj_ctx) & set(ben_ctx):
    errs.append("context index shared between labels")
inj_norm = {norm(c) for c in inj_ctx.values()}
if any(norm(c) in inj_norm for c in ben_ctx.values()):
    errs.append("identical context text shared between labels")
reused = {k: v for k, v in ctx_uses.items() if len(v) > 1}
for k, v in reused.items():
    if len(v) > 2:
        errs.append(f"context {k} used {len(v)} times")
    if len({x["origin"]["position"] for x in v}) < len(v) or len({x["injected_instruction"] for x in v}) < len(v):
        errs.append(f"context {k} reuse with same position/attack")
    if any(x["core"] for x in v):
        warn.append(f"context {k} reuse touches a core record")
dup_attacks = {a: n for a, n in attack_strings.items() if n > 1}

# cross-label near-duplicates of contexts (same subset)
cross = []
for (s1, _, _), c1 in inj_ctx.items():
    for (s2, _, _), c2 in ben_ctx.items():
        if s1 != s2:
            continue
        d, j, rr = is_dup(c1, c2)
        if d:
            cross.append((round(j, 2), round(rr, 2)))
if cross:
    errs.append(f"{len(cross)} injection/benign context near-duplicate pairs: {cross[:5]}")

# within-output text near-duplicates (same subset)
within = Counter()
within_examples = defaultdict(list)
for i in range(len(recs)):
    for k in range(i + 1, len(recs)):
        a, b = recs[i], recs[k]
        if a["subset"] != b["subset"]:
            continue
        d, j, rr = is_dup(a["text"], b["text"])
        if d:
            ka = (a["subset"], a["origin"].get("split") or "test", a["origin"]["index"])
            kb = (b["subset"], b["origin"].get("split") or "test", b["origin"]["index"])
            kind = "same-context reuse" if ka == kb else f"{a['label']}/{b['label']} {a['subset']}"
            within[kind] += 1
            within_examples[kind].append((a["id"], b["id"], round(j, 2), round(rr, 2)))

# against other parts
other = []
for fn in sorted(os.listdir(PARTS)):
    if fn.endswith(".jsonl") and fn != "bipia.jsonl":
        for l in open(os.path.join(PARTS, fn), encoding="utf-8"):
            if l.strip():
                other.append(json.loads(l))
ext = []
for r in recs:
    for o in other:
        d, j, rr = is_dup(r["text"], o["text"])
        if d:
            ext.append((r["id"], o["id"], round(j, 2), round(rr, 2)))
if ext:
    errs.append(f"near-duplicates vs other parts: {ext[:5]}")

print("counts", {f"{l}/{s}": n for (l, s), n in sorted(cnt.items())})
for t in ["email", "table", "code"]:
    inj = [r for r in recs if r["subset"] == t and r["label"] == "injection"]
    print(t, "positions", dict(Counter(r["origin"]["position"] for r in inj)))
    cc = Counter(r["origin"]["attack_category"] for r in inj)
    print(t, "categories", len(cc), "min/max per cat", min(cc.values()), max(cc.values()))
    pc = Counter((r["origin"]["attack_category"], r["origin"]["position"]) for r in inj)
    print(t, "max same (cat,pos) within subset", max(pc.values()))
    sp = Counter((r["label"], r["origin"].get("split") or "test") for r in recs if r["subset"] == t)
    print(t, "splits", dict(sp))
tc = Counter(r["origin"]["attack_category"] for r in recs if r["label"] == "injection" and r["subset"] != "code")
print("text categories over email+table", len(tc), sorted(set(tc.values())))
print("attack files", dict(Counter(r["origin"]["attack_file"] for r in recs if r["label"] == "injection")))
print("reused injection contexts", len(reused), {k: [x["id"] for x in v] for k, v in reused.items()})
print("duplicate attack strings", len(dup_attacks))
print("within-output strict near-dup pairs", dict(within))
for kind, ex in within_examples.items():
    print("  ", kind, ex[:6])
lens = sorted(len(r["text"]) for r in recs)
for lab in ["injection", "benign"]:
    l = sorted(len(r["text"]) for r in recs if r["label"] == lab)
    print(lab, "len min/median/max", l[0], l[len(l) // 2], l[-1])
for w in warn:
    print("WARN", w)
print("ERRORS:" if errs else "OK: all checks passed")
for e in errs:
    print("  ", e)
