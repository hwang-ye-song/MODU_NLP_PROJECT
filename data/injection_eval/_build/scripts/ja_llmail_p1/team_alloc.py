"""Per-team availability of eligible rows by detector/tier. Usage: team_alloc.py <pool> <overrides>"""
import json, re, sys, unicodedata
from collections import Counter, defaultdict
sys.stdout.reconfigure(encoding="utf-8")
pool = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
ovr = {int(k): v for k, v in json.load(open(sys.argv[2], encoding="utf-8")).items()}
AI_CUE = re.compile(r"\b(assistant|a\.?i\.?|llm|language model|model|agent|bot|summar\w*|tool|api|function|"
                    r"system|automat\w*|processing|process(ed)?|script|execute|dispatch|json|send_?e?mail|"
                    r"instruction|prompt|user|log)\b|<\||\{\s*\"", re.I)
T = defaultdict(lambda: defaultdict(Counter))
for r in pool:
    o = ovr.get(r["row_index"], {})
    if o.get("exclude"):
        continue
    t = unicodedata.normalize("NFKC", r["text"]); L = [c for c in t if c.isalpha()]
    if sum(1 for c in L if not c.isascii()) / max(1, len(L)) > 0.12:
        continue
    f = r["f"]
    if r["tier"] == "partial":
        if not ((f["goal_addr"] or f["goal_body"]) and f["send_verb"]) or not AI_CUE.search(r["text"]):
            continue
    T[r["team_id"]][r["detector"]][r["tier"]] += 1
for d in ["llm_judge", "all", "task_tracker", "prompt_shield"]:
    tf = [k for k in T if T[k][d]["full"]]
    tp = [k for k in T if T[k][d]["full"] + T[k][d]["partial"]]
    cap = sum(min(3, T[k][d]["full"] + T[k][d]["partial"]) for k in tp)
    print(d, "teams_full", len(tf), "teams_any", len(tp), "cap3_max", cap,
          "rows full", sum(T[k][d]["full"] for k in T), "partial", sum(T[k][d]["partial"] for k in T))
both = [k for k in T if T[k]["llm_judge"].total() and T[k]["all"].total()]
print("teams with both judge & all:", len(both))
