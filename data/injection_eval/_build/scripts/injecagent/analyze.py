import json, sys, ast, collections
d = sys.argv[1]
uc = [json.loads(l) for l in open(f"{d}/user_cases.jsonl", encoding="utf-8")]
uc_tools = [u["User Tool"] for u in uc]
print("user_cases tools:", uc_tools)
tmpl_by_tool = {u["User Tool"]: u["Tool Response Template"] for u in uc}
def tryparse(s):
    r = []
    try: json.loads(s); r.append("json")
    except Exception: pass
    try: ast.literal_eval(s); r.append("literal")
    except Exception: pass
    return r
for fn in ["test_cases_dh_base.json", "test_cases_ds_base.json"]:
    data = json.load(open(f"{d}/{fn}", encoding="utf-8"))
    stats = collections.Counter()
    for i, c in enumerate(data):
        t, tr, ai = c["Tool Response Template"], c["Tool Response"], c["Attacker Instruction"]
        stats["tmpl==uc"] += t == tmpl_by_tool.get(c["User Tool"])
        filled = t.replace("<Attacker Instruction>", ai)
        stats["tr==filled"] += tr == filled
        stats["tr==quoted filled"] += tr == '"' + filled + '"'
        stats["tr==json.dumps(filled)"] += tr == json.dumps(filled)
        stats["ai in tr"] += ai in tr
        stats["placeholder count==1"] += t.count("<Attacker Instruction>") == 1
        stats["tr parse " + "+".join(tryparse(tr))] += 1
        stats["tmpl-filled parse " + "+".join(tryparse(filled))] += 1
        if tr.startswith('"') and tr.endswith('"'):
            stats["tr inner parse " + "+".join(tryparse(tr[1:-1]))] += 1
    print(fn, len(data), dict(stats))
    print(" user tools set == uc:", set(c["User Tool"] for c in data) == set(uc_tools))
