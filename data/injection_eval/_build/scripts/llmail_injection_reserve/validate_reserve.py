"""Validate the reserve file. Usage: validate_reserve.py <reserve.jsonl> <WD>
Checks: valid JSON, 20 records, ids llmail-inj-r01..r20 unique and not used elsewhere, schema fields,
injected_instruction substring, text <= 3000 and == "Subject: ...\\n\\n...", rows not used in the three
exclusion files, team cap, and prints level/team/stratum/length summaries."""
import glob, json, statistics, sys
from collections import Counter
sys.stdout.reconfigure(encoding="utf-8")
path, wd = sys.argv[1:3]
recs = [json.loads(l) for l in open(path, encoding="utf-8")]
assert len(recs) == 20, len(recs)
ids = [r["id"] for r in recs]
assert ids == [f"llmail-inj-r{i:02d}" for i in range(1, 21)], ids
other_ids, used_rows = set(), set()
for p in glob.glob(wd + "/_build/parts_v2/*.jsonl") + [wd + "/_build/ja_llmail_candidates.jsonl", wd + "/judge_attack/dataset_ja_600.jsonl", wd + "/en/dataset_en_700.jsonl"]:
    if p.replace("\\", "/").endswith("llmail_injection_reserve.jsonl"):
        continue
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        other_ids.add(r["id"])
        if r.get("source") == "LLMail-Inject" and "row_index" in (r.get("origin") or {}):
            used_rows.add(int(r["origin"]["row_index"]))
assert not set(ids) & other_ids, set(ids) & other_ids
KEYS = ["id", "label", "source", "subset", "doc_type", "text", "injected_instruction", "origin", "notes", "core"]
for r in recs:
    assert list(r.keys()) == KEYS, list(r.keys())
    assert (r["label"], r["source"], r["subset"], r["doc_type"], r["core"]) == ("injection", "LLMail-Inject", "phase2", "email", False)
    assert r["text"].startswith("Subject: ") and "\n\n" in r["text"] and len(r["text"]) <= 3000
    ii = r["injected_instruction"]
    assert ii is None or (ii and ii in r["text"]), r["id"]
    assert r["origin"]["row_index"] not in used_rows, r["id"]
    assert r["notes"].startswith("[techniques: ")
rows = [r["origin"]["row_index"] for r in recs]
assert len(set(rows)) == 20
teams = Counter(r["origin"]["team_id"] for r in recs)
assert max(teams.values()) <= 2, teams
print("OK: 20 records, ids unique, substrings ok, rows unused")
print("levels", sorted(Counter(r["origin"]["scenario"] for r in recs).items()))
print("strata", Counter(r["origin"]["success_stratum"] for r in recs))
print("teams", len(teams), "null instr", sum(r["injected_instruction"] is None for r in recs))
L = [len(r["text"]) for r in recs]
print("len median", statistics.median(L), "top10 median", statistics.median(L[:10]), "min/max", min(L), max(L))
