"""Select 10 benign NotInject samples (4/3/3 from one/two/three-trigger splits), write JSONL, validate.

usage: python -I select_notinject.py <download_dir> <output_jsonl>
"""
import collections
import json
import os
import random
import sys
import unicodedata

sys.stdout.reconfigure(encoding="utf-8")
DL, OUT = sys.argv[1], sys.argv[2]

REVISION = "847ae76cf8fea5ed325429e569ae8cfef022d2e0"  # main @ 2025-04-04T02:09:26Z
URL = "https://huggingface.co/datasets/leolee99/NotInject"
PLAN = [("NotInject_one", 4), ("NotInject_two", 3), ("NotInject_three", 3)]


def is_english(text):
    """Reject any letter/mark outside Latin script (CJK, Cyrillic, ...); emoji/symbols/punct allowed."""
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


random.seed(42)
selected = []
seen_texts = set()
for split, n in PLAN:
    rows = json.load(open(os.path.join(DL, split + ".json"), encoding="utf-8"))
    pool = collections.defaultdict(list)
    for r in sorted(rows, key=lambda r: r["row_idx"]):
        if r["category"] == "Multilingual" or not is_english(r["prompt"]):
            continue
        pool[r["category"]].append(r)
    cats = sorted(pool)
    quota = {c: n // len(cats) for c in cats}
    for c in random.sample(cats, n % len(cats)):
        quota[c] += 1
    for c in cats:
        cands = [r for r in pool[c] if r["prompt"].strip().lower() not in seen_texts]
        for r in random.sample(cands, quota[c]):
            seen_texts.add(r["prompt"].strip().lower())
            selected.append((split, r))

records = []
for i, (split, r) in enumerate(selected, 1):
    missing = [w for w in r["word_list"] if w.lower() not in r["prompt"].lower()]
    notes = ""
    if missing:
        notes = "trigger word(s) %s appear only as an inflected form in the text" % missing
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
    })

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for rec in records:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

# ---- validation (re-read from disk) ----
lines = open(OUT, encoding="utf-8").read().splitlines()
assert len(lines) == 10, len(lines)
recs = [json.loads(l) for l in lines]
assert len({r["id"] for r in recs}) == 10
assert len({r["text"] for r in recs}) == 10
assert all(r["label"] == "benign" and r["injected_instruction"] is None for r in recs)
splits = collections.Counter(r["subset"] for r in recs)
assert splits == {"NotInject_one": 4, "NotInject_two": 3, "NotInject_three": 3}, splits
src = {s: {x["row_idx"]: x for x in json.load(open(os.path.join(DL, s + ".json"), encoding="utf-8"))}
       for s, _ in PLAN}
for r in recs:
    o = src[r["origin"]["split"]][r["origin"]["row_index"]]
    assert o["prompt"] == r["text"] and o["word_list"] == r["origin"]["trigger_words"]
    assert len(o["word_list"]) == {"NotInject_one": 1, "NotInject_two": 2, "NotInject_three": 3}[r["subset"]]
print("OK", dict(splits))
print("by category:", dict(collections.Counter(r["origin"]["category"] for r in recs)))
print("by split x category:", dict(collections.Counter((r["subset"], r["origin"]["category"]) for r in recs)))
for r in recs:
    print(r["id"], r["subset"], r["origin"]["row_index"], r["origin"]["category"], r["origin"]["trigger_words"],
          "|", r["text"], "|", r["notes"])
