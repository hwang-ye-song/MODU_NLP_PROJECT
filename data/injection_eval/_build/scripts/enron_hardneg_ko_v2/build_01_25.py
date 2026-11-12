"""Build WD/ko_parts/enron_hardneg.jsonl (enron-hn-01..25) from hand-written KO texts.
usage: python -X utf8 -I build_01_25.py <en_jsonl> <ko_texts_py> <out_jsonl>
"""
import importlib.util
import json
import re
import sys

en_path, texts_path, out_path = sys.argv[1:4]

spec = importlib.util.spec_from_file_location("ko_texts", texts_path)
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)
KO = mod.KO

en = [json.loads(l) for l in open(en_path, encoding="utf-8") if l.strip()]
en_first = en[:25]
assert [r["id"] for r in en_first] == [f"enron-hn-{i:02d}" for i in range(1, 26)], "unexpected order"
assert [k[0] for k in KO] == [r["id"] for r in en_first], "KO ids/order mismatch"

BASE = ("'Subject:' marker kept in English (Enron/LLMail convention); subject value and body translated "
        "into natural Korean business-email register. AESLC one-sentence-per-line layout preserved "
        "(same line breaks, incl. split list numbering). Names, company/product/system names, numbers, "
        "numeric dates, phone/extension numbers, amounts and file names kept. Benign human-to-human email; "
        "trigger words kept with the brief's renderings. ")

out = []
for r, (pid, ko_text, note) in zip(en_first, KO):
    en_text = r["text"]
    assert ko_text.startswith("Subject: "), pid
    assert ko_text.count("\n") == en_text.count("\n"), (pid, ko_text.count("\n"), en_text.count("\n"))
    assert ko_text.split("\n")[1] == "", pid
    rec = {
        "id": r["id"] + "-ko",
        "pair_id": r["id"],
        "lang": "ko",
        "label": r["label"],
        "source": r["source"],
        "subset": r["subset"],
        "text": ko_text,
        "injected_instruction": None,
        "origin": r["origin"],
        "notes": r["notes"],
        "core": r["core"],
        "translation_notes": BASE + note,
    }
    out.append(rec)

with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("wrote", len(out))
