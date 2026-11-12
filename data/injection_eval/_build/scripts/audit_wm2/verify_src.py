import json, sys, pyarrow.parquet as pq
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
t=pq.read_table(sys.argv[2])
print(t.schema)
cols=t.column_names
content=t.column('content').to_pylist()
labcol=[c for c in cols if c!='content']
lab={c:t.column(c).to_pylist() for c in labcol}
for r in recs:
    o=r['origin']; i=o['row_index']
    src=content[i]
    others={c:lab[c][i] for c in labcol}
    print(r['id'], i, 'EXACT' if src==r['text'] else ('STRIP' if src.strip()==r['text'].strip() else 'DIFF'), others, o.get('dataset_label'), o.get('payload_placement'), o.get('attack_template'), o.get('site_brand'))
