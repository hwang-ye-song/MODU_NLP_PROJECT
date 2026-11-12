import sys, json, os, difflib, yaml
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ad_lib
repo = sys.argv[1]; rel = sys.argv[2]; s = sys.argv[3]; fn = sys.argv[4]; kind = sys.argv[5]; ident = sys.argv[6]
d = json.load(open(os.path.join(repo, rel), encoding="utf-8"))
S = ad_lib.Suite(repo, s); env = S.load_env(d.get("injections") or {})
its = {k: t for k, tool, kd, t in ad_lib.items(s, env)}
mine = its[(kind, ident)]
for m in d["messages"]:
    if m["role"] == "tool" and (m.get("tool_call") or {}).get("function") == fn:
        c = m["content"]; c = "".join(x.get("content","") or "" for x in c) if isinstance(c, list) else c
        if kind in ("email","calendar","drive"):
            el = [e for e in (yaml.safe_load(c) if isinstance(yaml.safe_load(c), list) else [yaml.safe_load(c)]) if isinstance(e, dict) and e.get("id_") == ident]
            if not el: continue
            theirs = ad_lib.ydump([el[0]]) if kind != "drive" or fn != "get_file_by_id" else c
            mine2 = mine if kind != "drive" else ad_lib.ydump([yaml.safe_load(mine)])
        else:
            theirs, mine2 = c, mine
        for l in difflib.unified_diff(mine2.splitlines(), theirs.splitlines(), lineterm="", n=1):
            print(l[:300])
        break
