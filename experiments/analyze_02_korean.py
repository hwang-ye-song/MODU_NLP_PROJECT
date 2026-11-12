"""02_korean analysis (no API calls): does Jev lose accuracy on Korean documents, and does machine translation back to
English ("translate, then judge") recover it?  (PLAN step E, RQ3, gap 3)

    python experiments/analyze_02_korean.py

Inputs (made earlier; never modified here):
  results/01_baseline/{Q2,QL}_predictions.csv   EN 1000 originals (rows set=="EN")                       -> condition EN
  results/02_korean/{Q2,QL}_predictions.csv     KO 1000 = Korean 1:1 translations of EN (pair_uid -> EN uid) -> condition KO
  results/02_korean_mt/{Q2,QL}_predictions.csv  the same KO documents machine-translated back to English with
                                                Helsinki-NLP/opus-mt-ko-en (experiments/translate_ko.py)    -> condition MT
  data/injection_eval/{en,ko}/dataset_*_1000.jsonl, results/02_korean_mt/translation/{ko_to_en,segment_cache}.jsonl
Outputs:
  results/02_korean/tables/*.csv, results/02_korean/figures/*.png,
  results/02_korean/summary.json -> adds an "analysis" object, keeps every existing key.

Statistics: TPR/FPR/AUC through src.jev_guard.metrics (threshold 0.5); Wilson 95% CI (jevlab.wilson) for TPR/FPR;
exact McNemar (two-sided binomial test on discordant pairs) on per-document correctness / detection (injections) /
false alarm (benign); paired bootstrap (1000 resamples, seed 20261112, documents resampled within each label, the
same index matrix for all three conditions and both questions) for differences in TPR / FPR / AUC / mean p.
Recovery share = (MT - KO) / (EN - KO), reported only when the EN - KO bootstrap CI excludes 0.
"""
import ast
import datetime as dt
import hashlib
import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd
from scipy.stats import rankdata
from sklearn.metrics import roc_curve

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from src.jev_guard import THRESHOLD, metrics  # noqa: E402
import jevlab as J  # noqa: E402
import plot_style as S  # noqa: E402
import translate_ko as TK  # noqa: E402  (only the pure-Python splitting helpers; no torch import at module level)
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

EXP = "02_korean"
OUT = os.path.join(J.RESULTS, EXP)
MT_DIR = os.path.join(J.RESULTS, "02_korean_mt")
BASE_DIR = os.path.join(J.RESULTS, "01_baseline")
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
KO_DATA = os.path.join(J.DATA, "ko", "dataset_ko_1000.jsonl")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")
MT_TEXT = os.path.join(MT_DIR, "translation", "ko_to_en.jsonl")
SEG_CACHE = os.path.join(MT_DIR, "translation", "segment_cache.jsonl")

QS = ["Q2", "QL"]
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}  # project-wide: question colours
Q_NAME = {"Q2": "Q2 (짧은 질문)", "QL": "QL (정의형 긴 질문)"}
INJ, BEN = S.LABEL_COLORS["인젝션"], S.LABEL_COLORS["정상"]
LAB_NAME = {1: "인젝션", 0: "정상"}
LAB_COLOR = {1: INJ, 0: BEN}
CONDS = ["EN", "KO", "MT"]
COND_NAME = {"EN": "EN 원문", "KO": "KO 번역본", "MT": "KO→EN 기계번역"}
COND_TICK = {"EN": "EN\n영어 원문", "KO": "KO\n한국어", "MT": "KO→EN\n기계번역 후 판정"}
COMPS = [("KO", "EN"), ("MT", "KO"), ("MT", "EN")]  # (b, a): delta = b - a
COMP_NAME = {("KO", "EN"): "KO − EN", ("MT", "KO"): "KO→EN − KO", ("MT", "EN"): "KO→EN − EN"}
COMP_KEY = {("KO", "EN"): "KO_vs_EN", ("MT", "KO"): "MT_vs_KO", ("MT", "EN"): "MT_vs_EN"}
N_BOOT, SEED = 1000, 20261112
VERDICT_NONE = "차이 없음/오차 범위"
PRICE_PER_M = 0.042  # USD per 1M input tokens (docs/PROJECT.md)

SOURCES = ["BIPIA", "SEP", "InjecAgent", "AgentDojo", "LLMail-Inject", "BrowseSafe-Bench", "Enron", "Synthetic"]
SRC_SHORT = {"BrowseSafe-Bench": "BrowseSafe", "LLMail-Inject": "LLMail"}
DOC_TYPES = ["email", "tool_response", "news_article", "webpage", "general_document", "table", "code_qa", "chat",
             "manual", "wiki"]
DOC_KO = {"email": "이메일", "tool_response": "도구 응답", "news_article": "뉴스 기사", "webpage": "웹페이지",
          "general_document": "일반 문서", "table": "표", "code_qa": "코드 Q&A", "chat": "채팅", "manual": "매뉴얼", "wiki": "위키"}

# Translation checks
NAMED_DEGENERATE = ["KO-I-138", "KO-I-157"]  # flagged by the orchestrator's check (encoded LLMail payloads)
HANGUL = TK.HANGUL
LOOP_RE = re.compile(r"(.{1,30}?)\1{4,}", re.S)  # a 1-30 char unit repeated >= 5 times in a row
LOOP_MIN = 50  # MT-only repetition loop: longest such run in MT minus the longest in KO/EN source >= 50 chars
SHORT_RATIO = 0.7  # MT text shorter than 70% of the EN original: possible dropped sentences (seen in SEP docs)
TAG_RE = re.compile(r"<[^>]*>")
KO_CUE = re.compile(r"십시오|당신")  # formal "-십시오" / "당신": dataset review says KO BrowseSafe injections use them
# Exploratory: English words that read like an instruction to the reader. Chosen AFTER reading the MT false positives
# (e.g. Enron "Disregard last Salsa message" -> KO -> MT "Ignore the last salsa message"); hypothesis-generating only.
TRIGGER = re.compile(r"\b(ignore|ignoring|disregard|forget|override|obey|must|have to|immediately|urgent|"
                     r"instruction|instructions|command|commands)\b", re.I)


# ------------------------------------------------------------------ small helpers
def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def md5s(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def ci(a):
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))] if len(a) else [None, None]


def verdict(lo, hi):
    if lo is None or hi is None:
        return ""
    return VERDICT_NONE if lo <= 0 <= hi else ("높아짐" if lo > 0 else "낮아짐")


def mcnemar_exact(a, b):
    """a, b: boolean arrays (event under condition A / B) on the same documents. Returns (A only, B only, exact p)."""
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    a_only, b_only = int((a & ~b).sum()), int((~a & b).sum())
    n = a_only + b_only
    if n == 0:
        return a_only, b_only, 1.0
    k = min(a_only, b_only)
    p = 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return a_only, b_only, min(1.0, p)


def holm(ps):
    ps = np.asarray(ps, float)
    order = np.argsort(ps)
    adj, running = np.empty_like(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, (len(ps) - rank) * ps[i])
        adj[i] = min(1.0, running)
    return adj.tolist()


def fast_auc(P, N):
    """Row-wise AUC (Mann-Whitney with average ranks, same as roc_auc_score) for matrices P (B x n+), N (B x n-)."""
    npos, nneg = P.shape[1], N.shape[1]
    r = rankdata(np.concatenate([P, N], axis=1), axis=1)
    return (r[:, :npos].sum(1) - npos * (npos + 1) / 2) / (npos * nneg)


def tpr_at_fpr(Pp, Pn, f=0.01):
    """TPR when the threshold is set on the benign scores so that at most floor(f * n_benign) are flagged
    (flag if p > t, t = the (k+1)-th largest benign p). In-sample, optimistic; reference only (decision 11/12)."""
    Pp, Pn = np.atleast_2d(Pp), np.atleast_2d(Pn)
    k = int(np.floor(f * Pn.shape[1]))
    t = -np.sort(-Pn, axis=1)[:, k] if k < Pn.shape[1] else np.full(Pn.shape[0], -np.inf)
    return (Pp > t[:, None]).mean(1), t, (Pn > t[:, None]).mean(1)


