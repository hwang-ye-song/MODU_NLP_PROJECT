import json,sys,re
mine={json.loads(l)['id']:json.loads(l) for l in open(sys.argv[1],encoding='utf-8')}
parts={}
for f in sys.argv[2].split(','):
    for l in open(f,encoding='utf-8'):
        r=json.loads(l); parts[r['id']]=r
ctx=[json.loads(l)['context'] for l in open(sys.argv[3],encoding='utf-8')]
bip=sys.argv[4]
atk={}
for fn in ['text_attack_test.json','text_attack_train.json']:
    atk[fn]=json.load(open(bip+'/benchmark/'+fn,encoding='utf-8'))
n=0
for i,r in mine.items():
    if not i.startswith('bipia'): continue
    o=parts[i]['origin']; c=ctx[o['index']]; t=r['text']; a=r['injected_instruction']
    af=o['attack_file'].split('/')[-1]; cat=o.get('attack_category'); ai=o.get('attack_index')
    ok_att = None
    if cat in atk[af] and ai is not None: ok_att = atk[af][cat][ai]==a
    cands=[a+'\n'+c, c+'\n'+a]
    good = t in cands
    if not good:
        # middle: removal check
        good = re.sub(r'\s+','',t.replace(a,''))==re.sub(r'\s+','',c)
        mode='middle-ws' if good else 'FAIL'
    else: mode='exact'
    n+=1
    print(i,mode,ok_att) if (not good or ok_att is not True) else None
    if False: print(i,mode,'attack_ok=',ok_att, o.get('attack_category'),o.get('attack_index'))
print('checked',n, 'origin keys', list(o.keys()))
