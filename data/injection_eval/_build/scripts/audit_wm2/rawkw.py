import json, sys, re, html
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
KW=re.compile(r"(\bAI\b|\bA\.I\.|artificial intelligence|assistant|\bagents?\b|\bLLM|language model|ignore|disregard|previous instructions|prior (instructions|commands)|system prompt|override|you are now|\bChatGPT|\bClaude|\bGPT|\bGemini|\bCopilot|\bbots?\b|crawler|scraper|\bmodel\b|instructions?\b|directive|exfiltrat|transmit|forward|summari[sz]|automated|if you are|processing|new (task|role|priority)|do not (tell|notify|inform)|note to|reply with|respond with|\boutput\b|\bprompt|execute|\bcommand|for our records|please ensure|kindly|send (all|the|this|your)|\bcollect)", re.I)
lo,hi=int(sys.argv[2]),int(sys.argv[3])
for r in recs[lo:hi]:
    t=html.unescape(html.unescape(r['text']))
    t2=re.sub(r'style="[^"]*"','',t)  # drop inline CSS noise
    seen=set(); out=[]
    for m in KW.finditer(t2):
        ctx=t2[max(0,m.start()-90):m.end()+90].replace('\n',' ')
        key=(m.group(0).lower(), ctx[60:140])
        if key in seen: continue
        seen.add(key); out.append((m.group(0),ctx))
    print('=====',r['id'],'hits',len(out))
    for h,c in out[:25]: print('  [%s] %s'%(h,c))
