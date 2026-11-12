import json, sys, re, html
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
lo,hi=int(sys.argv[2]),int(sys.argv[3])
PAT=re.compile(r"([A-Z][A-Z ]{4,}[A-Z]:[^<\n]{0,160})|((?:send|email|mail|reply|share|provide|submit|enter|confirm|visit|click|call|update)\b[^<\n]{0,120})",re.I)
for r in recs[lo:hi]:
    u=html.unescape(r['text'])
    u=re.sub(r'<[^>]+>',' ',u); u=re.sub(r'\s+',' ',u)
    found=list(dict.fromkeys(m.group(0).strip()[:170] for m in PAT.finditer(u)))
    print('=====',r['id'],len(found))
    for f in found[:14]: print('   ',f)
