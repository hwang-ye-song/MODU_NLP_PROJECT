import json, re, difflib, sys
rs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
ids=[r['id'] for r in rs]
print('dup ids', len(ids)-len(set(ids)))
moj=re.compile(r'(Ã.|â€|Â |\ufffd|ï¿½)')
ph=re.compile(r'(\{[a-z_]+\}|<Attacker Instruction>|<[A-Z][a-z]+ [A-Z][a-z]+>|\[INSERT|PLACEHOLDER)', re.I)
for r in rs:
    t=r['text']; ii=r['injected_instruction']
    flags=[]
    if not t.strip(): flags.append('empty')
    if ii is None: flags.append('ii None')
    elif ii not in t: flags.append('ii not substring')
    if moj.search(t): flags.append('mojibake:'+moj.search(t).group(0))
    m=ph.search(t)
    if m: flags.append('placeholder:'+m.group(0))
    try: t.encode('ascii')
    except: 
        na=set(c for c in t if ord(c)>127)
        flags.append('nonascii:'+''.join(sorted(na))[:20])
    if flags: print(r['id'], len(t), flags)
# near dup
def sh(t):
    w=t.lower().split(); return set(tuple(w[i:i+5]) for i in range(len(w)-4))
S=[sh(r['text']) for r in rs]
for i in range(len(rs)):
    for j in range(i+1,len(rs)):
        a,b=S[i],S[j]
        jac=len(a&b)/max(1,len(a|b))
        if jac>=0.5:
            print('NEARDUP jac',rs[i]['id'],rs[j]['id'],round(jac,2))
        else:
            if abs(len(rs[i]['text'])-len(rs[j]['text']))<400:
                r_=difflib.SequenceMatcher(None,rs[i]['text'],rs[j]['text']).quick_ratio()
                if r_>=0.8:
                    r2=difflib.SequenceMatcher(None,rs[i]['text'],rs[j]['text']).ratio()
                    if r2>=0.8: print('NEARDUP diff',rs[i]['id'],rs[j]['id'],round(r2,2))
