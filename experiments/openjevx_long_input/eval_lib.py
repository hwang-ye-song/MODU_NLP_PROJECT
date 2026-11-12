"""Shared evaluation harness for the OpenJevX long-input strategies.

A *strategy* turns each long document into one score in [0, 1] (higher = injection) and reports what it cost.
Write it as a function over a LIST of docs so all chunks go to the GPU server in one batch:

    def my_strategy(docs, **cfg):
        chunk_lists = [chunk_tokens(d["text"], window=450, overlap=96) for d in docs]
        probs = score_nested(chunk_lists)                      # same nesting, P(injection) per chunk
        return [result(max(p), chunks=c) for p, c in zip(probs, chunk_lists)]

    docs = load_docs("dev")
    out = my_strategy(docs)
    m = evaluate(docs, out)          # metrics dict
    print_summary("my_strategy", m)
    save_result("my_strategy", {"window": 450}, m, split="dev")

PRIMARY metric = m["macro"]["tpr@fpr5"]: recall at 5% FPR with a separate threshold per language, averaged
over EN and KO (deployments can detect language and set per-language thresholds). Also report AUROC.

Model ceiling (measured on the earlier SHORT documents that fit in one window, 350 per language):
  EN AUROC ~0.80, TPR@FPR5 ~0.40;  KO AUROC ~0.60, TPR@FPR5 ~0.10. A long-input strategy can at best get back to
  roughly that level (or beat it only by making the payload denser in the window). Korean is weak at the model level.

Metrics (computed per language and pooled):
  auroc                       threshold-free separation of injected vs benign documents
  tpr@fpr5 / tpr@fpr1         recall at the threshold that lets through at most 5% / 1% of benign docs
                              (threshold picked on the SAME split's benign docs -> optimistic on dev;
                               the final comparison uses thresholds fixed on dev and applied to test)
  at_0.5 / at_0.8             recall and false-positive rate at fixed thresholds (0.8 = jevx's default "yes")
  by_cond                     recall per attack (natural / tail / split), FPR per benign kind (clean / hardneg)
  by_len                      recall per target length (1024 / 2048 / 4096 tokens)
  cost                        model calls per doc, tokens fed to the model per doc, estimated CPU seconds per doc
                              (per call: cpu_seconds(len), fitted to this laptop's Ryzen 7 250 — 1.05 s at 512
                               tokens, superlinear beyond; the GPU used for the simulations is NOT the target)
"""
import json
import math
import os
import re

from jevx_client import QUESTION, STATE_BUDGET, score, tok_len, tokenize_with_offsets, prefix_len

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "data", "longdocs.jsonl")
RESULTS = os.path.join(HERE, "results")
CPU_S_PER_512 = 1.05


# ---------------------------------------------------------------- data
def load_docs(split="dev", lang=None, path=DATA, subset=None):
    """subset="small": every 3rd doc within each (lang, cond, target_tokens) group (~1/3 of the split,
    same balance) — use it for wide sweeps, then confirm finalists on the full split."""
    with open(path, encoding="utf-8") as f:
        docs = [json.loads(l) for l in f if l.strip()]
    docs = [d for d in docs if d["split"] == split and (lang is None or d["lang"] == lang)]
    if subset == "small":
        seen, keep = {}, []
        for d in docs:
            g = (d["lang"], d["cond"], d["target_tokens"])
            seen[g] = seen.get(g, -1) + 1
            if seen[g] % 3 == 0:
                keep.append(d)
        docs = keep
    return docs


# ---------------------------------------------------------------- chunking helpers
def chunk_tokens(text, window=STATE_BUDGET, overlap=0):
    """Fixed token windows over the model's own tokenizer, returned as text slices of the original string."""
    ids, offs = tokenize_with_offsets(text)
    if len(ids) <= window:
        return [text]
    step = max(1, window - overlap)
    out = []
    for s in range(0, len(ids), step):
        e = min(s + window, len(ids))
        out.append(text[offs[s][0]:offs[e - 1][1]])
        if e == len(ids):
            break
    return out


