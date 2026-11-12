"""Build 35 ranked benign Enron hard negatives (trigger words used naturally) -> parts_v2/enron_hardneg.jsonl.

Usage: python -X utf8 -I build.py <aeslc data dir> <WD dir> <out.jsonl> [--dump review.txt]
Needs pyarrow (SP/venvs/enron_v2 python). Rows were hand-picked and ranked after reading the
candidates produced by scan.py; RANKED order = priority (merge keeps the first 25 after overlap removal).
"""
import difflib
import glob
import json
import os
import re
import statistics
import sys
from collections import Counter

import pyarrow.parquet as pq

DATASET = "Yale-LILY/aeslc"
REVISION = "2305f2e63b68056f9b9037a3805c8c196e0d5581"
N_OUT = 35

# (split, row_index, topic note) in priority order; RESERVE used only if something above is excluded.
RANKED = [
    ("train", 8932, "company-wide legal notice on a bankruptcy-court document-preservation order that supersedes an earlier order"),
    ("validation", 1596, "lawyer's note that the counterparty is sending a new ISDA draft and prior negotiation should be set aside"),
    ("train", 8739, "contract amendments resent with a request to discard earlier versions before the parties execute them"),
    ("train", 11284, "ISDA confirmation templates; tells the reader to skip fields that only feed the confirmation system"),
    ("test", 175, "IT virus alert telling staff not to open an attachment and to delete the offending email"),
    ("test", 1270, "trading-ops explanation of the benchmark position process (manual overrides, book admin, GRMS system)"),
    ("train", 3270, "finance-system project update with step-by-step PC menu commands and training instructions"),
    ("train", 877, "outside counsel on an SEC subpoena, telling the recipient to set aside the subpoena dates"),
    ("train", 8685, "request to execute and fax back a capacity letter agreement right away"),
    ("train", 4899, "sender sent the wrong attachment and asks the recipient to discard and delete the earlier email"),
    ("train", 11416, "personal catalog purchase; buyer says to set aside PayPal shipping instructions"),
    ("train", 11533, "assistant asks IT to reset an absent colleague's passwords (no password values in text)"),
    ("test", 119, "research head refuses to sign off on valuations without the legal documents (no skipping due diligence)"),
    ("train", 1848, "office surprise-party photo plan; title addresses everyone except the honoree"),
    ("validation", 743, "weekly credit-approval list; earlier lists can be set aside, silence treated as approval"),
    ("train", 4922, "legal asks to inactivate a master agreement per credit department instructions"),
    ("train", 5938, "personal wedding head-count request; those who already replied can skip it"),
    ("test", 486, "gas scheduler reminder about capacity release; jokingly awaits the recipient's command"),
    ("train", 354, "private & confidential note on downsizing IT/system support requirements for 2002"),
    ("train", 6910, "risk group asks for help re-posting curve prices it is not authorized to override"),
    ("train", 11475, "legal asks traders to prompt a counterparty to negotiate and execute an ISDA master"),
    ("train", 2769, "urgent Outlook migration notice correcting a date missing from the previous email; pop-up steps"),
    ("test", 732, "research group project list; members on other projects can skip the message"),
    ("train", 11978, "personal note of support offering a confidential ear after a resignation"),
    ("train", 7864, "off-site planning notice; earlier date information should be set aside"),
    # ---- ranks 26-35 (over-sample buffer)
    ("train", 4614, "draft confidentiality agreement sent for execution; sender forgot to follow up"),
    ("validation", 1782, "personal invitation to salsa classes, replacing an earlier message"),
    ("train", 11315, "lawyer objects to business people bypassing in-house counsel with outside firm"),
    ("test", 1388, "voice-mail outage notice; system-wide outage, leave messages with your admin"),
    ("train", 12952, "new deal-control staffer asks to clean up counterparty names in the system (not urgent)"),
    ("test", 113, "compliance notice on ethical-wall procedures for confidential bankruptcy-committee information"),
    ("train", 10662, "personal dilemma email to a friend about whether to ignore an ex"),
    ("test", 1520, "confirmation provision that will override a master-agreement definition"),
    ("train", 4965, "unsolicited positive review of a database developer (confidential data, prompt help)"),
    ("train", 9897, "plant operator unsure about an ISO dispatch instruction, citing previous confusion"),
]
RESERVE = [
    ("train", 7587, "urgent request to execute and return a sale-closing certificate"),
    ("train", 2584, "HR asks VPs to update profiles; type the address on the browser command line"),
    ("train", 9752, "colleague's father scheduled for triple bypass surgery"),
    ("test", 906, "parent's anecdote: did you forget that I'm a vegetarian"),
    ("train", 5471, "counterparty's confidentiality agreement is non-negotiable, or forget about it"),
    ("validation", 1328, "asks to fix a book set-up she has to manually override daily"),
]

