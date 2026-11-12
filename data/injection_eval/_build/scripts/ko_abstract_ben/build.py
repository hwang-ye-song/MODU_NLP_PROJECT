"""Assemble KO translations of BIPIA abstract benign records.
Usage: python -X utf8 -I build.py <en_jsonl> <chunk_dir> <out_jsonl>
Chunk files chunk*.txt contain blocks starting with '=== <id> ===' followed by the Korean text.
"""
import glob
import json
import os
import re
import sys

en_path, chunk_dir, out_path = sys.argv[1:4]
recs = [json.loads(l) for l in open(en_path, encoding="utf-8") if l.strip()]
ben = [r for r in recs if r["label"] == "benign"]

ko = {}
for fp in sorted(glob.glob(os.path.join(chunk_dir, "chunk*.txt"))):
    raw = open(fp, encoding="utf-8").read()
    parts = re.split(r"^=== (\S+) ===\n", raw, flags=re.M)
    assert parts[0].strip() == "", fp
    for i in range(1, len(parts), 2):
        rid, body = parts[i], parts[i + 1]
        if body.endswith("\n"):
            body = body[:-1]
        assert rid not in ko, rid
        ko[rid] = body

NOTES = ("Translated in Korean news-article style (기사체). Line breaks and line count preserved; "
         "XSum-style '' quote marks and any stray trailing quote kept as in source. "
         "Names of people, clubs, companies, organisations and most places kept in Latin script; "
         "countries/home nations and well-known names with standard Korean forms (영국, 런던, 잉글랜드, 프리미어리그 etc.) in Korean. "
         "Amounts, phone numbers, times, scores and timestamps kept as in source.")

EXTRA = {
    "bipia-abs-ben-01": "Phone number and the stray trailing double quote kept.",
    "bipia-abs-ben-05": "Timestamp '14:14 BST' kept; date localized.",
    "bipia-abs-ben-13": "Mojibake currency tokens (Â£125m, â‚¬1.166) kept byte-identical from source.",
    "bipia-abs-ben-18": "Glued byline 'By Shirong ChenBBC China Editor' rendered as a separated Korean byline.",
    "bipia-abs-ben-19": "Mojibake currency tokens (Â£...) kept byte-identical from source.",
    "bipia-abs-ben-20": "Stray source line 'Apologies for the delay, see below as requested.' translated as-is (human-to-human, benign).",
    "bipia-abs-ben-23": "Mojibake Â£10,000 and mixed closing quote ('') kept as in source.",
    "bipia-abs-ben-28": "Trailing comma at end of the 'shots were heard' line kept as in source.",
    "bipia-abs-ben-39": "Mojibake Â£500m kept byte-identical from source.",
}

out, problems = [], []
for r in ben:
    rid = r["id"]
    if rid not in ko:
        problems.append(f"missing {rid}")
        continue
    t = ko[rid]
    en_lines = r["text"].split("\n")
    ko_lines = t.split("\n")
    if len(en_lines) != len(ko_lines):
        problems.append(f"{rid}: line count EN {len(en_lines)} vs KO {len(ko_lines)}")
    for a, b in zip(en_lines, ko_lines):
        if (a.strip() == "") != (b.strip() == ""):
            problems.append(f"{rid}: blank-line mismatch")
            break
    o = {"id": rid + "-ko", "pair_id": rid, "lang": "ko"}
    for k in ("label", "source", "subset"):
        o[k] = r[k]
    o["text"] = t
    o["injected_instruction"] = None
    o["origin"] = r["origin"]
    o["notes"] = r["notes"]
    o["core"] = r["core"]
    o["translation_notes"] = NOTES + (" " + EXTRA[rid] if rid in EXTRA else "")
    out.append(o)

extra = set(ko) - {r["id"] for r in ben}
if extra:
    problems.append(f"extra ids {sorted(extra)}")

print(f"benign EN: {len(ben)}  translated: {len(ko)}  written: {len(out)}")
for p in problems:
    print("PROBLEM:", p)
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")
print("wrote", out_path)
