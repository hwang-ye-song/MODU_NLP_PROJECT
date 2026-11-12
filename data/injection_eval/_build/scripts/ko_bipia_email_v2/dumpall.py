import json,sys
wd=sys.argv[1]
i=0
for l in open(wd+'/parts_v2/bipia.jsonl',encoding='utf-8'):
    r=json.loads(l)
    if r['subset']=='email' and r['core'] is False:
        print('=====',i,r['id'],r['label'],'idx',r['origin'].get('index'),r['origin'].get('attack_category'),r['origin'].get('position'))
        print(repr(r['text']))
        print('--- inj:',repr(r.get('injected_instruction')))
        i+=1
