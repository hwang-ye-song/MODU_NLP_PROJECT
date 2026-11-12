import json, re, sys, difflib
rs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
pii=re.compile(r'(?i)(password|passwd|pwd|login|user ?id|ssn|social security|account (no|number|#)|acct|routing|card (no|number)|visa|mastercard|amex|\b\d{3}-\d{2}-\d{4}\b|\b(?:\d[ -]?){13,19}\b|pin\b|swift|iban|license|passport)')
moj=re.compile(r'(Ã.|â€|Â|�|ï¿½)')
ph=re.compile(r'(\{[a-z_]+\}|<Attacker|<[A-Z][a-z]+ Instruction>)')
trig=re.compile(r'(?i)\b(ignore|disregard|override|forget|instead|AI|assistant|chatbot|LLM|model|system prompt|you must|do not tell)\b')
for i,r in enumerate(rs):
    t=r['text']
    flags=[]
    m=pii.findall(t)
    if m: flags.append('PII:'+','.join(sorted(set(x[0] if isinstance(x,tuple) else x for x in m)))[:80])
    if moj.search(t): flags.append('MOJ')
    if ph.search(t): flags.append('PH')
    tr=sorted(set(x.lower() for x in trig.findall(t)))
    if tr: flags.append('TRIG:'+','.join(tr))
    end=t.rstrip()[-1:] 
    print(i, r['id'], len(t), repr(end), ' | '.join(flags))
# near dups
for i in range(len(rs)):
    for j in range(i+1,len(rs)):
        a,b=rs[i]['text'],rs[j]['text']
        r_=difflib.SequenceMatcher(None,a[:1500],b[:1500]).quick_ratio()
        if r_>0.8:
            r2=difflib.SequenceMatcher(None,a[:1500],b[:1500]).ratio()
            if r2>0.75: print('DUP?',rs[i]['id'],rs[j]['id'],round(r2,3))
