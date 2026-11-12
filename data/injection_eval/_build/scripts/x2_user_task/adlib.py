"""Static (AST-only) extraction of AgentDojo user-task prompts and ground-truth tool names. Never imports repo code."""
import ast, os, re, glob, json
VERSIONS = ["v1", "v1_1", "v1_1_1", "v1_1_2", "v1_2", "v1_2_1", "v1_2_2"]

class Unresolved(Exception): pass

def ev(node, env):
    if isinstance(node, ast.Constant): return node.value
    if isinstance(node, ast.Name):
        if node.id in env: return env[node.id]
        raise Unresolved(node.id)
    if isinstance(node, ast.JoinedStr):
        out = []
        for v in node.values:
            if isinstance(v, ast.Constant): out.append(str(v.value))
            else:
                val = ev(v.value, env)
                if v.format_spec is not None: raise Unresolved("fmt")
                if v.conversion not in (-1, None): raise Unresolved("conv")
                out.append(str(val))
        return "".join(out)
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        return ev(node.left, env) + ev(node.right, env)
    raise Unresolved(type(node).__name__)

def parse_file(path, mod_env):
    src = open(path, encoding="utf-8").read()
    tree = ast.parse(src)
    env = dict(mod_env)
    for n in tree.body:
        if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
            try: env[n.targets[0].id] = ev(n.value, env)
            except Unresolved: pass
    tasks = {}
    for n in tree.body:
        if isinstance(n, ast.ClassDef) and re.fullmatch(r"UserTask\d+", n.name):
            cenv = dict(env); prompt = None; err = None
            for b in n.body:
                if isinstance(b, (ast.Assign, ast.AnnAssign)):
                    tgt = b.targets[0] if isinstance(b, ast.Assign) else b.target
                    if isinstance(tgt, ast.Name) and b.value is not None:
                        try:
                            cenv[tgt.id] = ev(b.value, cenv)
                            if tgt.id == "PROMPT": prompt = cenv[tgt.id]
                        except Unresolved as e:
                            if tgt.id == "PROMPT": err = str(e)
            seg = ast.get_source_segment(src, n)
            funcs = sorted(set(re.findall(r'function\s*=\s*"(\w+)"', seg)))
            tid = "user_task_" + n.name[len("UserTask"):]
            tasks[tid] = {"prompt": prompt, "err": err, "funcs": funcs, "file": path}
    return tasks

def load_user_tasks(repo):
    base = os.path.join(repo, "src", "agentdojo", "default_suites")
    out = {}
    for suite in ["banking", "slack", "travel", "workspace"]:
        tasks = {}
        for v in VERSIONS:
            p = os.path.join(base, v, suite, "user_tasks.py")
            if os.path.exists(p):
                for tid, t in parse_file(p, {}).items():
                    t["version"] = v
                    tasks[tid] = t  # later version overrides
        out[suite] = tasks
    return out

def log_prompt(repo, suite, tid):
    for f in sorted(glob.glob(os.path.join(repo, "runs", "*", suite, tid, "none", "none.json"))):
        try:
            d = json.load(open(f, encoding="utf-8"))
            for m in d["messages"]:
                if m["role"] == "user":
                    c = m["content"]
                    if isinstance(c, list): c = "".join(x.get("content", "") for x in c if isinstance(x, dict))
                    return c, f
        except Exception: continue
    return None, None
