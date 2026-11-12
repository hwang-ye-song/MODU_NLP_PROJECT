import sys,os; D=os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0,D)
import kolib as lib, json, yaml, ast, glob, copy, re
tr={}
for f in sorted(glob.glob(os.path.join(D,'tr_*.json'))): tr.update(json.load(open(f,encoding='utf8')))
def subst(o, it, key=None):
    if isinstance(o,dict): return {k:subst(v,it,k) for k,v in o.items()}
    if isinstance(o,list): return [subst(v,it,key) for v in o]
    if isinstance(o,str) and key in lib.NL_KEYS: return next(it)
    return o
out=[]
for r in lib.load():
    ko=tr[r['id']]; src=lib.nl_strings(r); assert len(ko)==len(src), r['id']
    k=lib.kind(r); o=lib.parse(r)
    if k=='raw': text=ko[0]
    elif k=='review':
        (name,s),=o.items(); h=s.split('\nReviews: ',1)[0]
        text=str({name: h.replace('Rating: ','평점: ')+'\n리뷰: '+'\n'.join(ko)})
        d=ast.literal_eval(text); assert list(d)==[name]
    else:
        it=iter(ko); no=subst(o,it); assert next(it,None) is None
        text=yaml.safe_dump(no, allow_unicode=True).strip()
        assert yaml.safe_load(text)==no
        # non-NL leaves unchanged
        assert subst(yaml.safe_load(text),iter(x for _,x in src))==o, r['id']
    rec={'id':r['id']+'-ko','pair_id':r['id'],'lang':'ko'}
    for key in ['label','source','subset','doc_type']: rec[key]=r[key]
    rec['text']=text; rec['injected_instruction']=None
    for key in ['origin','notes','core']: rec[key]=r[key]
    notes='Only natural-language field values translated ('+('review lines; dict rendered with str() as in the original; "Rating:"/"Reviews:" headers rendered 평점:/리뷰: per shared glossary' if k=='review' else 'whole file text; IBAN/amounts kept' if k=='raw' else 'subject/body/title/description/location/content; keys, ids, emails, timestamps, file names, enum values unchanged')+').'
    if k=='yaml': notes+=' Re-dumped with yaml.safe_dump(obj, allow_unicode=True).strip() (AgentDojo default would escape Hangul as Unicode escapes); line folding differs from EN accordingly; verified safe_load gives the same structure with only translated values changed.'
    if not src: notes='No natural-language values (channel names only); text identical to EN.'
    rec['translation_notes']=notes
    out.append(rec)
with open('<DATASET_ROOT>/_build/ko_parts/agentdojo_ben.jsonl','w',encoding='utf8') as f:
    for x in out: f.write(json.dumps(x,ensure_ascii=False)+'\n')
print(len(out))
