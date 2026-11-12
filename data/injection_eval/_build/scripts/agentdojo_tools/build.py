"""Build WD/_build/parts_v2/agentdojo_tools.jsonl: 60 injection + 60 benign AgentDojo tool outputs
(workspace emails / calendar events / drive files, banking files / transaction lists, travel review lists,
slack channel list / slack messages).
  - environment assembled like TaskSuite.load_and_inject_default_environment (see ad_lib.py)
  - injection strings: exactly those AgentDojo generated, copied from the released runs/ logs ('injections' field)
  - text: the tool output the agent sees (tool_result_to_str: yaml.safe_dump(model_dump()).strip(), or str())
usage: python build.py <agentdojo_repo> <index.json> <WD> <out_jsonl> <plan_json_out>
"""
import ast, collections, difflib, glob, json, os, random, re, statistics, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ad_lib

repo, index_path, WD, out_path, plan_out = sys.argv[1:6]
COMMIT = "089ed468cf3ed0322acc66b0211f26d9d90dbf60"
URL = "https://github.com/ethz-spylab/agentdojo"
SRC = "src/agentdojo"
random.seed(42)
N_INJ, N_BEN = 60, 60


# ------------------------------------------------------------------ similarity helpers (as build_webpage.py)
def toks(t):
    return re.findall(r"\w+", t.lower())


def grams(t, n=5):
    w = toks(t)
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


def jacc(a, b):
    return len(a & b) / max(1, len(a | b))


def near_dup(t, g, pool):
    for t2, g2 in pool:
        if jacc(g, g2) >= 0.5:
            return True
        sm = difflib.SequenceMatcher(None, t, t2, autojunk=False)
        if sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8:
            # ratio() is order-dependent: test both directions
            if sm.ratio() >= 0.8 or difflib.SequenceMatcher(None, t2, t, autojunk=False).ratio() >= 0.8:
                return True
    return False


existing = []
for f in glob.glob(os.path.join(WD, "_build", "parts_v2", "*.jsonl")) + [os.path.join(WD, "_build", "ja_llmail_candidates.jsonl")]:
    if os.path.abspath(f) == os.path.abspath(out_path) or not os.path.exists(f):
        continue
    for line in open(f, encoding="utf-8"):
        if line.strip():
            t = json.loads(line)["text"]
            existing.append((t, grams(t)))
print("existing texts for dedup:", len(existing))

# ------------------------------------------------------------------ suites, items, vectors
SUITES = ["workspace", "travel", "banking", "slack"]
S = {s: ad_lib.Suite(repo, s) for s in SUITES}
BASE = {s: S[s].load_env() for s in SUITES}


def item_map(s, env):
    return {k: (tool, kind, txt) for k, tool, kind, txt in ad_lib.items(s, env)}


BASE_ITEMS = {s: item_map(s, BASE[s]) for s in SUITES}


def raw_obj(s, env, key):
    kind, ident = key
    if s == "workspace":
        coll = {"email": env["inbox"]["initial_emails"], "calendar": env["calendar"]["initial_events"],
                "drive": env["cloud_drive"]["initial_files"]}[kind]
        return next(x for x in coll if x["id_"] == ident)
    if s == "travel":
        coll = {"hotel": env["hotels"]["hotel_list"], "restaurant": env["restaurants"]["restaurant_list"],
                "car": env["car_rental"]["company_list"]}[kind]
        return next(x for x in coll if x["name"] == ident)
    if s == "banking":
        if kind == "file":
            return env["filesystem"]["files"][ident]
        return env["bank_account"]["transactions" if kind == "transactions" else "scheduled_transactions"]
    if s == "slack":
        if kind == "channels":
            return env["slack"]["channels"]
        return env["slack"]["channel_inbox" if kind == "channel_inbox" else "user_inbox"][ident]


def leaves(o, path=()):
    if isinstance(o, str):
        yield path, o
    elif isinstance(o, dict):
        for k, v in o.items():
            yield from leaves(v, path + (k,))
    elif isinstance(o, list):
        for i, v in enumerate(o):
            yield from leaves(v, path + (i,))


def cp(a, b):
    i = 0
    while i < min(len(a), len(b)) and a[i] == b[i]:
        i += 1
    return i


def cs(a, b, lim):
    i = 0
    while i < lim and a[-1 - i] == b[-1 - i]:
        i += 1
    return i