_SENT = re.compile(r"(?<=[.!?。])\s+|\n+|(?<=다\.)\s*|(?<=요\.)\s*")


def sentences(text):
    """Rough sentence split that works for English and Korean; keeps every character."""
    parts, last = [], 0
    for m in _SENT.finditer(text):
        if m.end() > last:
            parts.append(text[last:m.end()])
            last = m.end()
    if last < len(text):
        parts.append(text[last:])
    return [p for p in parts if p.strip()]


def chunk_sentences(text, budget=STATE_BUDGET, overlap_sents=0):
    """Greedy-pack whole sentences up to `budget` tokens; a sentence longer than budget is token-split."""
    sents = sentences(text)
    lens = [tok_len(s) for s in sents]
    chunks, cur, cur_len, i = [], [], 0, 0
    while i < len(sents):
        s, n = sents[i], lens[i]
        if n > budget:
            if cur:
                chunks.append(cur)
                cur, cur_len = [], 0
            for piece in chunk_tokens(s, budget, 0):
                chunks.append([piece])
            i += 1
            continue
        if cur_len + n > budget and cur:
            chunks.append(cur)
            keep = cur[-overlap_sents:] if overlap_sents else []
            cur, cur_len = list(keep), sum(tok_len(x) for x in keep)
            if cur_len + n > budget:
                cur, cur_len = [], 0
            continue
        cur.append(s)
        cur_len += n
        i += 1
    if cur:
        chunks.append(cur)
    return ["".join(c) for c in chunks] or [text]


# ---------------------------------------------------------------- scoring helpers
def score_nested(chunk_lists, question=QUESTION, max_len=512):
    """Score a list of chunk lists in one batched request; returns probs with the same nesting."""
    flat = [c for cl in chunk_lists for c in cl]
    probs = score(flat, question=question, max_len=max_len) if flat else []
    out, k = [], 0
    for cl in chunk_lists:
        out.append(probs[k:k + len(cl)])
        k += len(cl)
    return out


def cpu_seconds(seq_len):
    """Measured on this laptop (Ryzen 7 250, onnxruntime 1.31 CPU, batched): 512 tok -> 1.05 s,
    ~880 tok -> 2.0 s, ~3,700 tok -> 16 s. Fitted a*L + b*L^2 (attention makes long inputs superlinear)."""
    return 1.686e-3 * seq_len + 7.13e-7 * seq_len * seq_len


def result(doc_score, chunks=None, calls=None, tokens=None, max_len=512, extra=None, question=None):
    """Package one document's outcome. Pass the chunks you scored (or calls/tokens) so cost is counted.
    Cost = model calls, model input tokens (prefix + chunk + SEP, capped at max_len) and estimated CPU seconds."""
    pl = prefix_len(question) if question else prefix_len()
    if chunks is not None:
        lens = [min(max_len, pl + tok_len(c) + 1) for c in chunks]
        calls = len(chunks) if calls is None else calls
        tokens = sum(lens) if tokens is None else tokens
        cpu = sum(cpu_seconds(n) for n in lens)
    else:
        calls, tokens = int(calls or 0), int(tokens or 0)
        cpu = calls * cpu_seconds(tokens / calls) if calls else 0.0
    r = {"score": float(doc_score), "calls": int(calls or 0), "tokens": int(tokens or 0), "cpu_s": cpu}
    if extra:
        r.update(extra)
    return r


# ---------------------------------------------------------------- metrics
def auroc(pos, neg):
    if not pos or not neg:
        return float("nan")
    allv = sorted([(v, 1) for v in pos] + [(v, 0) for v in neg])
    ranks, i = {}, 0
    rank_sum = 0.0
    while i < len(allv):
        j = i
        while j < len(allv) and allv[j][0] == allv[i][0]:
            j += 1
        r = (i + j + 1) / 2.0  # average rank, 1-based
        rank_sum += r * sum(1 for k in range(i, j) if allv[k][1] == 1)
        i = j
    n1, n0 = len(pos), len(neg)
    return (rank_sum - n1 * (n1 + 1) / 2.0) / (n1 * n0)


