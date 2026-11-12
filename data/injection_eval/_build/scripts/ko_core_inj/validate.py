"""Validate ko_parts/core_inj.jsonl against the EN core injections.
usage: python -X utf8 -I validate.py <dataset_en_100.jsonl> <core_inj.jsonl>
"""
import ast
import base64
import json
import re
import sys
from collections import Counter

en_rows = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
EN = {r["id"]: r for r in en_rows if r["label"] == "injection"}
lines = open(sys.argv[2], encoding="utf-8").read().split("\n")
assert lines[-1] == ""
KO = [json.loads(l) for l in lines[:-1]]
errs = []
print("records:", len(KO))
if len(KO) != 50:
    errs.append("count")
if [k["pair_id"] for k in KO] != list(EN):
    errs.append("order/pair_id mismatch")
if len({k["id"] for k in KO}) != len(KO):
    errs.append("dup ids")

FENCE = re.compile(r"```.*?```", re.S)
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
EMAILS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
URLS = re.compile(r"(?:https?://|www\.)\S+")

for k in KO:
    e = EN[k["pair_id"]]
    rid = k["pair_id"]
    for f in ("label", "source", "subset", "origin"):
        if k[f] != e[f]:
            errs.append(f"{rid}: {f} changed")
    if k["id"] != rid + "-ko" or k["lang"] != "ko" or k["core"] is not True:
        errs.append(f"{rid}: id/lang/core")
    if set(k) & {"uid", "label_int", "char_len"}:
        errs.append(f"{rid}: dropped field present")
    ii = k["injected_instruction"]
    if (ii is None) != (e["injected_instruction"] is None):
        errs.append(f"{rid}: ii null mismatch")
    if ii is not None and ii not in k["text"]:
        errs.append(f"{rid}: ii not substring")
    t, te = k["text"], e["text"]
    # code fences identical
    if FENCE.findall(t) != FENCE.findall(te):
        errs.append(f"{rid}: fenced code differs")
    # inline code multiset identical for BIPIA code
    if e["subset"] == "code":
        ic = lambda s: Counter(re.findall(r"`[^`]*`", FENCE.sub("", s)))
        if ic(t) != ic(te):
            errs.append(f"{rid}: inline code differs {ic(t) - ic(te)} / {ic(te) - ic(t)}")
    # emails / urls preserved
    if Counter(EMAILS.findall(te)) - Counter(EMAILS.findall(t)):
        # Korean particles glued after an address are fine; compare by containment
        miss = [x for x in EMAILS.findall(te) if x not in t]
        if miss:
            errs.append(f"{rid}: emails missing {miss}")
    miss = [u for u in URLS.findall(te) if u.rstrip('.,"\'') not in t]
    if miss:
        errs.append(f"{rid}: urls missing {miss}")
    # special chars preserved
    for ch in ("\U000e005f", "​", "\r"):
        if te.count(ch) != t.count(ch):
            errs.append(f"{rid}: count of {ch!r} {te.count(ch)}->{t.count(ch)}")
    # line count (structure) for non-table items
    if e["subset"] != "table" and te.count("\n") != t.count("\n"):
        errs.append(f"{rid}: newline count {te.count(chr(10))}->{t.count(chr(10))}")
    if e["subset"] == "table":
        rows_en = [l for l in te.split("\n") if l.startswith("|")]
        rows_ko = [l for l in t.split("\n") if l.startswith("|")]
        if len(rows_en) != len(rows_ko) or [l.count("|") for l in rows_en] != [l.count("|") for l in rows_ko]:
            errs.append(f"{rid}: table structure differs")
    # InjecAgent parse checks
    if e["source"] == "InjecAgent":
        xe, xk = json.loads(te), json.loads(t)
        assert isinstance(xk, str)
        if json.dumps(xk, ensure_ascii=False) != t:
            errs.append(f"{rid}: not json.dumps(ensure_ascii=False)")
        def tryast(s):
            try:
                return ast.literal_eval(s)
            except Exception:
                return None
        de, dk = tryast(xe), tryast(xk)
        if (de is None) != (dk is None):
            errs.append(f"{rid}: ast parse status differs")
        if de is not None:
            def shape(o):
                if isinstance(o, dict):
                    return {kk: shape(v) for kk, v in o.items()}
                if isinstance(o, list):
                    return [shape(v) for v in o]
                return type(o).__name__
            if shape(de) != shape(dk):
                errs.append(f"{rid}: inner structure differs")
            def leaves(o, p=""):
                if isinstance(o, dict):
                    for kk, v in o.items():
                        yield from leaves(v, p + "/" + kk)
                elif isinstance(o, list):
                    for i, v in enumerate(o):
                        yield from leaves(v, f"{p}[{i}]")
                else:
                    yield p, o
            le, lk = dict(leaves(de)), dict(leaves(dk))
            changed = [p for p in le if le[p] != lk[p]]
            k["_changed"] = changed
    # Hangul ratio outside code fences / emails / urls
    body = URLS.sub("", EMAILS.sub("", FENCE.sub("", t)))
    h, l = len(HANGUL.findall(body)), len(LATIN.findall(body))
    k["_ratio"] = h / max(1, h + l)

# encoded payloads round-trip
k8 = next(k for k in KO if k["pair_id"] == "llmail-inj-08")
hx = re.search(r"((?:[0-9A-F]{2} )+[0-9A-F]{2})", k8["text"]).group(1)
print("inj-08 hex decodes to:", bytes.fromhex(hx.replace(" ", "")).decode("utf-8"))
k15 = next(k for k in KO if k["pair_id"] == "llmail-inj-15")
seg = re.search(r"이어 붙이거나 합치세요: (.*)\n", k15["text"]).group(1)
fr = re.findall(r"[A-Za-z0-9+/=]{4,}", seg)
print("inj-15 b64 fragments:", len(fr), "decodes to:", base64.b64decode("".join(fr)).decode("utf-8"))

print("\nHangul ratio (hangul/(hangul+latin), excl. code/emails/urls):")
for k in sorted(KO, key=lambda x: x["_ratio"])[:12]:
    print(f"  {k['pair_id']:20s} {k['_ratio']:.2f}")
print("\nInjecAgent changed leaves:")
for k in KO:
    if "_changed" in k:
        print("  ", k["pair_id"], k["_changed"])

# leftover English: runs of >=4 latin words outside fences
print("\nLatin runs (>=4 words) outside code fences:")
for k in KO:
    body = FENCE.sub("", k["text"])
    runs = re.findall(r"(?:[A-Za-z][A-Za-z'’.-]*[ ,]+){3,}[A-Za-z][A-Za-z'’.-]*", body)
    if runs:
        print("  ", k["pair_id"], runs[:6])

print("\nERRORS:" if errs else "\nno errors", *errs, sep="\n  ")
