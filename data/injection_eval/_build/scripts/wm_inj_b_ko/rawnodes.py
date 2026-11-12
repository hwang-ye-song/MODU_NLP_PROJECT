import sys; sys.path.insert(0, '.')
from lib import *
BS = chr(92)
for n in (61, 62, 66, 70):
    t = open(f'src/web-inj-{n}.html', encoding='utf-8').read()
    for i, p in enumerate(TOK.split(t)):
        s = p.strip()
        if i % 2 == 0 and s and ('\n' in s or BS in p or 'Search' in p or (p != s and len(s) < 40 and s[0].isalpha())):
            print(n, repr(p)[:150])
