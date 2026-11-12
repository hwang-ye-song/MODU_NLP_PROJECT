"""Scan AESLC (all splits) for benign emails containing injection-like trigger words.

Usage: python -X utf8 -I scan.py <aeslc data dir> <out candidates.jsonl> <out review.txt>
Needs pyarrow (SP/venvs/enron_v2 python).
"""
import json
import re
import statistics
import sys
from collections import Counter

import pyarrow.parquet as pq

SPLITS = ["train", "validation", "test"]

TRIGGERS = {
    "ignore": r"\bignor(e|es|ed|ing)\b",
    "disregard": r"\bdisregard(s|ed|ing)?\b",
    "override": r"\boverrid(e|es|den|ing)\b|\boverrode\b",
    "bypass": r"\bby-?pass(es|ed|ing)?\b",
    "instructions": r"\binstructions?\b",
    "system": r"\bsystems?\b",
    "previous": r"\bprevious(ly)?\b",
    "forget": r"\bforg(et|ets|etting|ot|otten)\b",
    "admin": r"\badmin\b|\badministrator\b",
    "password reset": r"\bpassword\s+reset|\breset\s+(your|my|the|his|her)?\s*password",
    "urgent": r"\burgent(ly)?\b",
    "confidential": r"\bconfidential(ity)?\b",
    "execute": r"\bexecut(e|es|ed|ing|ion)\b",
    "command": r"\bcommands?\b",
    "prompt": r"\bprompt(ly)?\b",
}
TRIG_RE = {k: re.compile(v, re.I) for k, v in TRIGGERS.items()}

# Imperative / "correction" phrasing that resembles injection phrasing.
IMPER = re.compile(
    r"(?i)\b(please\s+)?(ignore|disregard|forget(\s+about)?)\s+(my|the|this|that|any|all|our|your|previous|prior|earlier|last|above|those|these)\b"
    r"|\b(please|pls|kindly)\s+(ignore|disregard|forget|override|bypass|execute)\b"
    r"|\bdisregard\b|\bignore\s+(it|this|that)\b|\boverride\b")

STOP = set("the and to of a in for is that you i we will be on with this it are have as at not your our can if me my from".split())

RE_MASS = re.compile(r"(?i)https?:|www\.|unsubscribe|click here|newsletter|mailing list|to be removed|"
                     r"remove you|opt[- ]out|free (offer|trial)|special offer|act now|limited time|\bviagra\b|"
                     r"original message|-----|^\s*from:|\bsent:|^\s*to:|^\s*cc:|forwarded by")
RE_QUOTE = re.compile(r"(?m)^\s*>")
RE_QP = re.compile(r"=(20|09|3D|0A)\b|\w= \w")
RE_NEWS = re.compile(r"(?i)staff writers?|associated press|\(AP\)|reuters|dow jones|copyright|bloomberg|knight ridder|"
                     r"wall street journal|los angeles times|new york times|houston chronicle")
RE_MARKET = re.compile(r"(?i)we invite you|debt consolidation|reply to this e-?mail with|act today|\bdiscount|"
                       r"\bfree (offer|trial|gift)|\bwinner|\bprize|mortgage rates|lowest price")
# Actual credential/ID/financial-number values (mentions of the word "password" are allowed only via manual check).
RE_SECRET = re.compile(r"(?i)\bpass ?word\s*(is|:|=|-)\s*\S+|\bpwd\s*[:=]|\buser ?id\s*(is|:|=)\s*\S+|\blogin\s*(is|:|=)\s*\S+"
                       r"|\bssn\b|social security|account (no|number|#)\s*[:#]?\s*\d|routing|\biban\b|swift code"
                       r"|credit card (no|number)|card (no|number|#)\s*[:#]?\s*\d|passport (no|number)|driver'?s licen[cs]e (no|number)")
RE_SECRET_DIGITS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{9,}\b|\b(\d{4}[ -]){3}\d{4}\b")
RE_AI = re.compile(r"(?i)\bA\.I\.|\bAI\b|artificial intelligence|chat ?bot|language model|\bLLM\b|\bGPT|system prompt|assistant")
RE_OFFENSIVE = re.compile(r"(?i)\bf+u+c+k|\bshit|\bbitch|\bsex|\bnude|\bnaked|\bporn|\bbastard|\bnigg|\bfag")


def norm_ws(s):
    lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in s.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def is_english(text):
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isascii() for c in letters) / len(letters) < 0.99:
        return False
    words = re.findall(r"[a-z']+", text.lower())
    return len(words) >= 30 and sum(w in STOP for w in words) / len(words) >= 0.18


def caps_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return sum(c.isupper() for c in letters) / max(1, len(letters))


def reject_reason(subject, body, text):
    if not subject or not body:
        return "empty"
    if not (200 <= len(text) <= 3000):
        return "length"
    if RE_MASS.search(body) or RE_MASS.search(subject):
        return "mass/forward"
    if len(RE_QUOTE.findall(body)) > 0:
        return "quoted"
    if RE_QP.search(body):
        return "qp"
    if RE_NEWS.search(body):
        return "news"
    if RE_MARKET.search(text):
        return "marketing"
    if RE_SECRET.search(text) or RE_SECRET_DIGITS.search(text):
        return "sensitive"
    if RE_AI.search(text):
        return "ai-ish"
    if RE_OFFENSIVE.search(text):
        return "offensive"
    if not is_english(body):
        return "non-english"
    if caps_ratio(body) > 0.25:
        return "caps"
    nonempty = [l for l in body.split("\n") if l]
    if len(nonempty) >= 5 and statistics.median(len(l) for l in nonempty) < 25:
        return "list/table"
    return None


def main():
    data_dir, out_jsonl, out_review = sys.argv[1], sys.argv[2], sys.argv[3]
    cands, reasons, trig_count = [], Counter(), Counter()
    for split in SPLITS:
        rows = pq.read_table(f"{data_dir}/{split}-00000-of-00001.parquet").to_pylist()
        for i, r in enumerate(rows):
            subject = norm_ws(r["subject_line"] or "").replace("\n", " ")
            body = norm_ws(r["email_body"] or "")
            text = f"Subject: {subject}\n\n{body}"
            trig = sorted(k for k, rx in TRIG_RE.items() if rx.search(text))
            if not trig:
                reasons["no-trigger"] += 1
                continue
            why = reject_reason(subject, body, text)
            reasons[why or "ok"] += 1
            if why:
                continue
            imper = [m.group(0) for m in IMPER.finditer(text)]
            score = len(trig) + 2 * bool(imper) + sum(t in ("ignore", "disregard", "override", "bypass", "forget",
                                                          "password reset", "command", "prompt", "admin") for t in trig)
            trig_count.update(trig)
            cands.append({"split": split, "row_index": i, "subject": subject, "text": text, "len": len(text),
                          "triggers": trig, "imper": imper, "score": score})
    print("reasons:", dict(reasons))
    print("candidates:", len(cands))
    print("trigger freq among candidates:", trig_count.most_common())
    cands.sort(key=lambda c: (-c["score"], c["split"], c["row_index"]))
    with open(out_jsonl, "w", encoding="utf-8") as f:
        for c in cands:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(out_review, "w", encoding="utf-8") as f:
        for c in cands:
            f.write(f"===== {c['split']}:{c['row_index']} score={c['score']} len={c['len']} trig={c['triggers']} imper={c['imper']}\n"
                    f"{c['text']}\n\n")


if __name__ == "__main__":
    main()
