"""Rebuild BIPIA's abstract (summarization) context files from XSum parquet, replicating
benchmark/abstract/process.py without running it:
    ds = load_dataset("xsum"); ds[split].select(index.json[split]);
    {"ideal": summary, "context": document} written with jsonlines (ensure_ascii=False, "\n").
Then checks the md5 values listed in benchmark/abstract/md5.txt.

Usage: python -X utf8 -I extract.py <bipia_repo_dir> <xsum_parquet_dir> <out_dir>
Writes <out_dir>/test.jsonl, train.jsonl (BIPIA format) and test_meta.jsonl, train_meta.jsonl
(line -> xsum split, row_index, xsum id).
"""
import hashlib
import json
import os
import sys

import pyarrow.parquet as pq

REPO, PQ_DIR, OUT = sys.argv[1:4]
index = json.load(open(os.path.join(REPO, "benchmark/abstract/index.json"), encoding="utf-8"))
md5_old = {}
for line in open(os.path.join(REPO, "benchmark/abstract/md5.txt"), encoding="utf-8"):
    if line.strip():
        h, name = line.strip().split("  ")
        md5_old[name] = h

for split in ["test", "train"]:
    t = pq.read_table(os.path.join(PQ_DIR, f"{split}-00000-of-00001.parquet"))
    docs = t.column("document").to_pylist()
    sums = t.column("summary").to_pylist()
    ids = t.column("id").to_pylist()
    print(split, "rows", len(docs))
    lines, meta = [], []
    for k, i in enumerate(index[split]):
        lines.append(json.dumps({"ideal": sums[i], "context": docs[i]}, ensure_ascii=False))
        meta.append(json.dumps({"line": k, "xsum_split": split, "row_index": i, "xsum_id": ids[i]}))
    data = ("\n".join(lines) + "\n").encode("utf-8")
    h = hashlib.md5(data).hexdigest()
    h_crlf = hashlib.md5(data.replace(b"\n", b"\r\n")).hexdigest()
    print(split, "md5", h, "crlf", h_crlf, "expected", md5_old[f"{split}.jsonl"],
          "MATCH" if md5_old[f"{split}.jsonl"] in (h, h_crlf) else "MISMATCH")
    with open(os.path.join(OUT, f"{split}.jsonl"), "wb") as f:
        f.write(data)
    with open(os.path.join(OUT, f"{split}_meta.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(meta) + "\n")
