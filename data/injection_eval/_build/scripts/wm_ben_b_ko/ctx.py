import sys,os,re
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from common import *
for fn in sys.argv[1:]:
    t=open(fn,encoding='utf8').read()
    out=[]; last=''
    for k,p in tokens(t):
        if k=='tag':
            m=re.match(r'<\s*(/?[A-Za-z][\w-]*)',p); last=m.group(1) if m else p[:5]
        elif k=='text' and p.strip():
            out.append(f'<{last}>'+p.strip().replace('\n','⏎'))
        elif k=='comment': out.append('<!--'+p[4:-3].strip()[:100])
    print('==',fn); print('\n'.join(out))
