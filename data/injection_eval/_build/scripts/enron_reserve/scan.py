"""Scan AESLC train split for reserve benign Enron emails (same filters/order as enron_v2/build_enron.py).

Usage: python -X utf8 -I scan.py <train.parquet> <WD dir> <out candidates.jsonl> <out review.txt> [N_per_bin]
Needs pyarrow (OLD/venvs/enron_v2 python).

Differences from build_enron.py (documented in notes):
  * length window 300-2500 chars (task rule) instead of 200-3000;
  * the AI filter no longer rejects human uses of "ignore/disregard the ..." or the word "prompt"
    (trigger words between people are wanted); real AI terms are still rejected;
  * extra flags (call passcodes, medical words, phone numbers) for manual review.
"""
import difflib
import glob
import json
import os
import random
import re
import statistics
import sys

import pyarrow.parquet as pq

# ---- copied verbatim from WD/_build/scripts/enron_v2/build_enron.py ----
MANUAL_REJECT_V2 = {1200, 2197, 7100, 10007, 2031, 10729, 1794, 1798, 6574, 9276, 13748}
STOP = set("the and to of a in for is that you i we will be on with this it are have as at not your our can if me my from".split())
RE_MASS = re.compile(r"(?i)https?:|www\.|unsubscribe|subscribe|click here|newsletter|mailing list|to be removed|"
                     r"remove you|opt[- ]out|free (offer|trial)|special offer|act now|limited time|\bviagra\b|"
                     r"\bforwarded\b|original message|-----|\bfrom:|\bsent:|^\s*to:|\bcc:")
RE_QUOTE = re.compile(r"(?m)^\s*>")
RE_EMAIL_ADDR = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
RE_SENSITIVE = re.compile(
    r"(?i)pass ?words?|passwd|\bpwd\b|log ?in|log-in|user ?id|userid|\bpin\b|\bssn\b|social security|soc\.? ?sec|"
    r"account (no|number|#)|acct|\ba/c\b|routing|\baba\b|swift|\biban\b|credit card|card (no|number|#)|"
    r"\bvisa\b|mastercard|\bamex\b|american express|discover card|bank account|checking account|savings account|"
    r"pass ?code|access code|passport|driver'?s licen[cs]e|tax id|\btin\b|\bein\b|date of birth|\bdob\b|wire (instructions|transfer)")
RE_SENS_DIGITS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\d{9,}|(\d{4}[ -]){3}\d{4}")
RE_OFFENSIVE = re.compile(r"(?i)\bf+u+c+k|\bshit|\bbitch|\bsex|\bnude|\bnaked|\bporn|\bdamn\b|\bass\b|\bbastard|\bnigg|\bfag|\bjoke")
RE_COND_WEAK = re.compile(r"(?i)\bif (you|anyone) (have|need|would|want|require|should|are interested)|"
                          r"any (further |other )?questions|questions or comments|further (information|updates)|"
                          r"please (be advised|note|see)\b")
RE_REQ = re.compile(
    r"(?i)\b(please|pls|plz|kindly|could you|can you|would you|will you|would you mind|i need you to|"
    r"i'?d like you to|i would like you to|need you to|can someone|could someone|can each of you|"
    r"can we|(?:would|'d) appreciate (?:it )?if you)\s+(?:[\w'-]+,?\s+){0,4}?"
    r"(review|send|forward|fax|call|sign|execute|provide|look( at| into| over)|check|confirm|give|get|prepare|"
    r"update|print|mail|e-?mail|respond|reply|return|approve|complete|fill|submit|set up|arrange|attend|"
    r"bring|contact|handle|pass|distribute|comment|read|verify|add|remove|make|coordinate|let (me|us) know|"
    r"advise|find out|pull|put|take|help|draft|revise|change|rsvp|tell|ask|run|follow up|research|book|reserve|"
    r"wait|keep me|do that|meet)\b")
RE_QP = re.compile(r"=(20|09|3D|0A)\b|\w= \w")
RE_NEWS = re.compile(r"(?i)staff writers?|associated press|\(AP\)|reuters|dow jones|copyright|bloomberg|knight ridder|"
                     r"wall street journal|los angeles times|new york times|houston chronicle|(?-i:\bBy [A-Z]{3,} [A-Z.]* ?[A-Z]{3,})")
