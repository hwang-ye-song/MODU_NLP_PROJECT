import json,sys
wd=sys.argv[1]
for l in open(wd+'/parts_v2/bipia.jsonl',encoding='utf-8'):
    r=json.loads(l)
    if r['subset']=='email' and r['core']:
        print('=====',r['id'],r['label'],'idx',r['origin'].get('index'))
        print(repr(r['text']))
        print('--- inj:',r.get('injected_instruction'))
