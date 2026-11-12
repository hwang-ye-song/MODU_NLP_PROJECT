"""Precompute the 'near duplicate of existing data' flag for pool rows, in parallel, into the
cache file that select_p1.py reads (same normalisation, similarity rule and cache signature).

Usage: python -X utf8 -I precompute_ex.py <pool.jsonl> <out_dir> <detectors comma|all> <tiers comma> <existing.jsonl> [...]
"""
import hashlib
import json
import re
import sys
import unicodedata
from difflib import SequenceMatcher
from multiprocessing import Pool
from pathlib import Path

ZW = re.compile("[​-‏⁠-⁤﻿­᠎͏]")
COMB = re.compile("[̀-ͯ҉⃐-⃿]")


def norm_sim(t):
    t = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t)
    t = unicodedata.normalize("NFKC", ZW.sub("", t))
    t = COMB.sub("", unicodedata.normalize("NFKD", t))
    return re.sub(r"\s+", " ", t.lower()).strip()


def shingles(t):
    return {hash(t[i:i + 5]) for i in range(max(1, len(t) - 4))}


EX = []


def init(ex):
    global EX
    EX = [(t, ll, shingles(t)) for t, ll in ex]


def similar(a, sa, b, sb, contain):
    la, lb = len(a), len(b)
    inter = len(sa & sb)
    if contain and min(la, lb) >= 150 and inter / max(1, min(len(sa), len(sb))) >= 0.8:
        return True
    jac = inter / max(1, len(sa) + len(sb) - inter)
    if jac >= 0.5:
        return True
    if 2 * min(la, lb) / (la + lb) < 0.6:
        return False
    if jac < 0.12:
        return False
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.6


def work(item):
    ri, nt = item
    s = shingles(nt)
    return str(ri), any(similar(nt, s, t, st, ll) for t, ll, st in EX)


def main():
    pool_p, out_dir, dets, tiers = sys.argv[1:5]
    files = sys.argv[5:]
    ex = []
    for p in files:
        for l in Path(p).read_text(encoding="utf-8").splitlines():
            if l.strip():
                r = json.loads(l)
                ex.append((norm_sim(r["text"]), r.get("source") == "LLMail-Inject"))
    sig = hashlib.sha1(("v3-contain-jacc|||" + "|||".join(sorted(t for t, _ in ex))).encode("utf-8")).hexdigest()[:16]
    cache_p = Path(out_dir) / f"ex_neardup_cache_{sig}.json"
    cache = json.loads(cache_p.read_text(encoding="utf-8")) if cache_p.exists() else {}
    dets = None if dets == "all_detectors" else set(dets.split(","))
    tiers = set(tiers.split(","))
    items = []
    for l in open(pool_p, encoding="utf-8"):
        r = json.loads(l)
        if (dets is None or r["detector"] in dets) and r["tier"] in tiers and str(r["row_index"]) not in cache:
            items.append((r["row_index"], norm_sim(r["text"])))
    print("signature", sig, "cached", len(cache), "to compute", len(items), flush=True)
    with Pool(15, initializer=init, initargs=(ex,)) as pool:
        for k, (key, flag) in enumerate(pool.imap_unordered(work, items, chunksize=8), 1):
            cache[key] = flag
            if k % 1000 == 0:
                print(k, flush=True)
    cache_p.write_text(json.dumps(cache), encoding="utf-8")
    print("written", cache_p.name, len(cache), "flagged", sum(cache.values()))


if __name__ == "__main__":
    main()