# vector -> item keys (canary per vector)
VEC_ITEMS = {}
for s in SUITES:
    can = {k: f"QQCANARY{i}QQ" for i, k in enumerate(sorted(S[s].defaults))}
    env_c = S[s].load_env(can)
    for key, (tool, kind, txt) in item_map(s, env_c).items():
        for k, c in can.items():
            if c in txt:
                VEC_ITEMS.setdefault((s, k), []).append(key)
print("vectors located:", {s: sum(1 for (ss, _) in VEC_ITEMS if ss == s) for s in SUITES},
      "of", {s: len(S[s].defaults) for s in SUITES})

DATA_FILE = {("workspace", "email"): "data/suites/workspace/include/inbox.yaml",
             ("workspace", "calendar"): "data/suites/workspace/include/calendar.yaml",
             ("workspace", "drive"): "data/suites/workspace/include/cloud_drive.yaml"}
SUBSET = {("workspace", "email"): "workspace_email", ("workspace", "calendar"): "workspace_calendar",
          ("workspace", "drive"): "workspace_drive", ("travel", "hotel"): "travel_hotel_review",
          ("travel", "restaurant"): "travel_restaurant_review", ("travel", "car"): "travel_car_rental_review",
          ("banking", "file"): "banking_file", ("banking", "transactions"): "banking_transaction",
          ("banking", "scheduled"): "banking_transaction", ("slack", "channels"): "slack_channel",
          ("slack", "channel_inbox"): "slack_message", ("slack", "user_inbox"): "slack_message"}
DOC_TYPE = {"workspace_email": "email", "workspace_calendar": "tool_response", "workspace_drive": "general_document",
            "travel_hotel_review": "tool_response", "travel_restaurant_review": "tool_response",
            "travel_car_rental_review": "tool_response", "banking_file": "general_document",
            "banking_transaction": "tool_response", "slack_channel": "tool_response", "slack_message": "chat"}
RENDER = {"str": "tool_result_to_str -> str(tool_result) (dict/str return value)",
          "yaml": "tool_result_to_str -> yaml.safe_dump(model_dump()).strip()"}


def render_kind(s, kind):
    return "str" if s == "travel" or (s == "banking" and kind == "file") else "yaml"



# ------------------------------------------------------------------ goals of every injection task in every version (ast)
def ev(node, ns):
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant):
                out.append(v.value)
            else:
                out.append(str(ev(v.value, ns)))
        return "".join(out)
    if isinstance(node, ast.Name):
        return ns[node.id]
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return ev(node.left, ns) + ev(node.right, ns)
    raise ValueError(ast.dump(node))


GOALS = collections.defaultdict(list)  # (suite, task_id) -> [(version_dir, goal, file)]
for f in sorted(glob.glob(os.path.join(repo, SRC, "default_suites", "*", "*", "injection_tasks.py"))):
    parts = f.replace("\\", "/").split("/")
    ver, suite = parts[-3], parts[-2]
    tree = ast.parse(open(f, encoding="utf-8").read())
    mod_ns = {}
    for st in tree.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
            try:
                mod_ns[st.targets[0].id] = ev(st.value, mod_ns)
            except Exception:
                pass
        if isinstance(st, ast.ClassDef) and st.name.startswith("InjectionTask"):
            ns = dict(mod_ns)
            for b in st.body:
                if isinstance(b, ast.Assign) and isinstance(b.targets[0], ast.Name):
                    try:
                        ns[b.targets[0].id] = ev(b.value, ns)
                    except Exception:
                        pass
            if "GOAL" in ns:
                GOALS[(suite, "injection_task_" + st.name[len("InjectionTask"):])].append(
                    (ver, ns["GOAL"], os.path.relpath(f, repo).replace("\\", "/")))


def goal_of(s, task, inj):
    best = None
    for ver, g, f in GOALS.get((s, task), []):
        if g in inj and (best is None or len(g) > len(best[1])):
            best = (ver, g, f)
    return best


ATTACK_FILE = {a: "important_instructions_attacks.py" for a in [
    "important_instructions", "important_instructions_no_user_name", "important_instructions_no_model_name",
    "important_instructions_no_names", "important_instructions_wrong_model_name", "important_instructions_wrong_user_name",
    "tool_knowledge"]}
