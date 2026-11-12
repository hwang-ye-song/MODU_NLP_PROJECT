"""Build the long-document test set for the OpenJevX long-input experiments.

Each document is a benign long carrier (web page / wiki / news / email thread) cut to a target token
length, optionally with something inserted at a sentence boundary:

  label=1  cond=natural  one injected instruction at a uniformly random position
  label=1  cond=tail     the instruction in the last ~5% of the document (beyond the 465-token window)
  label=1  cond=split    the instruction cut into 3 word-fragments "(1/3) ..." spread at ~15/50/85%
  label=0  cond=clean    carrier only
  label=0  cond=hardneg  a benign text full of trigger words ("ignore the previous worksheet") inserted

Payloads and hard negatives come from the earlier 100/500-item dataset (BIPIA, InjecAgent, LLMail,
NotInject, synthetic hard negatives, and their Korean translations). Splits are disjoint in payloads
(by pair id, so an English payload and its Korean translation share a split) and in carrier documents.

    python build_longdocs.py --per-lang-split 60
"""
import argparse
import hashlib
import json
import os
import random
import re

from jevx_client import tokenize_with_offsets

HERE = os.path.dirname(os.path.abspath(__file__))
PRIOR = os.environ.get("PRIOR_DATA", os.path.join(HERE, "data", "prior"))  # frozen copy of the earlier dataset parts
LENGTHS = [1024, 2048, 4096]


def jl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def split_of(key):
    """Deterministic 50/50 dev/test split by a stable key."""
    return "dev" if int(hashlib.md5(key.encode()).hexdigest(), 16) % 2 == 0 else "test"


def load_payloads():
    out = {"en": [], "ko": []}
    seen = set()
    en_files = ["parts_v2/bipia.jsonl", "parts_v2/injecagent.jsonl", "parts/llmail_injection.jsonl"]
    ko_files = ["ko_parts/core_inj.jsonl", "ko_parts/injecagent_inj_new.jsonl"]
    for lang, files in (("en", en_files), ("ko", ko_files)):
        for f in files:
            for r in jl(os.path.join(PRIOR, f)):
                p = (r.get("injected_instruction") or "").strip()
                if r.get("label") != "injection" or not p or (lang, p) in seen:
                    continue
                seen.add((lang, p))
                pid = r.get("pair_id") or r["id"]
                pid = re.sub(r"-ko$", "", pid)
                out[lang].append({"payload_id": r["id"], "pair": pid, "source": r.get("source"), "subset": r.get("subset"),
                                  "text": p})
    return out


def load_hardnegs():
    out = {"en": [], "ko": []}
    for r in jl(os.path.join(PRIOR, "parts_v2/hardneg.jsonl")) + jl(os.path.join(PRIOR, "parts_v2/notinject.jsonl")):
        out["en"].append({"id": r["id"], "subset": r.get("subset"), "text": r["text"].strip()})
    for r in jl(os.path.join(PRIOR, "ko_parts/misc_ben_new.jsonl")) + jl(os.path.join(PRIOR, "ko_parts/core_ben.jsonl")):
        if r.get("subset") in ("hard_negative", "NotInject_one", "NotInject_two", "NotInject_three"):
            out["ko"].append({"id": r["id"], "subset": r.get("subset"), "text": r["text"].strip()})
    return out


def load_carriers():
    """Benign long texts per language, each with a stable id for splitting."""
    out = {"en": [], "ko": []}
    # en_email = Enron threads of 3-6 consecutive emails (corbt/enron-emails), grouped at fetch time.
    for name in ("en_web", "en_wiki", "en_email", "ko_web", "ko_wiki", "ko_news"):
        path = os.path.join(HERE, "raw", name + ".jsonl")
        if not os.path.exists(path):
            continue
        for i, r in enumerate(jl(path)):
            out[r["lang"]].append({"cid": f"{name}-{i:04d}", "src": name, "text": r["text"]})
    return out


BOUNDARY = re.compile(r"(?<=[.!?。])\s+|\n+|(?<=다\.)|(?<=요\.)")


def boundaries(text):
    b = sorted({m.end() for m in BOUNDARY.finditer(text)} | {0, len(text)})
    return b


def cut_to_tokens(text, n_tokens):
    """Cut text at the last sentence boundary at or before n_tokens tokens."""
    ids, offs = tokenize_with_offsets(text)
    if len(ids) <= n_tokens:
        return text
    limit = offs[n_tokens - 1][1]
    b = [x for x in boundaries(text) if x <= limit]
    end = b[-1] if b and b[-1] > limit * 0.8 else limit
    return text[:end].rstrip()


def make_carrier(pool, rng, n_tokens, used):
    """Concatenate docs from one source until n_tokens, then cut at a sentence boundary."""
    src = rng.choice(sorted({c["src"] for c in pool}))
    cands = [c for c in pool if c["src"] == src and c["cid"] not in used] or [c for c in pool if c["src"] == src]
    rng.shuffle(cands)
    parts, ids = [], []
    for c in cands:
        parts.append(c["text"])
        ids.append(c["cid"])
        used.add(c["cid"])
        if len(tokenize_with_offsets("\n\n".join(parts))[0]) >= n_tokens * 1.02:
            break
    text = cut_to_tokens("\n\n".join(parts), n_tokens)
    return text, src, ids


