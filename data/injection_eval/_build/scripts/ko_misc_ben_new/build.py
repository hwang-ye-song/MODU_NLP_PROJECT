"""Build WD/ko_parts/misc_ben_new.jsonl from hand-written Korean translations.

usage: python -X utf8 -I build.py <WD>
"""
import json, os, re, sys, runpy, difflib

HERE = os.path.dirname(os.path.abspath(__file__))
WD = sys.argv[1]

L = runpy.run_path(os.path.join(HERE, "tr_llmail.py"))
N = runpy.run_path(os.path.join(HERE, "tr_notinject.py"))
H = runpy.run_path(os.path.join(HERE, "tr_hardneg.py"))


def load(p):
    with open(p, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


llm = [r for r in load(os.path.join(WD, "parts_v2", "llmail_benign.jsonl")) if r["core"] is False]
ni = [r for r in load(os.path.join(WD, "parts_v2", "notinject.jsonl")) if r["core"] is False]
hn = load(os.path.join(WD, "parts_v2", "hardneg.jsonl"))
assert (len(llm), len(ni), len(hn)) == (25, 15, 15), (len(llm), len(ni), len(hn))


def mk(en, text, note):
    return {
        "id": en["id"] + "-ko",
        "pair_id": en["id"],
        "lang": "ko",
        "label": en["label"],
        "source": en["source"],
        "subset": en["subset"],
        "text": text,
        "injected_instruction": None,
        "origin": en["origin"],
        "notes": en["notes"],
        "core": en["core"],
        "translation_notes": note,
    }


out = []
for en in llm:
    out.append(mk(en, L["TR"][en["id"]], L["NOTE"] + L["EXTRA"].get(en["id"], "")))
for en in ni:
    t, n = N["TR"][en["id"]]
    pre = N["PREFIX_MULTI"] if en["id"] == "notinject-ben-20" else N["PREFIX"]
    out.append(mk(en, t, pre + n))
for en in hn:
    t, n = H["TR"][en["id"]]
    out.append(mk(en, t, "Synthetic hard negative; format and line structure preserved, kept unambiguously human-directed (no text addresses an AI). " + n))

# ---------------- validation ----------------
errs = []
en_by_id = {r["id"]: r for r in llm + ni + hn}
ids = [r["id"] for r in out]
if len(out) != 55: errs.append("count")
if len(set(ids)) != len(ids): errs.append("dup ids")
for r in out:
    en = en_by_id[r["pair_id"]]
    t, e = r["text"], en["text"]
    if r["label"] != "benign" or en["label"] != "benign": errs.append(r["id"] + " label")
    if r["injected_instruction"] is not None: errs.append(r["id"] + " inj")
    if t.count("\n") != e.count("\n"): errs.append(f"{r['id']} newline count {t.count(chr(10))} vs {e.count(chr(10))}")
    if t != t.strip(): errs.append(r["id"] + " leading/trailing ws")
    # email-style markers
    for m in ("Subject:", "From:", "To:"):
        if e.startswith(m) or ("\n" + m) in e:
            if not (t.startswith(m) or ("\n" + m) in t): errs.append(f"{r['id']} marker {m}")
    # preserved tokens: emails, things with digits+latin, code-ish tokens
    for tok in re.findall(r"[\w.+-]+@[\w.-]+\w|#[\w-]+|\b[\w.]*\d[\w.]*\.css|styles\.css\?v=\d+|Cache-Control: max-age=\d+|\?v=|Ctrl\+Shift\+R|Cmd\+Shift\+R", e):
        if tok not in t: errs.append(f"{r['id']} missing token {tok}")
    for tok in re.findall(r"\[\d\d:\d\d\]", e):
        if t.count(tok) != e.count(tok): errs.append(f"{r['id']} timestamp {tok}")
    # double spaces preserved
    if e.count("  ") != t.count("  "): errs.append(f"{r['id']} double-space count {t.count('  ')} vs {e.count('  ')}")
    # Hangul share among letters
    hang = len(re.findall(r"[\uac00-\ud7a3]", t))
    lat = len(re.findall(r"[A-Za-z]", t))
    r["_ratio"] = hang / max(1, hang + lat)
    # leftover English prose: 4+ consecutive latin words
    for m in re.finditer(r"(?:\b[A-Za-z][A-Za-z']*\b[ ,]+){4,}[A-Za-z]+", t):
        r.setdefault("_eng", []).append(m.group(0))

# similarity: within output and against existing KO core benign
core_ko = load(os.path.join(WD, "ko_parts", "core_ben.jsonl"))
pool = [(c["id"], c["text"]) for c in core_ko]
sims = []
for i, r in enumerate(out):
    for j in range(i):
        s = difflib.SequenceMatcher(None, r["text"], out[j]["text"]).ratio()
        if s >= 0.8: sims.append((r["id"], out[j]["id"], round(s, 3)))
    for cid, ct in pool:
        s = difflib.SequenceMatcher(None, r["text"], ct).ratio()
        if s >= 0.8: sims.append((r["id"], cid, round(s, 3)))

for r in out:
    if r["_ratio"] < 0.6 or r.get("_eng"):
        print("CHECK", r["id"], round(r["_ratio"], 2), r.get("_eng"))
print("sims>=0.8:", sims)
print("errors:", errs)
for r in out:
    r.pop("_ratio", None); r.pop("_eng", None)

if errs:
    sys.exit(1)
dst = os.path.join(WD, "ko_parts", "misc_ben_new.jsonl")
with open(dst, "w", encoding="utf-8", newline="\n") as f:
    for r in out:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
# re-read check
back = load(dst)
assert [b["id"] for b in back] == ids
print("wrote", dst, len(back))
from collections import Counter
print(Counter(b["source"] for b in back))
