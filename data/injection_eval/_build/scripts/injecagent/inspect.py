import json, sys, collections
d = sys.argv[1]
for fn in ["test_cases_dh_base.json", "test_cases_ds_base.json"]:
    data = json.load(open(f"{d}/{fn}", encoding="utf-8"))
    print(fn, type(data).__name__, len(data))
    print(" keys:", list(data[0].keys()))
    ut = collections.Counter(c["User Tool"] for c in data)
    at = collections.Counter(tuple(c["Attacker Tools"]) for c in data)
    print(" user tools:", len(ut), " attacker tool sets:", len(at), " attacker instr:", len(set(c["Attacker Instruction"] for c in data)))
    print(" templates distinct:", len(set(c["Tool Response Template"] for c in data)))
    c = data[0]
    for k, v in c.items():
        print("  ", k, "=>", repr(v)[:300])
uc = [json.loads(l) for l in open(f"{d}/user_cases.jsonl", encoding="utf-8")]
print("user_cases", len(uc), list(uc[0].keys()))
for k, v in uc[0].items(): print("  ", k, "=>", repr(v)[:300])
