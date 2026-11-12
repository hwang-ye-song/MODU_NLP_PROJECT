import sys,os; sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
import kolib as lib, json
from collections import Counter
out={}
for r in lib.load(): out[r['id']]=lib.nl_strings(r)
json.dump(out,open(os.path.join(os.path.dirname(os.path.abspath(__file__)),'strings.json'),'w',encoding='utf8'),ensure_ascii=False,indent=0)
c=Counter(s for v in out.values() for k,s in v)
print(sum(len(v) for v in out.values()), len(c)); print([s for s,n in c.items() if n>1])
