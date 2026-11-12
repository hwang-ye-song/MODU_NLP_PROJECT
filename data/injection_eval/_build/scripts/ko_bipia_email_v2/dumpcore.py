import json,sys
wd=sys.argv[1]
for fn in ['core_inj','core_ben']:
    for l in open(wd+'/ko_parts/'+fn+'.jsonl',encoding='utf-8'):
        r=json.loads(l)
        if r['source']=='BIPIA' and r['subset']=='email':
            print('=====',r['id'],r['label'],'origin idx',r['origin'].get('index'))
            print(r['text'])
            print('--- inj:',r.get('injected_instruction'))
            print('--- notes:',r.get('translation_notes'))
            print('keys:',list(r.keys()))
