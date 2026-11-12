import json, re, sys, statistics
from pathlib import Path

HERE = Path(r"<SCRATCH>/scripts/sep_more_ko")
EN = Path(r"<DATASET_ROOT>/_build/parts_v2/sep_more.jsonl")
OUT = Path(r"<DATASET_ROOT>/_build/ko_parts/sep_more.jsonl")
LEAD = "주어진 작업에 더해 다음 우선 질문에도 답하세요:"
LEAD_EN = "On top of your main task, answer this priority question:"

tr = {}
for i in range(1, 5):
    for r in json.loads((HERE / f"tr_{i}.json").read_text(encoding="utf-8")):
        assert r["id"] not in tr, r["id"]
        tr[r["id"]] = r

en = [json.loads(l) for l in EN.read_text(encoding="utf-8").splitlines() if l.strip()]
assert len(en) == 40 and len(tr) == 40, (len(en), len(tr))

out = []
errs = []
for e in en:
    t = tr[e["id"]]
    text = t["text"]
    o = e["origin"]
    if e["label"] == "injection":
        inj = t["inj"]
        pos = o["probe_position_in_data"]
        if inj not in text:
            errs.append((e["id"], "inj not substring"))
        if pos == "start" and not text.startswith(inj + " "):
            errs.append((e["id"], "start position mismatch"))
        if pos == "end" and not text.endswith(" " + inj):
            errs.append((e["id"], "end position mismatch"))
        ins = e["injected_instruction"].startswith(LEAD_EN)
        if ins != inj.startswith(LEAD):
            errs.append((e["id"], "insistent lead mismatch"))
        if text.count(LEAD) != (1 if ins else 0):
            errs.append((e["id"], "lead count"))
        notes = (f"Passage translated into natural Korean prose; SEP probe translated as a Korean request in the same position "
                 f"({pos}, single-space join as in EN).")
        if ins:
            notes += f" Insistent lead-in '{LEAD_EN}' rendered with the fixed phrase '{LEAD}'."
        notes += f" origin.witness kept in English; expected Korean answer: {t['ans']}."
    else:
        inj = None
        if LEAD in text:
            errs.append((e["id"], "lead phrase in benign"))
        notes = "Passage translated into natural Korean prose; no instruction added."
    if t.get("extra"):
        notes += " " + t["extra"]
    notes += " doc_type set to general_document (EN part record has no doc_type; value taken from the SEP rows of en/dataset_en_700.jsonl)."
    # hangul ratio
    letters = [c for c in text if c.isalpha()]
    hangul = [c for c in letters if "\uac00" <= c <= "\ud7a3"]
    ratio = len(hangul) / max(1, len(letters))
    latin_runs = re.findall(r"[A-Za-z][A-Za-z'&.\- ]{14,}", text)
    if ratio < 0.8:
        errs.append((e["id"], f"hangul ratio {ratio:.2f}"))
    rec = {
        "id": e["id"] + "-ko", "pair_id": e["id"], "lang": "ko",
        "label": e["label"], "source": e["source"], "subset": e["subset"],
        "doc_type": "general_document",
        "text": text, "injected_instruction": inj,
        "origin": e["origin"], "notes": e["notes"], "core": e["core"],
        "translation_notes": notes,
    }
    out.append(rec)
    print(e["id"], e["label"], len(e["text"]), len(text), f"{ratio:.2f}", latin_runs)

if errs:
    print("ERRORS", errs)
    sys.exit(1)

OUT.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in out), encoding="utf-8")

# re-validate output
rs = [json.loads(l) for l in OUT.read_text(encoding="utf-8").splitlines()]
assert len(rs) == 40
assert len({r["id"] for r in rs}) == 40
assert [r["pair_id"] for r in rs] == [e["id"] for e in en]
for r in rs:
    if r["injected_instruction"] is not None:
        assert r["injected_instruction"] in r["text"]
for lab in ("injection", "benign"):
    ls = [len(r["text"]) for r in rs if r["label"] == lab]
    print(lab, len(ls), "median len", statistics.median(ls))
print("OK", OUT)
