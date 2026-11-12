import json, sys, re
from html.parser import HTMLParser
from collections import Counter
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
mode=sys.argv[2]  # 'ben' or 'inj'
KW=re.compile(r"(\bAI\b|\bA\.I\.|assistant|\bagent|\bLLM|language model|ignore|disregard|previous instructions|prior instructions|system prompt|override|you are now|\bChatGPT|\bClaude|\bGPT|\bGemini|\bbot\b|crawler|scraper|\bmodel\b|instruction|directive|exfiltrat|transmit|forward (all|this|the)|summar|automated (system|tool|reader)|if you are|when processing|processing this|new (task|role)|do not (tell|notify|inform)|\bnote to\b|reply with|respond with|output)", re.I)
ENSTOP=set("the and to of a in is for you your on with this that it are be as at by from or have an will can not we our all more".split())
class P(HTMLParser):
    def __init__(s):
        super().__init__(convert_charrefs=True); s.vis=[]; s.comments=[]; s.attrs=[]; s.scripts=[]; s.stack=[]; s.hidden=[]
    def handle_starttag(s,tag,attrs):
        a=dict(attrs); st=(a.get('style') or '').replace(' ','').lower()
        hid = ('display:none' in st or 'visibility:hidden' in st or 'font-size:0' in st or 'opacity:0' in st or 'hidden' in a or a.get('aria-hidden')=='true' or (tag=='input' and a.get('type')=='hidden'))
        for k,v in attrs:
            if v and k not in ('style','class','id','href','src','type','rel','target','width','height') and len(v)>3:
                s.attrs.append((tag,k,v))
        if tag in ('br','img','input','meta','link','hr','source','wbr'): return
        s.stack.append((tag,hid))
    def handle_endtag(s,tag):
        for i in range(len(s.stack)-1,-1,-1):
            if s.stack[i][0]==tag: del s.stack[i:]; break
    def handle_data(s,d):
        if not d.strip(): return
        intag=[t for t,_ in s.stack]
        if 'script' in intag or 'style' in intag:
            if 'script' in intag: s.scripts.append(d)
            return
        if any(h for _,h in s.stack): s.hidden.append(d.strip())
        else: s.vis.append(d.strip())
    def handle_comment(s,d): s.comments.append(d.strip())
lo,hi=int(sys.argv[3]),int(sys.argv[4])
for r in recs[lo:hi]:
    t=r['text']; p=P(); p.feed(t)
    vis=' '.join(p.vis)
    words=re.findall(r"[A-Za-z]+",vis.lower())
    nonascii=[c for c in vis if ord(c)>127 and c.isalpha()]
    enr=sum(w in ENSTOP for w in words)/max(1,len(words))
    print('=====',r['id'],'len',len(t),'vischars',len(vis),'en_stop_ratio %.2f'%enr,'nonascii_alpha',len(nonascii), ''.join(nonascii[:30]))
    print(' VIS_HEAD:',vis[:300])
    for c in p.comments: print(' COMMENT:',c[:250])
    for h in p.hidden: print(' HIDDEN:',h[:250])
    for tag,k,v in p.attrs:
        if k.startswith('data-') or k in ('alt','title','aria-label','value','content','placeholder','name') :
            if len(v)>25 or KW.search(v): print(' ATTR:',tag,k,repr(v[:200]))
    for sc in p.scripts:
        lits=re.findall(r"(['\"`])((?:\.|(?!\1).){8,}?)\1",sc)
        print(' SCRIPT len',len(sc),'lits',[l[1][:120] for l in lits][:15])
    # keyword hits in visible text
    hits=[(m.group(0), vis[max(0,m.start()-80):m.end()+80]) for m in KW.finditer(vis)]
    for h,ctx in hits[:12]: print(' KW[%s]:'%h, ctx.replace('\n',' '))
    # escaped html presence
    if '&lt;' in t: print(' NOTE: contains escaped HTML &lt; count',t.count('&lt;'))
