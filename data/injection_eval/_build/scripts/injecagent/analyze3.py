import json, sys, collections
d = sys.argv[1]
uc = [json.loads(l) for l in open(f"{d}/user_cases.jsonl", encoding="utf-8")]
for u in uc:
    print(u["User Tool"], "::", u["Tool Response Template"]); print()
for fn in ["test_cases_dh_base.json", "test_cases_ds_base.json"]:
    data = json.load(open(f"{d}/{fn}", encoding="utf-8"))
    seen = {}
    for c in data:
        seen.setdefault(c["Attacker Instruction"], (c["Attack Type"], c["Attacker Tools"]))
    print(fn, collections.Counter(v[0] for v in seen.values()))
    for k, v in seen.items(): print("  ", v[0], v[1], "|", k[:110])