ATTACK_FILE.update({a: "baseline_attacks.py" for a in ["direct", "ignore_previous", "system_message", "injecagent"]})
ATTACK_FILE.update({a: "dos_attacks.py" for a in ["dos", "captcha_dos"]})

# ------------------------------------------------------------------ injection candidates
index = json.load(open(index_path, encoding="utf-8"))
CANARY_CACHE = {}


def canary_leaves(s, vec, key, fast):
    ck = (s, vec, key, fast)
    if ck not in CANARY_CACHE:
        CANARY_CACHE[ck] = (dict(leaves(raw_obj(s, S[s].load_env({vec: "QQQQ"}, fast=fast), key))),
                            dict(leaves(raw_obj(s, S[s].load_env({vec: "ZZZZ"}, fast=fast), key))))
    return CANARY_CACHE[ck]


def make_cand(s, att, task, vec, inj_str, info, key, fast, nfail):
    try:
        env_i = S[s].load_env({vec: inj_str}, fast=fast)
    except Exception:
        nfail["yaml_error"] += 1
        return None
    tool = BASE_ITEMS[s][key][0]
    kind = key[0]
    txt = item_map(s, env_i)[key][2]
    # injected block (after YAML folding) in the raw field; two canaries bound the common prefix/suffix
    o_i = dict(leaves(raw_obj(s, env_i, key)))
    o_1, o_2 = canary_leaves(s, vec, key, fast)
    diff = [p for p in o_i if o_i[p] != o_1.get(p)]
    if len(diff) != 1:
        nfail["field_diff"] += 1
        return None
    p = diff[0]
    a = min(cp(o_i[p], o_1[p]), cp(o_i[p], o_2[p]))
    b = min(cs(o_i[p], o_1[p], min(len(o_i[p]), len(o_1[p])) - a), cs(o_i[p], o_2[p], min(len(o_i[p]), len(o_2[p])) - a))
    block = o_i[p][a:len(o_i[p]) - b].strip()
    loc = ad_lib.locate(txt, block) if block else None
    if not loc:
        nfail["locate"] += 1
        return None
    g = goal_of(s, task, inj_str)
    if g is None and att not in ("dos", "captcha_dos"):
        nfail["goal_unmatched"] += 1
        return None
    return {"suite": s, "attack": att, "task": task, "vector": vec, "key": key, "tool": tool, "kind": kind,
            "subset": SUBSET[(s, kind)], "text": txt, "inj": txt[loc[0]:loc[1]], "inj_raw": inj_str,
            "goal": g, "info": info, "field": list(p)}


import pickle
CACHE = os.environ.get("CANDS_CACHE")
if CACHE and os.path.exists(CACHE):
    cands, nfail = pickle.load(open(CACHE, "rb"))
else:
    cands = []
    nfail = collections.Counter()
    for k, strings in sorted(index.items()):
        s, att, task, vec = k.split("|")
        if att not in ATTACK_FILE or (s, vec) not in VEC_ITEMS:
            nfail["attack_or_vector_skipped"] += 1
            continue
        # one injection string per key: random among the distinct strings the runs used (pipelines differ in model name / version)
        inj_str = random.choice(sorted(strings))
        key = random.choice(VEC_ITEMS[(s, vec)])
        c = make_cand(s, att, task, vec, inj_str, strings[inj_str], key, True, nfail)
        if c:
            cands.append(c)

    # system_message has no released runs/ logs: format its template (baseline_attacks.py) with the latest GOAL
    def vtuple(v):
        t = [int(x) for x in v[1:].split("_")]
        return tuple(t + [0] * (3 - len(t)))


    SYS_TPL = None
    for n in ast.walk(ast.parse(open(os.path.join(repo, SRC, "attacks", "baseline_attacks.py"), encoding="utf-8").read())):
        if isinstance(n, ast.ClassDef) and n.name == "SystemMessageAttack":
            for c in ast.walk(n):
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute) and c.func.attr == "__init__" and c.args:
                    SYS_TPL = ast.literal_eval(c.args[0])
    assert SYS_TPL == "###(system_message) {goal}", SYS_TPL
    for (s_, task), lst in sorted(GOALS.items()):
        ver, goal, gfile = max(lst, key=lambda x: vtuple(x[0]))
        inj_str = SYS_TPL.format(goal=goal, user="the user", model="the AI language model", task="")
        info = {"pipelines": [], "files": [], "user_tasks": [], "benchmark_version": [ver],
                "generated": f"{SRC}/attacks/baseline_attacks.py SystemMessageAttack template .format(goal=GOAL) with GOAL from {gfile}"}
        for (s2, vec), keys in sorted(VEC_ITEMS.items()):
            if s2 != s_:
                continue
            c = make_cand(s_, "system_message", task, vec, inj_str, info, random.choice(keys), True, nfail)
            if c:
                cands.append(c)

    if CACHE:
        pickle.dump((cands, nfail), open(CACHE, "wb"))
