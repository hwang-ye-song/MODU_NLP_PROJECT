"""Dump BrowseSafe-Bench test.parquet rows to JSON: row_index, label, content (no filtering)."""
import json, sys
import pyarrow.parquet as pq
src, out = sys.argv[1:3]
t = pq.read_table(src)
print(t.schema)
cols = t.to_pydict()
n = t.num_rows
recs = [{"row_index": i, **{k: cols[k][i] for k in cols}} for i in range(n)]
json.dump(recs, open(out, "w", encoding="utf-8"), ensure_ascii=False)
import collections
print(n, collections.Counter(r["label"] for r in recs))
