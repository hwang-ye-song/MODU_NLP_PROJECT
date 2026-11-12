"""Validate parts_v2/enron.jsonl. Usage: validate_enron.py <enron.jsonl> <train.parquet> <parts_dir> [<parts_v2_dir>]"""
import difflib
import glob
import json
import re
import statistics
import sys

import pyarrow.parquet as pq


def ngrams(s, n=5):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def sim(a, b):
    ga, gb = ngrams(a), ngrams(b)
    j = len(ga & gb) / len(ga | gb) if ga and gb else 0.0
    return j, difflib.SequenceMatcher(None, a, b, autojunk=False).ratio()


path, src, parts = sys.argv[1], sys.argv[2], sys.argv[3]
others_dirs = [parts] + sys.argv[4:]
rows = pq.read_table(src).to_pylist()
recs = [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]
assert len(recs) == 40, len(recs)
ids = [r["id"] for r in recs]
assert ids == [f"enron-ben-{i:02d}" for i in range(1, 41)], ids
keys = {"id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes", "core"}
for r in recs:
    assert set(r) == keys, set(r) ^ keys
    assert r["label"] == "benign" and r["source"] == "Enron" and r["subset"] == "enron_email"
    assert r["injected_instruction"] is None and r["core"] is False
    o = r["origin"]
    src_row = rows[o["row_index"]]
    raw = "Subject:" + src_row["subject_line"] + src_row["email_body"]
    assert re.sub(r"\s+", "", raw) == re.sub(r"\s+", "", r["text"]), r["id"]  # whitespace-only changes
    assert r["text"].startswith("Subject: ") and "\n\n" in r["text"]
    assert 200 <= len(r["text"]) <= 3000
    assert not re.search(r"(?i)\b(AI|assistant|chatbot|language model|ignore (previous|prior|all))\b", r["text"]) \
        or r["id"] in {"enron-ben-04"}, r["id"]  # ben-04: human 'The Assistant in each group'
assert len({r["origin"]["row_index"] for r in recs}) == 40
L = sorted(len(r["text"]) for r in recs)
print("ok: 40 records; len min/median/mean/max", L[0], statistics.median(L), round(statistics.mean(L)), L[-1])
print("requests flagged in notes:", sum("human-to-human request" in r["notes"] for r in recs))

mx = (0, 0, None)
for i in range(40):
    for k in range(i + 1, 40):
        j, d = sim(recs[i]["text"], recs[k]["text"])
        if max(j, d) > max(mx[0], mx[1]):
            mx = (j, d, (ids[i], ids[k]))
print("max within-file (jaccard5, difflib):", mx)

others = []
for d in others_dirs:
    for fp in glob.glob(d.rstrip("/\\") + "/*.jsonl"):
        if fp.replace("\\", "/").endswith("parts_v2/enron.jsonl"):
            continue
        for l in open(fp, encoding="utf-8"):
            if l.strip():
                o = json.loads(l)
                others.append((fp.split("/")[-1].split("\\")[-1] + ":" + o["id"], o["text"]))
mx = (0, 0, None)
for r in recs:
    for oid, t in others:
        j, d = sim(r["text"], t)
        if max(j, d) > max(mx[0], mx[1]):
            mx = (j, d, (r["id"], oid))
print(f"max vs {len(others)} other records (jaccard5, difflib):", mx)
assert mx[0] < 0.5 and mx[1] < 0.8
print("VALID")
