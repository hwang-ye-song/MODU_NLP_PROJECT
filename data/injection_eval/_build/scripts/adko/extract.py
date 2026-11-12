import json,yaml,ast,re,sys
SRC='<DATASET_ROOT>/_build/parts_v2/agentdojo_tools.jsonl'
def load():
    r=[json.loads(l) for l in open(SRC,encoding='utf-8')]
    return r
def kind(t):
    try:
        o=yaml.safe_load(t)
        if yaml.safe_dump(o).strip()==t: return 'yaml',o
    except Exception: pass
    try:
        o=ast.literal_eval(t)
        if str(o)==t: return 'repr',o
    except Exception: pass
    return 'raw',t
SKIPKEYS={'id_','sender','recipients','cc','bcc','owner','shared_with','filename','status','participants','recipient','sender','iban','currency','date','timestamp','start_time','end_time','last_modified','size','read','recurring','amount','all_day'}
def leaves(o,key=None,out=None):
    if out is None: out=[]
    if isinstance(o,dict):
        for k,v in o.items():
            if isinstance(k,str) and key!='__top' and ' ' in k and not '@' in k: out.append(k)
            leaves(v,k,out)
    elif isinstance(o,list):
        for v in o: leaves(v,key,out)
    elif isinstance(o,str):
        if key in SKIPKEYS: return out
        if re.fullmatch(r'[\w.\-@/:]+',o) and ' ' not in o: return out
        out.append(o)
    return out
if __name__=='__main__':
    r=load()
    inj=[x for x in r if x['label']=='injection']; ben=[x for x in r if x['label']=='benign']
    def L(x):
        k,o=kind(x['text'])
        return leaves(o) if k!='raw' else [o]
    bl=set(s for x in ben for s in L(x))
    shared=sorted(set(s for x in inj for s in L(x))&bl)
    json.dump(shared,open('shared.json','w',encoding='utf-8'),ensure_ascii=False,indent=0)
    print(len(shared))
    a,b=int(sys.argv[1]),int(sys.argv[2])
    for i in range(a,b):
        x=inj[i]; print('=====',i,x['id'],kind(x['text'])[0])
        for s in L(x): print(json.dumps(s,ensure_ascii=False))
