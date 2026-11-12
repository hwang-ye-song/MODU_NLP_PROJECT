import json, sys, os
from collections import Counter
bench = sys.argv[1]
for task in ["email", "table", "code"]:
    for split in ["test"]:
        p = os.path.join(bench, task, split + ".jsonl")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        ctxs = []
        for r in rows:
            c = r["context"]
            if isinstance(c, list):
                c = "\n".join(c)
            ctxs.append(c)
        lens = [len(c) for c in ctxs]
        dup = Counter(ctxs)
        ndup = sum(1 for c, n in dup.items() if n > 1)
        nonascii = [sum(1 for ch in c if ord(ch) > 127) for c in ctxs]
        print(task, split, "rows", len(rows), "unique ctx", len(dup), "dup-groups", ndup,
              "len<=2400", sum(1 for x in lens if x <= 2400), "len<=3000", sum(1 for x in lens if x <= 3000),
              "min/max", min(lens), max(lens), "nonascii>0", sum(1 for x in nonascii if x > 0))
        print("  keys", list(rows[0].keys()))
ca = json.load(open(os.path.join(bench, "code_attack_test.json"), encoding="utf-8"))
print("code attack types", Counter(type(s).__name__ for v in ca.values() for s in v))
print("code attack lens", sorted(len(s) for v in ca.values() for s in v))
ta = json.load(open(os.path.join(bench, "text_attack_test.json"), encoding="utf-8"))
print("text attack nonascii", [s for v in ta.values() for s in v if any(ord(ch) > 127 for ch in s)])
