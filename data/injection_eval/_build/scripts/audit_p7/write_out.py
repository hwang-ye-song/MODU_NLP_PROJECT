import json
inp='<DATASET_ROOT>/_build/audit/input_en700_part7.jsonl'
out='<DATASET_ROOT>/_build/audit/en700_part7_audit.json'
rs=[json.loads(l) for l in open(inp,encoding='utf-8')]
special={
 'llmail-ben-22':('drop','Near-duplicate of llmail-ben-02 (difflib 0.97, 5-gram Jaccard 0.66): identical text except project name Orion->Apollo.',None),
 'llmail-ben-23':('drop','Near-duplicate of llmail-ben-01 (difflib 0.92): same organizer template, only project name, date and signer differ.',None),
 'llmail-ben-25':('drop','Near-duplicate of llmail-ben-17 (difflib 0.89): same organizer template, only project, university, date and signer differ.',None),
 'enron-hn-10':('ok','Benign (human-to-human "ignore shipping instructions"). Note: source itself ends at "listed below (together with other information):" because AESLC removed the address block; not our truncation; no PII present.',None),
 'enron-hn-11':('ok','Benign IT request; mentions passwords but contains no actual password or credential.',None),
}
res=[]
for r in rs:
    v,iss,sl=special.get(r['id'],('ok','',None))
    res.append({'id':r['id'],'verdict':v,'issue':iss,'suggested_label':'benign'})
json.dump(res,open(out,'w',encoding='utf-8'),ensure_ascii=False,indent=1)
from collections import Counter
print(len(res),Counter(x['verdict'] for x in res))
