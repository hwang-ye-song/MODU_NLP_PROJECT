import json, sys
path, a, b = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
rs=[json.loads(l) for l in open(path,encoding='utf8')]
inj=[r for r in rs if r['label']=='injection']
for r in inj[a:b]:
    t=r['text']; ii=r['injected_instruction']
    lines=t.split('\n')
    full = ii in lines
    print('=====', r['id'], r['origin']['position'], r['origin']['attack_category'], 'fullline=',full, 'nlines=',len(lines))
    for i,l in enumerate(lines):
        mark = ' <<INJ' if ii in l else ''
        print(f'{i}|{l}{mark}')
