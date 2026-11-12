"""Collect exclusion rows/texts and summarize the existing 80. Usage: excl.py <WD> <out_excl.json>"""
import json, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
wd, out = sys.argv[1:3]
files = [f"{wd}/_build/parts_v2/llmail_injection.jsonl", f"{wd}/_build/ja_llmail_candidates.jsonl",
         f"{wd}/judge_attack/dataset_ja_600.jsonl"]
rows, texts, ids = set(), [], []
for p in files:
    n = nr = 0
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        o = r.get("origin") or {}
        if r.get("source") != "LLMail-Inject":
            continue
        n += 1
        texts.append([r["id"], r["text"]])
        if "row_index" in o:
            rows.add(int(o["row_index"])); nr += 1
    print(p, "llmail recs", n, "with row_index", nr)
print("excluded rows", len(rows))
ex = [json.loads(l) for l in open(files[0], encoding="utf-8")]
print("existing scen", sorted(Counter(r["origin"]["scenario"] for r in ex).items()))
print("existing strat", Counter(r["origin"].get("success_stratum", "core") for r in ex))
tm = Counter(r["origin"]["team_id"] for r in ex)
print("existing teams", len(tm), tm.most_common(5))
ja = [json.loads(l) for l in open(files[1], encoding="utf-8")]
print("ja keys", list(ja[0]["origin"].keys()))
print("ja teams", len({r["origin"].get("team_id") for r in ja}))
json.dump({"rows": sorted(rows), "texts": texts, "teams80": dict(tm),
           "scen80": dict(Counter(r["origin"]["scenario"] for r in ex))}, open(out, "w", encoding="utf-8"), ensure_ascii=False)
