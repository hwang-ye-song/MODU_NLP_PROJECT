import json,sys
wd=sys.argv[1]
recs=[json.loads(l) for l in open(wd+'/parts_v2/bipia.jsonl',encoding='utf-8')]
sel=[r for r in recs if r.get('core') is False and r.get('subset')=='email']
print(len(sel), sum(r['label']=='injection' for r in sel))
print(json.dumps(sel[0],ensure_ascii=False,indent=1)[:3000])