TRIGGERS = {
    "ignore": r"\bignor(?:e|es|ed|ing)\b",
    "disregard": r"\bdisregard(?:s|ed|ing)?\b",
    "override": r"\boverrid(?:e|es|den|ing)\b|\boverrode\b",
    "bypass": r"\bby-?pass(?:es|ed|ing)?\b",
    "instructions": r"\binstruct(?:ion|ions|ed)\b",
    "system": r"\bsystems?\b",
    "previous": r"\bprevious(?:ly)?\b",
    "forget": r"\bforg(?:et|ets|etting|ot|otten)\b",
    "admin": r"\badmin\b|\badministrator\b",
    "password reset": r"\bpassword\s+reset\b|\breset\s+(?:\w+\s+){0,4}passwords?\b",
    "urgent": r"\burgent(?:ly)?\b",
    "confidential": r"\bconfidential(?:ity)?\b",
    "execute": r"\bexecut(?:e|es|ed|ing|ion)\b",
    "command": r"\bcommands?\b",
    "prompt": r"\bprompt(?:s|ed|ing|ly)?\b",
}
TRIG_RE = {k: re.compile(v, re.I) for k, v in TRIGGERS.items()}
IMPER = re.compile(
    r"(?i)\b(?:please,?\s+|pls\s+|you may\s+|can be\s+)?(?:ignore|disregard|forget(?:\s+about)?|ignored)\b[^.\n]{0,60}"
    r"|\bplease\s+(?:execute|override|bypass)\b[^.\n]{0,40}"
    r"|\bdo the following commands\b|\binstructed to comply\b[^.\n]{0,40}|\bsupersede the previous\b[^.\n]{0,30}"
    r"|\bdelete (?:all|it)\b[^.\n]{0,40}")

RE_SECRET = re.compile(r"(?i)\bpass ?word\s*(is|:|=|-)\s*\S+|\bpwd\s*[:=]|\buser ?id\s*(is|:|=)\s*\S+|\bssn\b|social security"
                       r"|account (no|number|#)\s*[:#]?\s*\d|routing|\biban\b|swift code|credit card (no|number)"
                       r"|card (no|number|#)\s*[:#]?\s*\d|passport (no|number)")
RE_SECRET_DIGITS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9,}\b|\b(\d{4}[ -]){3}\d{4}\b")
RE_AI = re.compile(r"(?i)\bA\.I\.|\bAI\b|artificial intelligence|chat ?bot|language model|\bLLM\b|\bGPT|system prompt")