print("candidates:", len(cands), dict(nfail), collections.Counter(c["attack"] for c in cands))

# ------------------------------------------------------------------ select injections
random.seed(42)  # selection is independent of whether candidates came from the cache
# template mix: every AgentDojo template that has a non-offensive string, weighted towards the short baseline
# templates so the injected items do not become much longer than the benign ones (length-only AUC)
TPL_Q = json.loads(os.environ.get("TPL_Q", "null")) or {
    "important_instructions": 4, "important_instructions_no_user_name": 2, "important_instructions_no_model_name": 2,
    "important_instructions_no_names": 2, "important_instructions_wrong_model_name": 2,
    "important_instructions_wrong_user_name": 2, "tool_knowledge": 3, "captcha_dos": 3, "dos": 3, "direct": 10,
    "ignore_previous": 9, "system_message": 9, "injecagent": 9}
SUB_Q = json.loads(os.environ.get("SUB_Q", "null")) or {
    "workspace_email": 14, "workspace_calendar": 12, "workspace_drive": 7, "banking_file": 5, "banking_transaction": 2,
    "travel_hotel_review": 6, "travel_restaurant_review": 5, "travel_car_rental_review": 4, "slack_channel": 5}
assert sum(TPL_Q.values()) == N_INJ and sum(SUB_Q.values()) == N_INJ, (sum(TPL_Q.values()), sum(SUB_Q.values()))
FAMILY = lambda a: "ii" if a.startswith("important_instructions") else a

sel, pool = [], []
used_vec, used_goal, used_combo, used_vec_fam = collections.Counter(), collections.Counter(), set(), set()
dead = set()
by_ts = collections.defaultdict(list)
for c in cands:
    by_ts[(c["attack"], c["subset"])].append(c)
for v in by_ts.values():
    random.shuffle(v)
