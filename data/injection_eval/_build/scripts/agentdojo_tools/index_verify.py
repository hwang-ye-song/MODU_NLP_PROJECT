"""Index the injection strings AgentDojo actually used (runs/<pipeline>/<suite>/<user_task>/<attack>/<inj_task>.json,
field 'injections') and verify our re-assembly + tool rendering against the tool outputs recorded in the same logs.
usage: python index_verify.py <agentdojo_repo> <out_index.json> [max_verify_files_per_group]
"""
import ast, collections, glob, json, os, random, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import yaml
import ad_lib

repo, out = sys.argv[1], sys.argv[2]
MAXV = int(sys.argv[3]) if len(sys.argv) > 3 else 25
PIPES = ["gpt-4o-2024-05-13", "Meta-SecAlign-70B", "claude-3-7-sonnet-20250219", "gemini-2.0-flash-001", "command-r-plus",
         "claude-3-5-sonnet-20241022", "meta-llama_Llama-3.3-70B-Instruct", "gpt-4o-mini-2024-07-18"]
SKIP_ATT = {"none", "manual", "swearwords_dos", "felony_dos", "offensive_email_dos"}
SUITES = ["workspace", "travel", "banking", "slack"]
random.seed(42)
suites = {s: ad_lib.Suite(repo, s) for s in SUITES}

index = collections.defaultdict(dict)  # "suite|attack|inj_task|vector" -> {injection: info}
vfiles = collections.defaultdict(list)
for p in PIPES:
    for s in SUITES:
        for f in sorted(glob.glob(os.path.join(repo, "runs", p, s, "user_task_*", "*", "injection_task_*.json"))):
            parts = f.replace("\\", "/").split("/")
            ut, att, it = parts[-3], parts[-2], parts[-1][:-5]
            if att in SKIP_ATT:
                continue
            d = json.load(open(f, encoding="utf-8"))
            inj = d.get("injections") or {}
            for vec, val in inj.items():
                k = f"{s}|{att}|{it}|{vec}"
                e = index[k].setdefault(val, {"pipelines": [], "files": [], "user_tasks": [], "benchmark_version": set()})
                if p not in e["pipelines"]:
                    e["pipelines"].append(p)
                if len(e["files"]) < 3:
                    e["files"].append(os.path.relpath(f, repo).replace("\\", "/"))
                if ut not in e["user_tasks"]:
                    e["user_tasks"].append(ut)
                e["benchmark_version"].add(d.get("benchmark_version") or "unrecorded")
            vfiles[(p, s, att)].append(f)

# ---------------------------------------------------------------- verification
env_cache = {}


def env_for(s, inj):
    key = (s, tuple(sorted(inj.items())))
    if key not in env_cache:
        env_cache[key] = suites[s].load_env(inj)
    return env_cache[key]


def content_str(m):
    c = m["content"]
    if isinstance(c, list):
        c = "".join(x.get("content", "") or "" for x in c)
    return c


stats = collections.Counter()
mism = collections.defaultdict(list)
for (p, s, att), files in sorted(vfiles.items()):
    for f in random.sample(files, min(MAXV, len(files))):
        d = json.load(open(f, encoding="utf-8"))
        inj = d.get("injections") or {}
        try:
            env = env_for(s, inj)
        except Exception as ex:  # malformed yaml after injection
            stats[("env_error", s)] += 1
            continue
        its = {k: txt for k, tool, kind, txt in ad_lib.items(s, env)}
        for m in d["messages"]:
            if m["role"] != "tool" or m.get("error"):
                continue
            fn = (m.get("tool_call") or {}).get("function")
            args = (m.get("tool_call") or {}).get("args") or {}
            c = content_str(m)
            if not c:
                continue
            res = None
            if s == "workspace" and fn in ("search_emails", "get_received_emails", "search_calendar_events",
                                             "get_day_calendar_events", "search_files_by_filename", "search_files",
                                             "list_files", "get_file_by_id"):
                kind = {"search_emails": "email", "get_received_emails": "email"}.get(fn, "calendar" if "calendar" in fn else "drive")
                try:
                    parsed = yaml.safe_load(c)
                except Exception:
                    continue
                elems = parsed if isinstance(parsed, list) else [parsed]
                for el in elems:
                    if not isinstance(el, dict) or "id_" not in el or (kind, el["id_"]) not in its:
                        continue
                    mine = its[(kind, el["id_"])]
                    if fn == "get_file_by_id":
                        ok = mine == c
                    else:
                        ok = (mine if kind != "drive" else ad_lib.ydump([yaml.safe_load(mine)])) in c if kind == "drive" else mine in c
                    if kind == "drive" and fn != "get_file_by_id":
                        ok = ad_lib.ydump([yaml.safe_load(mine)]) in c
                    stats[(s, fn, ok)] += 1
                    if not ok and len(mism[(s, fn)]) < 3:
                        mism[(s, fn)].append((os.path.relpath(f, repo), el["id_"]))
            elif s == "banking" and fn == "read_file":
                k = ("file", args.get("file_path"))
                if k in its:
                    ok = its[k] == c
                    stats[(s, fn, ok)] += 1
                    if not ok and len(mism[(s, fn)]) < 3:
                        mism[(s, fn)].append((os.path.relpath(f, repo), k))
            elif s == "banking" and fn in ("get_most_recent_transactions", "get_scheduled_transactions"):
                k = ("transactions", "all") if fn == "get_most_recent_transactions" else ("scheduled", "all")
                if fn == "get_most_recent_transactions" and int(args.get("n", 100)) < 5:
                    continue
                ok = c.startswith(its[k])
                stats[(s, fn, ok)] += 1
                if not ok and len(mism[(s, fn)]) < 3:
                    mism[(s, fn)].append((os.path.relpath(f, repo), k))
            elif s == "slack" and fn in ("get_channels", "read_channel_messages", "read_inbox"):
                k = ("channels", "all") if fn == "get_channels" else (
                    ("channel_inbox", args.get("channel")) if fn == "read_channel_messages" else ("user_inbox", args.get("user")))
                if k in its:
                    ok = c.startswith(its[k])
                    stats[(s, fn, ok)] += 1
                    if not ok and len(mism[(s, fn)]) < 3:
                        mism[(s, fn)].append((os.path.relpath(f, repo), k))
            elif s == "travel" and fn.startswith("get_rating_reviews_for_"):
                kind = {"hotels": "hotel", "restaurants": "restaurant", "car_rental": "car"}[fn[len("get_rating_reviews_for_"):]]
                try:
                    parsed = ast.literal_eval(c)
                except Exception:
                    continue
                for name, val in parsed.items():
                    if (kind, name) in its:
                        ok = ast.literal_eval(its[(kind, name)])[name] == val and str({name: val}) == its[(kind, name)]
                        stats[(s, fn, ok)] += 1
                        if not ok and len(mism[(s, fn)]) < 3:
                            mism[(s, fn)].append((os.path.relpath(f, repo), name))

print("verification (suite, tool, match): count")
for k, v in sorted(stats.items(), key=str):
    print("  ", k, v)
for k, v in mism.items():
    print("MISMATCH samples", k, v)

ser = {k: {inj: dict(e, benchmark_version=sorted(e["benchmark_version"])) for inj, e in v.items()} for k, v in index.items()}
json.dump(ser, open(out, "w", encoding="utf-8"), ensure_ascii=False)
print("index keys:", len(ser), "distinct injection strings:", sum(len(v) for v in ser.values()))
cnt = collections.Counter(k.split("|")[1] for k in ser)
print(sorted(cnt.items()))
