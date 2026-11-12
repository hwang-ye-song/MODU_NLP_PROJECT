# -*- coding: utf-8 -*-
"""Validate KO core-benign output. Usage: validate.py <dataset_en_100.jsonl> <core_ben.jsonl>"""
import ast
import json
import re
import sys

FENCE = re.compile(r"```.*?```", re.S)
HANGUL = re.compile(r"[가-힣]")
LATIN = re.compile(r"[A-Za-z]")
# emails, URLs, $ amounts, masked card digits, clock times, percentages, ISO dates, RFC dates
PROTECTED = re.compile(
    r"[\w.+-]+@[\w.-]+|https?://\S+|\$\d[\d,]*(?:\.\d+)?|••\d+|\d{1,2}:\d{2}(?::\d{2})?"
    r"|\d+%|\b(?:19|20)\d{2}-\d{2}-\d{2}\b|\b\d{2} [A-Z][a-z]{2} \d{4}\b")


def main(inp, outp):
    en = {}
    for l in open(inp, encoding="utf-8"):
        r = json.loads(l)
        en[r["id"]] = r
    ko = [json.loads(l) for l in open(outp, encoding="utf-8")]  # raises on bad JSON
    en_ben = [r["id"] for r in en.values() if r["label"] == "benign"]
    probs = []
    if len(ko) != 50:
        probs.append(f"count {len(ko)}")
    if [k["pair_id"] for k in ko] != en_ben:
        probs.append("order/pairing mismatch")
    if len({k["id"] for k in ko}) != len(ko):
        probs.append("duplicate ids")
    for k in ko:
        e = en[k["pair_id"]]
        rid = k["id"]
        if rid != e["id"] + "-ko":
            probs.append(f"{rid}: id")
        for f in ("label", "source", "subset", "origin"):
            if k[f] != e[f]:
                probs.append(f"{rid}: {f} changed")
        if k["lang"] != "ko" or k["core"] is not True or k["injected_instruction"] is not None:
            probs.append(f"{rid}: lang/core/injected_instruction")
        for f in ("uid", "label_int", "char_len"):
            if f in k:
                probs.append(f"{rid}: has {f}")
        t, et = k["text"], e["text"]
        if t == et:
            probs.append(f"{rid}: untranslated")
        if FENCE.findall(t) != FENCE.findall(et):
            probs.append(f"{rid}: code fences differ")
        if e["source"] != "InjecAgent" and t.count("\n") != et.count("\n"):
            probs.append(f"{rid}: line count differs")
        if e["source"] == "InjecAgent":
            s1, s2 = json.loads(et), json.loads(t)
            d1, d2 = ast.literal_eval(s1), ast.literal_eval(s2)
            if type(s2) is not str or type(d2) is not dict or list(d1) != list(d2):
                probs.append(f"{rid}: injecagent parse")
        for tok in set(PROTECTED.findall(et)):
            if tok not in t:
                probs.append(f"{rid}: protected token missing {tok!r}")
        prose = FENCE.sub("", t)
        h = len(HANGUL.findall(prose))
        la = len(LATIN.findall(prose))
        k["_ratio"] = h / max(1, h + la)
    print("problems:", probs or "none")
    print("records:", len(ko), "| by source:",
          {s: sum(1 for k in ko if k["source"] == s) for s in sorted({k["source"] for k in ko})})
    print("Hangul/(Hangul+Latin) in prose, lowest 12:")
    for k in sorted(ko, key=lambda x: x["_ratio"])[:12]:
        print(f"  {k['id']:22s} {k['_ratio']:.2f}")
    # leftover English prose: 4+ consecutive English words outside code/inline code/URLs
    print("Runs of >=4 English words outside code:")
    for k in ko:
        p = FENCE.sub("", k["text"])
        p = re.sub(r"`[^`]*`", "", p)
        p = re.sub(r"\S+@\S+|https?://\S+", "", p)
        for m in re.finditer(r"(?:[A-Za-z][A-Za-z'.,-]*\s+){3,}[A-Za-z][A-Za-z'.,-]*", p):
            print(f"  {k['id']}: {m.group(0)!r}")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
