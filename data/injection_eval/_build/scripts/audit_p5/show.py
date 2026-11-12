import json,sys
rs=[json.loads(l) for l in open('<DATASET_ROOT>/_build/audit/input_en700_part5.jsonl',encoding='utf-8')]
a,b=int(sys.argv[1]),int(sys.argv[2])
for r in rs[a:b]:
    print('=====',r['id'],'|',r['doc_type'],'|',r['subset'],'| inj:',repr(r['injected_instruction']),'| notes:',r.get('notes'))
    print(r['text'])
