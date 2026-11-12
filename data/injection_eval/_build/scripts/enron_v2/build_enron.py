"""Build 40 benign Enron emails (AESLC train split) -> parts_v2/enron.jsonl.

Usage: python -X utf8 -I build_enron.py <train.parquet> <WD/parts dir> <out.jsonl> [--dump review.txt]
Needs pyarrow (run with SP/venvs/enron_v2 python).
"""
import difflib
import glob
import json
import random
import re
import statistics
import sys

import pyarrow.parquet as pq

DATASET = "Yale-LILY/aeslc"
REVISION = "2305f2e63b68056f9b9037a3805c8c196e0d5581"
FILE = "data/train-00000-of-00001.parquet"
SPLIT = "train"

# (lo, hi_exclusive, total, n_with_request)
BINS = [
    (200, 450, 7, 2),
    (450, 700, 9, 3),
    (700, 1000, 10, 4),
    (1000, 1600, 8, 2),
    (1600, 3001, 6, 2),
]

# Rows rejected on manual reading of earlier candidate draws (reason recorded).
MANUAL_REJECT = {
    1200: "Travelocity marketing mail",
    2197: "pasted LA Times news article, truncated",
    7100: "quoted-printable artifacts (=20), truncated",
    10007: "debt-consolidation spam",
    2031: "truncated mid-sentence by AESLC",
    10729: "sexist dress-code joke",
    1794: "mass event invitation from outside organisation",
    1798: "announced quote stripped by AESLC, ends mid-thought",
    6574: "fragmentary event notice (details stripped)",
    9276: "mock-accent ethnic humour",
    13748: "private individual's medical situation",
}

# Selected rows whose clear request the regex missed (found on manual reading). Notes only;
# does not change the sampling strata.
MANUAL_REQ_NOTE = {
    5349: "we would appreciate your assistance in getting ... to execute this agreement",
    8342: "insert the confidentiality language and print out on letterhead and initial",
}

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
RE_AI = re.compile(r"(?i)\bA\.?I\.?\b|artificial intelligence|chat ?bot|language model|\bLLM\b|\bGPT|"
                   r"ignore (all|the|any|previous|prior|above)|system prompt|\bprompt\b|disregard (all|the|any|previous|prior|above)")
RE_OFFENSIVE = re.compile(r"(?i)\bf+u+c+k|\bshit|\bbitch|\bsex|\bnude|\bnaked|\bporn|\bdamn\b|\bass\b|\bbastard|\bnigg|\bfag|\bjoke")

# Boilerplate offers ("call me if you have questions") do not count as substantive requests.
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


def ngrams(s, n=5):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def too_similar(a, b):
    ga, gb = ngrams(a), ngrams(b)
    if ga and gb and len(ga & gb) / len(ga | gb) >= 0.5:
        return True
    return difflib.SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.8


def reject_reason(subject, body, text):
    if not subject or not body:
        return "empty"
    if not (200 <= len(text) <= 3000):
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
    src, parts_dir, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
    dump = sys.argv[sys.argv.index("--dump") + 1] if "--dump" in sys.argv else None
    rows = pq.read_table(src).to_pylist()

    existing = []
    for fp in glob.glob(parts_dir.rstrip("/\\") + "/*.jsonl"):
        with open(fp, encoding="utf-8") as f:
            existing += [json.loads(l)["text"] for l in f if l.strip()]

    pool, reasons, seen_subj = [], {}, set()
    for i, r in enumerate(rows):
        subject = norm_ws(r["subject_line"]).replace("\n", " ")
        body = norm_ws(r["email_body"])
        text = f"Subject: {subject}\n\n{body}"
        why = reject_reason(subject, body, text)
        if why is None and i in MANUAL_REJECT:
            why = "manual"
        if why is None and subject.lower() in seen_subj:
            why = "dup-subject"
        reasons[why] = reasons.get(why, 0) + 1
        if why is None:
            seen_subj.add(subject.lower())
            pool.append({"i": i, "subject": subject, "body": body, "text": text, "req": has_request(body)})
    print("filter:", reasons, "pool", len(pool))

    # Fix a random order over ALL row indices (independent of filtering), so that a manual
    # rejection only replaces that one item with the next eligible row of the same stratum.
    order = list(range(len(rows)))
    random.seed(42)
    random.shuffle(order)
    rank = {i: k for k, i in enumerate(order)}
    pool.sort(key=lambda c: rank[c["i"]])
    chosen = []
    for lo, hi, total, nreq in BINS:
        need = {True: nreq, False: total - nreq}
        for c in pool:
            if not need[True] and not need[False]:
                break
            if not (lo <= len(c["text"]) < hi) or need[c["req"]] <= 0:
                continue
            if any(too_similar(c["text"], x["text"]) for x in chosen):
                continue
            if any(too_similar(c["text"], e) for e in existing):
                continue
            c["bin"] = f"{lo}-{hi - 1}"
            chosen.append(c)
            need[c["req"]] -= 1
        assert not need[True] and not need[False], (lo, hi, need)

    chosen.sort(key=lambda c: c["i"])
    url = f"https://huggingface.co/datasets/{DATASET}/resolve/{REVISION}/{FILE}"
    recs = []
    for n, c in enumerate(chosen, 1):
        recs.append({
            "id": f"enron-ben-{n:02d}",
            "label": "benign",
            "source": "Enron",
            "subset": "enron_email",
            "text": c["text"],
            "injected_instruction": None,
            "origin": {"dataset": DATASET, "url": url, "revision": REVISION, "file": FILE,
                       "split": SPLIT, "row_index": c["i"]},
            "notes": ("Real Enron email from AESLC (Zhang & Tetreault 2019) train split; text = 'Subject: ' + "
                      "subject_line + blank line + email_body, whitespace-normalised only (AESLC source has "
                      "quoted text/forward headers removed and one sentence per line; kept as-is). "
                      + ("Contains a natural human-to-human request (hard negative). " if c["req"] else "")
                      + ("Contains a natural human-to-human request (hard negative; found on manual review). "
                         if not c["req"] and c["i"] in MANUAL_REQ_NOTE else "")
                      + f"Length bin {c['bin']} chars. Reviewed manually: benign, nothing addressed to an AI system."),
            "core": False,
        })
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for r in recs:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    L = sorted(len(r["text"]) for r in recs)
    print("wrote", len(recs), "req", sum(c["req"] for c in chosen),
          "len min/median/max", L[0], statistics.median(L), L[-1])
    if dump:
        with open(dump, "w", encoding="utf-8") as f:
            for r, c in zip(recs, chosen):
                f.write(f"===== {r['id']} row={c['i']} req={c['req']} len={len(c['text'])}\n{c['text']}\n\n")


if __name__ == "__main__":
    main()
