import json, sys, re, html
sys.argv=[sys.argv[0],sys.argv[1],'x','0','0']
exec(open('scan.py',encoding='utf-8').read().split('lo,hi=')[0])
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
for r in recs:
    t=r['text']
    n_script=len(re.findall(r'<script',t,re.I)); n_noscript=len(re.findall(r'<noscript',t,re.I)); n_esc_script=len(re.findall(r'&lt;script',t,re.I))
    u=html.unescape(t)
    p=P(); p.feed(u)
    extra=[]
    for c in p.comments: extra.append('COMMENT: '+c[:200])
    for h in p.hidden: extra.append('HIDDEN: '+h[:200])
    for tag,k,v in p.attrs:
        if (k.startswith('data-') or k in ('alt','title','aria-label','value','content','placeholder','name')) and (len(v)>25):
            extra.append('ATTR %s %s: %r'%(tag,k,v[:200]))
    for sc in p.scripts: extra.append('SCRIPT: '+sc[:200].replace('\n',' '))
    # meta tags
    print('=====',r['id'],r['label'],'script',n_script,'noscript',n_noscript,'esc_script',n_esc_script)
    for e in dict.fromkeys(extra): print('  ',e)