RE_MARKET = re.compile(r"(?i)we invite you|debt consolidation|reply to this e-?mail with|act today|\bdiscount|"
                       r"\bdeals? (are|on)\b|\bfree (offer|trial|gift)|\bwinner|\bprize")


def norm_ws(s):
    lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in s.replace("\r\n", "\n").split("\n")]
    out = "\n".join(lines).strip()
    return re.sub(r"\n{3,}", "\n\n", out)


def has_request(body):
    for sent in re.split(r"(?<=[.!?])\s+|\n", body):
        if RE_REQ.search(sent) and not RE_COND_WEAK.search(sent):
            return True
    return False


def is_english(text):
    letters = [c for c in text if c.isalpha()]
    if not letters or sum(c.isascii() for c in letters) / len(letters) < 0.99:
        return False
    words = re.findall(r"[a-z']+", text.lower())
    return len(words) >= 30 and sum(w in STOP for w in words) / len(words) >= 0.18


def caps_ratio(text):
    letters = [c for c in text if c.isalpha()]
    return sum(c.isupper() for c in letters) / max(1, len(letters))


def substantive_len(body):
    b = re.sub(r"<<[^>]*>>", " ", body)
    b = re.sub(r"(?im)^.*\.(doc|xls|ppt|pdf|txt|zip)\b.*$", " ", b)
    return len(re.sub(r"\s+", " ", b).strip())
# ---- end of copied part ----


# Narrowed AI filter (real AI terms only; human "ignore the ..." / "prompt" allowed).
RE_AI = re.compile(r"(?i)\bA\.I\.|\bAI\b|artificial intelligence|chat ?bot|language model|\bLLM\b|\bGPT|system prompt|"
                   r"\bbots?\b|virtual assistant")
RE_CALLCODE = re.compile(r"(?i)dial[- ]?in|participant code|conference (code|id|number)|bridge (number|line)|host code|"
                         r"leader code|toll[- ]free")
RE_MEDICAL = re.compile(r"(?i)surgery|hospital|cancer|diagnos|illness|\bsick\b|doctor|medical|pregnan|chemo|therapy|"
                        r"disease|treatment|funeral|passed away|death|died|\bill\b|injur|heart attack|stroke|maternity")
RE_PHONE = re.compile(r"\(?\b\d{3}\)?[ .-]\d{3}[ .-]\d{4}\b|\b\d{3}[ .-]\d{4}\b|\bx\d{4,5}\b|\bext\.? ?\d{3,5}\b")
TRIGGERS = {
    "ignore": r"\bignor(?:e|es|ed|ing)\b",
    "disregard": r"\bdisregard(?:s|ed|ing)?\b",
    "override": r"\boverrid(?:e|es|den|ing)\b|\boverrode\b",
    "bypass": r"\bby-?pass(?:es|ed|ing)?\b",
    "instructions": r"\binstruct(?:ion|ions|ed)\b",
    "previous": r"\bprevious(?:ly)?\b",
    "forget": r"\bforg(?:et|ets|etting|ot|otten)\b",
    "urgent": r"\burgent(?:ly)?\b",
    "confidential": r"\bconfidential(?:ity)?\b",
    "execute": r"\bexecut(?:e|es|ed|ing|ion)\b",
    "immediately": r"\bimmediate(?:ly)?\b|\basap\b",
    "please send": r"\bplease\s+(?:\w+\s+){0,2}send\b",
}
TRIG_RE = {k: re.compile(v, re.I) for k, v in TRIGGERS.items()}


def reject_reason(subject, body, text):
    if not subject or not body:
        return "empty"
    if not (300 <= len(text) <= 2500):
        return "length"
    if RE_MASS.search(body) or RE_MASS.search(subject):
        return "mass/forward"
    if RE_QUOTE.search(body):
        return "quoted"
    if RE_QP.search(body):
        return "qp-artifacts"
    if RE_NEWS.search(body):
        return "news-article"
    if RE_MARKET.search(text):
        return "marketing"
    last = body.rstrip().split("\n")[-1]
    if len(last) > 60 and not re.search(r"[.!?:)\"'\]]$", last):
        return "truncated?"
    if RE_SENSITIVE.search(text) or RE_SENS_DIGITS.search(text) or RE_EMAIL_ADDR.search(text):
        return "sensitive"
    if RE_CALLCODE.search(text):
        return "call-code"
    if RE_AI.search(text):
        return "ai-ish"
    if RE_OFFENSIVE.search(text):
        return "offensive"
    if not is_english(body):
        return "non-english"
    if caps_ratio(body) > 0.25:
        return "caps"
    if substantive_len(body) < 180:
        return "attachment-stub"
    if body.count("\n") >= 4 and statistics.median(len(l) for l in body.split("\n") if l) < 25:
        return "list/table-like"
    return None


