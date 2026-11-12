import json,sys,re
c=json.load(open(sys.argv[1],encoding='utf-8'))
lab=sys.argv[2]
pat=re.compile(r"(ignore|disregard|\bAI\b|assistant|\bagent\b|system (prompt|instruction|message)|you are now|override|admin mode|developer mode|previous (task|instruction)|prior (task|instruction)|\bTODO\b|important message|language model|instructions|bypass|exfiltrat|forward (all|the|sensitive|user)|reveal|display your|\byour (task|instructions|configuration)|hypothetical|in a scenario|pretend|roleplay|act as|new task|before (you|continuing|proceeding))",re.I)
n=0
for x in c:
    if x['label']!=lab: continue
    h=x['content']
    hits=[m for m in pat.finditer(h)]
    if not hits: continue
    n+=1
    segs=[]
    for m in hits[:3]:
        s=h[max(0,m.start()-110):m.end()+130].replace('\n',' ')
        segs.append(s)
    print('##',x['row_index'],len(h),'||',' ... '.join(segs)[:520])
print('count',n)