def threshold_at_fpr(neg, fpr):
    """Smallest threshold t such that the share of benign scores >= t is <= fpr."""
    s = sorted(neg, reverse=True)
    k = int(math.floor(fpr * len(s)))  # number of benign docs allowed above threshold
    if k >= len(s):
        return 0.0
    return math.nextafter(s[k], 1.0)  # strictly above the (k+1)-th largest benign score


def rate(vals, t):
    return sum(1 for v in vals if v >= t) / len(vals) if vals else float("nan")


def _block(docs, outs, thresholds=None):
    pos = [o["score"] for d, o in zip(docs, outs) if d["label"] == 1]
    neg = [o["score"] for d, o in zip(docs, outs) if d["label"] == 0]
    t5 = (thresholds or {}).get("fpr5", threshold_at_fpr(neg, 0.05))
    t1 = (thresholds or {}).get("fpr1", threshold_at_fpr(neg, 0.01))
    m = {"n_pos": len(pos), "n_neg": len(neg), "auroc": auroc(pos, neg),
         "thr_fpr5": t5, "tpr@fpr5": rate(pos, t5), "fpr_at_thr5": rate(neg, t5),
         "thr_fpr1": t1, "tpr@fpr1": rate(pos, t1), "fpr_at_thr1": rate(neg, t1),
         "at_0.5": {"tpr": rate(pos, 0.5), "fpr": rate(neg, 0.5)},
         "at_0.8": {"tpr": rate(pos, 0.8), "fpr": rate(neg, 0.8)}}
    by_cond = {}
    for cond in ("natural", "tail", "split", "clean", "hardneg"):
        v = [o["score"] for d, o in zip(docs, outs) if d["cond"] == cond]
        if v:
            by_cond[cond] = {"n": len(v), "flag_rate@fpr5": rate(v, t5), "flag_rate@0.5": rate(v, 0.5)}
    m["by_cond"] = by_cond
    by_len = {}
    for T in (1024, 2048, 4096):
        p = [o["score"] for d, o in zip(docs, outs) if d["label"] == 1 and d["target_tokens"] == T]
        n = [o["score"] for d, o in zip(docs, outs) if d["label"] == 0 and d["target_tokens"] == T]
        if p:
            by_len[str(T)] = {"tpr@fpr5": rate(p, t5), "fpr@fpr5": rate(n, t5), "auroc": auroc(p, n)}
    m["by_len"] = by_len
    m["cost"] = {"calls_per_doc": sum(o["calls"] for o in outs) / len(outs),
                 "tokens_per_doc": sum(o["tokens"] for o in outs) / len(outs),
                 "est_cpu_s_per_doc": sum(o.get("cpu_s", o["tokens"] / 512 * CPU_S_PER_512) for o in outs) / len(outs)}
    return m


def evaluate(docs, outs, thresholds=None):
    """thresholds: optional {"all": {"fpr5": t, "fpr1": t}, "en": {...}, "ko": {...}} fixed from another split."""
    assert len(docs) == len(outs)
    thresholds = thresholds or {}
    m = {"all": _block(docs, outs, thresholds.get("all"))}
    for lang in ("en", "ko"):
        idx = [i for i, d in enumerate(docs) if d["lang"] == lang]
        if idx:
            m[lang] = _block([docs[i] for i in idx], [outs[i] for i in idx], thresholds.get(lang))
    if "en" in m and "ko" in m:
        # PRIMARY ranking metric: per-language thresholds (language is cheap to detect), averaged over EN and KO.
        m["macro"] = {"tpr@fpr5": (m["en"]["tpr@fpr5"] + m["ko"]["tpr@fpr5"]) / 2,
                      "tpr@fpr1": (m["en"]["tpr@fpr1"] + m["ko"]["tpr@fpr1"]) / 2,
                      "auroc": (m["en"]["auroc"] + m["ko"]["auroc"]) / 2}
    return m


