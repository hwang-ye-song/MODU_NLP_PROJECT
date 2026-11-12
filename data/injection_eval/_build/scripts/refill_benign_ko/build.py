"""Build WD/_build/ko_parts/refill_benign.jsonl from the EN refill input and hand-written KO texts.
usage: python -X utf8 -I build.py <en_jsonl> <ko_texts_py> <out_jsonl>
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

# Same base notes as the earlier KO Enron parts (enron_hardneg_ko_v2/build_01_25.py and ko_enron/build.py).
BASE_HN = ("'Subject:' marker kept in English (Enron/LLMail convention); subject value and body translated "
           "into natural Korean business-email register. AESLC one-sentence-per-line layout preserved "
           "(same line breaks, incl. split list numbering). Names, company/product/system names, numbers, "
           "numeric dates, phone/extension numbers, amounts and file names kept. Benign human-to-human email; "
           "trigger words kept with the brief's renderings. ")
BASE_BEN = ("'Subject:' marker kept in English, subject value and body translated into Korean business-email register; "
            "one-sentence-per-line structure kept (identical line count, incl. mid-abbreviation splits); "
            "names of people, companies, places, products, systems and deal/contract titles kept in Latin script; "
            "numbers, amounts, extensions, deal numbers kept verbatim")

en = [json.loads(l) for l in open(en_path, encoding="utf-8") if l.strip()]
assert [k[0] for k in KO] == [r["id"] for r in en], "KO ids/order mismatch"

out = []
for r, (pid, ko_text, note) in zip(en, KO):
    en_text = r["text"]
    assert r["label"] == "benign" and r["injected_instruction"] is None, pid
    assert ko_text.startswith("Subject: "), pid
    assert ko_text.count("\n") == en_text.count("\n"), (pid, ko_text.count("\n"), en_text.count("\n"))
    assert ko_text.split("\n")[1] == "", pid
    if r["subset"] == "enron_trigger_words":
        tn = BASE_HN + note
    else:
        tn = BASE_BEN + "; " + note
    rec = {
        "id": r["id"] + "-ko",
        "pair_id": r["id"],
        "lang": "ko",
        "label": r["label"],
        "source": r["source"],
        "subset": r["subset"],
        "doc_type": r["doc_type"],
        "text": ko_text,
        "injected_instruction": None,
        "origin": r["origin"],
        "notes": r["notes"],
        "core": r["core"],
        "translation_notes": tn,
    }
    out.append(rec)

with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("wrote", len(out))