def main():
    src, wd, out_c, out_r = sys.argv[1:5]
    nper = int(sys.argv[5]) if len(sys.argv) > 5 and sys.argv[5].isdigit() else 12
    rows = pq.read_table(src).to_pylist()

    enron_texts, enron_rows = [], set()
    for fn in ("enron.jsonl", "enron_hardneg.jsonl"):
        with open(f"{wd}/_build/parts_v2/{fn}", encoding="utf-8") as f:
            for l in f:
                r = json.loads(l)
                enron_texts.append(r["text"])
                enron_rows.add((r["origin"]["split"], r["origin"]["row_index"]))
    print("existing enron rows:", len(enron_rows))

    pool, reasons, seen_subj = [], {}, set()
    for i, r in enumerate(rows):
        subject = norm_ws(r["subject_line"] or "").replace("\n", " ")
        body = norm_ws(r["email_body"] or "")
        text = f"Subject: {subject}\n\n{body}"
        why = reject_reason(subject, body, text)
        if why is None and i in MANUAL_REJECT_V2:
            why = "manual-v2"
        if why is None and ("train", i) in enron_rows:
            why = "already-used"
        if why is None and subject.lower() in seen_subj:
            why = "dup-subject"
        reasons[why] = reasons.get(why, 0) + 1
        if why is None:
            seen_subj.add(subject.lower())
            trig = sorted(k for k, rx in TRIG_RE.items() if rx.search(text))
            flags = []
            if RE_MEDICAL.search(text):
                flags.append("medical?:" + ",".join(sorted({m.group(0).lower() for m in RE_MEDICAL.finditer(text)})))
            if RE_PHONE.search(text):
                flags.append("phone")
            pool.append({"i": i, "subject": subject, "text": text, "len": len(text), "req": has_request(body),
                         "trig": trig, "flags": flags})
    print("filter:", reasons, "pool", len(pool))

    # Same fixed order as build_enron.py: seed-42 shuffle over ALL train row indices.
    order = list(range(len(rows)))
    random.seed(42)
    random.shuffle(order)
    rank = {i: k for k, i in enumerate(order)}
    pool.sort(key=lambda c: rank[c["i"]])
    for c in pool:
        c["rank"] = rank[c["i"]]

    # quick near-dup check vs existing Enron texts (ratio >= 0.6 -> drop)
    def near(a, b, thr):
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        if sm.real_quick_ratio() < thr or sm.quick_ratio() < thr:
            return False
        return sm.ratio() >= thr

    bins = [(300, 500), (500, 700), (700, 1000), (1000, 1600), (1600, 2501)]
    picked = []
    for lo, hi in bins:
        n = 0
        for c in pool:
            if n >= nper:
                break
            if not lo <= c["len"] < hi:
                continue
            if any(near(c["text"], t, 0.6) for t in enron_texts):
                c["flags"].append("near-enron")
                continue
            c["bin"] = f"{lo}-{hi - 1}"
            picked.append(c)
            n += 1
    if "--pool" in sys.argv:
        with open(sys.argv[sys.argv.index("--pool") + 1], "w", encoding="utf-8") as f:
            for c in pool:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(out_c, "w", encoding="utf-8") as f:
        for c in picked:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    with open(out_r, "w", encoding="utf-8") as f:
        for c in picked:
            f.write(f"===== row={c['i']} rank={c['rank']} bin={c['bin']} len={c['len']} req={c['req']} "
                    f"trig={c['trig']} flags={c['flags']}\n{c['text']}\n\n")
    print("candidates written:", len(picked), "req", sum(c["req"] for c in picked))


if __name__ == "__main__":
    main()
