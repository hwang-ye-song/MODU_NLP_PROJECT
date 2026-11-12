import json,sys,unicodedata
rows=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
a,b=int(sys.argv[2]),int(sys.argv[3])
for r in rows[a:b]:
    t=r['text']
    print('='*30,r['id'],r['doc_type'],r['subset'])
    print('NOTES:',r['notes'])
    print('II:',repr(r['injected_instruction']))
    print('TEXT:'); print(t)
    na=[c for c in t if ord(c)>127]
    if na:
        s=sorted(set(na))
        print('NONASCII:',' '.join('%s(U+%04X %s)'%(c if unicodedata.category(c)[0]!='C' and unicodedata.category(c)!='Mn' else '',ord(c),unicodedata.name(c,'?')[:20]) for c in s[:30]))
