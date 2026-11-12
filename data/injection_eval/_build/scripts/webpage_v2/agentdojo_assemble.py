"""Assemble AgentDojo slack-suite web pages (benign defaults + injected) exactly as
TaskSuite.load_and_inject_default_environment does, without importing AgentDojo code:
  env_text = yaml.dump(yaml.load(environment.yaml), default_flow_style=False)  [all str double-quoted]
  injected = env_text.format(**{defaults, **injections}); env = yaml.safe_load(injected)
  page = env['web']['web_content'][url]
Attack strings / goals are read from the repo source with `ast` (no execution of repo code).
Then verify against get_webpage outputs recorded in the released runs/ logs.
usage: python agentdojo_assemble.py <agentdojo_repo_dir> <out_json>
"""
import ast, glob, json, os, sys
import yaml

repo, out = sys.argv[1], sys.argv[2]
src = os.path.join(repo, "src", "agentdojo")


def quoted_presenter(dumper, data):  # same as agentdojo/yaml_loader.py
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style='"')


class QDumper(yaml.Dumper):
    pass


QDumper.add_representer(str, quoted_presenter)


def read_suite_file(path):
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)  # slack env has no !include, SafeLoader == ImportLoader here
    return yaml.dump(data, Dumper=QDumper, default_flow_style=False)


env_text = read_suite_file(os.path.join(src, "data/suites/slack/environment.yaml"))
vec_text = read_suite_file(os.path.join(src, "data/suites/slack/injection_vectors.yaml"))
defaults = {k: v["default"] for k, v in yaml.safe_load(vec_text).items()}


def load_env(injections):
    inj = dict(defaults)
    inj.update(injections)
    return yaml.safe_load(env_text.format(**inj))


# ---- goals from injection_tasks.py via ast
def eval_joined(node, consts):
    if isinstance(node, ast.Constant):
        return node.value
    parts = []
    for v in node.values:
        if isinstance(v, ast.Constant):
            parts.append(v.value)
        else:
            parts.append(consts[v.value.id])
    return "".join(parts)


goals = {}
tree = ast.parse(open(os.path.join(src, "default_suites/v1/slack/injection_tasks.py"), encoding="utf-8").read())
for cls in [n for n in tree.body if isinstance(n, ast.ClassDef)]:
    consts = {}
    for st in cls.body:
        if isinstance(st, ast.Assign) and isinstance(st.targets[0], ast.Name):
            name = st.targets[0].id
            if name.startswith("_") and isinstance(st.value, ast.Constant):
                consts[name] = st.value.value
            if name == "GOAL":
                num = int(cls.name.replace("InjectionTask", ""))
                goals[f"injection_task_{num}"] = eval_joined(st.value, consts)


# ---- attack strings via ast
def str_of(node):
    return ast.literal_eval(node)


attacks = {}
t = ast.parse(open(os.path.join(src, "attacks/important_instructions_attacks.py"), encoding="utf-8").read())
for cls in [n for n in t.body if isinstance(n, ast.ClassDef)]:
    for st in cls.body:
        if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "_JB_STRING":
            attacks[cls.name] = str_of(st.value)
t = ast.parse(open(os.path.join(src, "attacks/baseline_attacks.py"), encoding="utf-8").read())
for cls in [n for n in t.body if isinstance(n, ast.ClassDef)]:
    for n in ast.walk(cls):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "__init__" and n.args:
            attacks[cls.name] = str_of(n.args[0])
t = ast.parse(open(os.path.join(src, "attacks/dos_attacks.py"), encoding="utf-8").read())
for cls in [n for n in t.body if isinstance(n, ast.ClassDef)]:
    for st in cls.body:
        if isinstance(st, ast.Assign) and getattr(st.targets[0], "id", "") == "_DOS_STRING":
            attacks[cls.name] = str_of(st.value)

# attack name -> (template, user, model-mode)
ATT = {
    "important_instructions": ("ImportantInstructionsAttack", "Emma Johnson", "model"),
    "important_instructions_no_user_name": ("ImportantInstructionsAttack", "the user", "model"),
    "important_instructions_no_model_name": ("ImportantInstructionsAttack", "Emma Johnson", "default"),
    "important_instructions_no_names": ("ImportantInstructionsAttack", "the user", "default"),
    "important_instructions_wrong_user_name": ("ImportantInstructionsAttack", "Mark Smith", "model"),
    "direct": ("DirectAttack", None, None),
    "ignore_previous": ("IgnorePreviousAttack", None, None),
    "system_message": ("SystemMessageAttack", None, None),
    "injecagent": ("InjecAgentAttack", None, None),
    "dos": ("DoSAttack", "Emma Johnson", "model"),
    "captcha_dos": ("CaptchaDoSAttack", "Emma Johnson", "model"),
}

# vector -> url
base_env = load_env({})
canary_env = load_env({k: f"<CANARY---{k}--->" for k in defaults})
vec_url = {}
for url, txt in canary_env["web"]["web_content"].items():
    for k in defaults:
        if f"<CANARY---{k}--->" in txt:
            vec_url[k] = url


def injection_string(attack, goal, model_name):
    key, user, mode = ATT[attack]
    tpl = attacks[key]
    model = model_name if mode == "model" else "the AI language model"
    return tpl.format(goal=goal, user=user or "the user", model=model, task="")


# ---- verification against runs/ logs + vector->user_task mapping
vec_user_tasks = {}
checked = matched = 0
mism = []
for f in glob.glob(os.path.join(repo, "runs", "*", "slack", "user_task_*", "*", "injection_task_*.json")):
    parts = f.replace("\\", "/").split("/")
    model_dir, ut, attack, it = parts[-5], parts[-3], parts[-2], parts[-1][:-5]
    if attack not in ATT and attack != "none":
        continue
    d = json.load(open(f, encoding="utf-8"))
    inj = d.get("injections") or {}
    for k in inj:
        vec_user_tasks.setdefault(k, set()).add(ut)
    if attack == "none" or not inj:
        continue
    env = load_env(inj)
    for m in d["messages"]:
        if m["role"] == "tool" and (m.get("tool_call") or {}).get("function") == "get_webpage":
            url = m["tool_call"]["args"].get("url", "")
            url = url[8:] if url.startswith("https://") else url[7:] if url.startswith("http://") else url
            if url in env["web"]["web_content"] and m["content"] is not None and m.get("error") is None:
                checked += 1
                content = m["content"] if isinstance(m["content"], str) else "".join(c.get("content", "") for c in m["content"])
                if content == env["web"]["web_content"][url]:
                    matched += 1
                else:
                    mism.append(model_dir)
    # check that the stored injection equals what our template produces (model name from MODEL_NAMES)
print("runs get_webpage outputs checked:", checked, "matched:", matched, "mismatches by pipeline:", __import__("collections").Counter(mism))

# verify injection strings themselves for important_instructions on gpt-4o run
f = glob.glob(os.path.join(repo, "runs", "gpt-4o-2024-05-13", "slack", "user_task_1", "important_instructions", "injection_task_2.json"))[0]
d = json.load(open(f, encoding="utf-8"))
print("template check:", list(d["injections"].values())[0] == injection_string("important_instructions", goals["injection_task_2"], "GPT-4"))

json.dump({
    "goals": goals,
    "attacks_raw": attacks,
    "vec_url": vec_url,
    "vec_user_tasks": {k: sorted(v) for k, v in vec_user_tasks.items()},
    "benign_pages": base_env["web"]["web_content"],
    "env_dump_len": len(env_text),
}, open(out, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print("goals", goals)
print("vec_url", vec_url)
print({k: sorted(v) for k, v in vec_user_tasks.items()})