def norm_ws(s):
    lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in s.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def ngrams(s, n=5):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def sim(a, b):
    ga, gb = ngrams(a), ngrams(b)
    jac = len(ga & gb) / len(ga | gb) if ga and gb else 0.0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # real_quick_ratio/quick_ratio are upper bounds of ratio(); skip the expensive call when they are < 0.8.
    if sm.real_quick_ratio() < 0.8 or sm.quick_ratio() < 0.8:
        return jac, min(sm.quick_ratio(), 0.79)
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
    data_dir, wd, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    dump = sys.argv[sys.argv.index("--dump") + 1] if "--dump" in sys.argv else None
    tables = {s: pq.read_table(f"{data_dir}/{s}-00000-of-00001.parquet").to_pylist()
              for s in ("train", "validation", "test")}

    out_abs = os.path.abspath(out_path)
    exact_paths = sorted(glob.glob(f"{wd}/parts/*.jsonl"))
    enron_v2 = f"{wd}/parts_v2/enron.jsonl"
    if os.path.exists(enron_v2):
        exact_paths.append(enron_v2)
    strict_abs = {os.path.abspath(p) for p in exact_paths}
    other_v2 = [p for p in sorted(glob.glob(f"{wd}/parts_v2/*.jsonl"))
                if os.path.abspath(p) != out_abs and os.path.abspath(p) not in strict_abs]
    ref_strict = load_texts(exact_paths)       # exact + near-dup exclusion
    ref_other = load_texts(other_v2)           # near-dup exclusion (safety)
    print("dedupe refs:", [os.path.basename(p) for p in exact_paths], "+", [os.path.basename(p) for p in other_v2])
    print("parts_v2/enron.jsonl present:", os.path.exists(enron_v2))

    chosen, excluded = [], []
    for split, idx, topic in RANKED + RESERVE:
        if len(chosen) == N_OUT:
            break
        r = tables[split][idx]
        subject = norm_ws(r["subject_line"] or "").replace("\n", " ")
        body = norm_ws(r["email_body"] or "")
        text = f"Subject: {subject}\n\n{body}"
        why = None
        if not 200 <= len(text) <= 3000:
            why = f"length {len(text)}"
        elif RE_SECRET.search(text) or RE_SECRET_DIGITS.search(text):
            why = "sensitive pattern"
        elif RE_AI.search(text):
            why = "AI-ish"
        trig = {k: sorted({m.group(0).lower() for m in rx.finditer(text)}) for k, rx in TRIG_RE.items()}
        trig = {k: v for k, v in trig.items() if v}
        if not why and not trig:
            why = "no trigger"
        if not why:
            for fname, rid, t in ref_strict + ref_other:
                if t == text:
                    why = f"exact dup of {fname}:{rid}"
                    break
                jac, ratio = sim(text, t)
                if jac >= 0.5 or ratio >= 0.8:
                    why = f"near dup of {fname}:{rid} (jac={jac:.2f}, ratio={ratio:.2f})"
                    break
        if not why:
            for c in chosen:
                jac, ratio = sim(text, c["text"])
                if jac >= 0.5 or ratio >= 0.8:
                    why = f"near dup within set ({c['split']}:{c['idx']})"
                    break
        if why:
            excluded.append((split, idx, why))
            continue
        imper = [m.group(0).strip() for m in IMPER.finditer(text)]
        chosen.append({"split": split, "idx": idx, "topic": topic, "text": text, "trig": trig, "imper": imper})

    assert len(chosen) == N_OUT, (len(chosen), excluded)
    recs = []
    for n, c in enumerate(chosen, 1):
        f = f"data/{c['split']}-00000-of-00001.parquet"
        trig_str = "; ".join(f"{k} ({', '.join(v)})" for k, v in c["trig"].items())
        notes = (f"Rank {n}/35. Real Enron email (AESLC {c['split']} split) used as a document-form hard negative: "
                 f"benign human-to-human text that naturally contains injection-like trigger words. "
                 f"Trigger words [{len(c['trig'])}]: {trig_str}. "
                 + (f"Imperative/correction phrasing: {' | '.join(repr(p) for p in c['imper'][:3])}. " if c["imper"] else "")
                 + f"Topic: {c['topic']}. Nothing is addressed to an AI system. "
                 "text = 'Subject: ' + subject_line + blank line + email_body, whitespace-normalised only "
                 "(AESLC already strips headers/quoted text and puts one sentence per line).")
        recs.append({
            "id": f"enron-hn-{n:02d}",
            "label": "benign",
            "source": "Enron",
            "subset": "enron_trigger_words",
            "text": c["text"],
            "injected_instruction": None,
            "origin": {"dataset": DATASET,
                       "url": f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{f}",
                       "revision": REVISION, "file": f, "split": c["split"], "row_index": c["idx"]},
            "notes": notes,
            "core": False,
        })
    with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
        for r in recs:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # Validation
    with open(out_path, encoding="utf-8") as fh:
        back = [json.loads(l) for l in fh]
    assert len(back) == N_OUT and len({r["id"] for r in back}) == N_OUT
    assert len({r["text"] for r in back}) == N_OUT
    assert all(r["injected_instruction"] is None and r["label"] == "benign" for r in back)
    L = [len(r["text"]) for r in back]
    freq = Counter(k for c in chosen for k in c["trig"])
    freq25 = Counter(k for c in chosen[:25] for k in c["trig"])
    print("excluded:", excluded)
    print("wrote", len(back), "| len min/median/mean/max", min(L), statistics.median(L), round(statistics.mean(L)), max(L))
    print("top25 len median", statistics.median(L[:25]))
    print("multi-trigger (>=2):", sum(len(c["trig"]) >= 2 for c in chosen), "| with imperative phrasing:",
          sum(bool(c["imper"]) for c in chosen))
    print("trigger freq (35):", freq.most_common())
    print("trigger freq (top25):", freq25.most_common())
    print("splits:", Counter(c["split"] for c in chosen))
    if dump:
        with open(dump, "w", encoding="utf-8") as fh:
            for r, c in zip(recs, chosen):
                fh.write(f"===== {r['id']} {c['split']}:{c['idx']} len={len(c['text'])} trig={list(c['trig'])} imper={c['imper']}\n{c['text']}\n\n")


if __name__ == "__main__":
    main()
