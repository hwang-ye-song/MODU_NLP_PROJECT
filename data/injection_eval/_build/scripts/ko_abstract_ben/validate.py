import json, re, sys
en_path, ko_path = sys.argv[1:3]
en = {r["id"]: r for r in (json.loads(l) for l in open(en_path, encoding="utf-8"))}
ko = [json.loads(l) for l in open(ko_path, encoding="utf-8")]
ids = [r["id"] for r in ko]
assert len(ids) == len(set(ids)), "dup ids"
ben_order = [i for i, r in en.items() if r["label"] == "benign"]
assert [r["pair_id"] for r in ko] == ben_order, "order/pairing mismatch"
bad = 0
for r in ko:
    e = en[r["pair_id"]]
    assert r["id"] == e["id"] + "-ko" and r["lang"] == "ko"
    for k in ("label", "source", "subset", "origin", "core"):
        assert r[k] == e[k], (r["id"], k)
    assert r["injected_instruction"] is None and r["label"] == "benign"
    t = r["text"]
    hangul = len(re.findall(r"[\uac00-\ud7a3]", t))
    letters = len(re.findall(r"[A-Za-z\uac00-\ud7a3]", t))
    ratio = hangul / letters
    ratio_len = len(t) / len(e["text"])
    # untranslated English runs: 6+ consecutive Latin words
    runs = re.findall(r"(?:\b[A-Za-z][A-Za-z'\-]*\b[ ,]+){6,}[A-Za-z]+", t)
    # numbers in EN that are missing in KO (ignoring ones possibly localized)
    nums_en = set(re.findall(r"\d[\d,.:]*\d|\d", e["text"]))
    missing = [n for n in nums_en if n not in t]
    flag = ratio < 0.5 or runs or ratio_len < 0.3
    if flag or missing:
        print(r["id"], f"hangul={ratio:.2f} len_ratio={ratio_len:.2f}", "runs:", runs[:3], "missing nums:", missing)
    bad += bool(flag)
print("records", len(ko), "flagged", bad)
