"""Literal task criterion: difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() < 0.6 on raw texts,
reserve vs every text in the three exclusion files and within the reserve.
Usage: rawcheck.py <reserve.jsonl> <WD>"""
import json, sys
from difflib import SequenceMatcher
from multiprocessing import Pool

sys.stdout.reconfigure(encoding="utf-8")
res_p, wd = sys.argv[1:3]
res = [json.loads(l) for l in open(res_p, encoding="utf-8")]
ex = []
for p in [wd + "/_build/parts_v2/llmail_injection.jsonl", wd + "/_build/ja_llmail_candidates.jsonl",
          wd + "/judge_attack/dataset_ja_600.jsonl"]:
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        if r.get("source") == "LLMail-Inject":
            ex.append((r["id"], r["text"]))


def best(i):
    t = res[i]["text"]
    cands = ex + [(r["id"], r["text"]) for j, r in enumerate(res) if j != i]
    m = (0.0, "")
    for cid, s in cands:
        sm = SequenceMatcher(None, t, s, autojunk=False)
        if sm.real_quick_ratio() > m[0] and sm.quick_ratio() > m[0]:
            r = sm.ratio()
            if r > m[0]:
                m = (r, cid)
    return res[i]["id"], m


if __name__ == "__main__":
    with Pool(10) as mp:
        out = mp.map(best, range(len(res)))
    worst = max(m[0] for _, m in out)
    for rid, (r, cid) in out:
        print(f"{rid}: max raw ratio {r:.3f} vs {cid}")
    print("ALL < 0.6" if worst < 0.6 else "FAIL", f"(max {worst:.3f})")
