import json, sys, re
recs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
PH=re.compile(r"\{[a-z_]+\}|<Attacker|\[INSERT|\{\{|\}\}|PLACEHOLDER|TODO|lorem ipsum|\ufffd|Ã.|â€",re.I)
for r in recs:
    t=r['text']
    opens=len(re.findall(r'<div\b',t)); closes=len(re.findall(r'</div>',t))
    ph=list(dict.fromkeys(m.group(0) for m in PH.finditer(t)))
    print(r['id'], 'div %d/%d'%(opens,closes), 'PH',ph[:5], 'END:',repr(t[-90:]))
