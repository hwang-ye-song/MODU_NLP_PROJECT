import json, re, sys, difflib
rows=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
moj=re.compile(r'(Ã.|â€|Â |ï¿½|\ufffd)')
ph=re.compile(r'(\{[a-z_]*injection[a-z_]*\}|<Attacker Instruction>|\{context\}|\{question\}|\{.*?attack.*?\})',re.I)
def ngrams(t,n=5):
    w=t.lower().split(); return set(tuple(w[i:i+n]) for i in range(len(w)-n+1))
for i,r in enumerate(rows):
    t=r['text']; ii=r['injected_instruction']
    issues=[]
    if not t.strip(): issues.append('EMPTY')
    if ii is None: issues.append('II_NULL')
    elif ii not in t: issues.append('II_NOT_SUBSTR')
    else:
        c=t.count(ii)
        if c>1: issues.append(f'II_x{c}')
    if moj.search(t): issues.append('MOJIBAKE:'+moj.search(t).group(0))
    if ph.search(t): issues.append('PLACEHOLDER:'+ph.search(t).group(0))
    na=[ch for ch in t if ord(ch)>127]
    if na: issues.append('NONASCII:'+''.join(sorted(set(na)))[:30])
    pos = t.find(ii) if ii else -1
    print(i, r['id'], r['subset'], len(t), 'pos=%d'%pos, 'end=%s'%repr(t[-40:]), issues)
# near dup within
ng=[ngrams(r['text']) for r in rows]
for a in range(len(rows)):
    for b in range(a+1,len(rows)):
        if not ng[a] or not ng[b]: continue
        j=len(ng[a]&ng[b])/len(ng[a]|ng[b])
        if j>=0.3:
            print('DUP?',rows[a]['id'],rows[b]['id'],round(j,2))
