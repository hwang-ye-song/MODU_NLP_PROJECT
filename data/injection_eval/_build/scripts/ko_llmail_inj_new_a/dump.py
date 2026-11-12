import json, sys, unicodedata
src, out = sys.argv[1], sys.argv[2]
rs=[json.loads(l) for l in open(src,encoding='utf-8')]
sel=[r for r in rs if 16<=int(r['id'].split('-')[-1])<=48]
def vis(s):
    o=[]
    for ch in s:
        c=ord(ch)
        if ch in '\n': o.append('\n')
        elif ch=='\r': o.append('\r')
        elif ch=='\t': o.append('\t')
        elif 32<=c<127: o.append(ch)
        else:
            cat=unicodedata.category(ch)
            if cat in ('Cf','Co','Cn','Cc','Zs','Mn') or c>0xFFFF or (0xFF00<=c<=0xFFEF):
                o.append('{U+%04X}'%c)
            else: o.append(ch)
    return ''.join(o)
with open(out,'w',encoding='utf-8') as f:
    for r in sel:
        f.write('='*30+' '+r['id']+'\n')
        f.write('NOTES: '+r['notes']+'\n')
        f.write('INJ: '+repr(r['injected_instruction'])+'\n')
        f.write('--- TEXT ---\n'+vis(r['text'])+'\n')
