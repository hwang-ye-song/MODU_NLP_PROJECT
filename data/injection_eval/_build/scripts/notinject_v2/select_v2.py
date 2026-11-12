"""Expand NotInject benign slice from 10 core to 25 (one 9 / two 8 / three 8).

usage: python -X utf8 -I select_v2.py <download_dir> <core_jsonl> <parts_dir> <output_jsonl> [exclude_rows]

exclude_rows: optional comma list "split:row_idx" rejected after manual review (re-sampled).
"""
import collections
import difflib
import json
import os
import random
import re
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")
DL, CORE, PARTS, OUT = sys.argv[1:5]
EXCLUDE = set(sys.argv[5].split(",")) if len(sys.argv) > 5 and sys.argv[5] else set()

REVISION = "847ae76cf8fea5ed325429e569ae8cfef022d2e0"
URL = "https://huggingface.co/datasets/leolee99/NotInject"
CATS = ["Common Queries", "Technique Queries", "Virtual Creation"]
# target totals per split x category (core included). one: 3/3/3; two: Virtual has only 4 rows -> 2;
# three: Common gets 2 so overall category totals are 8/9/8.
TARGET = {
    "NotInject_one": {"Common Queries": 3, "Technique Queries": 3, "Virtual Creation": 3},
    "NotInject_two": {"Common Queries": 3, "Technique Queries": 3, "Virtual Creation": 2},
    "NotInject_three": {"Common Queries": 2, "Technique Queries": 3, "Virtual Creation": 3},
}


def is_english(text):
    for ch in text:
        if ord(ch) < 128:
            continue
        cat = unicodedata.category(ch)
        if cat[0] in ("S", "P", "Z"):
            continue
        if cat[0] == "L" and "LATIN" in unicodedata.name(ch, ""):
            continue
        return False
    return True


def grams(t, n=5):
    w = re.findall(r"\w+", t.lower())
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def too_similar(a, b):
    if difflib.SequenceMatcher(None, a.lower(), b.lower()).ratio() >= 0.8:
        return True
    ga, gb = grams(a), grams(b)
    return len(ga & gb) / max(1, len(ga | gb)) >= 0.5


core_lines = open(CORE, encoding="utf-8").read().splitlines()
core = [json.loads(l) for l in core_lines]
assert len(core) == 10
used = {(r["origin"]["split"], r["origin"]["row_index"]) for r in core}

# all other texts in WD/parts (for near-duplicate check), plus core texts
other_texts = []
for fn in sorted(os.listdir(PARTS)):
    if fn.endswith(".jsonl"):
        for l in open(os.path.join(PARTS, fn), encoding="utf-8"):
            if l.strip():
                other_texts.append(json.loads(l)["text"])

random.seed(42)
chosen = []
accepted_texts = list(other_texts)
for split in TARGET:
    rows = json.load(open(os.path.join(DL, split + ".json"), encoding="utf-8"))
    have = collections.Counter(r["origin"]["category"] for r in core if r["subset"] == split)
    pool = collections.defaultdict(list)
    for r in sorted(rows, key=lambda r: r["row_idx"]):
        if r["category"] == "Multilingual" or not is_english(r["prompt"]):
            continue
        if (split, r["row_idx"]) in used or "%s:%d" % (split, r["row_idx"]) in EXCLUDE:
            continue
        pool[r["category"]].append(r)
    for c in CATS:
        need = TARGET[split][c] - have[c]
        cands = pool[c][:]
        random.shuffle(cands)
        got = 0
        for r in cands:
            if got == need:
                break
            if any(too_similar(r["prompt"], t) for t in accepted_texts):
                print("skip near-dup", split, r["row_idx"], r["prompt"][:80])
                continue
            accepted_texts.append(r["prompt"])
            chosen.append((split, r))
            got += 1
        assert got == need, (split, c, got, need)

# order: by split order then category then row
order = {s: i for i, s in enumerate(TARGET)}
chosen.sort(key=lambda x: (order[x[0]], CATS.index(x[1]["category"]), x[1]["row_idx"]))

records = []
for i, (split, r) in enumerate(chosen, 11):
    missing = [w for w in r["word_list"] if w.lower() not in r["prompt"].lower()]
    notes = ""
    if missing:
        notes = "trigger word(s) %s appear only as an inflected/variant form in the text" % missing
    records.append({
        "id": "notinject-ben-%02d" % i,
        "label": "benign",
        "source": "NotInject",
        "subset": split,
        "text": r["prompt"],
        "injected_instruction": None,
        "origin": {"url": URL, "revision": REVISION, "split": split, "row_index": r["row_idx"],
                   "category": r["category"], "trigger_words": r["word_list"]},
        "notes": notes,
        "core": False,
    })

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for l in core_lines:
        # keep core record content unchanged, append "core": true
        rec = json.loads(l)
        rec["core"] = True
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# ---- validation (re-read from disk) ----
lines = open(OUT, encoding="utf-8").read().splitlines()
recs = [json.loads(l) for l in lines]
assert len(recs) == 25, len(recs)
assert len({r["id"] for r in recs}) == 25
assert [r["id"] for r in recs] == ["notinject-ben-%02d" % i for i in range(1, 26)]
for l, r in zip(core_lines, recs[:10]):
    d = dict(r)
    assert d.pop("core") is True
    assert json.dumps(d, ensure_ascii=False) == l  # byte-identical apart from the added key
assert all(r["core"] is False for r in recs[10:])
assert all(r["label"] == "benign" and r["injected_instruction"] is None for r in recs)
splits = collections.Counter(r["subset"] for r in recs)
assert splits == {"NotInject_one": 9, "NotInject_two": 8, "NotInject_three": 8}, splits
src = {s: {x["row_idx"]: x for x in json.load(open(os.path.join(DL, s + ".json"), encoding="utf-8"))}
       for s in TARGET}
for r in recs:
    o = src[r["origin"]["split"]][r["origin"]["row_index"]]
    assert o["prompt"] == r["text"] and o["word_list"] == r["origin"]["trigger_words"]
    assert o["category"] != "Multilingual" and is_english(r["text"])
    assert len(o["word_list"]) == {"NotInject_one": 1, "NotInject_two": 2, "NotInject_three": 3}[r["subset"]]
texts = [r["text"] for r in recs]
for i in range(len(texts)):
    for j in range(i + 1, len(texts)):
        assert not too_similar(texts[i], texts[j]), (i, j)
    for t in other_texts:
        if t != texts[i]:
            assert not too_similar(texts[i], t), (i, t[:60])
print("OK", dict(splits))
print("by split x category:", sorted(collections.Counter((r["subset"], r["origin"]["category"]) for r in recs).items()))
print("by category:", dict(collections.Counter(r["origin"]["category"] for r in recs)))
for r in recs[10:]:
    print(r["id"], r["subset"], r["origin"]["row_index"], r["origin"]["category"], r["origin"]["trigger_words"],
          "|", r["text"], "|", r["notes"])
