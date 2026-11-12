import json, sys, re, html
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
KW=re.compile(r"(\bAI\b|assistant|\bagents?\b|\bLLM|language model|ignore (all )?previous|disregard|system prompt|override|you are now|if you are|exfiltrat|transmit|forwarded? (all|to)|send (all|the|it|them)|for our records|kindly forward|directive)", re.I)
for r in recs:
    t=r['text']; ii=r['injected_instruction']
    rest=t.replace(ii,' <<II>> ')
    u=html.unescape(rest); u=re.sub(r'style="[^"]*"','',u)
    nonascii=[c for c in re.sub(r'<[^>]+>',' ',u) if ord(c)>127 and c.isalpha()]
    hits=list(dict.fromkeys(u[max(0,m.start()-80):m.end()+80].replace('\n',' ') for m in KW.finditer(u)))
    print('=====',r['id'],'nonascii_alpha',len(nonascii),''.join(nonascii[:20]),'extra_hits',len(hits))
    for h in hits[:6]: print('   ',h)
