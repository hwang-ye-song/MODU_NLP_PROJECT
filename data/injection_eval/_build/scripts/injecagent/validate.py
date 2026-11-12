"""Validate output. Usage: python -I validate.py <out_jsonl> <repo_dir>"""
import json, sys, ast, re, subprocess, collections
out, repo = sys.argv[1], sys.argv[2]
raw = open(out, "rb").read()
raw.decode("utf-8")
lines = raw.decode("utf-8").split("\n")
assert lines[-1] == "" and all(lines[:-1]), "trailing newline / empty lines"
rows = [json.loads(l) for l in lines[:-1]]
assert len(rows) == 25, len(rows)
KEYS = ["id", "label", "source", "subset", "text", "injected_instruction", "origin", "notes"]
files = {}
def load(f):
    if f not in files:
        p = f"{repo}/{f}"
        files[f] = [json.loads(l) for l in open(p, encoding="utf-8")] if f.endswith(".jsonl") else json.load(open(p, encoding="utf-8"))
    return files[f]
cnt = collections.Counter((r["label"], r["subset"]) for r in rows)
assert cnt == {("injection", "dh_base"): 8, ("injection", "ds_base"): 7, ("benign", "template_benign"): 10}, cnt
assert len({r["id"] for r in rows}) == 25
sha = rows[0]["origin"]["commit"]
inj_tools, ben_tools, ben_texts = set(), set(), set()
bad_words = re.compile(r"\b(ignore|disregard|assistant|agent|AI|send|transfer|delete|share|forward|email|tool|instruction|please)\b", re.I)
for r in rows:
    assert list(r) == KEYS, list(r)
    assert r["source"] == "InjecAgent" and r["origin"]["url"] == "https://github.com/uiuc-kang-lab/InjecAgent" and r["origin"]["commit"] == sha
    o = r["origin"]; recs = load(o["file"]); c = recs[o["index"]]
    assert c["User Tool"] == o["user_tool"]
    assert isinstance(json.loads(r["text"]), str)
    if r["label"] == "injection":
        assert re.fullmatch(r"injecagent-inj-\d\d", r["id"]) and "inserted_benign_text" not in o
        assert r["text"] == c["Tool Response"] and r["injected_instruction"] == c["Attacker Instruction"]
        assert o["attacker_tools"] == c["Attacker Tools"]
        assert r["injected_instruction"] in r["text"]
        assert json.loads(r["text"]) == c["Tool Response Template"].replace("<Attacker Instruction>", c["Attacker Instruction"])
        inj_tools.add(o["user_tool"])
    else:
        assert re.fullmatch(r"injecagent-ben-\d\d", r["id"]) and r["injected_instruction"] is None and o["attacker_tools"] == []
        s = o["inserted_benign_text"]
        assert "<Attacker Instruction>" not in r["text"]
        tmpl = c["Tool Response Template"]
        inner = json.loads(r["text"])
        assert inner == tmpl.replace("<Attacker Instruction>", s)   # rest of template byte-identical
        pre, post = tmpl.split("<Attacker Instruction>")
        assert inner.startswith(pre) and inner.endswith(post)
        assert isinstance(ast.literal_eval(inner), dict)             # inner literal parses as a dict
        assert r["text"] == json.dumps(inner)                        # same serialization as originals
        assert s.isascii() and "'" not in s and '"' not in s
        m = bad_words.findall(s); assert not m, (r["id"], m)
        ben_tools.add(o["user_tool"]); ben_texts.add(tmpl)
assert not (inj_tools & ben_tools), inj_tools & ben_tools
assert len(ben_tools) == 10 and len(ben_texts) == 10
# diversity summary
inj = [r for r in rows if r["label"] == "injection"]
print("OK. commit", sha)
print("inj user tools:", len(inj_tools), sorted(inj_tools))
print("ben user tools:", len(ben_tools), sorted(ben_tools))
print("distinct attacker tool sets:", len({tuple(r["origin"]["attacker_tools"]) for r in inj}), "distinct instructions:", len({r["injected_instruction"] for r in inj}))
for r in inj:
    inner = json.loads(r["text"])
    try: ast.literal_eval(inner); p = "literal-ok"
    except Exception: p = "literal-fail"
    print(" ", r["id"], r["subset"], r["origin"]["index"], r["origin"]["user_tool"], r["origin"]["attacker_tools"], p)
for r in rows:
    if r["label"] == "benign": print(" ", r["id"], r["origin"]["user_tool"], "|", r["origin"]["inserted_benign_text"])
