import json, sys
rs=[json.loads(l) for l in open(sys.argv[1],encoding='utf-8')]
a,b=int(sys.argv[2]),int(sys.argv[3])
for i in range(a,min(b,len(rs))):
    r=rs[i]
    print(f"=== [{i}] {r['id']} | {r['doc_type']} | {r['label']} | ii={r['injected_instruction']!r}")
    print("NOTES:", r['notes'][:300])
    print(r['text'])
