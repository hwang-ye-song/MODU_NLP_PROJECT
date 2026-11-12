import json,sys
wd=sys.argv[1]
ko=[json.loads(l) for l in open(wd+'/ko_parts/bipia_email_new.jsonl',encoding='utf-8')]
for tok,rid in [("$100.00","bipia-ben-16-ko"),("ganesh@moonchaser.io","bipia-inj-41-ko"),("1131423339","bipia-ben-29-ko"),("$2,099.00","bipia-ben-19-ko"),("$586.89","bipia-ben-27-ko"),("$213.56","bipia-ben-30-ko"),("$373.52","bipia-ben-20-ko"),("www.example.com","bipia-inj-41-ko")]:
    r=[x for x in ko if x['id']==rid][0]; print(tok, tok in r['text'])
for r in ko:
    print('=====',r['id'],r['label'])
    print(r['text'])
