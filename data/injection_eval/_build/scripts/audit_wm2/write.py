import json, sys
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
out=[{"id":r['id'],"verdict":"ok","issue":"","suggested_label":r['label']} for r in recs]
with open(sys.argv[2],'w',encoding='utf-8') as f: json.dump(out,f,ensure_ascii=False,indent=1)
chk=json.load(open(sys.argv[2],encoding='utf-8'))
print(len(chk), len({c['id'] for c in chk}), {c['verdict'] for c in chk})
