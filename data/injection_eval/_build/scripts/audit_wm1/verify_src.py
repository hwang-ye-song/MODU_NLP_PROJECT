import json, sys
import pyarrow.parquet as pq

inp, parquet = sys.argv[1], sys.argv[2]
recs = [json.loads(l) for l in open(inp, encoding='utf-8')]
tbl = pq.read_table(parquet)
print(tbl.schema)
cols = tbl.column_names
data = tbl.to_pydict()
n = tbl.num_rows
for r in recs:
    o = r['origin']
    i = o['row_index']
    row = {c: data[c][i] for c in cols}
    content = row.get('content')
    same = content == r['text']
    meta = {c: (str(v)[:60]) for c, v in row.items() if c != 'content'}
    print(r['id'], i, 'verbatim' if same else 'DIFF', meta)
    if not same:
        a, b = content, r['text']
        k = next((j for j in range(min(len(a), len(b))) if a[j] != b[j]), min(len(a), len(b)))
        print('   lens', len(a), len(b), 'first diff', k, repr(a[k-40:k+60]), '||', repr(b[k-40:k+60]))
