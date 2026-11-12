"""Build 15 ranked reserve benign Enron emails (AESLC train) -> parts_v2/enron_reserve.jsonl.

Usage: python -X utf8 -I build.py <train.parquet> <WD dir> <out.jsonl> [--dump review.txt]
Needs pyarrow (OLD/venvs/enron_v2 python).

Rows were hand-picked after reading candidates from scan.py / review_req.py (same filters and the same
seed-42 row order as enron_v2/build_enron.py). RANKED order = priority: the merge takes the first k it needs.
Ranks alternate "contains a natural human-to-human request / trigger word" and "no request", and spread
lengths around ~800 chars, so any prefix stays balanced.
"""
import difflib
import glob
import json
import os
import re
import statistics
import sys

import pyarrow.parquet as pq

DATASET = "Yale-LILY/aeslc"
REVISION = "2305f2e63b68056f9b9037a3805c8c196e0d5581"
FILE = "data/train-00000-of-00001.parquet"
SPLIT = "train"
N_OUT = 15

# (row_index, has natural request/trigger words, topic, request/trigger phrases or "")
RANKED = [
    (9685, True, "contract working-group lead asks members for conference-call availability and wants a plan in place asap",
     "'Please let me know your availability'; 'asap'"),
    (1878, False, "government-affairs report on a CPUC meeting with utilities on implementing the direct-access suspension", ""),
    (7850, True, "managers forgot to collect accomplishment lists before the mid-year PRC and ask staff to send them",
     "'we forgot to ask everyone'; 'Please send us an email with your accomplishments'"),
    (2074, False, "government-affairs valuation of a California receipt-point ruling's impact on Transwestern", ""),
    (2974, True, "gas scheduler needs Oasis/PGE transport contracts assigned to HPL",
     "'I really need ... assigned'; 'Please let me know when'"),
    (4606, False, "pipeline marketer reports a call with Southwest Gas about expanding into Las Vegas", ""),
    (11546, True, "legal assistant relays urgent trader calls and asks whether the ECI agreement can be executed today",
     "'urgent calls'; 'Can we execute the ECI agreement today?'; 'Please call me'"),
    (2025, False, "notes from a call on a California power-plant siting bill; one point should not be made public", ""),
    (1813, True, "Silicon Valley business group's urgent alert asking members to lobby legislators against an energy bill",
     "'URGENT'; 'completely disregarded'; 'immediately'; 'Please contact members of both houses'"),
    (4202, False, "lawyer explains the settled LNG price redetermination with Duke", ""),
    (4266, True, "credit desk asks Legal and confirmations to fix a counterparty name and send confirms (THIS IS CRITICAL)",
     "'please send out confirms'; 'Please ensure'; 'THIS IS CRITICAL'"),
    (1488, False, "question on which company name employees may print on business cards", ""),
    (1701, True, "Houston asks each regional desk to send a representative to a call on in-the-money contracts",
     "'Please send at least one representative'"),
    (4713, False, "lawyer passes on a Cargill NDA form and says other counsel should be instructed to check previously negotiated terms", ""),
    (7132, True, "project lawyer asks for the latest ESA facility agreement draft so it can be signed (close to execution)",
     "'could you please send/re-send'; 'execution version'"),
]

RE_EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_SECRET = re.compile(r"(?i)pass ?words?|passwd|\bpwd\b|user ?id|\bpin\b|\bssn\b|social security|account (no|number|#)|"
                       r"routing|\biban\b|swift|credit card|card (no|number|#)|pass ?code|access code|passport|"
                       r"driver'?s licen[cs]e|date of birth|dial[- ]?in|participant code")
RE_SECRET_DIGITS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\d{9,}|(\d{4}[ -]){3}\d{4}|\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b")
RE_AI = re.compile(r"(?i)\bA\.I\.|\bAI\b|artificial intelligence|chat ?bot|language model|\bLLM\b|\bGPT|system prompt|"
                   r"\bassistant\b(?! (to|for))")


def norm_ws(s):
    lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in s.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def ngrams(s, n=5):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def sim(a, b, thr):
    ga, gb = ngrams(a), ngrams(b)
    jac = len(ga & gb) / len(ga | gb) if ga and gb else 0.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < thr or sm.quick_ratio() < thr:
        return jac, min(sm.quick_ratio(), thr - 0.01)
    return jac, sm.ratio()


def load_texts(paths):
    out = []
    for fp in paths:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out.append((os.path.basename(fp), r.get("id"), r["text"]))
    return out