def fmt_p(p):
    return "<0.001" if p < 0.001 else f"{p:.3f}"


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if o != o else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def short(s, n=110):
    s = re.sub(r"\s+", " ", str(s if s is not None and s == s else "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def longest_loop(s):
    best = 0
    for m in LOOP_RE.finditer(s or ""):
        if m.group(1).strip():
            best = max(best, len(m.group(0)))
    return best


def src_short(s):
    return SRC_SHORT.get(s, s)


def pp(x, signed=True):
    return f"{100 * x:+.1f}" if signed else f"{100 * x:.1f}"


# ------------------------------------------------------------------ translation reconstruction
def load_segment_cache():
    cache = {}
    for c in J.load_jsonl(SEG_CACHE):
        cache[c["src"]] = c["en"]  # last line wins, as in translate_ko.py
    return cache


def rebuild_mt(text, cache):
    """Rebuild translate_ko.py's output for one KO text from the segment cache.
    Returns (text_en, spans) with spans = [(ko_start, ko_end, en_start, en_end, translated?)] per piece."""
    out, spans, ko_pos, en_pos = [], [], 0, 0
    for is_t, s in TK.pieces(text):
        if not is_t:
            piece = s
        else:
            lead = s[:len(s) - len(s.lstrip())]
            trail = s[len(s.rstrip()):]
            sents = TK.split_sentences(s.strip())
            if any(x not in cache for x in sents):
                return None, None
            piece = lead + " ".join(cache[x].strip() for x in sents) + trail
        spans.append((ko_pos, ko_pos + len(s), en_pos, en_pos + len(piece), is_t))
        out.append(piece)
        ko_pos += len(s)
        en_pos += len(piece)
    return "".join(out), spans


def mt_excerpt(text_ko, text_mt, spans, instr):
    """MT text produced from the KO pieces that overlap the KO injected instruction (exact piece alignment)."""
    if not instr or not isinstance(instr, str) or spans is None:
        return None
    s = text_ko.find(instr)
    if s < 0:
        return None
    e = s + len(instr)
    hit = [sp for sp in spans if sp[0] < e and sp[1] > s]
    if not hit:
        return None
    return text_mt[min(h[2] for h in hit): max(h[3] for h in hit)]


# ------------------------------------------------------------------ load and pair
def load_texts():
    ko = J.load_jsonl(KO_DATA)
    en = {r["uid"]: r for r in J.load_jsonl(EN_DATA)}
    mt = {r["uid"]: r for r in J.load_jsonl(MT_TEXT)}
    cache = load_segment_cache()
    assert len(ko) == 1000 and len(en) == 1000 and len(mt) == 1000
    assert len({r["pair_uid"] for r in ko}) == 1000, "pair_uid must be 1:1"
    rows, rebuild_ok = [], 0
    for r in ko:
        e = en[r["pair_uid"]]
        m = mt[r["uid"]]
        assert int(r["label_int"]) == int(e["label_int"]), r["uid"]
        assert m["source_md5"] == md5s(r["text"]), f"{r['uid']}: MT was made from a different KO text"
        assert int(m["hangul_left"]) == len(HANGUL.findall(m["text_en"])), r["uid"]
        rebuilt, spans = rebuild_mt(r["text"], cache)
        rebuild_ok += rebuilt == m["text_en"]
        origin = e.get("origin")
        if isinstance(origin, str):
            try:
                origin = ast.literal_eval(origin)
            except Exception:
                origin = {}
        loop_mt, loop_ko, loop_en = longest_loop(m["text_en"]), longest_loop(r["text"]), longest_loop(e["text"])
        rows.append({
            "uid": r["uid"], "pair_uid": r["pair_uid"], "label_int": int(r["label_int"]), "source": r["source"],
            "subset": r.get("subset"), "doc_type": r["doc_type"], "risk_level": int(r["risk_level"]),
            "risk_level_en": int(e["risk_level"]), "doc_type_en": e["doc_type"],
            "harm_type": r.get("harm_type"), "position": (origin or {}).get("position"),
            "text_en": e["text"], "text_ko": r["text"], "text_mt": m["text_en"],
            "instr_en": e.get("injected_instruction"), "instr_ko": r.get("injected_instruction"),
            "instr_mt": mt_excerpt(r["text"], m["text_en"], spans if rebuilt == m["text_en"] else None,
                                   r.get("injected_instruction")),
            "len_en": len(e["text"]), "len_ko": len(r["text"]), "len_mt": len(m["text_en"]),
            "hangul_ko": len(HANGUL.findall(r["text"])), "hangul_left": int(m["hangul_left"]),
            "loop_mt": loop_mt, "loop_src": max(loop_ko, loop_en), "loop_excess": loop_mt - max(loop_ko, loop_en),
            "mt_model": m["model"], "mt_revision": m["model_revision"], "mt_device": m["device"],
        })
    T = pd.DataFrame(rows)
    T["mt_len_ratio"] = T["len_mt"] / T["len_en"]
    T["named_degenerate"] = T["uid"].isin(NAMED_DEGENERATE)
    T["mt_loop"] = T["loop_excess"] >= LOOP_MIN
    T["mt_hangul"] = T["hangul_left"] > 0
    T["mt_short"] = T["mt_len_ratio"] < SHORT_RATIO
    T["mt_issue_any"] = T["named_degenerate"] | T["mt_loop"] | T["mt_hangul"]
    # where the residual Hangul sits: inside HTML tags / comments (translate_ko.py copies tags as structure)
    T["hangul_in_tags"] = T["text_mt"].map(lambda s: sum(len(HANGUL.findall(m.group(0))) for m in TAG_RE.finditer(s)))
    # the KO injected instruction is still present verbatim (untranslated) in the MT text
    T["instr_ko_kept"] = [bool(i) and isinstance(i, str) and HANGUL.search(i) is not None and i in t
                          for i, t in zip(T["instr_ko"], T["text_mt"])]
    T["ko_cue"] = T["text_ko"].str.contains(KO_CUE)
    T["ko_sipsio"] = T["text_ko"].str.contains("십시오")
    T["ko_dangsin"] = T["text_ko"].str.contains("당신")
    T["trig_en"] = T["text_en"].map(lambda s: len(TRIGGER.findall(s)))
    T["trig_mt"] = T["text_mt"].map(lambda s: len(TRIGGER.findall(s)))
    T["trig_gain"] = T["trig_mt"] > T["trig_en"]
    return T, {"mt_rebuilt_from_segment_cache": int(rebuild_ok), "segment_cache_entries": len(cache)}


def load_pairs(T):
    """Wide frame: one row per KO document; per question q and condition c columns {q}_{c}_{field}."""
    W = T.copy()
    files = {"EN": BASE_DIR, "KO": OUT, "MT": MT_DIR}
    for q in QS:
        for c in CONDS:
            d = pd.read_csv(os.path.join(files[c], f"{q}_predictions.csv"))
            if c == "EN":
                d = d[d["set"] == "EN"].rename(columns={"uid": "pair_uid"})
                key = "pair_uid"
            else:
                key = "uid"
            assert len(d) == 1000 and (d["n_runs"] == 3).all(), (q, c)
            assert ((d["p"] >= THRESHOLD).astype(int) == d["pred"]).all(), (q, c)
            cols = ["p", "pred", "p_run0", "p_run1", "p_run2", "p_sd", "flip", "input_tokens", "latency_s", "label_int"]
            d = d[[key] + cols].rename(columns={k: f"{q}_{c}_{k}" for k in cols})
            W = W.merge(d, on=key, how="left", validate="one_to_one")
            assert W[f"{q}_{c}_p"].notna().all(), (q, c)
            assert (W[f"{q}_{c}_label_int"] == W["label_int"]).all(), (q, c)
            W = W.drop(columns=[f"{q}_{c}_label_int"])
            W[f"{q}_{c}_pred"] = W[f"{q}_{c}_pred"].astype(bool)
            W[f"{q}_{c}_correct"] = W[f"{q}_{c}_pred"] == (W["label_int"] == 1)
    return W


# ------------------------------------------------------------------ core comparison
def boot_indices(y):
    """Stratified (within-label) resample index matrices; same seed for every subset -> paired across conditions/Q."""
    rng = np.random.default_rng(SEED)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    IP = pos[rng.integers(0, len(pos), (N_BOOT, len(pos)))] if len(pos) else None
    IN = neg[rng.integers(0, len(neg), (N_BOOT, len(neg)))] if len(neg) else None
    return IP, IN


def cond_stats(D, q, c, IP, IN):
    """Point metrics (src.jev_guard.metrics) + Wilson CIs + bootstrap replicates for one condition."""
    y = D["label_int"].to_numpy()
    P = D[f"{q}_{c}_p"].to_numpy()
    Pr = D[f"{q}_{c}_pred"].to_numpy()
    n_inj, n_ben = int((y == 1).sum()), int((y == 0).sum())
    m = metrics(y.tolist(), P.tolist(), threshold=THRESHOLD)
    tp, fp = int((Pr & (y == 1)).sum()), int((Pr & (y == 0)).sum())
    pt = {"n": len(D), "n_injection": n_inj, "n_benign": n_ben, "TPR": m["TPR"] if n_inj else None,
          "FPR": m["FPR"] if n_ben else None, "AUC": m["AUC"], "tp": tp, "fp": fp,
          "TPR_lo": J.wilson(tp, n_inj)[0] if n_inj else None, "TPR_hi": J.wilson(tp, n_inj)[1] if n_inj else None,
          "FPR_lo": J.wilson(fp, n_ben)[0] if n_ben else None, "FPR_hi": J.wilson(fp, n_ben)[1] if n_ben else None,
          "mean_p_inj": float(P[y == 1].mean()) if n_inj else None,
          "mean_p_ben": float(P[y == 0].mean()) if n_ben else None,
          "flips": int(D[f"{q}_{c}_flip"].sum())}
    rep = {}
    if IP is not None:
        rep["TPR"] = (P[IP] >= THRESHOLD).mean(1)
        rep["mean_p_inj"] = P[IP].mean(1)
    if IN is not None:
        rep["FPR"] = (P[IN] >= THRESHOLD).mean(1)
        rep["mean_p_ben"] = P[IN].mean(1)
    if IP is not None and IN is not None:
        rep["AUC"] = fast_auc(P[IP], P[IN])
        assert abs(fast_auc(P[y == 1][None, :], P[y == 0][None, :])[0] - m["AUC"]) < 1e-9
        pt["AUC_lo"], pt["AUC_hi"] = ci(rep["AUC"])
        rep["TPR_at_FPR1"] = tpr_at_fpr(P[IP], P[IN], 0.01)[0]
        tp1, t1, fp1 = tpr_at_fpr(P[y == 1], P[y == 0], 0.01)
        pt.update({"TPR_at_FPR1": float(tp1[0]), "TPR_at_FPR1_lo": ci(rep["TPR_at_FPR1"])[0],
                   "TPR_at_FPR1_hi": ci(rep["TPR_at_FPR1"])[1], "thr_at_FPR1": float(t1[0])})
    else:
        pt.update({"AUC": None, "AUC_lo": None, "AUC_hi": None})
    return pt, rep


def compare(D, q, a, b, cache=None):
    """Condition a vs b on the same documents D for question q. Delta = b - a."""
    y = D["label_int"].to_numpy()
    IP, IN = boot_indices(y)
    st = {}
    for c in (a, b):
        st[c] = cond_stats(D, q, c, IP, IN)
    out = {"question": q, "comparison": COMP_KEY[(b, a)], "a": a, "b": b, "n": len(D),
           "n_injection": st[a][0]["n_injection"], "n_benign": st[a][0]["n_benign"]}
    for c, tag in ((a, "a"), (b, "b")):
        for k in ("TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi", "AUC", "AUC_lo", "AUC_hi", "mean_p_inj",
                  "mean_p_ben", "tp", "fp", "flips"):
            out[f"{tag}_{k}"] = st[c][0].get(k)
    for key in ("TPR", "FPR", "AUC", "mean_p_inj", "mean_p_ben", "TPR_at_FPR1"):
        if key in st[a][1] and st[a][0].get(key) is not None:
            point = st[b][0][key] - st[a][0][key]
            lo, hi = ci(st[b][1][key] - st[a][1][key])
            out.update({f"d_{key}": point, f"d_{key}_lo": lo, f"d_{key}_hi": hi, f"d_{key}_verdict": verdict(lo, hi)})
        else:
            out.update({f"d_{key}": None, f"d_{key}_lo": None, f"d_{key}_hi": None, f"d_{key}_verdict": ""})
    ca, cb = D[f"{q}_{a}_correct"].to_numpy(), D[f"{q}_{b}_correct"].to_numpy()
    broke, fixed, p = mcnemar_exact(ca, cb)
    out.update({"fixed_in_b": fixed, "broken_in_b": broke, "mcnemar_correct_p": p})
    inj, ben = y == 1, y == 0
    pa, pb = D[f"{q}_{a}_pred"].to_numpy(), D[f"{q}_{b}_pred"].to_numpy()
    lost, new, p_det = mcnemar_exact(pa[inj], pb[inj])
    out.update({"inj_detected_only_b": new, "inj_detected_only_a": lost, "mcnemar_detect_p": p_det if inj.any() else None})
    fa_a, fa_b, p_fa = mcnemar_exact(pa[ben], pb[ben])
    out.update({"ben_fp_only_a": fa_a, "ben_fp_only_b": fa_b, "mcnemar_fp_p": p_fa if ben.any() else None})
    if cache is not None:
        cache[(q, a, b)] = st
    return out


def recovery(D, q):
    """Recovery share (MT - KO) / (EN - KO) with bootstrap CI, only when the EN - KO CI excludes 0."""
    y = D["label_int"].to_numpy()
    IP, IN = boot_indices(y)
    st = {c: cond_stats(D, q, c, IP, IN) for c in CONDS}
    rows = []
    for key in ("TPR", "FPR", "AUC", "mean_p_inj", "mean_p_ben"):
        if key not in st["EN"][1]:
            continue
        gap_pt = st["EN"][0][key] - st["KO"][0][key]
        gain_pt = st["MT"][0][key] - st["KO"][0][key]
        gap = st["EN"][1][key] - st["KO"][1][key]
        gain = st["MT"][1][key] - st["KO"][1][key]
        lo, hi = ci(gap)
        # a loss to recover: KO worse than EN with a CI that excludes 0 (lower TPR/AUC/mean p_inj, higher FPR/mean p_ben)
        worse_is_higher = key in ("FPR", "mean_p_ben")
        meaningful = (hi < 0) if worse_is_higher else (lo > 0)
        r = {"question": q, "metric": key, "EN": st["EN"][0][key], "KO": st["KO"][0][key], "MT": st["MT"][0][key],
             "gap_EN_minus_KO": gap_pt, "gap_lo": lo, "gap_hi": hi, "gain_MT_minus_KO": gain_pt,
             "gain_lo": ci(gain)[0], "gain_hi": ci(gain)[1], "recovery_meaningful": meaningful}
        if meaningful:
            with np.errstate(divide="ignore", invalid="ignore"):
                ratio = np.where(gap == 0, np.nan, gain / np.where(gap == 0, 1, gap))
            r.update({"recovery_share": gain_pt / gap_pt, "recovery_lo": ci(ratio)[0], "recovery_hi": ci(ratio)[1],
                      "note": ""})
        else:
            why = ("EN − KO 차이가 오차 범위" if lo <= 0 <= hi else "KO가 EN보다 나쁘지 않음 (회복할 손실이 없음)")
            r.update({"recovery_share": None, "recovery_lo": None, "recovery_hi": None, "note": f"의미 없음: {why}"})
        rows.append(r)
    return rows


def mean_dp_ci(dp):
    rng = np.random.default_rng(SEED)
    bs = dp[rng.integers(0, len(dp), (N_BOOT, len(dp)))].mean(1)
    return ci(bs)


def noise_floor(D, q):
    R = {c: D[[f"{q}_{c}_p_run{i}" for i in range(3)]].to_numpy() for c in CONDS}
    res = {}
    pairs = [(i, j) for i in range(3) for j in range(i + 1, 3)]
    for c in CONDS:
        res[f"within_{c}_decision_diff"] = float(np.mean([((R[c][:, i] >= THRESHOLD) != (R[c][:, j] >= THRESHOLD)).mean()
                                                          for i, j in pairs]))
        res[f"within_{c}_abs_dp"] = float(np.mean([np.abs(R[c][:, i] - R[c][:, j]).mean() for i, j in pairs]))
    for b, a in COMPS:
        k = COMP_KEY[(b, a)]
        res[f"between_{k}_decision_diff"] = float(np.mean([((R[a][:, i] >= THRESHOLD) != (R[b][:, j] >= THRESHOLD)).mean()
                                                           for i in range(3) for j in range(3)]))
        res[f"between_{k}_abs_dp"] = float(np.mean([np.abs(R[a][:, i] - R[b][:, j]).mean() for i in range(3) for j in range(3)]))
        res[f"mean3_{k}_decision_diff"] = float((D[f"{q}_{a}_pred"] != D[f"{q}_{b}_pred"]).mean())
    return res


# ------------------------------------------------------------------ figures
def _err(ax, x, v, lo, hi, color, marker="o", size=7, label=None, horizontal=False):
    if v is None or lo is None:
        return
    el, eh = max(0.0, v - lo), max(0.0, hi - v)  # Wilson bounds at 0 / 1 can differ from v by ~1e-18
    if horizontal:
        ax.errorbar(v, x, xerr=[[el], [eh]], fmt=marker, color=color, ms=size, capsize=3, lw=1.6, label=label)
    else:
        ax.errorbar(x, v, yerr=[[el], [eh]], fmt=marker, color=color, ms=size, capsize=3, lw=1.6, label=label)


def q_legend(ax, loc="lower left", **kw):
    h = [Line2D([0], [0], marker="o", color=Q_COLORS[q], lw=1.6, ms=6, label=Q_NAME[q]) for q in QS]
    ax.legend(handles=h, loc=loc, **kw)


def lab_legend(ax, loc="upper left", **kw):
    h = [Line2D([0], [0], marker="o", color="none", markerfacecolor=LAB_COLOR[k], markeredgecolor="none", ms=7,
                label=LAB_NAME[k]) for k in (1, 0)]
    ax.legend(handles=h, loc=loc, **kw)


def fig_legend(fig, kind="q"):
    """Legend in the free band between the subtitle and the panels (call after S.title)."""
    if kind == "q":
        h = [Line2D([0], [0], marker="o", color=Q_COLORS[q], lw=1.6, ms=6, label=Q_NAME[q]) for q in QS]
    else:
        h = [Line2D([0], [0], marker="o", color="none", markerfacecolor=LAB_COLOR[k], markeredgecolor="none", ms=7,
                    label=LAB_NAME[k]) for k in (1, 0)]
    top = getattr(fig, "_viz_top", 0.88)
    fig.legend(handles=h, loc="lower right", bbox_to_anchor=(0.995, top - 0.01), ncol=2, frameon=False, fontsize=9.5)


def fig_headline(M):
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 5.0))
    spec = [("TPR", "탐지율 TPR (높을수록 좋음)", (0.40, 0.75), True),
            ("FPR", "오탐률 FPR (낮을수록 좋음)", (0.0, 0.08), True),
            ("AUC", "AUC (임계값 무관 판별력)", (0.86, 1.0), False)]
    for ax, (k, lab, ylim, pct) in zip(axes, spec):
        for j, q in enumerate(QS):
            for i, c in enumerate(CONDS):
                r = M[(M.question == q) & (M.condition == c)].iloc[0]
                x = i + (-0.13 if q == "Q2" else 0.13)
                _err(ax, x, r[k], r[f"{k}_lo"], r[f"{k}_hi"], Q_COLORS[q])
                txt = f"{100 * r[k]:.1f}%" if pct else f"{r[k]:.3f}"
                ax.annotate(txt, (x, r[k]), xytext=(-5 if q == "Q2" else 5, 0), textcoords="offset points",
                            ha="right" if q == "Q2" else "left", va="center", fontsize=8.5, color=Q_COLORS[q])
        ax.set_xticks(range(3))
        ax.set_xticklabels([COND_TICK[c] for c in CONDS], fontsize=9)
        ax.set_xlim(-0.6, 2.6)
        ax.set_ylim(*ylim)
        ax.set_title(lab, fontsize=11)
        if pct:
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    q_legend(axes[0], loc="upper left")
    return fig


