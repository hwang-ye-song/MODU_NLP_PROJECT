"""Explore tool outputs in runs/ logs: which tools expose which injection vectors (canary-free:
look for the injection string fragments) -- prints sample outputs per (suite, tool)."""
import glob, json, os, sys, collections
repo, suite = sys.argv[1], sys.argv[2]
model = sys.argv[3] if len(sys.argv) > 3 else "gpt-4o-2024-05-13"
seen = collections.Counter()
samples = {}
for f in sorted(glob.glob(os.path.join(repo, "runs", model, suite, "user_task_*", "important_instructions", "injection_task_*.json"))):
    d = json.load(open(f, encoding="utf-8"))
    for m in d["messages"]:
        if m["role"] != "tool":
            continue
        fn = (m.get("tool_call") or {}).get("function")
        c = m["content"]
        if isinstance(c, list):
            c = "".join(x.get("content", "") or "" for x in c)
        c = c or ""
        has = "<INFORMATION>" in c
        seen[(fn, has)] += 1
        if (fn, has) not in samples:
            samples[(fn, has)] = (os.path.relpath(f, repo), c[:1200])
for k, v in sorted(seen.items(), key=lambda x: str(x)):
    print(k, v)
for k, (f, c) in samples.items():
    print("=====", k, f)
    print(c)