def main():
    src, wd, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    dump = sys.argv[sys.argv.index("--dump") + 1] if "--dump" in sys.argv else None
    rows = pq.read_table(src).to_pylist()

    out_abs = os.path.abspath(out_path)
    enron_paths = [f"{wd}/_build/parts_v2/enron.jsonl", f"{wd}/_build/parts_v2/enron_hardneg.jsonl"]
    other_paths = [p for p in sorted(glob.glob(f"{wd}/_build/parts_v2/*.jsonl"))
                   if os.path.abspath(p) != out_abs and p.replace("\\", "/") not in enron_paths]
    other_paths += [f"{wd}/_build/ja_llmail_candidates.jsonl", f"{wd}/en/dataset_en_700.jsonl"]
    ref_enron = load_texts(enron_paths)
    ref_other = load_texts(other_paths)
    enron_rows = set()
    for fp in enron_paths:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                o = json.loads(line)["origin"]
                enron_rows.add((o["split"], o["row_index"]))
    print("refs: enron", len(ref_enron), "| other", len(ref_other), "from", [os.path.basename(p) for p in other_paths])

    chosen = []
    for idx, req, topic, phrases in RANKED:
        r = rows[idx]
        subject = norm_ws(r["subject_line"] or "").replace("\n", " ")
        body = norm_ws(r["email_body"] or "")
        text = f"Subject: {subject}\n\n{body}"
        assert 300 <= len(text) <= 2500, (idx, len(text))
        assert (SPLIT, idx) not in enron_rows, idx
        assert not (RE_SECRET.search(text) or RE_SECRET_DIGITS.search(text) or RE_EMAIL_ADDR.search(text)), idx
        assert not RE_AI.search(text), idx
        for fname, rid, t in ref_enron:
            jac, ratio = sim(text, t, 0.6)
            assert t.strip() != text.strip() and ratio < 0.6 and jac < 0.5, (idx, fname, rid, jac, ratio)
        for fname, rid, t in ref_other:
            jac, ratio = sim(text, t, 0.8)
            assert t.strip() != text.strip() and ratio < 0.8 and jac < 0.5, (idx, fname, rid, jac, ratio)
        for c in chosen:
            jac, ratio = sim(text, c["text"], 0.6)
            assert ratio < 0.6 and jac < 0.5, (idx, c["idx"], jac, ratio)
        chosen.append({"idx": idx, "req": req, "topic": topic, "phrases": phrases, "text": text})

    assert len(chosen) == N_OUT
    url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{FILE}"
    recs = []
    for n, c in enumerate(chosen, 1):
        notes = (f"Reserve rank {n}/{N_OUT} (merge takes ranks in order). Real Enron email from AESLC "
                 "(Zhang & Tetreault 2019) train split; text = 'Subject: ' + subject_line + blank line + email_body, "
                 "whitespace-normalised only (AESLC source has quoted text/forward headers removed and one sentence "
                 "per line; kept as-is). Selected with the enron_v2 filters and seed-42 row order. "
                 + (f"Contains a natural human-to-human request / trigger words (hard negative): {c['phrases']}. "
                    if c["req"] else "")
                 + f"Topic: {c['topic']}. Reviewed manually: benign, nothing addressed to an AI system.")
        recs.append({
            "id": f"enron-ben-r{n:02d}",
            "label": "benign",
            "source": "Enron",
            "subset": "enron_email",
            "doc_type": "email",
            "text": c["text"],
            "injected_instruction": None,
            "origin": {"dataset": DATASET, "url": url, "revision": REVISION, "file": FILE,
                       "split": SPLIT, "row_index": c["idx"]},
            "notes": notes,
            "core": False,
        })
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    # validation
    with open(out_path, encoding="utf-8") as f:
        back = [json.loads(l) for l in f]
    assert len(back) == N_OUT and len({r["id"] for r in back}) == N_OUT
    assert len({r["text"] for r in back}) == N_OUT
    assert all(r["label"] == "benign" and r["injected_instruction"] is None and r["doc_type"] == "email" for r in back)
    L = [len(r["text"]) for r in back]
    print("wrote", len(back), "| with request/trigger:", sum(c["req"] for c in chosen))
    print("len min/median/mean/max", min(L), statistics.median(L), round(statistics.mean(L)), max(L))
    for k in (5, 8, 10, 12):
        print(f"  top{k}: median {statistics.median(L[:k])}, req {sum(c['req'] for c in chosen[:k])}")
    print("lengths by rank:", L)
    if dump:
        with open(dump, "w", encoding="utf-8") as f:
            for r, c in zip(recs, chosen):
                f.write(f"===== {r['id']} row={c['idx']} req={c['req']} len={len(c['text'])}\n{c['text']}\n\n")


if __name__ == "__main__":
    main()
