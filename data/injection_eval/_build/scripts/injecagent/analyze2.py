import json, sys, collections
d = sys.argv[1]
data = json.load(open(f"{d}/test_cases_ds_base.json", encoding="utf-8"))
bad = [(i, c) for i, c in enumerate(data) if c["Tool Response"] != json.dumps(c["Tool Response Template"].replace("<Attacker Instruction>", c["Attacker Instruction"]))]
print(len(bad), collections.Counter(c["User Tool"] for i, c in bad), collections.Counter(tuple(c["Attacker Tools"]) for i,c in bad))
i, c = bad[0]
print(i, repr(c["Tool Response"])[:600])
print(repr(c["Attacker Instruction"]))
# dh: quoted-filled vs json.dumps mismatch reason
dh = json.load(open(f"{d}/test_cases_dh_base.json", encoding="utf-8"))
mm = [c for c in dh if c["Tool Response"] != '"' + c["Tool Response Template"].replace("<Attacker Instruction>", c["Attacker Instruction"]) + '"']
print(len(mm), collections.Counter(c["User Tool"] for c in mm))
print(repr(mm[0]["Tool Response Template"])[:400])
# placeholder quoting context per template
uc = [json.loads(l) for l in open(f"{d}/user_cases.jsonl", encoding="utf-8")]
for u in uc:
    t = u["Tool Response Template"]; k = t.index("<Attacker Instruction>")
    print(u["User Tool"], "| before:", repr(t[k-1]), "after:", repr(t[k+22]), "| len", len(t))