while len(sel) < N_INJ:
    tq = {t: q - sum(1 for x in sel if x["attack"] == t) for t, q in TPL_Q.items()}
    sq = {u: q - sum(1 for x in sel if x["subset"] == u) for u, q in SUB_Q.items()}
    pairs = [(tq[t] / TPL_Q[t] + sq[u] / SUB_Q[u] + random.random() * 0.05, t, u) for t in tq for u in sq
             if tq[t] > 0 and sq[u] > 0 and (t, u) not in dead]
    if not pairs:
        # remaining template slots cannot go to the subsets with quota left: move one subset slot to the subset with
        # the most feasible candidates for that template (overflow), and record it
        left_t = [t for t in tq if tq[t] > 0]
        left_u = [u for u in sq if sq[u] > 0]
        if not left_t:
            break
        moved = False
        for t in left_t:
            for u in sorted(SUB_Q, key=lambda u: -len(by_ts[(t, u)])):
                if (t, u) in dead or u in left_u:
                    continue
                SUB_Q[u] += 1
                SUB_Q[left_u[0]] -= 1
                print("overflow: one", left_u[0], "slot moved to", u, "for", t)
                moved = True
                break
            if moved:
                break
        if not moved:
            print("STUCK: remaining", {t: q for t, q in tq.items() if q}, {u: q for u, q in sq.items() if q})
            break
        continue
    _, t, u = max(pairs)
    opts = [c for c in by_ts[(t, u)] if (c["vector"], c["task"], c["attack"]) not in used_combo
            and (c["vector"], FAMILY(c["attack"])) not in used_vec_fam and len(c["text"]) <= 3000]
    opts.sort(key=lambda c: (used_vec[(c["suite"], c["vector"])], used_goal[(c["suite"], c["task"])], len(c["text"]) // 150))
    ok = None
    for c in opts:
        g = grams(c["text"])
        if near_dup(c["text"], g, pool + existing):
            continue
        ok = c
        break
    if ok is None:
        dead.add((t, u))
        continue
    sel.append(ok)
    pool.append((ok["text"], grams(ok["text"])))
    used_vec[(ok["suite"], ok["vector"])] += 1
    used_goal[(ok["suite"], ok["task"])] += 1
    used_combo.add((ok["vector"], ok["task"], ok["attack"]))
    used_vec_fam.add((ok["vector"], FAMILY(ok["attack"])))
print("selected injections:", len(sel))
for x in sel:  # rebuild with yaml.safe_load (what AgentDojo uses) and require identical output
    y = make_cand(x["suite"], x["attack"], x["task"], x["vector"], x["inj_raw"], x["info"], x["key"], False, collections.Counter())
    assert y and y["text"] == x["text"] and y["inj"] == x["inj"], (x["suite"], x["vector"], x["attack"])
print("pure-python yaml.safe_load rebuild identical for all selected injections")

# ------------------------------------------------------------------ select benign
BEN_Q = json.loads(os.environ.get("BEN_Q", "null")) or {
    "workspace_email": 16, "workspace_calendar": 10, "workspace_drive": 17, "banking_file": 2, "banking_transaction": 1,
    "travel_hotel_review": 4, "travel_restaurant_review": 3, "travel_car_rental_review": 3, "slack_channel": 1,
    "slack_message": 3}
assert sum(BEN_Q.values()) == N_BEN, sum(BEN_Q.values())
vec_of_item = {}
for (s, v), keys in VEC_ITEMS.items():
    for k in keys:
        vec_of_item.setdefault((s, k), []).append(v)
inj_len = collections.defaultdict(list)
for x in sel:
    inj_len[x["subset"]].append(len(x["text"]))
ben_cands = []
for s in SUITES:
    for key, (tool, _, txt) in BASE_ITEMS[s].items():
        kind = key[0]
        ben_cands.append({"suite": s, "key": key, "tool": tool, "kind": kind, "subset": SUBSET[(s, kind)], "text": txt,
                          "vectors": vec_of_item.get((s, key), [])})
ben = []
BEN_VEC_BONUS = int(os.environ.get("BEN_VEC_BONUS", "200"))
for u, q in BEN_Q.items():
    cs_ = [c for c in ben_cands if c["subset"] == u and len(c["text"]) <= 3000]
    target = statistics.median(inj_len[u]) if inj_len.get(u) else statistics.median(len(x["text"]) for x in sel)
    # vector-bearing items (default values) first, then the others closest to the injection length of the subset
    random.shuffle(cs_)
    cs_.sort(key=lambda c: -(len(c["text"]) + (BEN_VEC_BONUS if c["vectors"] else 0)))
    got = 0
    for c in cs_:
        if got == q:
            break
        g = grams(c["text"])
        if near_dup(c["text"], g, pool + existing):
            continue
        ben.append(c)
        pool.append((c["text"], g))
        got += 1
    if got < q:
        print("benign short in", u, got, "/", q)
print("selected benign:", len(ben))


# ------------------------------------------------------------------ records
def data_file(s, kind):
    return SRC + "/" + DATA_FILE.get((s, kind), f"data/suites/{s}/environment.yaml")


def item_id(key):
    kind, ident = key
    return {"kind": kind, "id": ident}


vec_uts = collections.defaultdict(set)
for k, strings in index.items():
    s, att, task, vec = k.split("|")
    for e in strings.values():
        vec_uts[(s, vec)].update(e["user_tasks"])

random.shuffle(sel)
random.shuffle(ben)
recs = []
for i, x in enumerate(sel, 1):
    g = x["goal"]
    info = x["info"]
    o = {"url": URL, "commit": COMMIT, "suite": x["suite"], "file": data_file(x["suite"], x["kind"]),
         "injection_vectors_file": f"{SRC}/data/suites/{x['suite']}/injection_vectors.yaml",
         "injection_vector": x["vector"], "injection_vector_description": S[x["suite"]].descriptions[x["vector"]],
         "item": item_id(x["key"]), "tool": x["tool"], "rendering": RENDER[render_kind(x["suite"], x["kind"])],
         "attack_template": x["attack"], "attack_file": f"{SRC}/attacks/{ATTACK_FILE[x['attack']]}",
         "injection_task_id": None if x["attack"] in ("dos", "captcha_dos") else x["task"],
         "injection_task_goal": g[1] if g else None, "injection_task_file": g[2] if g else None,
         "injection_string_source": ({"run_log": info["files"][0], "pipelines": info["pipelines"],
                                      "benchmark_version": info["benchmark_version"]} if info["files"] else
                                     {"generated": info["generated"], "benchmark_version": info["benchmark_version"]}),
         "user_task_id": info["files"][0].split("/")[-3] if info["files"] else None,
         "user_tasks_exposing_vector": sorted(vec_uts[(x["suite"], x["vector"])], key=lambda t: int(t.split("_")[-1]))}
    notes = (f"Output of AgentDojo tool `{x['tool']}` for one {x['kind']} item. Environment assembled like "
             "TaskSuite.load_and_inject_default_environment (environment.yaml loaded with !include, dumped with "
             "double-quoted strings, injection placeholders .format()-ed, re-parsed with yaml.safe_load), only this "
             "vector injected, all others at defaults. " + (
                 "Injection string copied verbatim from the run log's 'injections' field (exactly what AgentDojo's "
                 "attack generated). " if info["files"] else
                 "system_message has no released run logs: injection string = SystemMessageAttack template "
                 "'###(system_message) {goal}' formatted with the injection task's latest GOAL (as FixedJailbreakAttack.attack does). ")
             + "injected_instruction = injected block as it appears in the rendered tool output (after YAML folding / quoting).")
    if x["attack"] in ("dos", "captcha_dos"):
        notes += " DoS attack: goal-independent string (run log from injection_task listed in run_log)."
    recs.append({"id": f"agentdojo-inj-{i:02d}", "label": "injection", "source": "AgentDojo", "subset": x["subset"],
                 "doc_type": DOC_TYPE[x["subset"]], "text": x["text"], "injected_instruction": x["inj"],
                 "origin": o, "notes": notes, "core": False})
for i, x in enumerate(ben, 1):
    o = {"url": URL, "commit": COMMIT, "suite": x["suite"], "file": data_file(x["suite"], x["kind"]),
         "item": item_id(x["key"]), "tool": x["tool"], "rendering": RENDER[render_kind(x["suite"], x["kind"])],
         "injection_vectors_in_item": x["vectors"],
         "injection_vectors_file": f"{SRC}/data/suites/{x['suite']}/injection_vectors.yaml" if x["vectors"] else None,
         "attack_template": None, "injection_task_id": None,
         "user_tasks_exposing_vector": sorted(set().union(*[vec_uts[(x["suite"], v)] for v in x["vectors"]]),
                                              key=lambda t: int(t.split("_")[-1])) if x["vectors"] else None}
    notes = (f"Output of AgentDojo tool `{x['tool']}` for one {x['kind']} item of the default (uninjected) environment, "
             "assembled like TaskSuite.load_and_inject_default_environment with every injection vector at its "
             "default value. ")
    notes += ("Item contains injection vector(s) " + ", ".join(x["vectors"]) + " at their benign default value(s)."
              if x["vectors"] else "Item has no injection vector (ordinary environment item).")
    recs.append({"id": f"agentdojo-ben-{i:02d}", "label": "benign", "source": "AgentDojo", "subset": x["subset"],
                 "doc_type": DOC_TYPE[x["subset"]], "text": x["text"], "injected_instruction": None,
                 "origin": o, "notes": notes, "core": False})

with open(out_path, "w", encoding="utf-8") as f:
    for r in recs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
json.dump({"inj_subsets": collections.Counter(x["subset"] for x in sel),
           "ben_subsets": collections.Counter(x["subset"] for x in ben),
           "templates": collections.Counter(x["attack"] for x in sel),
           "vectors": collections.Counter(f"{x['suite']}|{x['vector']}" for x in sel),
           "tasks": collections.Counter(f"{x['suite']}|{x['task']}" for x in sel if x['attack'] not in ('dos', 'captcha_dos'))},
          open(plan_out, "w", encoding="utf-8"), indent=1)
L = {lab: [len(r["text"]) for r in recs if r["label"] == lab] for lab in ("injection", "benign")}
print("medians", {k: statistics.median(v) for k, v in L.items() if v}, "n", {k: len(v) for k, v in L.items()})