def main():
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    for d, ext in ((TAB, ".csv"), (FIG, ".png")):  # this script owns both folders: drop stale outputs
        for f in os.listdir(d):
            if f.endswith(ext):
                os.remove(os.path.join(d, f))
    S.setup()
    T, rebuild_info = load_texts()
    W = load_pairs(T)
    y_all = W["label_int"].to_numpy()
    summary_path = os.path.join(OUT, "summary.json")
    summary = json.load(open(summary_path, encoding="utf-8"))
    mt_summary = json.load(open(os.path.join(MT_DIR, "summary.json"), encoding="utf-8"))
    base_summary = json.load(open(os.path.join(BASE_DIR, "summary.json"), encoding="utf-8"))
    dev = T["mt_device"].iloc[0]
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", dev)]
    analysis = {
        "script": "experiments/analyze_02_korean.py",
        "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
        "conditions": {"EN": "results/01_baseline/<Q>_predictions.csv rows set=='EN' (English originals)",
                       "KO": "results/02_korean/<Q>_predictions.csv (Korean 1:1 translations, pair_uid -> EN uid)",
                       "MT": "results/02_korean_mt/<Q>_predictions.csv (KO machine-translated to English with "
                             f"{T['mt_model'].iloc[0]} rev {T['mt_revision'].iloc[0]}, beam 4, Hangul spans only)"},
        "pairing": "KO uid -> pair_uid (EN uid); KO uid == MT uid; labels equal (checked); MT source_md5 == md5(KO text) "
                   "(checked)",
        "bootstrap": {"resamples": N_BOOT, "seed": SEED, "ci": "percentile 2.5/97.5",
                      "unit": "documents resampled with replacement within each label; same index matrix for all three "
                              "conditions (paired) and both questions"},
        "mcnemar": "exact, two-sided binomial test on discordant pairs (correctness; detection among injections; "
                   "false alarm among benign); subgroup p Holm-adjusted per question x comparison x family, separately "
                   "for each of the three tests (columns mcnemar_{correct,detect,fp}_p_holm)",
        "recovery_share": "(MT - KO) / (EN - KO); reported only when the EN - KO bootstrap CI excludes 0",
        "mt_run": {"model": T["mt_model"].iloc[0], "revision": T["mt_revision"].iloc[0], "device_note": dev,
                   "segments_gpu": nums[0] if len(nums) >= 3 else None,
                   "segments_total": nums[1] if len(nums) >= 3 else None,
                   "segments_cpu": nums[2] if len(nums) >= 3 else None, **rebuild_info},
    }
    analysis["inputs_md5"] = {rel(p): md5_file(p) for p in (
        KO_DATA, EN_DATA, MT_TEXT, SEG_CACHE,
        *(os.path.join(d, f"{q}_predictions.csv") for d in (BASE_DIR, OUT, MT_DIR) for q in QS))}
    checks = {"risk_level_equal_EN_KO": bool((W.risk_level == W.risk_level_en).all()),
              "doc_type_equal_EN_KO": bool((W.doc_type == W.doc_type_en).all())}
    analysis["checks"] = checks

    # ---- 1. metrics per condition (all 1000)
    m_rows = []
    IP, IN = boot_indices(y_all)
    for q in QS:
        for c in CONDS:
            pt, _ = cond_stats(W, q, c, IP, IN)
            lens = W[{"EN": "len_en", "KO": "len_ko", "MT": "len_mt"}[c]].to_numpy().astype(float)
            pt["length_only_AUC"] = float(fast_auc(lens[y_all == 1][None, :], lens[y_all == 0][None, :])[0])
            m_rows.append({"question": q, "condition": c, "condition_name": COND_NAME[c], **pt})
    M = pd.DataFrame(m_rows)
    M.to_csv(os.path.join(TAB, "metrics_by_condition.csv"), index=False, encoding="utf-8-sig")

    # ---- 2. paired comparisons (E1: KO vs EN; E4: MT vs KO, MT vs EN), all 1000
    cmp_cache = {}
    C = pd.DataFrame([compare(W, q, a, b, cmp_cache) for q in QS for b, a in COMPS])
    C.to_csv(os.path.join(TAB, "paired_comparisons.csv"), index=False, encoding="utf-8-sig")

    # diff-of-diff: does the condition effect differ between Q2 and QL? (same index matrix -> paired across Q)
    dd_rows = []
    for b, a in COMPS:
        st2, stl = cmp_cache[("Q2", a, b)], cmp_cache[("QL", a, b)]
        for key in ("TPR", "FPR", "AUC", "mean_p_inj", "mean_p_ben"):
            d2 = st2[b][1][key] - st2[a][1][key]
            dl = stl[b][1][key] - stl[a][1][key]
            point = (stl[b][0][key] - stl[a][0][key]) - (st2[b][0][key] - st2[a][0][key])
            lo, hi = ci(dl - d2)
            dd_rows.append({"comparison": COMP_KEY[(b, a)], "metric": key, "delta_Q2": st2[b][0][key] - st2[a][0][key],
                            "delta_QL": stl[b][0][key] - stl[a][0][key], "QL_minus_Q2": point, "lo": lo, "hi": hi,
                            "verdict": verdict(lo, hi)})
    DD = pd.DataFrame(dd_rows)
    DD.to_csv(os.path.join(TAB, "diff_of_diff_QL_vs_Q2.csv"), index=False, encoding="utf-8-sig")

    # ---- 3. recovery by translation (E4)
    REC = pd.DataFrame([r for q in QS for r in recovery(W, q)])
    REC.to_csv(os.path.join(TAB, "recovery.csv"), index=False, encoding="utf-8-sig")

    # ---- 4. subgroups: source / doc_type / risk_level (exploratory, Holm per question x comparison x family)
    fam_rows = []
    families = {"source": [(s, W.source == s) for s in SOURCES],
                "doc_type": [(d, W.doc_type == d) for d in DOC_TYPES if (W.doc_type == d).any()],
                "risk_level": [(f"{k}", (W.risk_level == k) & (W.label_int == 1)) for k in range(1, 6)]}
    for fam, groups in families.items():
        for g, mask in groups:
            D = W[mask]
            for q in QS:
                for b, a in COMPS:
                    fam_rows.append({"family": fam, "group": g, **compare(D, q, a, b)})
    SG = pd.DataFrame(fam_rows)
    # Holm per family x question x comparison, separately for each McNemar test (correctness / detection among
    # injections / false alarm among benign); a test that is undefined in a group (no injections or no benign docs)
    # is left out of that group's Holm family.
    for test in ("correct", "detect", "fp"):
        col = f"mcnemar_{test}_p"
        SG[f"{col}_holm"] = np.nan
        for (fam, q, comp), idx in SG.groupby(["family", "question", "comparison"]).groups.items():
            ok = [i for i in idx if pd.notna(SG.at[i, col])]
            if ok:
                SG.loc[ok, f"{col}_holm"] = holm(SG.loc[ok, col].astype(float).to_numpy())
    for fam in families:
        SG[SG.family == fam].to_csv(os.path.join(TAB, f"by_{fam}.csv"), index=False, encoding="utf-8-sig")

    # long per-group metrics per condition (for figures)
    g_rows = []
    for fam, groups in families.items():
        for g, mask in groups:
            D = W[mask]
            yy = D["label_int"].to_numpy()
            ip, inn = boot_indices(yy)
            for q in QS:
                for c in CONDS:
                    pt, _ = cond_stats(D, q, c, ip, inn)
                    g_rows.append({"family": fam, "group": g, "question": q, "condition": c, **pt})
    GM = pd.DataFrame(g_rows)
    GM.to_csv(os.path.join(TAB, "group_metrics_by_condition.csv"), index=False, encoding="utf-8-sig")

    # ---- 5. mean p shift per document by source x label
    dp_rows = []
    for q in QS:
        for b, a in COMPS:
            for grp, mask in [("전체", pd.Series(True, index=W.index))] + [(s, W.source == s) for s in SOURCES]:
                for lab in (1, 0):
                    D = W[mask & (W.label_int == lab)]
                    if not len(D):
                        continue
                    dp = (D[f"{q}_{b}_p"] - D[f"{q}_{a}_p"]).to_numpy()
                    lo, hi = mean_dp_ci(dp)
                    dp_rows.append({"question": q, "comparison": COMP_KEY[(b, a)], "source": grp, "label": LAB_NAME[lab],
                                    "n": len(D), f"mean_p_a": float(D[f"{q}_{a}_p"].mean()),
                                    "mean_p_b": float(D[f"{q}_{b}_p"].mean()), "mean_dp": float(dp.mean()),
                                    "mean_dp_lo": lo, "mean_dp_hi": hi, "verdict": verdict(lo, hi),
                                    "median_dp": float(np.median(dp)), "share_up_0.1": float((dp > 0.1).mean()),
                                    "share_down_0.1": float((dp < -0.1).mean()),
                                    "pearson_r": float(np.corrcoef(D[f"{q}_{a}_p"], D[f"{q}_{b}_p"])[0, 1])})
    DP = pd.DataFrame(dp_rows)
    DP.to_csv(os.path.join(TAB, "p_shift_by_source_label.csv"), index=False, encoding="utf-8-sig")

    # ---- 6. BrowseSafe register cue check ("-십시오" / "당신" only in KO)
    cue_rows = []
    for s in SOURCES:
        for lab in (1, 0):
            D = W[(W.source == s) & (W.label_int == lab)]
            if not len(D):
                continue
            cue_rows.append({"source": s, "label": LAB_NAME[lab], "n": len(D), "n_cue": int(D.ko_cue.sum()),
                             "n_sipsio": int(D.ko_sipsio.sum()), "n_dangsin": int(D.ko_dangsin.sum()),
                             "share_cue": float(D.ko_cue.mean())})
    CUE = pd.DataFrame(cue_rows)
    CUE.to_csv(os.path.join(TAB, "ko_register_cue_by_source.csv"), index=False, encoding="utf-8-sig")
    cue_auc = {}
    for grp, mask in [("all", pd.Series(True, index=W.index)), ("BrowseSafe-Bench", W.source == "BrowseSafe-Bench"),
                      ("InjecAgent", W.source == "InjecAgent")]:
        D = W[mask]
        yy, xx = D.label_int.to_numpy(), D.ko_cue.astype(float).to_numpy()
        cue_auc[grp] = float(fast_auc(xx[yy == 1][None, :], xx[yy == 0][None, :])[0])
    bs_rows = []
    bsm = W.source == "BrowseSafe-Bench"
    for q in QS:
        for grp, mask in [("BrowseSafe", bsm), ("BrowseSafe 제외", ~bsm), ("전체", pd.Series(True, index=W.index))]:
            r = compare(W[mask], q, "EN", "KO")
            bs_rows.append({"group": grp, **r})
        # within BrowseSafe injections: with vs without the cue (n small)
        for cue in (True, False):
            D = W[bsm & (W.label_int == 1) & (W.ko_cue == cue)]
            if len(D):
                dp = (D[f"{q}_KO_p"] - D[f"{q}_EN_p"]).to_numpy()
                lo, hi = mean_dp_ci(dp)
                bs_rows.append({"group": f"BrowseSafe 인젝션, KO 단서 {'있음' if cue else '없음'}", "question": q,
                                "n": len(D), "n_injection": len(D), "a_mean_p_inj": float(D[f"{q}_EN_p"].mean()),
                                "b_mean_p_inj": float(D[f"{q}_KO_p"].mean()), "d_mean_p_inj": float(dp.mean()),
                                "d_mean_p_inj_lo": lo, "d_mean_p_inj_hi": hi, "d_mean_p_inj_verdict": verdict(lo, hi)})
    BS = pd.DataFrame(bs_rows)
    BS.to_csv(os.path.join(TAB, "browsesafe_register_check.csv"), index=False, encoding="utf-8-sig")
    # does the KO-EN delta differ between BrowseSafe and the other sources? (difference of mean dp, bootstrap)
    bsd_rows = []
    for q in QS:
        for lab in (1, 0):
            a_ = (W.loc[bsm & (W.label_int == lab), f"{q}_KO_p"] - W.loc[bsm & (W.label_int == lab), f"{q}_EN_p"]).to_numpy()
            b_ = (W.loc[~bsm & (W.label_int == lab), f"{q}_KO_p"] - W.loc[~bsm & (W.label_int == lab), f"{q}_EN_p"]).to_numpy()
            rng = np.random.default_rng(SEED)
            da = a_[rng.integers(0, len(a_), (N_BOOT, len(a_)))].mean(1)
            db = b_[rng.integers(0, len(b_), (N_BOOT, len(b_)))].mean(1)
            lo, hi = ci(da - db)
            bsd_rows.append({"question": q, "label": LAB_NAME[lab], "n_browsesafe": len(a_), "n_other": len(b_),
                             "mean_dp_browsesafe": float(a_.mean()), "mean_dp_other": float(b_.mean()),
                             "difference": float(a_.mean() - b_.mean()), "lo": lo, "hi": hi, "verdict": verdict(lo, hi)})
    BSD = pd.DataFrame(bsd_rows)
    BSD.to_csv(os.path.join(TAB, "browsesafe_vs_other_dp.csv"), index=False, encoding="utf-8-sig")

    # ---- 7. translation quality sanity
    TQ = W[["uid", "pair_uid", "source", "doc_type", "label_int", "len_en", "len_ko", "len_mt", "mt_len_ratio",
            "hangul_ko", "hangul_left", "loop_mt", "loop_src", "loop_excess", "named_degenerate", "mt_loop",
            "mt_hangul", "hangul_in_tags", "instr_ko_kept", "mt_short", "mt_issue_any", "trig_en", "trig_mt"]].copy()
    TQ.to_csv(os.path.join(TAB, "translation_quality_docs.csv"), index=False, encoding="utf-8-sig")
    tq_rows = []
    for grp, mask in [("전체", pd.Series(True, index=W.index))] + [(s, W.source == s) for s in SOURCES]:
        D = W[mask]
        hl = D.loc[D.mt_hangul, "hangul_left"]
        tq_rows.append({"source": grp, "n": len(D), "n_hangul_left": int(D.mt_hangul.sum()),
                        "n_hangul_left_injection": int((D.mt_hangul & (D.label_int == 1)).sum()),
                        "n_hangul_left_benign": int((D.mt_hangul & (D.label_int == 0)).sum()),
                        "hangul_left_median": float(hl.median()) if len(hl) else None,
                        "hangul_left_max": int(hl.max()) if len(hl) else None,
                        "share_ko_hangul_left": float(D.hangul_left.sum() / max(1, D.hangul_ko.sum())),
                        "n_mt_loop": int(D.mt_loop.sum()), "n_mt_loop_injection": int((D.mt_loop & (D.label_int == 1)).sum()),
                        "n_mt_loop_benign": int((D.mt_loop & (D.label_int == 0)).sum()),
                        "n_named_degenerate": int(D.named_degenerate.sum()),
                        "mt_len_ratio_median": float(D.mt_len_ratio.median()),
                        "n_mt_len_ratio_gt_1_3": int((D.mt_len_ratio > 1.3).sum()),
                        "n_mt_len_ratio_lt_0_7": int(D.mt_short.sum()),
                        "n_mt_short_injection": int((D.mt_short & (D.label_int == 1)).sum()),
                        "hangul_left_chars": int(D.hangul_left.sum()), "hangul_in_tags_chars": int(D.hangul_in_tags.sum()),
                        "n_injection_with_instr": int(((D.label_int == 1) & D.instr_ko.notna()).sum()),
                        "n_instr_ko_kept_verbatim": int(D.instr_ko_kept.sum())})
    TQS = pd.DataFrame(tq_rows)
    TQS.to_csv(os.path.join(TAB, "translation_quality_by_source.csv"), index=False, encoding="utf-8-sig")
    # residual Hangul: what is left (first 3 runs of Hangul per doc)
    hl_ex = W[W.mt_hangul].copy()
    hl_ex["hangul_runs"] = hl_ex["text_mt"].map(lambda s: " | ".join(re.findall(r"[가-힣ㄱ-ㆎ]+", s)[:5]))
    hl_ex["n_runs"] = hl_ex["text_mt"].map(lambda s: len(re.findall(r"[가-힣ㄱ-ㆎ]+", s)))
    run_lens = [len(x) for s in hl_ex["text_mt"] for x in re.findall(r"[가-힣ㄱ-ㆎ]+", s)]
    run_words = pd.Series([x for s in hl_ex["text_mt"] for x in re.findall(r"[가-힣ㄱ-ㆎ]+", s)]).value_counts()
    hl_ex[["uid", "source", "label_int", "hangul_left", "n_runs", "hangul_runs"]].sort_values(
        "hangul_left", ascending=False).to_csv(os.path.join(TAB, "translation_hangul_left_docs.csv"), index=False,
                                               encoding="utf-8-sig")
    run_words.head(30).rename_axis("hangul_run").reset_index(name="count").to_csv(
        os.path.join(TAB, "translation_hangul_left_top_runs.csv"), index=False, encoding="utf-8-sig")
    # effect of a much shorter translation (possible dropped sentences) on the MT - KO p shift, by source x label
    sh_rows = []
    for q in QS:
        for s_ in SOURCES:
            for lab in (1, 0):
                for short_ in (True, False):
                    D = W[(W.source == s_) & (W.label_int == lab) & (W.mt_short == short_)]
                    if not len(D):
                        continue
                    sh_rows.append({"question": q, "source": s_, "label": LAB_NAME[lab], "mt_short": short_, "n": len(D),
                                    "mean_p_EN": float(D[f"{q}_EN_p"].mean()), "mean_p_KO": float(D[f"{q}_KO_p"].mean()),
                                    "mean_p_MT": float(D[f"{q}_MT_p"].mean()),
                                    "mean_dp_MT_minus_KO": float((D[f"{q}_MT_p"] - D[f"{q}_KO_p"]).mean()),
                                    "flag_rate_KO": float(D[f"{q}_KO_pred"].mean()),
                                    "flag_rate_MT": float(D[f"{q}_MT_pred"].mean())})
    pd.DataFrame(sh_rows).to_csv(os.path.join(TAB, "translation_short_effect.csv"), index=False, encoding="utf-8-sig")
    # AUC within SEP (where the short translations sit), MT vs KO, with and without the short docs
    sep_rows = []
    for name, mask in (("SEP 전체", W.source == "SEP"), ("SEP, 짧은 번역 제외", (W.source == "SEP") & ~W.mt_short)):
        for q in QS:
            sep_rows.append({"subset": name, **compare(W[mask], q, "KO", "MT")})
    pd.DataFrame(sep_rows).to_csv(os.path.join(TAB, "translation_short_sep_auc.csv"), index=False, encoding="utf-8-sig")
    loop_ex = W[W.mt_loop | W.named_degenerate].copy()

    def loop_snip(s):
        best, mm = 0, None
        for m in LOOP_RE.finditer(s):
            if m.group(1).strip() and len(m.group(0)) > best:
                best, mm = len(m.group(0)), m
        return short(s[max(0, mm.start() - 60): mm.start() + 90], 160) if mm else ""
    loop_ex["loop_snippet"] = loop_ex["text_mt"].map(loop_snip)
    loop_ex[["uid", "source", "label_int", "named_degenerate", "mt_loop", "loop_excess", "len_en", "len_mt",
             "Q2_KO_p", "Q2_MT_p", "QL_KO_p", "QL_MT_p", "loop_snippet"]].sort_values(
        "loop_excess", ascending=False).to_csv(os.path.join(TAB, "translation_loops_docs.csv"), index=False,
                                               encoding="utf-8-sig")

    # sensitivity of the MT result to the translation problems
    sens_sets = [("전체", pd.Series(True, index=W.index)),
                 ("퇴화 2건 제외", ~W.named_degenerate),
                 ("반복 루프 제외", ~(W.mt_loop | W.named_degenerate)),
                 ("한글 잔존 제외", ~W.mt_hangul),
                 ("짧은 번역 제외", ~W.mt_short),
                 ("네 문제 모두 제외", ~(W.mt_issue_any | W.mt_short))]
    sens_rows = []
    for name, mask in sens_sets:
        D = W[mask]
        for q in QS:
            for b, a in (("MT", "KO"), ("MT", "EN"), ("KO", "EN")):
                sens_rows.append({"subset": name, **compare(D, q, a, b)})
    SENS = pd.DataFrame(sens_rows)
    SENS.to_csv(os.path.join(TAB, "mt_sensitivity_exclusions.csv"), index=False, encoding="utf-8-sig")
    # the two named degenerate docs themselves
    deg = W[W.named_degenerate][["uid", "source", "label_int", "len_en", "len_ko", "len_mt", "loop_mt", "hangul_left"] +
                                [f"{q}_{c}_p" for q in QS for c in CONDS]].copy()
    deg["mt_start"] = W.loc[W.named_degenerate, "text_mt"].map(lambda s: short(s, 200))
    deg["instr_en"] = W.loc[W.named_degenerate, "instr_en"].map(lambda s: short(s, 160))
    deg.to_csv(os.path.join(TAB, "translation_degenerate_docs.csv"), index=False, encoding="utf-8-sig")

    # trigger words (exploratory; list chosen after reading MT false positives)
    tw_rows = []
    for q in QS:
        for lab in (1, 0):
            for gain in (True, False):
                D = W[(W.label_int == lab) & (W.trig_gain == gain)]
                if not len(D):
                    continue
                dp = (D[f"{q}_MT_p"] - D[f"{q}_EN_p"]).to_numpy()
                lo, hi = mean_dp_ci(dp)
                r = {"question": q, "label": LAB_NAME[lab], "mt_more_trigger_words_than_en": gain, "n": len(D),
                     "mean_dp_MT_minus_EN": float(dp.mean()), "lo": lo, "hi": hi,
                     "mean_dp_MT_minus_KO": float((D[f"{q}_MT_p"] - D[f"{q}_KO_p"]).mean())}
                for c in CONDS:
                    k = int(D[f"{q}_{c}_pred"].sum())
                    r[f"flag_rate_{c}"] = k / len(D)
                    r[f"flag_rate_{c}_lo"], r[f"flag_rate_{c}_hi"] = J.wilson(k, len(D))
                tw_rows.append(r)
    TW = pd.DataFrame(tw_rows)
    TW.to_csv(os.path.join(TAB, "trigger_words_mt_vs_en.csv"), index=False, encoding="utf-8-sig")
    tw_new_fp = {}
    for q in QS:
        nf = W[(W.label_int == 0) & W[f"{q}_MT_pred"] & ~W[f"{q}_KO_pred"]]
        tw_new_fp[q] = {"new_fp_vs_KO": len(nf), "with_trigger_gain": int(nf.trig_gain.sum()),
                        "by_source": nf.source.value_counts().to_dict()}

    # ---- 8. decision changes and examples
    dc_rows = []
    for q in QS:
        for b, a in COMPS:
            ch = W[W[f"{q}_{a}_pred"] != W[f"{q}_{b}_pred"]]
            for _, r in ch.iterrows():
                dc_rows.append({"question": q, "comparison": COMP_KEY[(b, a)], "uid": r.uid, "pair_uid": r.pair_uid,
                                "source": r.source, "doc_type": r.doc_type, "label": LAB_NAME[r.label_int],
                                "change": ("fixed" if r[f"{q}_{b}_correct"] else "broken"),
                                "p_EN": r[f"{q}_EN_p"], "p_KO": r[f"{q}_KO_p"], "p_MT": r[f"{q}_MT_p"],
                                "mt_hangul": r.hangul_left, "mt_loop": r.mt_loop, "trig_en": r.trig_en, "trig_mt": r.trig_mt,
                                "instr_en": short(r.instr_en, 200), "instr_ko": short(r.instr_ko, 200),
                                "instr_mt": short(r.instr_mt, 200)})
    DC = pd.DataFrame(dc_rows)
    DC.to_csv(os.path.join(TAB, "decision_changes_documents.csv"), index=False, encoding="utf-8-sig")
    dcs = DC.groupby(["question", "comparison", "source", "label", "change"]).size().unstack(fill_value=0).reset_index()
    dcs.to_csv(os.path.join(TAB, "decision_changes_by_source.csv"), index=False, encoding="utf-8-sig")

    # examples where MT changed the decision vs KO in BOTH questions (most robust), plus top single-question ones
    W["dp_mt_ko"] = (W["Q2_MT_p"] - W["Q2_KO_p"] + W["QL_MT_p"] - W["QL_KO_p"]) / 2
    both_fp = W[(W.label_int == 0) & W.Q2_MT_pred & W.QL_MT_pred & ~W.Q2_KO_pred & ~W.QL_KO_pred]
    both_miss = W[(W.label_int == 1) & ~W.Q2_MT_pred & ~W.QL_MT_pred & W.Q2_KO_pred & W.QL_KO_pred]
    both_fix = W[(W.label_int == 1) & W.Q2_MT_pred & W.QL_MT_pred & ~W.Q2_KO_pred & ~W.QL_KO_pred]
    ex = pd.concat([both_fp.sort_values("dp_mt_ko", ascending=False).assign(kind="MT 새 오탐 (두 질문)"),
                    both_miss.sort_values("dp_mt_ko").assign(kind="MT 새 놓침 (두 질문)"),
                    both_fix.sort_values("dp_mt_ko", ascending=False).assign(kind="MT 새 탐지 (두 질문)")])
    EXO = ex[["kind", "uid", "source", "doc_type", "label_int"] + [f"{q}_{c}_p" for q in QS for c in CONDS] +
             ["hangul_left", "mt_loop", "trig_en", "trig_mt"]].copy()

    def first_trigger_ctx(s):
        m = TRIGGER.search(s or "")
        return short(s[max(0, m.start() - 60): m.end() + 80], 150) if m else ""
    EXO["instr_en"] = ex["instr_en"].map(lambda s: short(s, 160))
    EXO["instr_ko"] = ex["instr_ko"].map(lambda s: short(s, 160))
    EXO["instr_mt"] = ex["instr_mt"].map(lambda s: short(s, 160))
    EXO["mt_trigger_context"] = ex["text_mt"].map(first_trigger_ctx)
    EXO["en_start"] = ex["text_en"].map(lambda s: short(s, 140))
    EXO["mt_start"] = ex["text_mt"].map(lambda s: short(s, 140))
    EXO.to_csv(os.path.join(TAB, "examples_mt_changed_decision.csv"), index=False, encoding="utf-8-sig")
    # KO vs EN robust changes (both questions)
    ko_fix = W[(W.Q2_KO_correct & ~W.Q2_EN_correct) & (W.QL_KO_correct & ~W.QL_EN_correct)]
    ko_brk = W[(~W.Q2_KO_correct & W.Q2_EN_correct) & (~W.QL_KO_correct & W.QL_EN_correct)]
    exk = pd.concat([ko_fix.assign(kind="KO가 바로잡음 (두 질문)"), ko_brk.assign(kind="KO가 망침 (두 질문)")])
    EXK = exk[["kind", "uid", "source", "doc_type", "label_int"] + [f"{q}_{c}_p" for q in QS for c in ("EN", "KO")] +
              ["ko_cue"]].copy()
    EXK["instr_en"] = exk["instr_en"].map(lambda s: short(s, 160))
    EXK["instr_ko"] = exk["instr_ko"].map(lambda s: short(s, 160))
    EXK.to_csv(os.path.join(TAB, "examples_ko_vs_en_both_questions.csv"), index=False, encoding="utf-8-sig")

    # ---- 9. noise floor, cost
    NF = pd.DataFrame([{"question": q, **noise_floor(W, q)} for q in QS])
    NF.to_csv(os.path.join(TAB, "noise_floor.csv"), index=False, encoding="utf-8-sig")
    cost_rows = []
    sums = {"EN": base_summary, "KO": summary, "MT": mt_summary}
    for q in QS:
        for c in CONDS:
            tok = W[f"{q}_{c}_input_tokens"]
            run = sums[c][q]["run"]
            cost_rows.append({"question": q, "condition": c, "input_tokens_mean": float(tok.mean()),
                              "input_tokens_median": float(tok.median()),
                              "input_tokens_inj_mean": float(tok[W.label_int == 1].mean()),
                              "usd_per_1000_docs_one_call": float(tok.sum() * PRICE_PER_M / 1e6),
                              "latency_ms_median_all_calls": run.get("latency_ms_median"),
                              "first_call": run.get("first_call"), "last_call": run.get("last_call"),
                              "api_calls": run.get("api_calls"), "api_errors": run.get("api_errors"),
                              "api_retries": run.get("api_retries"), "commit_at_call": sums[c].get("commit")})
    COST = pd.DataFrame(cost_rows)
    COST.to_csv(os.path.join(TAB, "cost_tokens_latency.csv"), index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------ figures
    figs = []

    def save(fig, name):
        S.save(fig, name, out_dir=FIG)
        figs.append(f"figures/{name}.png")

    mrow = {(r.question, r.condition): r for r in M.itertuples()}
    crow = {(r.question, r.comparison): r for r in C.itertuples()}

    # f01 headline
    fig = fig_headline(M)
    k2, kl = crow[("Q2", "KO_vs_EN")], crow[("QL", "KO_vs_EN")]
    S.title(fig, "한국어 문서도 영어와 비슷하게 판정했고, 영어로 기계번역하면 오히려 나빠졌다",
            f"같은 문서 1,000건(인젝션 500 / 정상 500)을 세 형태로 판정. 임계값 0.5, p = 3회 호출 평균. "
            f"TPR·FPR은 Wilson 95% CI, AUC는 부트스트랩 95% CI")
    save(fig, "f01_headline_metrics")

    # f02 paired deltas
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6), sharey=True)
    spec = [("TPR", "Δ 탐지율 TPR (%p)", 100), ("FPR", "Δ 오탐률 FPR (%p)", 100), ("AUC", "Δ AUC", 1)]
    for ax, (k, lab, sc) in zip(axes, spec):
        for i, (b, a) in enumerate(COMPS):
            for q in QS:
                r = crow[(q, COMP_KEY[(b, a)])]
                yv = i + (-0.13 if q == "Q2" else 0.13)
                v, lo, hi = getattr(r, f"d_{k}") * sc, getattr(r, f"d_{k}_lo") * sc, getattr(r, f"d_{k}_hi") * sc
                _err(ax, yv, v, lo, hi, Q_COLORS[q], horizontal=True)
                fmt = f"{v:+.1f}" if sc == 100 else f"{v:+.3f}"
                ax.annotate(f"{fmt} [{lo:+.1f}, {hi:+.1f}]" if sc == 100 else f"{fmt} [{lo:+.3f}, {hi:+.3f}]",
                            (hi, yv), xytext=(5, 0), textcoords="offset points", va="center", fontsize=7.5,
                            color=Q_COLORS[q])
        ax.axvline(0, color=S.INK_2, lw=0.9)
        ax.set_title(lab, fontsize=11)
        ax.set_yticks(range(3))
        ax.set_yticklabels([COMP_NAME[c] for c in COMPS])
        ax.invert_yaxis()
        lo_all = min(getattr(crow[(q, COMP_KEY[c])], f"d_{k}_lo") for q in QS for c in COMPS) * sc
        hi_all = max(getattr(crow[(q, COMP_KEY[c])], f"d_{k}_hi") for q in QS for c in COMPS) * sc
        span = hi_all - lo_all
        ax.set_xlim(min(lo_all, 0) - 0.1 * span, max(hi_all, 0) + 0.85 * span)
    S.title(fig, "번역 후 판정은 회복이 아니라 손실: KO→EN은 KO·EN보다 오탐이 늘고 AUC가 떨어졌다",
            "같은 문서끼리 짝지은 차이. 95% CI = 짝 부트스트랩 1,000회(seed 20261112, 라벨별 재추출). 0을 지나면 차이 없음/오차 범위")
    fig_legend(fig)
    save(fig, "f02_paired_deltas")

    # f03 / f04 scatter
    def scatter(a, b, name, headline, sub):
        fig, axes = plt.subplots(1, 2, figsize=(11, 5.6))
        for ax, q in zip(axes, QS):
            for lab in (0, 1):
                D = W[W.label_int == lab]
                ax.scatter(D[f"{q}_{a}_p"], D[f"{q}_{b}_p"], s=12, alpha=0.45, color=LAB_COLOR[lab], lw=0,
                           label=LAB_NAME[lab])
            ax.plot([0, 1], [0, 1], color=S.MUTED, lw=0.9, ls="--")
            ax.axhline(0.5, color=S.AXIS, lw=0.8, ls=":")
            ax.axvline(0.5, color=S.AXIS, lw=0.8, ls=":")
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(-0.02, 1.02)
            ax.set_aspect("equal")
            ax.set_xlabel(f"{COND_NAME[a]} p")
            ax.set_ylabel(f"{COND_NAME[b]} p")
            r = crow[(q, COMP_KEY[(b, a)])]
            inj_r = np.corrcoef(W.loc[W.label_int == 1, f"{q}_{a}_p"], W.loc[W.label_int == 1, f"{q}_{b}_p"])[0, 1]
            ax.set_title(f"{Q_NAME[q]}", color=Q_COLORS[q], fontsize=11)
            txt = (f"인젝션: {COND_NAME[b]}에서만 탐지 {r.inj_detected_only_b} / {COND_NAME[a]}에서만 {r.inj_detected_only_a}\n"
                   f"정상: {COND_NAME[b]}에서만 오탐 {r.ben_fp_only_b} / {COND_NAME[a]}에서만 {r.ben_fp_only_a}\n"
                   f"인젝션 p 상관 r = {inj_r:.2f}")
            ax.text(0.0, -0.13, txt, transform=ax.transAxes, ha="left", va="top", fontsize=8.5, color=S.INK_2)
        S.title(fig, headline, sub)
        fig_legend(fig, "label")
        save(fig, name)

    scatter("EN", "KO", "f03_scatter_en_vs_ko",
            "문서별로도 KO p는 EN p를 거의 그대로 따라갔다",
            "점 하나 = 같은 문서의 EN 원문 p(가로)와 KO 번역본 p(세로). 점선 = 0.5 임계값, 대각선 = 변화 없음. n = 1,000")
    scatter("KO", "MT", "f04_scatter_ko_vs_mt",
            "기계번역은 정상 문서의 p를 끌어올리고 인젝션 p를 흩뜨렸다",
            "점 하나 = 같은 문서의 KO p(가로)와 KO→EN 기계번역 p(세로). 점선 = 0.5 임계값. n = 1,000")

    # f05 p distribution
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    rng = np.random.default_rng(SEED)
    for ax, q in zip(axes, QS):
        for i, c in enumerate(CONDS):
            for lab, off in ((1, -0.18), (0, 0.18)):
                v = W.loc[W.label_int == lab, f"{q}_{c}_p"].to_numpy()
                x = i + off + rng.uniform(-0.11, 0.11, len(v))
                ax.scatter(x, v, s=5, alpha=0.30, color=LAB_COLOR[lab], lw=0)
                bp = ax.boxplot([v], positions=[i + off], widths=0.26, showfliers=False, patch_artist=True,
                                medianprops=dict(color=S.INK, lw=1.6), whiskerprops=dict(color=S.INK_2, lw=0.9),
                                capprops=dict(color=S.INK_2, lw=0.9),
                                boxprops=dict(facecolor="none", edgecolor=S.INK_2, lw=0.9))
                ax.annotate(f"평균 {v.mean():.2f}", (i + off, 1.03), ha="center", fontsize=7.5, color=LAB_COLOR[lab])
        ax.axhline(0.5, color=S.MUTED, lw=0.9, ls="--")
        ax.set_xticks(range(3))
        ax.set_xticklabels([COND_TICK[c] for c in CONDS], fontsize=9)
        ax.set_ylim(-0.03, 1.08)
        ax.set_title(Q_NAME[q], color=Q_COLORS[q], fontsize=11)
        ax.set_ylabel("p (3회 평균)")
    S.title(fig, "KO→EN 번역본에서 정상 문서 p의 위쪽 꼬리가 길어졌다",
            "점 하나 = 문서 하나 (인젝션 500 / 정상 500). 상자 = 사분위, 굵은 선 = 중앙값, 점선 = 임계값 0.5")
    fig_legend(fig, "label")
    save(fig, "f05_p_distribution")

    # f06 ROC (zoom)
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6), sharey=True)
    for ax, c in zip(axes, CONDS):
        for q in QS:
            fpr, tpr, _ = roc_curve(y_all, W[f"{q}_{c}_p"])
            r = mrow[(q, c)]
            ax.plot(fpr, tpr, color=Q_COLORS[q], lw=1.8, label=f"{q} AUC {r.AUC:.3f}")
            ax.plot([r.FPR], [r.TPR], "o", color=Q_COLORS[q], ms=6)
        ax.set_xlim(0, 0.30)
        ax.set_ylim(0.3, 1.0)
        ax.set_xlabel("오탐률 FPR")
        ax.set_title(COND_TICK[c].replace("\n", " · "), fontsize=11)
        ax.legend(loc="lower right")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    axes[0].set_ylabel("탐지율 TPR")
    S.title(fig, "ROC: EN과 KO는 거의 겹치고, KO→EN은 Q2·QL 모두 아래로 처졌다",
            "FPR 0~30% 구간 확대. 점 = 임계값 0.5의 위치. n = 1,000 (인젝션 500 / 정상 500)")
    save(fig, "f06_roc_zoom")

    # f07 / f08 by source
    def by_source_fig(metric, lab, sources, name, headline, sub, ncols):
        nrows = int(math.ceil(len(sources) / ncols))
        fig, axes = plt.subplots(nrows, ncols, figsize=(3.1 * ncols, 3.3 * nrows + 0.6), sharey=True)
        axes = np.atleast_1d(axes).ravel()
        for ax, s in zip(axes, sources):
            for q in QS:
                for i, c in enumerate(CONDS):
                    r = GM[(GM.family == "source") & (GM.group == s) & (GM.question == q) & (GM.condition == c)].iloc[0]
                    x = i + (-0.12 if q == "Q2" else 0.12)
                    _err(ax, x, r[metric], r[f"{metric}_lo"], r[f"{metric}_hi"], Q_COLORS[q], size=5.5)
            n = int(GM[(GM.family == "source") & (GM.group == s)].iloc[0]["n_injection" if metric == "TPR" else "n_benign"])
            ax.set_title(f"{src_short(s)} (n={n})", fontsize=10)
            ax.set_xticks(range(3))
            ax.set_xticklabels(["EN", "KO", "KO→EN"], fontsize=8.5)
            ax.set_xlim(-0.5, 2.5)
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
        for ax in axes[len(sources):]:
            ax.set_visible(False)
        for ax in axes[::ncols]:
            ax.set_ylabel(lab)
        q_legend(axes[0], loc="best" if metric == "TPR" else "upper left", fontsize=8)
        S.title(fig, headline, sub)
        save(fig, name)

    inj_src = [s for s in SOURCES if ((W.source == s) & (W.label_int == 1)).any()]
    ben_src = [s for s in SOURCES if ((W.source == s) & (W.label_int == 0)).any()]
    by_source_fig("TPR", "탐지율 TPR", inj_src, "f07_by_source_tpr",
                  "출처별 탐지율: 출처 사이 차이가 언어·번역 차이보다 훨씬 컸다",
                  "인젝션 문서만. 점 = TPR(임계값 0.5), 막대 = Wilson 95% CI", 3)
    def fp_note(s, q):  # KO->EN vs KO: new false alarms / vanished, exact McNemar p (same benign documents)
        r = SG[(SG.family == "source") & (SG.group == s) & (SG.question == q) & (SG.comparison == "MT_vs_KO")].iloc[0]
        return f"{src_short(s)} {int(r.ben_fp_only_b)}/{int(r.ben_fp_only_a)} (p={r.mcnemar_fp_p:.3f})"
    fp_lines = [f"{q}: " + ", ".join(fp_note(s, q) for s in ("BrowseSafe-Bench", "Enron", "Synthetic")) for q in QS]
    by_source_fig("FPR", "오탐률 FPR", ben_src, "f08_by_source_fpr",
                  "출처별 오탐률: KO→EN에서 BrowseSafe(Q2) 오탐이 늘었다. Enron·합성은 같은 방향이지만 문서 수가 적어 불확실",
                  "정상 문서만. 점 = FPR(임계값 0.5), 막대 = Wilson 95% CI. 합성 n=15는 CI가 넓다\n"
                  f"KO→EN vs KO 새 오탐 / 사라진 오탐 (McNemar exact p), {fp_lines[0]}\n{fp_lines[1]}", 4)

    # f09 p shift by source x label
    fig, axes = plt.subplots(2, 2, figsize=(12, 8.2), sharey=True)
    srcs = ["전체"] + SOURCES
    for row, (b, a) in enumerate([("KO", "EN"), ("MT", "KO")]):
        for col, q in enumerate(QS):
            ax = axes[row, col]
            for i, s in enumerate(srcs):
                for lab, off in ((1, -0.16), (0, 0.16)):
                    r = DP[(DP.question == q) & (DP.comparison == COMP_KEY[(b, a)]) & (DP.source == s) &
                           (DP.label == LAB_NAME[lab])]
                    if not len(r):
                        continue
                    r = r.iloc[0]
                    _err(ax, i + off, r.mean_dp, r.mean_dp_lo, r.mean_dp_hi, LAB_COLOR[lab], horizontal=True, size=5)
            ax.axvline(0, color=S.INK_2, lw=0.9)
            ax.set_yticks(range(len(srcs)))
            def n_of(s, lab):
                in_src = (W.source == s) if s != "전체" else pd.Series(True, index=W.index)
                return int((in_src & (W.label_int == lab)).sum())
            ax.set_yticklabels([f"{src_short(s)} ({n_of(s, 1)}/{n_of(s, 0)})" for s in srcs], fontsize=8.5)
            ax.set_title(f"{COMP_NAME[(b, a)]} · {q}", fontsize=11, color=Q_COLORS[q])
            ax.set_xlabel("문서별 p 변화의 평균 (95% CI)")
            ax.set_xlim(-0.30, 0.42)
    axes[0, 0].invert_yaxis()  # shared y: inverts every panel once
    S.title(fig, "평균 p 변화: KO는 출처마다 작게 오르내리고, KO→EN은 정상 문서 p를 일관되게 올렸다",
            "위: KO − EN, 아래: KO→EN − KO. 점 = 같은 문서 p 차이의 평균, 막대 = 부트스트랩 95% CI (출처·라벨 안에서 재추출). "
            "괄호 = 인젝션/정상 수")
    fig_legend(fig, "label")
    save(fig, "f09_p_shift_by_source")

    # f10 risk level
    fig, axes = plt.subplots(1, 3, figsize=(12.5, 4.6), sharey=True)
    for ax, c in zip(axes, CONDS):
        for q in QS:
            for k in range(1, 6):
                r = GM[(GM.family == "risk_level") & (GM.group == str(k)) & (GM.question == q) & (GM.condition == c)].iloc[0]
                _err(ax, k + (-0.12 if q == "Q2" else 0.12), r.TPR, r.TPR_lo, r.TPR_hi, Q_COLORS[q], size=5.5)
        ns = [int(GM[(GM.family == "risk_level") & (GM.group == str(k))].iloc[0]["n_injection"]) for k in range(1, 6)]
        ax.set_xticks(range(1, 6))
        ax.set_xticklabels([f"{k}\nn={n}" for k, n in zip(range(1, 6), ns)], fontsize=8.5)
        ax.set_xlabel("위험도")
        ax.set_title(COND_TICK[c].replace("\n", " · "), fontsize=11)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    axes[0].set_ylabel("탐지율 TPR")
    q_legend(axes[0], loc="lower right", fontsize=8)
    r3 = SG[(SG.family == "risk_level") & (SG.group == "3") & (SG.question == "QL") & (SG.comparison == "MT_vs_KO")].iloc[0]
    S.title(fig, "위험도별 탐지율: 세 조건 모두 위험도 1이 가장 낮았고, QL 위험도 3은 KO→EN에서 떨어졌다",
            "인젝션 500건. 위험도는 EN 짝의 값을 그대로 씀. 위험도 2는 n=13이라 CI가 넓다. 위험도는 출처와 겹친다 (탐색적)\n"
            f"QL 위험도 3 (n={int(r3.n_injection)}): KO {100 * r3.a_TPR:.1f}% → KO→EN {100 * r3.b_TPR:.1f}%, "
            f"새로 잡음 {int(r3.inj_detected_only_b)} / 새로 놓침 {int(r3.inj_detected_only_a)}, "
            f"Holm 보정 p = {r3.mcnemar_detect_p_holm:.3f}")
    save(fig, "f10_by_risk_level")

    # f11 BrowseSafe cue
    fig = plt.figure(figsize=(13, 5.0))
    gs = fig.add_gridspec(1, 3, width_ratios=[1.25, 1, 1])
    ax = fig.add_subplot(gs[0])
    cs = [s for s in SOURCES]
    for i, s in enumerate(cs):
        for lab, off in ((1, -0.18), (0, 0.18)):
            r = CUE[(CUE.source == s) & (CUE.label == LAB_NAME[lab])]
            if not len(r):
                continue
            r = r.iloc[0]
            ax.barh(i + off, r.share_cue, height=0.34, color=LAB_COLOR[lab])
            ax.annotate(f"{r.n_cue}/{r.n}", (r.share_cue, i + off), xytext=(3, 0), textcoords="offset points",
                        va="center", fontsize=7.5, color=S.INK_2)
    ax.set_yticks(range(len(cs)))
    ax.set_yticklabels([src_short(s) for s in cs])
    ax.invert_yaxis()
    ax.set_xlim(0, 1.18)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    ax.set_title("KO 문서에 '-십시오' 또는 '당신'이 있는 비율", fontsize=10.5)
    lab_legend(ax, loc="lower right")
    for j, q in enumerate(QS):
        ax = fig.add_subplot(gs[j + 1])
        for i, grp in enumerate(["BrowseSafe", "그 외 출처"]):
            for lab, off in ((1, -0.12), (0, 0.12)):
                r = BSD[(BSD.question == q) & (BSD.label == LAB_NAME[lab])].iloc[0]
                if grp == "BrowseSafe":
                    D = W[bsm & (W.label_int == lab)]
                else:
                    D = W[~bsm & (W.label_int == lab)]
                dp = (D[f"{q}_KO_p"] - D[f"{q}_EN_p"]).to_numpy()
                lo, hi = mean_dp_ci(dp)
                _err(ax, i + off, dp.mean(), lo, hi, LAB_COLOR[lab], size=6)
                ax.annotate(f"{dp.mean():+.3f}", (i + off, hi), xytext=(0, 4), textcoords="offset points", ha="center",
                            fontsize=7.5, color=LAB_COLOR[lab])
        ax.axhline(0, color=S.INK_2, lw=0.9)
        ax.set_xticks([0, 1])
        ax.set_xticklabels([f"BrowseSafe\n(인젝션 {int(bsm[W.label_int == 1].sum())} / 정상 {int(bsm[W.label_int == 0].sum())})",
                            f"그 외 출처\n(인젝션 {int((~bsm)[W.label_int == 1].sum())} / 정상 {int((~bsm)[W.label_int == 0].sum())})"],
                           fontsize=8.5)
        ax.set_xlim(-0.5, 1.5)
        ax.set_ylim(-0.12, 0.10)
        ax.set_title(f"KO − EN 평균 p 변화 · {q}", fontsize=10.5, color=Q_COLORS[q])
    S.title(fig, "'-십시오'·'당신'은 KO 인젝션 쪽에 몰려 있지만, KO BrowseSafe 인젝션 p가 오르지는 않았다",
            f"왼쪽: 단서 비율 (단서만으로 라벨을 맞히는 AUC: BrowseSafe {cue_auc['BrowseSafe-Bench']:.2f}, 전체 {cue_auc['all']:.2f}). "
            "오른쪽: 같은 문서의 KO p − EN p 평균과 부트스트랩 95% CI")
    save(fig, "f11_browsesafe_register_cue")

    # f12 translation quality
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.8))
    in_tags = W.hangul_in_tags.sum() / max(1, W.hangul_left.sum())
    for ax, (flag, lab_t) in zip(axes, [("mt_hangul", f"한글이 남은 문서 (남은 글자의 {100 * in_tags:.0f}%는 HTML 태그 안)"),
                                        ("mt_loop", "번역에만 생긴 반복 루프 (≥50자)"),
                                        ("mt_short", f"번역문이 EN 원문의 {int(100 * SHORT_RATIO)}% 미만 길이")]):
        left = np.zeros(len(SOURCES))
        for lab in (1, 0):
            v = np.array([int(((W.source == s) & W[flag] & (W.label_int == lab)).sum()) for s in SOURCES])
            ax.barh(range(len(SOURCES)), v, left=left, color=LAB_COLOR[lab], height=0.6, label=LAB_NAME[lab])
            left += v
        for i, s in enumerate(SOURCES):
            ax.annotate(f"{int(left[i])}/{int((W.source == s).sum())}", (left[i], i), xytext=(3, 0),
                        textcoords="offset points", va="center", fontsize=8, color=S.INK_2)
        ax.set_yticks(range(len(SOURCES)))
        ax.set_yticklabels([src_short(s) for s in SOURCES])
        ax.invert_yaxis()
        ax.set_xlim(0, left.max() * 1.25 + 1)
        ax.set_title(f"{lab_t}: {int(W[flag].sum())}건", fontsize=10)
        ax.set_xlabel("문서 수 (막대 끝 = 해당 / 출처 전체)")
    axes[0].legend(loc="lower right")
    S.title(fig, "번역 품질 점검: BrowseSafe는 태그 속 한글이 남고, BIPIA·LLMail은 반복 루프, SEP는 번역문이 짧아졌다",
            f"KO→EN 1,000건. 막대 끝 숫자 = 해당 문서 / 출처 전체. 퇴화 2건({', '.join(NAMED_DEGENERATE)})은 따로 지정. "
            "의미 충실도는 점검하지 않았다 (길이·문자만 셈)")
    save(fig, "f12_translation_quality")

    # f13 trigger words
    fig, axes = plt.subplots(1, 2, figsize=(12, 4.8), sharey=True)
    for ax, gain in zip(axes, (True, False)):
        for q in QS:
            r = TW[(TW.question == q) & (TW.label == "정상") & (TW.mt_more_trigger_words_than_en == gain)].iloc[0]
            for i, c in enumerate(CONDS):
                _err(ax, i + (-0.12 if q == "Q2" else 0.12), r[f"flag_rate_{c}"], r[f"flag_rate_{c}_lo"],
                     r[f"flag_rate_{c}_hi"], Q_COLORS[q], size=6)
                ax.annotate(f"{100 * r[f'flag_rate_{c}']:.1f}%", (i + (-0.12 if q == "Q2" else 0.12), r[f"flag_rate_{c}"]),
                            xytext=(-5 if q == "Q2" else 5, 0), textcoords="offset points",
                            ha="right" if q == "Q2" else "left", va="center", fontsize=7.5, color=Q_COLORS[q])
        n = int(TW[(TW.question == "Q2") & (TW.label == "정상") & (TW.mt_more_trigger_words_than_en == gain)].iloc[0]["n"])
        ax.set_title(("번역문에 지시성 단어가 EN 원문보다 많아진 정상 문서" if gain else "그 외 정상 문서") + f" (n={n})",
                     fontsize=10.5)
        ax.set_xticks(range(3))
        ax.set_xticklabels([COND_TICK[c] for c in CONDS], fontsize=9)
        ax.set_xlim(-0.6, 2.6)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    axes[0].set_ylabel("오탐률 FPR")
    nf2 = tw_new_fp["Q2"]
    S.title(fig, "탐색: 번역이 'ignore'·'must' 같은 단어를 만든 정상 문서는 오탐률이 더 높았지만, 새 오탐의 일부만 설명한다",
            f"Q2 KO→EN 새 오탐 {nf2['new_fp_vs_KO']}건 중 지시성 단어가 늘어난 문서는 {nf2['with_trigger_gain']}건. 막대 = Wilson 95% CI" + chr(10) +
            "단어 목록(ignore, must, instruction 등 11개)은 오탐 사례를 읽은 뒤 정했다 (가설 생성용)")
    fig_legend(fig)
    save(fig, "f13_trigger_words_benign")

    # f14 MT sensitivity
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8), sharey=True)
    names = [s for s, _ in sens_sets]
    spec = [("TPR", "Δ TPR (%p)", 100), ("FPR", "Δ FPR (%p)", 100), ("AUC", "Δ AUC", 1)]
    for ax, (k, lab, sc) in zip(axes, spec):
        for i, nm in enumerate(names):
            for q in QS:
                r = SENS[(SENS.subset == nm) & (SENS.question == q) & (SENS.comparison == "MT_vs_KO")].iloc[0]
                _err(ax, i + (-0.13 if q == "Q2" else 0.13), r[f"d_{k}"] * sc, r[f"d_{k}_lo"] * sc, r[f"d_{k}_hi"] * sc,
                     Q_COLORS[q], horizontal=True, size=6)
        ax.axvline(0, color=S.INK_2, lw=0.9)
        ax.set_yticks(range(len(names)))
        ns = [int(SENS[(SENS.subset == nm)].iloc[0]["n"]) for nm in names]
        ax.set_yticklabels([f"{nm}\n(n={n})" for nm, n in zip(names, ns)], fontsize=8.5)
        ax.set_title(f"KO→EN − KO: {lab}", fontsize=10.5)
    axes[0].invert_yaxis()
    S.title(fig, "번역 문제 문서를 빼도 KO→EN의 오탐 증가와 AUC 하락은 남았다. QL TPR 하락은 CI가 0을 덮게 된다",
            "같은 문서 짝 차이와 짝 부트스트랩 95% CI. 퇴화 2건 = KO-I-138·KO-I-157, 반복 루프 = 번역에만 생긴 ≥50자 반복,\n"
            f"한글 잔존 = 번역문에 한글 1자 이상, 짧은 번역 = EN 길이의 {int(100 * SHORT_RATIO)}% 미만")
    fig_legend(fig)
    save(fig, "f14_mt_sensitivity")

    # ------------------------------------------------------------------ summary.json
    def mblock(q, c):
        r = M[(M.question == q) & (M.condition == c)].iloc[0].to_dict()
        return {k: r[k] for k in ("n", "TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi", "AUC", "AUC_lo", "AUC_hi",
                                  "mean_p_inj", "mean_p_ben", "tp", "fp", "flips", "TPR_at_FPR1", "TPR_at_FPR1_lo",
                                  "TPR_at_FPR1_hi", "length_only_AUC")}

    def cblock(q, key):
        r = C[(C.question == q) & (C.comparison == key)].iloc[0].to_dict()
        keep = [k for k in r if k.startswith("d_") or k in ("fixed_in_b", "broken_in_b", "mcnemar_correct_p",
                                                           "inj_detected_only_b", "inj_detected_only_a", "mcnemar_detect_p",
                                                           "ben_fp_only_a", "ben_fp_only_b", "mcnemar_fp_p")]
        return {k: r[k] for k in keep}

    analysis["per_question"] = {q: {"metrics": {c: mblock(q, c) for c in CONDS},
                                    "paired": {COMP_KEY[(b, a)]: cblock(q, COMP_KEY[(b, a)]) for b, a in COMPS},
                                    "recovery": REC[REC.question == q].drop(columns="question").to_dict("records"),
                                    "noise_floor": NF[NF.question == q].iloc[0].drop("question").to_dict()}
                                for q in QS}
    analysis["diff_of_diff_QL_minus_Q2"] = DD.to_dict("records")
    analysis["browsesafe_register_check"] = {
        "cue": "KO text contains '십시오' or '당신'",
        "cue_counts": CUE.to_dict("records"), "cue_only_AUC": cue_auc,
        "KO_vs_EN": BS[BS["comparison"].notna()][["group", "question", "n", "a_TPR", "b_TPR", "d_TPR", "d_TPR_lo",
                                                   "d_TPR_hi", "a_FPR", "b_FPR", "d_FPR", "d_FPR_lo", "d_FPR_hi", "a_AUC",
                                                   "b_AUC", "d_AUC", "d_AUC_lo", "d_AUC_hi"]].to_dict("records"),
        "browsesafe_minus_other_mean_dp": BSD.to_dict("records")}
    analysis["translation_quality"] = {
        "hangul_left_docs": int(W.mt_hangul.sum()),
        "hangul_left_median_chars": float(W.loc[W.mt_hangul, "hangul_left"].median()),
        "hangul_left_max_chars": int(W.hangul_left.max()),
        "hangul_left_by_source": W[W.mt_hangul].source.value_counts().to_dict(),
        "hangul_left_share_of_ko_hangul": float(W.hangul_left.sum() / W.hangul_ko.sum()),
        "hangul_runs_total": len(run_lens), "hangul_runs_top": run_words.head(10).to_dict(),
        "mt_only_repetition_loop_docs": int(W.mt_loop.sum()),
        "mt_only_repetition_loop_rule": f"unit of 1-30 chars repeated >= 5 times; MT longest run minus KO/EN longest run "
                                        f">= {LOOP_MIN} chars",
        "mt_loop_by_source": W[W.mt_loop].source.value_counts().to_dict(),
        "named_degenerate": NAMED_DEGENERATE,
        "mt_len_ratio_median": float(W.mt_len_ratio.median()),
        "hangul_left_chars": int(W.hangul_left.sum()), "hangul_in_html_tags_chars": int(W.hangul_in_tags.sum()),
        "hangul_in_html_tags_by_source": W.groupby("source").hangul_in_tags.sum().astype(int).to_dict(),
        "injection_instruction_left_untranslated_verbatim": int(W.instr_ko_kept.sum()),
        "injection_instruction_left_untranslated_by_source": W[W.instr_ko_kept].source.value_counts().to_dict(),
        f"mt_shorter_than_{SHORT_RATIO}_of_EN_docs": int(W.mt_short.sum()),
        "mt_short_by_source": W[W.mt_short].source.value_counts().to_dict(),
        "mt_rebuilt_from_segment_cache": rebuild_info["mt_rebuilt_from_segment_cache"],
        "fidelity_note": "Only residual Hangul, repetition loops and length ratio were checked; translation meaning was "
                         "not evaluated."}
    analysis["mt_sensitivity"] = SENS[SENS.comparison == "MT_vs_KO"][
        ["subset", "question", "n", "a_TPR", "b_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi", "a_FPR", "b_FPR", "d_FPR", "d_FPR_lo",
         "d_FPR_hi", "a_AUC", "b_AUC", "d_AUC", "d_AUC_lo", "d_AUC_hi", "inj_detected_only_b", "inj_detected_only_a",
         "mcnemar_detect_p", "ben_fp_only_b", "ben_fp_only_a", "mcnemar_fp_p", "fixed_in_b", "broken_in_b",
         "mcnemar_correct_p"]].to_dict("records")
    # exploratory subgroups whose Holm-adjusted McNemar p < 0.05 in any of the three tests, per comparison
    hcols = ["mcnemar_correct_p_holm", "mcnemar_detect_p_holm", "mcnemar_fp_p_holm"]
    surv = SG[(SG[hcols] < 0.05).any(axis=1)]
    analysis["subgroups_holm"] = {
        "rule": "Holm per family (source / doc_type / risk_level) x question x comparison, separately for each test; "
                "exploratory",
        "n_surviving_by_comparison": {COMP_KEY[(b, a)]: int((surv.comparison == COMP_KEY[(b, a)]).sum()) for b, a in COMPS},
        "surviving": surv[["family", "group", "question", "comparison", "n", "n_injection", "n_benign", "a_TPR", "b_TPR",
                           "d_TPR", "d_TPR_lo", "d_TPR_hi", "a_FPR", "b_FPR", "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_AUC",
                           "fixed_in_b", "broken_in_b", "mcnemar_correct_p", "inj_detected_only_b", "inj_detected_only_a",
                           "mcnemar_detect_p", "ben_fp_only_b", "ben_fp_only_a", "mcnemar_fp_p"] + hcols
                          ].to_dict("records")}
    analysis["trigger_words_exploratory"] = {"regex": TRIGGER.pattern, "table": TW.to_dict("records"),
                                             "new_false_positives_MT_vs_KO": tw_new_fp,
                                             "note": "word list chosen after reading MT false positives"}
    analysis["cost"] = COST.to_dict("records")
    analysis["figures"] = figs
    analysis["tables"] = sorted(f"tables/{f}" for f in os.listdir(TAB))
    summary["analysis"] = clean(analysis)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1, default=float)

    # ------------------------------------------------------------------ console digest
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    print(M[["question", "condition", "TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi", "AUC", "AUC_lo", "AUC_hi",
             "mean_p_inj", "mean_p_ben", "TPR_at_FPR1", "length_only_AUC"]].round(4).to_string())
    print(C[["question", "comparison", "d_TPR", "d_TPR_lo", "d_TPR_hi", "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_AUC", "d_AUC_lo",
             "d_AUC_hi", "fixed_in_b", "broken_in_b", "mcnemar_correct_p", "inj_detected_only_b", "inj_detected_only_a",
             "mcnemar_detect_p", "ben_fp_only_b", "ben_fp_only_a", "mcnemar_fp_p"]].round(4).to_string())
    print(REC.round(4).to_string())
    print(f"saved {len(figs)} figures, {len(os.listdir(TAB))} tables; MT rebuilt from cache: {rebuild_info}")


if __name__ == "__main__":
    main()