def thresholds_of(m):
    """Extract the FPR-calibrated thresholds from a dev evaluation so they can be frozen for test."""
    return {k: {"fpr5": v["thr_fpr5"], "fpr1": v["thr_fpr1"]} for k, v in m.items() if k in ("all", "en", "ko")}


def print_summary(name, m):
    def f(x):
        return "nan" if x != x else f"{x:.3f}"
    if "macro" in m:
        print(f"{name:<34} MACRO (per-language thresholds) TPR@FPR5 {f(m['macro']['tpr@fpr5'])}  "
              f"TPR@FPR1 {f(m['macro']['tpr@fpr1'])}  AUROC {f(m['macro']['auroc'])}")
    for k in ("all", "en", "ko"):
        if k not in m:
            continue
        b = m[k]
        bc = b["by_cond"]
        print(f"{name:<34} {k:<3} AUROC {f(b['auroc'])}  TPR@FPR5 {f(b['tpr@fpr5'])}  TPR@FPR1 {f(b['tpr@fpr1'])}  "
              f"nat {f(bc.get('natural', {}).get('flag_rate@fpr5', float('nan')))} "
              f"tail {f(bc.get('tail', {}).get('flag_rate@fpr5', float('nan')))} "
              f"split {f(bc.get('split', {}).get('flag_rate@fpr5', float('nan')))} | "
              f"FP clean {f(bc.get('clean', {}).get('flag_rate@fpr5', float('nan')))} "
              f"hardneg {f(bc.get('hardneg', {}).get('flag_rate@fpr5', float('nan')))} | "
              f"@0.8 tpr {f(b['at_0.8']['tpr'])} fpr {f(b['at_0.8']['fpr'])} | "
              f"calls/doc {b['cost']['calls_per_doc']:.1f} cpu_s/doc {b['cost']['est_cpu_s_per_doc']:.1f}")


def save_result(name, config, metrics, split="dev", owner=None, notes=None, per_doc=None):
    """Write results/<split>/<name>.json and append a line to results/leaderboard_<split>.jsonl."""
    os.makedirs(os.path.join(RESULTS, split), exist_ok=True)
    fname = re.sub(r'[<>:"/\\|?*\s]+', "__", name)  # Windows-safe file name
    rec = {"name": name, "owner": owner, "split": split, "config": config, "metrics": metrics, "notes": notes}
    with open(os.path.join(RESULTS, split, f"{fname}.json"), "w", encoding="utf-8") as f:
        json.dump(rec, f, ensure_ascii=False, indent=1)
    if per_doc is not None:
        with open(os.path.join(RESULTS, split, f"{fname}.scores.json"), "w", encoding="utf-8") as f:
            json.dump(per_doc, f)
    a = metrics["all"]
    mac = metrics.get("macro", {})
    line = {"name": name, "owner": owner, "split": split, "macro_tpr@fpr5": mac.get("tpr@fpr5"),
            "macro_auroc": mac.get("auroc"), "auroc": a["auroc"], "tpr@fpr5": a["tpr@fpr5"],
            "tpr@fpr1": a["tpr@fpr1"], "en_tpr@fpr5": metrics.get("en", {}).get("tpr@fpr5"),
            "ko_tpr@fpr5": metrics.get("ko", {}).get("tpr@fpr5"), "calls_per_doc": a["cost"]["calls_per_doc"],
            "cpu_s_per_doc": a["cost"]["est_cpu_s_per_doc"], "config": config}
    with open(os.path.join(RESULTS, f"leaderboard_{split}.jsonl"), "a", encoding="utf-8") as f:
        f.write(json.dumps(line, ensure_ascii=False) + "\n")
