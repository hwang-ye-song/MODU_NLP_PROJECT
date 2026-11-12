import json,sys
OLD=sys.argv[1]
for sp in ['train','test']:
  for i,l in enumerate(open(OLD+'/dl/bipia/benchmark/code/'+sp+'.jsonl',encoding='utf8')):
    r=json.loads(l); c='\n'.join(r['context']); nb=c.count('```')
    indent=sum(1 for x in r['context'] if x.startswith('    ') or x.startswith('\t'))
    if nb==0 and indent==0: print(sp,i,len(c),repr(c[:150]))