def insert_at(text, frac, piece):
    """Insert piece at the sentence boundary closest to frac*len(text). Returns (new_text, (start, end))."""
    target = int(frac * len(text))
    b = boundaries(text)
    pos = min(b, key=lambda x: abs(x - target))
    before, after = text[:pos], text[pos:]
    sep_l = "" if before.endswith(("\n", " ")) or not before else " "
    sep_r = "" if after.startswith(("\n", " ")) or not after else " "
    new = before + sep_l + piece + sep_r + after
    s = len(before) + len(sep_l)
    return new, (s, s + len(piece))


def insert_many(text, fracs, pieces):
    for frac, piece in sorted(zip(fracs, pieces), key=lambda x: -x[0]):  # right-to-left so fractions stay meaningful
        text, _ = insert_at(text, frac, piece)
    # Find the spans afterwards, in order (each piece starts with a unique "(i/k)" marker).
    spans, cursor = [], 0
    for piece in pieces:
        i = text.find(piece, cursor)
        spans.append((i, i + len(piece)))
        cursor = i + len(piece)
    return text, spans


def split_payload(p, k=3):
    words = p.split()
    if len(words) < k:
        words = list(p)
        joiner = ""
    else:
        joiner = " "
    n = len(words)
    cuts = [round(i * n / k) for i in range(k + 1)]
    return [f"({i + 1}/{k}) " + joiner.join(words[cuts[i]:cuts[i + 1]]) for i in range(k)]


def token_spans(text, spans):
    ids, offs = tokenize_with_offsets(text)
    out = []
    for s, e in spans:
        toks = [i for i, (a, b) in enumerate(offs) if b > s and a < e]
        out.append((toks[0], toks[-1] + 1) if toks else (None, None))
    return out, len(ids)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-lang-split", type=int, default=60, help="payloads per language per split")
    ap.add_argument("--clean-per-lang-split", type=int, default=90)
    ap.add_argument("--hardneg-per-lang-split", type=int, default=45)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=os.path.join(HERE, "data", "longdocs.jsonl"))
    args = ap.parse_args()

    payloads, hardnegs, carriers = load_payloads(), load_hardnegs(), load_carriers()
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    docs = []
    for lang in ("en", "ko"):
        for split in ("dev", "test"):
            rng = random.Random(f"{args.seed}-{lang}-{split}")
            pool = [c for c in carriers[lang] if split_of(c["cid"]) == split]
            pays = [p for p in payloads[lang] if split_of(p["pair"]) == split]
            rng.shuffle(pays)
            pays = pays[:args.per_lang_split]
            hns = [h for h in hardnegs[lang] if split_of(h["id"]) == split] or hardnegs[lang]
            used = set()
            n = 0

            def add(label, cond, text, src, cids, extra):
                nonlocal n
                n += 1
                d = {"id": f"{lang}-{split}-{n:04d}", "lang": lang, "split": split, "label": label, "cond": cond,
                     "carrier_src": src, "carrier_ids": cids, **extra, "text": text}
                if extra.get("spans"):
                    tsp, ntok = token_spans(text, extra["spans"])
                    d["token_spans"] = tsp
                else:
                    ntok = len(tokenize_with_offsets(text)[0])
                d["n_tokens"] = ntok
                docs.append(d)

            for i, p in enumerate(pays):
                for j, cond in enumerate(("natural", "tail", "split")):
                    T = LENGTHS[(i + j) % 3]
                    text, src, cids = make_carrier(pool, rng, T, used)
                    if cond == "natural":
                        frac = rng.random()
                        new, sp = insert_at(text, frac, p["text"])
                        spans = [sp]
                    elif cond == "tail":
                        frac = rng.uniform(0.95, 1.0)
                        new, sp = insert_at(text, frac, p["text"])
                        spans = [sp]
                    else:
                        frac = None
                        fr = [rng.uniform(0.10, 0.20), rng.uniform(0.45, 0.55), rng.uniform(0.80, 0.90)]
                        new, spans = insert_many(text, fr, split_payload(p["text"]))
                    add(1, cond, new, src, cids, {"target_tokens": T, "payload_id": p["payload_id"], "payload_source": p["source"],
                                                  "payload": p["text"], "spans": spans,
                                                  "rel_pos": round(spans[0][0] / max(1, len(new)), 3)})
            for i in range(args.clean_per_lang_split):
                T = LENGTHS[i % 3]
                text, src, cids = make_carrier(pool, rng, T, used)
                add(0, "clean", text, src, cids, {"target_tokens": T})
            for i in range(args.hardneg_per_lang_split):
                T = LENGTHS[i % 3]
                text, src, cids = make_carrier(pool, rng, T, used)
                h = hns[i % len(hns)]
                new, sp = insert_at(text, rng.random(), h["text"])
                add(0, "hardneg", new, src, cids, {"target_tokens": T, "hardneg_id": h["id"], "spans": [sp],
                                                   "rel_pos": round(sp[0] / max(1, len(new)), 3)})
    with open(args.out, "w", encoding="utf-8") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    import collections
    c = collections.Counter((d["lang"], d["split"], d["cond"]) for d in docs)
    for k in sorted(c):
        print(k, c[k])
    print("total", len(docs), "docs;", sum(d["n_tokens"] for d in docs), "tokens")


if __name__ == "__main__":
    main()
