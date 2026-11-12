import json, sys
import pyarrow.parquet as pq
t = pq.read_table(sys.argv[1])
cols = t.column_names
print(cols)
ds = {}
for l in open(sys.argv[2], encoding='utf-8'):
    d = json.loads(l); ds[d['id']] = d
for i in range(6, 31):
    d = ds['web-ben-%02d' % i]; ri = d['origin']['row_index']
    row = {c: t.column(c)[ri].as_py() for c in cols if c != 'content'}
    src = t.column('content')[ri].as_py()
    st = 'EXACT' if src == d['text'] else ('STRIP' if src.strip() == d['text'].strip() else 'DIFF %d vs %d' % (len(src), len(d['text'])))
    print(d['id'], ri, row, st)
