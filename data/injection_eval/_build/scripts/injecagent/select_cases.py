"""Deterministic selection of InjecAgent cases. Usage: python -I select_cases.py <data_dir>"""
import json, sys, random, collections

def family(tool):
    for p in ["TwitterManager", "GoogleCalendar", "GitHub", "Gmail", "Amazon", "Evernote",
              "Shopify", "Teladoc", "Todoist", "Twilio", "WebBrowser"]:
        if tool.startswith(p):
            return p
    raise ValueError(tool)

def interleave_by_type(instrs, rng):
    groups = collections.defaultdict(list)
    for ins, atype in instrs:
        groups[atype].append(ins)
    types = sorted(groups)
    for t in types:
        rng.shuffle(groups[t])
    rng.shuffle(types)
    out = []
    while any(groups[t] for t in types):
        for t in types:
            if groups[t]:
                out.append((groups[t].pop(0), t))
    return out

def select(d):
    rng = random.Random(42)
    random.seed(42)
    uc = [json.loads(l) for l in open(f"{d}/user_cases.jsonl", encoding="utf-8")]
    dh = json.load(open(f"{d}/test_cases_dh_base.json", encoding="utf-8"))
    ds = json.load(open(f"{d}/test_cases_ds_base.json", encoding="utf-8"))
    tools = sorted(u["User Tool"] for u in uc)
    fams = collections.defaultdict(list)
    for t in tools:
        fams[family(t)].append(t)
    multi = sorted(f for f in fams if len(fams[f]) > 1)
    single = sorted(f for f in fams if len(fams[f]) == 1)
    # 17 user tools total; benign needs 10 tools disjoint from injection tools -> injection gets 7.
    inj_tools = [rng.choice(fams[f]) for f in multi]
    inj_tools += [fams[f][0] for f in rng.sample(single, 7 - len(inj_tools))]
    ben_tools = [t for t in tools if t not in inj_tools]
    assert len(inj_tools) == 7 and len(ben_tools) == 10

    def pick(cases, n, tool_order):
        def ok(c):  # keep only cases whose Tool Response is exactly json.dumps(filled template)
            return c["Tool Response"] == json.dumps(c["Tool Response Template"].replace("<Attacker Instruction>", c["Attacker Instruction"]))
        instr = {}
        excluded = set()
        for c in cases:
            instr.setdefault(c["Attacker Instruction"], c["Attack Type"])
            if not ok(c):
                excluded.add(c["Attacker Instruction"])
        pool = [(k, v) for k, v in instr.items() if k not in excluded]
        order = interleave_by_type(pool, rng)[:n]
        res = []
        for (ins, atype), tool in zip(order, tool_order):
            idx = [i for i, c in enumerate(cases) if c["User Tool"] == tool and c["Attacker Instruction"] == ins]
            assert len(idx) == 1, (tool, ins, idx)
            res.append(idx[0])
        return res, excluded

    dh_tools = inj_tools[:]; rng.shuffle(dh_tools); dh_tools.append(rng.choice(inj_tools))
    ds_tools = inj_tools[:]; rng.shuffle(ds_tools)
    dh_idx, dh_ex = pick(dh, 8, dh_tools)
    ds_idx, ds_ex = pick(ds, 7, ds_tools)
    return dict(uc=uc, dh=dh, ds=ds, inj_tools=inj_tools, ben_tools=ben_tools,
                dh_idx=dh_idx, ds_idx=ds_idx, dh_excluded=dh_ex, ds_excluded=ds_ex)

if __name__ == "__main__":
    r = select(sys.argv[1])
    print("inj tools:", r["inj_tools"]); print("ben tools:", r["ben_tools"])
    print("excluded instr dh:", len(r["dh_excluded"]), "ds:", len(r["ds_excluded"]))
    for name in ["dh", "ds"]:
        for i in r[name + "_idx"]:
            c = r[name][i]
            print(name, i, c["User Tool"], c["Attacker Tools"], c["Attack Type"], "|", c["Attacker Instruction"][:80])
