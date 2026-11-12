"""X1_register analysis (no API calls): does Jev catch the same injection when it is reworded?

    python experiments/analyze_X1_register.py

Inputs (all produced earlier by `python experiments/run_api.py X1_register` / `01_baseline`):
  results/X1_register/{Q2,QL}_predictions.csv   450 rows = 150 base injections x 3 registers (all label=injection)
  results/01_baseline/{Q2,QL}_predictions.csv   EN 1000 (set=="EN"): the 150 original base documents (join
                                                base_uid -> uid) and the 500 EN benign documents (AUC reference)
  data/injection_eval/experiments/X1_register.jsonl, data/injection_eval/en/dataset_en_1000.jsonl
                                                spans, text lengths, md5 (never modified)
Outputs:
  results/X1_register/tables/*.csv, results/X1_register/figures/*.png,
  results/X1_register/summary.json  -> adds an "analysis" object, keeps every existing key.

Conditions per base document (paired, same 150 bases in every condition and both questions):
  original            the base document from 01_baseline (its injected span as the benchmark wrote it)
  imperative_explicit the span rewritten as an explicit command with trigger words ("ignore previous ...")
  plain_request       the same intent as a plain work request, no trigger words
  polite              the same intent as a polite indirect ask, no trigger words
Statistics: TPR/AUC through src.jev_guard.metrics (threshold 0.5); Wilson 95% CI (jevlab.wilson); exact McNemar
(two-sided binomial test on discordant pairs) with Holm correction per question; paired bootstrap (1000 resamples,
seed 20261112) over base documents for differences in TPR / mean p / AUC. AUC resamples the 150 bases and the 500
EN benign documents independently with the same index matrices for every condition and both questions (paired).
"""
import datetime as dt
import hashlib
import itertools
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
from src.jev_guard import THRESHOLD, metrics  # noqa: E402
import jevlab as J  # noqa: E402
import plot_style as S  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

EXP = "X1_register"
OUT = os.path.join(J.RESULTS, EXP)
BASE_DIR = os.path.join(J.RESULTS, "01_baseline")
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
X1_DATA = os.path.join(J.DATA, "experiments", "X1_register.jsonl")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")

QS = ["Q2", "QL"]
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}  # project-wide: question colours
Q_NAME = {"Q2": "Q2 (짧은 질문)", "QL": "QL (정의형 긴 질문)"}
INJ, BEN = S.LABEL_COLORS["인젝션"], S.LABEL_COLORS["정상"]
CONDS = ["original", "imperative_explicit", "plain_request", "polite"]
REGS = CONDS[1:]
C_SHORT = {"original": "원문", "imperative_explicit": "명령형", "plain_request": "평범한 요청", "polite": "공손한 부탁"}
C_LONG = {"original": "원문 (기준선 문서)", "imperative_explicit": "노골적 명령형", "plain_request": "평범한 업무 요청",
          "polite": "공손한 부탁"}
SOURCES = ["BIPIA", "LLMail-Inject", "BrowseSafe-Bench", "SEP", "InjecAgent"]
N_BOOT, SEED = 1000, 20261112
VERDICT_NONE = "차이 없음/오차 범위"


# ------------------------------------------------------------------ small helpers
def md5_file(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def rel(path):
    return os.path.relpath(path, REPO).replace(os.sep, "/")


def ci(a):
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))] if len(a) else [None, None]


def paired_boot(a, b):
    """a, b: values on the same documents (0/1 detections or p). Percentile 95% CI of mean(b) - mean(a) over
    N_BOOT paired resamples drawn with a fresh rng(SEED) for this subset size (same scheme as paired_rows)."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    if len(a) == 0:
        return [None, None]
    bi = np.random.default_rng(SEED).integers(0, len(a), (N_BOOT, len(a)))
    return ci(b[bi].mean(1) - a[bi].mean(1))


def verdict(lo, hi):
    if lo is None or hi is None:
        return ""
    return VERDICT_NONE if lo <= 0 <= hi else ("높아짐" if lo > 0 else "낮아짐")


def mcnemar_exact(a, b):
    """a, b: boolean arrays (detected under condition A / B) on the same documents. Two-sided exact test."""
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


def det_block(p):
    """Detection (TPR at 0.5) for an injection-only vector of p, through metrics()."""
    p = np.asarray(p, float)
    m = metrics([1] * len(p), p.tolist(), threshold=THRESHOLD)
    tp = int(round(m["TPR"] * m["n"])) if m["n"] else 0
    lo, hi = J.wilson(tp, m["n"]) if m["n"] else (None, None)
    return {"n": m["n"], "tp": tp, "TPR": m["TPR"], "TPR_lo": lo, "TPR_hi": hi,
            "mean_p": float(p.mean()) if len(p) else None, "median_p": float(np.median(p)) if len(p) else None}


def auc_vs(inj, ben):
    inj, ben = np.asarray(inj, float), np.asarray(ben, float)
    return metrics([1] * len(inj) + [0] * len(ben), np.concatenate([inj, ben]).tolist())["AUC"]


def fmt_p(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if o != o else float(o)  # NaN -> null (valid JSON)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


# ------------------------------------------------------------------ load
def load_data():
    x1 = pd.DataFrame(J.load_jsonl(X1_DATA))
    en = {r["uid"]: r for r in J.load_jsonl(EN_DATA)}
    x1["identical_to_base"] = [t == en[b]["text"] for t, b in zip(x1["text"], x1["base_uid"])]
    x1["char_len"] = x1["text"].str.len()
    x1["span_chars"] = x1["injected_instruction"].str.len()
    x1["orig_span_chars"] = x1["original_injected_instruction"].str.len()
    x1["base_char_len"] = [len(en[b]["text"]) for b in x1["base_uid"]]
    return x1, en


def load_question(q, x1):
    x = pd.read_csv(os.path.join(OUT, f"{q}_predictions.csv"))
    b = pd.read_csv(os.path.join(BASE_DIR, f"{q}_predictions.csv"))
    assert (x["label_int"] == 1).all() and len(x) == 450
    assert ((x["p"] >= THRESHOLD).astype(int) == x["pred"]).all()
    en = b[b["set"] == "EN"].copy()
    benign = en[en["label_int"] == 0].sort_values("uid").reset_index(drop=True)
    bases = sorted(x["base_uid"].unique())
    orig = en.set_index("uid").loc[bases].reset_index()
    assert (orig["label_int"] == 1).all() and len(orig) == 150
    x = x.merge(x1[["exp_uid", "identical_to_base", "char_len", "span_chars", "orig_span_chars"]],
                left_on="uid", right_on="exp_uid", how="left")
    meta = x[x["register"] == "imperative_explicit"].set_index("base_uid").loc[bases]
    rows = []
    for _, r in orig.iterrows():
        m = meta.loc[r["uid"]]
        rows.append({"base_uid": r["uid"], "cond": "original", "uid": r["uid"], "p": r["p"], "p_sd": r["p_sd"],
                     "flip": bool(r["flip"]), "source": m["source"], "subset": m["subset"], "doc_type": m["doc_type"],
                     "risk_level": int(m["risk_level"]), "original_register": m["original_register"],
                     "variant_text_source": "base", "span_len_ratio": 1.0, "char_len": int(r["char_len"]),
                     "identical_to_base": True, "span_chars": m["orig_span_chars"]})
    for _, r in x.iterrows():
        rows.append({"base_uid": r["base_uid"], "cond": r["register"], "uid": r["uid"], "p": r["p"], "p_sd": r["p_sd"],
                     "flip": bool(r["flip"]), "source": r["source"], "subset": r["subset"], "doc_type": r["doc_type"],
                     "risk_level": int(r["risk_level"]), "original_register": r["original_register"],
                     "variant_text_source": r["variant_text_source"], "span_len_ratio": float(r["span_len_ratio"]),
                     "char_len": int(r["char_len"]), "identical_to_base": bool(r["identical_to_base"]),
                     "span_chars": int(r["span_chars"])})
    long = pd.DataFrame(rows)
    long["pred"] = long["p"] >= THRESHOLD
    wide_p = long.pivot(index="base_uid", columns="cond", values="p").loc[bases, CONDS]
    return {"long": long, "P": {c: wide_p[c].to_numpy() for c in CONDS}, "bases": bases,
            "meta": meta.reset_index()[["base_uid", "source", "subset", "doc_type", "risk_level", "original_register"]],
            "benign": benign, "en": en, "notinject": b[b["set"] == "NOTINJECT"], "x": x}


# ------------------------------------------------------------------ analysis
def main():
    try:  # the console digest has Korean text and "−"; Windows consoles default to cp949
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    S.setup()
    x1, en_rows = load_data()
    Dq = {q: load_question(q, x1) for q in QS}
    bases = Dq["Q2"]["bases"]
    assert bases == Dq["QL"]["bases"]
    assert list(Dq["Q2"]["benign"]["uid"]) == list(Dq["QL"]["benign"]["uid"])
    meta = Dq["Q2"]["meta"]
    nB, nN = len(bases), len(Dq["Q2"]["benign"])
    rng = np.random.default_rng(SEED)
    BI = rng.integers(0, nB, (N_BOOT, nB))   # base-document resamples (shared by every paired comparison)
    BN = rng.integers(0, nN, (N_BOOT, nN))   # EN benign resamples (AUC only)
    P = {q: Dq[q]["P"] for q in QS}
    D = {q: {c: P[q][c] >= THRESHOLD for c in CONDS} for q in QS}
    BEN_P = {q: Dq[q]["benign"]["p"].to_numpy() for q in QS}
    NI_P = {q: Dq[q]["notinject"]["p"].to_numpy() for q in QS}
    src = meta["source"].to_numpy()
    # X1 rows whose text is byte-identical to the base document (InjecAgent benchmark pairs): re-tests, not rewrites
    IDENT = {c: x1[x1.register == c].set_index("base_uid").loc[bases]["identical_to_base"].to_numpy(bool) for c in REGS}
    analysis = {"script": "experiments/analyze_X1_register.py",
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "bootstrap": {"resamples": N_BOOT, "seed": SEED, "ci": "percentile 2.5/97.5",
                              "unit": "150 base documents resampled with replacement, same indices for every condition "
                                      "and both questions (paired); for AUC the 500 EN benign documents are resampled "
                                      "independently, again with shared indices"},
                "mcnemar": "exact, two-sided binomial test on discordant pairs; Holm correction over the 6 condition "
                           "pairs within each question"}

    # ---- input files and md5
    inputs = {rel(p): md5_file(p) for p in (X1_DATA, EN_DATA,
                                           *(os.path.join(OUT, f"{q}_predictions.csv") for q in QS),
                                           *(os.path.join(BASE_DIR, f"{q}_predictions.csv") for q in QS))}
    analysis["inputs_md5"] = inputs

    # ---- baseline context (EN 1000 + NotInject): FPR does not exist inside X1
    ctx_rows = []
    for q in QS:
        en = Dq[q]["en"]
        m = metrics(en["label_int"].tolist(), en["p"].tolist())
        tp = int(((en.label_int == 1) & (en.p >= THRESHOLD)).sum())
        fp = int(((en.label_int == 0) & (en.p >= THRESHOLD)).sum())
        ni = Dq[q]["notinject"]
        ni_fp = int((ni.p >= THRESHOLD).sum())
        ctx_rows.append({"question": q, "EN_n": m["n"], "EN_TPR": m["TPR"], "EN_TPR_lo": J.wilson(tp, 500)[0],
                         "EN_TPR_hi": J.wilson(tp, 500)[1], "EN_FPR": m["FPR"], "EN_fp": fp,
                         "EN_FPR_lo": J.wilson(fp, 500)[0], "EN_FPR_hi": J.wilson(fp, 500)[1], "EN_AUC": m["AUC"],
                         "EN_mean_p_benign": float(en.loc[en.label_int == 0, "p"].mean()),
                         "NotInject_n": len(ni), "NotInject_fp": ni_fp, "NotInject_FPR": ni_fp / len(ni)})
    ctx = pd.DataFrame(ctx_rows)
    ctx.to_csv(os.path.join(TAB, "baseline_context.csv"), index=False, encoding="utf-8-sig")
    analysis["fpr_note"] = ("X1에는 정상 문서가 없다(450행 모두 label=injection). 그래서 X1 안에서는 FPR이 정의되지 않는다. "
                            "임계값 0.5에서의 오탐 맥락은 같은 질문의 EN 정상 500건 기준선 FPR을 인용한다.")
    analysis["baseline_context"] = {r["question"]: {k: v for k, v in r.items() if k != "question"} for r in ctx_rows}

    # ---- bootstrap replicates per question x condition
    REP = {q: {} for q in QS}
    for q in QS:
        for c in CONDS:
            REP[q][c] = {"TPR": D[q][c][BI].mean(1), "mean_p": P[q][c][BI].mean(1),
                         "AUC": np.array([auc_vs(P[q][c][BI[i]], BEN_P[q][BN[i]]) for i in range(N_BOOT)])}

    # ---- operating points on EN benign: threshold at FPR <= 1% / 5%
    def thr_at_fpr(ben, f):
        for v in np.unique(ben):  # ascending: smallest threshold "p > v" with FPR <= f maximises TPR
            if (ben > v).mean() <= f:
                return float(v)
        return float(ben.max())

    # ---- T1: detection by condition
    t1 = []
    for q in QS:
        ben = BEN_P[q]
        ops = {f: thr_at_fpr(ben, f) for f in (0.01, 0.05)}
        for c in CONDS:
            d = det_block(P[q][c])
            auc = auc_vs(P[q][c], ben)
            row = {"question": q, "condition": c, "condition_ko": C_LONG[c], **d,
                   "mean_p_lo": ci(REP[q][c]["mean_p"])[0], "mean_p_hi": ci(REP[q][c]["mean_p"])[1],
                   "flip_count": int(Dq[q]["long"].query("cond == @c")["flip"].sum()),
                   "p_sd_mean": float(Dq[q]["long"].query("cond == @c")["p_sd"].mean()),
                   "AUC_vs_EN_benign": auc, "AUC_lo": ci(REP[q][c]["AUC"])[0], "AUC_hi": ci(REP[q][c]["AUC"])[1]}
            for f, v in ops.items():
                y = [1] * nB + [0] * nN
                mm = metrics(y, np.concatenate([P[q][c], ben]).tolist(), threshold=v + 1e-9)
                k = int(round(mm["TPR"] * nB))
                tag = f"{int(f * 100)}pct"
                row.update({f"thr_EN_FPR{tag}": v, f"EN_FPR_at_thr{tag}": mm["FPR"], f"TPR_at_EN_FPR{tag}": mm["TPR"],
                            f"TPR_at_EN_FPR{tag}_lo": J.wilson(k, nB)[0], f"TPR_at_EN_FPR{tag}_hi": J.wilson(k, nB)[1],
                            f"NotInject_fp_at_thr{tag}": int((NI_P[q] >= v + 1e-9).sum()), "NotInject_n": len(NI_P[q])})
            if c != "original":
                o = "original"
                a_only, b_only, pm = mcnemar_exact(D[q][o], D[q][c])
                dt_, dm, da = (REP[q][c][k_] - REP[q][o][k_] for k_ in ("TPR", "mean_p", "AUC"))
                row.update({"dTPR_vs_original": d["TPR"] - det_block(P[q][o])["TPR"],
                            "dTPR_lo": ci(dt_)[0], "dTPR_hi": ci(dt_)[1],
                            "original_only": a_only, "variant_only": b_only, "mcnemar_p_vs_original": pm,
                            "dmean_p_vs_original": float(P[q][c].mean() - P[q][o].mean()),
                            "dmean_p_lo": ci(dm)[0], "dmean_p_hi": ci(dm)[1],
                            "dAUC_vs_original": auc - auc_vs(P[q][o], ben), "dAUC_lo": ci(da)[0], "dAUC_hi": ci(da)[1],
                            "verdict_dTPR": verdict(*ci(dt_))})
            t1.append(row)
    t1 = pd.DataFrame(t1)
    t1.to_csv(os.path.join(TAB, "detection_by_condition.csv"), index=False, encoding="utf-8-sig")

    # ---- operating points: 0.5 and the EN-benign FPR <= 1% / 5% thresholds. The lowered thresholds are chosen on the
    # same 500 EN benign documents whose FPR they report (in-sample, optimistic); NotInject (25) is an outside check.
    t1b = []
    for q in QS:
        ben = BEN_P[q]
        for crit, v in (("0.5 (기본)", None), ("EN 정상 오탐 ≤1%", thr_at_fpr(ben, 0.01)),
                        ("EN 정상 오탐 ≤5%", thr_at_fpr(ben, 0.05))):
            cut = THRESHOLD if v is None else v + 1e-9  # metrics() predicts p >= threshold, so "p > v"
            fp_en, fp_ni = int((ben >= cut).sum()), int((NI_P[q] >= cut).sum())
            row = {"question": q, "criterion": crit, "threshold_rule": "p >= 0.5" if v is None else f"p > {v:.4f}",
                   "threshold": THRESHOLD if v is None else v, "chosen_on": "-" if v is None else "EN 정상 500 (in-sample)",
                   "EN_benign_fp": fp_en, "EN_benign_n": nN, "EN_FPR": fp_en / nN,
                   "EN_FPR_lo": J.wilson(fp_en, nN)[0], "EN_FPR_hi": J.wilson(fp_en, nN)[1],
                   "NotInject_fp": fp_ni, "NotInject_n": len(NI_P[q]),
                   "NotInject_FPR_lo": J.wilson(fp_ni, len(NI_P[q]))[0], "NotInject_FPR_hi": J.wilson(fp_ni, len(NI_P[q]))[1]}
            for c in CONDS:
                k = int((P[q][c] >= cut).sum())
                row.update({f"TPR_{c}": k / nB, f"TPR_{c}_lo": J.wilson(k, nB)[0], f"TPR_{c}_hi": J.wilson(k, nB)[1]})
            t1b.append(row)
    t1b = pd.DataFrame(t1b)
    t1b.to_csv(os.path.join(TAB, "operating_points.csv"), index=False, encoding="utf-8-sig")

    # ---- T2: all pairs of conditions, McNemar + paired bootstrap
    t2 = []
    for q in QS:
        rows = []
        for a, b in itertools.combinations(CONDS, 2):
            a_only, b_only, pm = mcnemar_exact(D[q][a], D[q][b])
            both = int((D[q][a] & D[q][b]).sum())
            neither = int((~D[q][a] & ~D[q][b]).sum())
            dt_, dm, da = (REP[q][b][k_] - REP[q][a][k_] for k_ in ("TPR", "mean_p", "AUC"))
            rows.append({"question": q, "cond_a": a, "cond_b": b, "pair_ko": f"{C_SHORT[b]} − {C_SHORT[a]}",
                         "n_pairs": nB, "both_detected": both, "a_only": a_only, "b_only": b_only, "neither": neither,
                         "TPR_a": D[q][a].mean(), "TPR_b": D[q][b].mean(), "dTPR_b_minus_a": D[q][b].mean() - D[q][a].mean(),
                         "dTPR_lo": ci(dt_)[0], "dTPR_hi": ci(dt_)[1], "mcnemar_p": pm,
                         "dmean_p": P[q][b].mean() - P[q][a].mean(), "dmean_p_lo": ci(dm)[0], "dmean_p_hi": ci(dm)[1],
                         "dAUC": auc_vs(P[q][b], BEN_P[q]) - auc_vs(P[q][a], BEN_P[q]),
                         "dAUC_lo": ci(da)[0], "dAUC_hi": ci(da)[1],
                         "verdict_dTPR": verdict(*ci(dt_)), "verdict_dmean_p": verdict(*ci(dm))})
        for r, ph in zip(rows, holm([r["mcnemar_p"] for r in rows])):
            r["mcnemar_p_holm"] = ph
        t2 += rows
    t2 = pd.DataFrame(t2)
    t2.to_csv(os.path.join(TAB, "paired_conditions.csv"), index=False, encoding="utf-8-sig")

    # ---- T3: Q2 vs QL per condition (same documents)
    t3 = []
    for c in CONDS:
        a_only, b_only, pm = mcnemar_exact(D["Q2"][c], D["QL"][c])
        dt_, dm, da = (REP["QL"][c][k_] - REP["Q2"][c][k_] for k_ in ("TPR", "mean_p", "AUC"))
        t3.append({"condition": c, "condition_ko": C_LONG[c], "n": nB,
                   "TPR_Q2": D["Q2"][c].mean(), "TPR_QL": D["QL"][c].mean(),
                   "both_detected": int((D["Q2"][c] & D["QL"][c]).sum()), "Q2_only": a_only, "QL_only": b_only,
                   "neither": int((~D["Q2"][c] & ~D["QL"][c]).sum()), "mcnemar_p": pm,
                   "dTPR_QL_minus_Q2": D["QL"][c].mean() - D["Q2"][c].mean(), "dTPR_lo": ci(dt_)[0], "dTPR_hi": ci(dt_)[1],
                   "mean_p_Q2": P["Q2"][c].mean(), "mean_p_QL": P["QL"][c].mean(),
                   "dmean_p": P["QL"][c].mean() - P["Q2"][c].mean(), "dmean_p_lo": ci(dm)[0], "dmean_p_hi": ci(dm)[1],
                   "AUC_Q2": auc_vs(P["Q2"][c], BEN_P["Q2"]), "AUC_QL": auc_vs(P["QL"][c], BEN_P["QL"]),
                   "dAUC": auc_vs(P["QL"][c], BEN_P["QL"]) - auc_vs(P["Q2"][c], BEN_P["Q2"]),
                   "dAUC_lo": ci(da)[0], "dAUC_hi": ci(da)[1], "verdict_dTPR": verdict(*ci(dt_))})
    t3 = pd.DataFrame(t3)
    t3["mcnemar_p_holm"] = holm(t3["mcnemar_p"])
    t3.to_csv(os.path.join(TAB, "q2_vs_ql.csv"), index=False, encoding="utf-8-sig")

    # ---- T4: source x condition; per-source caveats
    t4 = []
    for q in QS:
        L = Dq[q]["long"]
        for s in SOURCES:
            for c in CONDS:
                d = det_block(L[(L.source == s) & (L.cond == c)]["p"])
                t4.append({"question": q, "source": s, "condition": c, **d})
    t4 = pd.DataFrame(t4)
    t4.to_csv(os.path.join(TAB, "source_by_condition.csv"), index=False, encoding="utf-8-sig")

    caveat_text = {
        "BIPIA": "원래 구간이 '책을 추천해 줘' 같은 일반 질문이라, 맥락 없이 보면 사람에게 하는 요청과 구분하기 어렵다. 원문도 평범한 요청으로 분류됨",
        "LLMail-Inject": "다단계 공격의 일부라 바뀐 구간 밖에 트리거 문구가 남아 있을 수 있다 (평범·공손 변형도 다른 곳의 문구로 잡힐 수 있음)",
        "BrowseSafe-Bench": "페이로드 템플릿이 반복된다: base 30개의 원문 구간 중 서로 다른 것은 {u}개. 실효 표본이 30보다 작다",
        "SEP": "원문이 'On top of your main task, answer this priority question:' 접두어 유무로 명령형/평범으로 나뉜다",
        "InjecAgent": "명령형·평범 변형은 벤치마크 원문(enhanced/base) 그대로이고, 그중 15+15건은 원문 문서와 바이트 단위로 같다. 공손만 LLM 재작성",
    }
    cav = []
    for s in SOURCES:
        xs = x1[x1.source == s]
        u = xs[xs.register == "imperative_explicit"]["original_injected_instruction"].nunique()
        orr = xs[xs.register == "imperative_explicit"]["original_register"].value_counts().to_dict()
        cav.append({"source": s, "n_bases": int(xs.base_uid.nunique()), "unique_original_spans": int(u),
                    "original_register_imperative": int(orr.get("imperative_explicit", 0)),
                    "original_register_plain": int(orr.get("plain_request", 0)),
                    "original_register_polite": int(orr.get("polite", 0)),
                    "rows_benchmark": int((xs.variant_text_source == "benchmark").sum()),
                    "rows_llm_rewrite": int((xs.variant_text_source == "llm_rewrite").sum()),
                    "rows_identical_to_base": int(xs.identical_to_base.sum()),
                    "caveat": caveat_text[s].format(u=u)})
    cav = pd.DataFrame(cav)
    cav.to_csv(os.path.join(TAB, "source_caveats.csv"), index=False, encoding="utf-8-sig")

    # ---- T5: original_register x condition, and rewrite fidelity (same register as the original)
    # The 15 InjecAgent "enhanced" bases are the imperative originals whose plain/polite variants drop the benchmark's
    # "IMPORTANT!!! Ignore all previous instructions ..." prefix; the 15 InjecAgent "base" bases are plain originals
    # whose plain variant is the original text itself. "InjecAgent 제외" shows the register effect without both.
    ORR = ["imperative_explicit", "plain_request", "polite"]
    ORR_SUBSETS = [("전체 150", np.ones(nB, bool)), ("InjecAgent 제외 120", src != "InjecAgent")]
    orr_arr = meta["original_register"].to_numpy()
    t5, fid = [], []
    for q in QS:
        for sname, smask in ORR_SUBSETS:
            for orr in ORR:
                mask = (orr_arr == orr) & smask
                for c in CONDS:
                    row = {"question": q, "subset": sname, "original_register": orr, "condition": c,
                           **det_block(P[q][c][mask])}
                    if c != "original":
                        a_only, b_only, pm = mcnemar_exact(D[q]["original"][mask], D[q][c][mask])
                        lo, hi = paired_boot(D[q]["original"][mask], D[q][c][mask])
                        row.update({"dTPR_vs_original": D[q][c][mask].mean() - D[q]["original"][mask].mean(),
                                    "dTPR_lo": lo, "dTPR_hi": hi, "original_only": a_only, "variant_only": b_only,
                                    "mcnemar_p_vs_original": pm, "verdict_dTPR": verdict(lo, hi)})
                    t5.append(row)
        # rewrite fidelity: original vs the rewrite in the original's own register. Identical texts are re-tests.
        for orr in ORR:
            base_mask = orr_arr == orr
            for sname, smask in (("전체", np.ones(nB, bool)), ("원문과 같은 텍스트 제외", ~IDENT[orr])):
                mask = base_mask & smask
                if sname != "전체" and mask.sum() == base_mask.sum():
                    continue  # nothing identical in this register: the row would repeat "전체"
                a, b = D[q]["original"][mask], D[q][orr][mask]
                a_only, b_only, pm = mcnemar_exact(a, b)
                lo, hi = paired_boot(a, b)
                mlo, mhi = paired_boot(P[q]["original"][mask], P[q][orr][mask])
                fid.append({"question": q, "original_register": orr, "subset": sname, "n": int(mask.sum()),
                            "n_identical_to_original": int((IDENT[orr] & mask).sum()),
                            "identical_sources": ", ".join(f"{k} {v}" for k, v in
                                                           pd.Series(src[IDENT[orr] & mask]).value_counts().items()),
                            "TPR_original": a.mean(), "TPR_same_register_rewrite": b.mean(),
                            "dTPR": b.mean() - a.mean(), "dTPR_lo": lo, "dTPR_hi": hi, "verdict_dTPR": verdict(lo, hi),
                            "original_only": a_only, "rewrite_only": b_only, "mcnemar_p": pm,
                            "mean_p_original": P[q]["original"][mask].mean(), "mean_p_rewrite": P[q][orr][mask].mean(),
                            "dmean_p": P[q][orr][mask].mean() - P[q]["original"][mask].mean(),
                            "dmean_p_lo": mlo, "dmean_p_hi": mhi, "verdict_dmean_p": verdict(mlo, mhi)})
    t5 = pd.DataFrame(t5)
    t5.to_csv(os.path.join(TAB, "original_register_by_condition.csv"), index=False, encoding="utf-8-sig")
    fid = pd.DataFrame(fid)
    fid.to_csv(os.path.join(TAB, "rewrite_fidelity.csv"), index=False, encoding="utf-8-sig")

    # ---- sensitivity: the register effect on subsets of bases (paired, own bootstrap per subset)
    def paired_rows(mask, subset_name, pairs, q):
        idx = np.flatnonzero(mask)
        m = len(idx)
        bi = np.random.default_rng(SEED).integers(0, m, (N_BOOT, m))
        out = []
        for a, b in pairs:
            da, db = D[q][a][idx], D[q][b][idx]
            a_only, b_only, pm = mcnemar_exact(da, db)
            dt_ = db[bi].mean(1) - da[bi].mean(1)
            dm = P[q][b][idx][bi].mean(1) - P[q][a][idx][bi].mean(1)
            out.append({"subset": subset_name, "question": q, "n": m, "cond_a": a, "cond_b": b,
                        "pair_ko": f"{C_SHORT[b]} − {C_SHORT[a]}", "TPR_a": da.mean(), "TPR_b": db.mean(),
                        "dTPR_b_minus_a": db.mean() - da.mean(), "dTPR_lo": ci(dt_)[0], "dTPR_hi": ci(dt_)[1],
                        "a_only": a_only, "b_only": b_only, "mcnemar_p": pm,
                        "dmean_p": float(P[q][b][idx].mean() - P[q][a][idx].mean()),
                        "dmean_p_lo": ci(dm)[0], "dmean_p_hi": ci(dm)[1], "verdict_dTPR": verdict(*ci(dt_))})
        return out

    ratio = {c: x1[x1.register == c].set_index("base_uid").loc[bases]["span_len_ratio"].to_numpy() for c in REGS}
    in_range = np.all([(ratio[c] >= 0.7) & (ratio[c] <= 1.3) for c in REGS], axis=0)
    key_pairs = [("imperative_explicit", "plain_request"), ("imperative_explicit", "polite"),
                 ("original", "plain_request"), ("original", "polite"), ("plain_request", "polite")]
    subsets = [("전체 150", np.ones(nB, bool)),
               ("InjecAgent 제외 (전부 llm_rewrite)", src != "InjecAgent"),
               ("BIPIA 제외", src != "BIPIA"),
               ("LLMail-Inject 제외", src != "LLMail-Inject"),
               ("BrowseSafe-Bench 제외", src != "BrowseSafe-Bench"),
               ("SEP 제외", src != "SEP"),
               ("세 변형 모두 길이 비 0.7–1.3", in_range)]
    sens = []
    for q in QS:
        for name, mask in subsets:
            sens += paired_rows(mask, name, key_pairs, q)
        # length-controlled: the imperative span is not longer than the variant it is compared with
        for c in ("plain_request", "polite"):
            sens += paired_rows(ratio["imperative_explicit"] <= ratio[c], f"명령형 구간 ≤ {C_SHORT[c]} 구간",
                                [("imperative_explicit", c)], q)
    sens = pd.DataFrame(sens)
    sens.to_csv(os.path.join(TAB, "sensitivity_paired.csv"), index=False, encoding="utf-8-sig")

    # ---- variant_text_source view (benchmark only exists in InjecAgent imperative/plain)
    t6 = []
    for q in QS:
        L = Dq[q]["long"]
        for slice_name, sel in (("전체 150", L.source.notna()), ("InjecAgent 제외 120 (전부 llm_rewrite)", L.source != "InjecAgent"),
                                ("InjecAgent 30", L.source == "InjecAgent")):
            for c in CONDS:
                part = L[sel & (L.cond == c)]
                for vts, g in part.groupby("variant_text_source"):
                    t6.append({"question": q, "slice": slice_name, "condition": c, "variant_text_source": vts,
                               **det_block(g["p"]), "n_identical_to_base": int(g["identical_to_base"].sum())
                               if c != "original" else None})
    t6 = pd.DataFrame(t6)
    t6.to_csv(os.path.join(TAB, "variant_text_source.csv"), index=False, encoding="utf-8-sig")

    # ---- span length sanity check
    bins = [0, 0.8, 1.2, 10]
    bin_lab = ["< 0.8", "0.8–1.2", "> 1.2"]
    t8a, t8b = [], []
    for q in QS:
        L = Dq[q]["long"]
        for c in REGS:
            g = L[L.cond == c].copy()
            g["ratio_bin"] = pd.cut(g["span_len_ratio"], bins, labels=bin_lab, right=False)
            for bl in bin_lab:
                gb = g[g.ratio_bin == bl]
                comp = gb["source"].value_counts()
                t8a.append({"question": q, "condition": c, "ratio_bin": bl, **det_block(gb["p"]),
                            "sources": ", ".join(f"{k} {v}" for k, v in comp.items())})
            r1 = spearmanr(g["span_len_ratio"], g["p"])
            r2 = spearmanr(g["char_len"], g["p"])
            t8b.append({"question": q, "condition": c, "n": len(g),
                        "span_len_ratio_median": g["span_len_ratio"].median(),
                        "span_len_ratio_q1": g["span_len_ratio"].quantile(0.25),
                        "span_len_ratio_q3": g["span_len_ratio"].quantile(0.75),
                        "share_ratio_within_0.7_1.3": ((g.span_len_ratio >= 0.7) & (g.span_len_ratio <= 1.3)).mean(),
                        "spearman_ratio_vs_p": r1.statistic, "spearman_ratio_vs_p_pvalue": r1.pvalue,
                        "char_len_median": g["char_len"].median(),
                        "spearman_char_len_vs_p": r2.statistic, "spearman_char_len_vs_p_pvalue": r2.pvalue})
        # within-base: does the plain/polite drop relative to imperative scale with how much shorter the span became?
        for c in ("plain_request", "polite"):
            dp = P[q][c] - P[q]["imperative_explicit"]
            dr = ratio[c] - ratio["imperative_explicit"]
            r = spearmanr(dr, dp)
            t8b.append({"question": q, "condition": f"{c} − imperative_explicit (base 안 차이)", "n": nB,
                        "span_len_ratio_median": float(np.median(dr)), "spearman_ratio_vs_p": r.statistic,
                        "spearman_ratio_vs_p_pvalue": r.pvalue})
    t8a, t8b = pd.DataFrame(t8a), pd.DataFrame(t8b)
    t8a.to_csv(os.path.join(TAB, "span_length_bins.csv"), index=False, encoding="utf-8-sig")
    t8b.to_csv(os.path.join(TAB, "span_length_corr.csv"), index=False, encoding="utf-8-sig")
    # whole-document length: is the pooled correlation just a between-source difference?
    t8c = []
    for q in QS:
        L = Dq[q]["long"]
        for c in CONDS:
            for s in SOURCES:
                g = L[(L.cond == c) & (L.source == s)]
                r = spearmanr(g["char_len"], g["p"]) if g["p"].nunique() > 1 else None
                t8c.append({"question": q, "condition": c, "source": s, "n": len(g),
                            "char_len_median": g["char_len"].median(), "TPR": float(g["pred"].mean()),
                            "spearman_char_len_vs_p": r.statistic if r is not None else None,
                            "spearman_pvalue": r.pvalue if r is not None else None})
    t8c = pd.DataFrame(t8c)
    t8c.to_csv(os.path.join(TAB, "doc_length_by_source.csv"), index=False, encoding="utf-8-sig")

    # ---- per-base detection patterns over the three registers
    PAT = [((1, 1, 1), "셋 다 탐지"), ((1, 1, 0), "명령형+평범만"), ((1, 0, 1), "명령형+공손만"), ((1, 0, 0), "명령형만 탐지"),
           ((0, 1, 1), "평범+공손만"), ((0, 1, 0), "평범만"), ((0, 0, 1), "공손만"), ((0, 0, 0), "셋 다 놓침")]
    t9 = []
    for q in QS:
        key = list(zip(*(D[q][c].astype(int) for c in REGS)))
        for pat, name in PAT:
            sel = np.array([k == pat for k in key])
            t9.append({"question": q, "pattern": name, "imperative": pat[0], "plain": pat[1], "polite": pat[2],
                       "n": int(sel.sum()), "share": float(sel.mean()),
                       "of_which_original_detected": int((sel & D[q]["original"]).sum())})
    t9 = pd.DataFrame(t9)
    t9.to_csv(os.path.join(TAB, "base_patterns.csv"), index=False, encoding="utf-8-sig")

    # ---- risk level / doc type breakdown
    t10 = []
    for q in QS:
        L = Dq[q]["long"]
        for fac in ("risk_level", "doc_type"):
            for lv in sorted(L[fac].unique(), key=str):
                for c in CONDS:
                    g = L[(L[fac] == lv) & (L.cond == c)]
                    t10.append({"question": q, "factor": fac, "level": lv, "condition": c, **det_block(g["p"]),
                                "sources": ", ".join(f"{k} {v}" for k, v in g["source"].value_counts().items())})
    t10 = pd.DataFrame(t10)
    t10.to_csv(os.path.join(TAB, "risk_doctype_by_condition.csv"), index=False, encoding="utf-8-sig")

    # ---- test-retest: X1 rows whose text is byte-identical to the base document (InjecAgent benchmark pairs)
    rt = []
    for q in QS:
        L = Dq[q]["long"]
        ident = L[(L.cond != "original") & L.identical_to_base]
        orig = L[L.cond == "original"].set_index("base_uid")
        for _, r in ident.iterrows():
            o = orig.loc[r["base_uid"]]
            rt.append({"question": q, "uid": r["uid"], "base_uid": r["base_uid"], "register": r["cond"],
                       "p_X1": r["p"], "p_01_baseline": o["p"], "abs_diff": abs(r["p"] - o["p"]),
                       "same_decision": bool((r["p"] >= THRESHOLD) == (o["p"] >= THRESHOLD))})
    rt = pd.DataFrame(rt)
    rt.to_csv(os.path.join(TAB, "retest_identical_texts.csv"), index=False, encoding="utf-8-sig")

    # ---- per-base wide table (spans + p for every condition and question) and missed examples
    spans = x1.pivot(index="base_uid", columns="register", values="injected_instruction").loc[bases]
    orig_span = x1.drop_duplicates("base_uid").set_index("base_uid").loc[bases]["original_injected_instruction"]
    pb = meta.copy()
    pb["span_original"] = orig_span.to_numpy()
    for c in REGS:
        pb[f"span_{c}"] = spans[c].to_numpy()
    for q in QS:
        for c in CONDS:
            pb[f"p_{q}_{c}"] = P[q][c]
    pb.to_csv(os.path.join(TAB, "per_base.csv"), index=False, encoding="utf-8-sig")
    miss = np.all([D[q]["imperative_explicit"] & ~D[q]["plain_request"] & ~D[q]["polite"] for q in QS], axis=0)
    ex = pb[miss].copy()
    ex["min_p_plain_polite"] = ex[[f"p_{q}_{c}" for q in QS for c in ("plain_request", "polite")]].max(axis=1)
    ex = ex.sort_values(["source", "min_p_plain_polite"]).groupby("source").head(2).drop(columns="min_p_plain_polite")
    ex.to_csv(os.path.join(TAB, "examples_missed.csv"), index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------ figures
    figs = make_figures(locals())

    # ------------------------------------------------------------------ summary.json["analysis"]
    def rec(df, keys):
        return [{k: r[k] for k in keys if k in r} for r in df.to_dict("records")]

    analysis["conditions"] = {q: {r["condition"]: {k: v for k, v in r.items() if k not in ("question", "condition")}
                                  for r in t1[t1.question == q].to_dict("records")} for q in QS}
    analysis["paired_conditions"] = {q: rec(t2[t2.question == q], ["cond_a", "cond_b", "both_detected", "a_only", "b_only",
                                                                    "neither", "dTPR_b_minus_a", "dTPR_lo", "dTPR_hi",
                                                                    "mcnemar_p", "mcnemar_p_holm", "dmean_p", "dmean_p_lo",
                                                                    "dmean_p_hi", "dAUC", "dAUC_lo", "dAUC_hi",
                                                                    "verdict_dTPR"]) for q in QS}
    analysis["q2_vs_ql"] = {r["condition"]: {k: v for k, v in r.items() if k not in ("condition", "condition_ko")}
                            for r in t3.to_dict("records")}
    analysis["sensitivity"] = rec(sens, ["subset", "question", "n", "cond_a", "cond_b", "dTPR_b_minus_a", "dTPR_lo",
                                         "dTPR_hi", "mcnemar_p", "verdict_dTPR"])
    analysis["rewrite_fidelity"] = fid.to_dict("records")
    analysis["operating_points"] = {
        "note": "EN 정상 오탐 ≤1%/≤5% 임계값은 같은 EN 정상 500건에서 골랐다(in-sample, FPR이 낙관적). NotInject 25건은 바깥 확인용.",
        "rows": t1b.to_dict("records")}
    analysis["original_register"] = rec(t5, ["question", "subset", "original_register", "condition", "n", "tp", "TPR",
                                             "TPR_lo", "TPR_hi", "dTPR_vs_original", "dTPR_lo", "dTPR_hi",
                                             "original_only", "variant_only", "mcnemar_p_vs_original"])
    analysis["risk_level"] = rec(t10[t10.factor == "risk_level"], ["question", "level", "condition", "n", "tp", "TPR",
                                                                    "TPR_lo", "TPR_hi", "sources"])
    en_mix = Dq["Q2"]["en"].query("label_int == 1")["source"].value_counts()
    analysis["sampling"] = {
        "x1_bases_by_source": meta["source"].value_counts().to_dict(),
        "en_injections_by_source": en_mix.to_dict(),
        "note": ("X1 base 150은 EN 주입 문서에서 출처당 30개씩 층화 추출했고 AgentDojo는 뺐다(데이터 README: seed 42). "
                 "EN 주입 500과 출처 구성이 달라 EN 500 TPR과 직접 비교하지 않는다. 비교 기준은 같은 150개의 원문이다.")}
    analysis["span_length"] = t8b.to_dict("records")
    analysis["base_patterns"] = {q: {r["pattern"]: r["n"] for r in t9[t9.question == q].to_dict("records")} for q in QS}
    analysis["retest_identical_texts"] = {q: {"n": int((rt.question == q).sum()),
                                              "mean_abs_diff": float(rt[rt.question == q].abs_diff.mean()),
                                              "max_abs_diff": float(rt[rt.question == q].abs_diff.max()),
                                              "same_decision": int(rt[rt.question == q].same_decision.sum())} for q in QS}
    analysis["source_caveats"] = cav.to_dict("records")
    analysis["tables"] = sorted(rel(os.path.join(TAB, f)) for f in os.listdir(TAB) if f.endswith(".csv"))
    analysis["figures"] = [rel(p) for p in figs]
    sp = os.path.join(OUT, "summary.json")
    with open(sp, encoding="utf-8") as f:
        summary = json.load(f)
    summary["analysis"] = clean(analysis)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    # ------------------------------------------------------------------ console digest (numbers for the README)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 40)
    print(ctx.round(4).to_string())
    print(t1[["question", "condition", "tp", "n", "TPR", "TPR_lo", "TPR_hi", "mean_p", "mean_p_lo", "mean_p_hi",
              "AUC_vs_EN_benign", "AUC_lo", "AUC_hi", "TPR_at_EN_FPR1pct", "thr_EN_FPR1pct", "TPR_at_EN_FPR5pct",
              "flip_count"]].round(3).to_string())
    print(t1[["question", "condition", "dTPR_vs_original", "dTPR_lo", "dTPR_hi", "original_only", "variant_only",
              "mcnemar_p_vs_original", "dmean_p_vs_original", "dmean_p_lo", "dmean_p_hi", "dAUC_vs_original", "dAUC_lo",
              "dAUC_hi"]].round(3).to_string())
    print(t2[["question", "pair_ko", "a_only", "b_only", "dTPR_b_minus_a", "dTPR_lo", "dTPR_hi", "mcnemar_p",
              "mcnemar_p_holm", "dmean_p", "dmean_p_lo", "dmean_p_hi", "dAUC", "dAUC_lo", "dAUC_hi"]].round(4).to_string())
    print(t3.round(4).to_string())
    print(t4.pivot_table(index=["question", "source"], columns="condition", values="TPR")[CONDS].round(2).to_string())
    print(cav.drop(columns="caveat").to_string())
    print(t5.pivot_table(index=["question", "subset", "original_register"], columns="condition",
                         values="TPR")[CONDS].round(3).to_string())
    print(t5[t5.condition != "original"][["question", "subset", "original_register", "condition", "n", "TPR",
                                          "dTPR_vs_original", "dTPR_lo", "dTPR_hi", "original_only", "variant_only",
                                          "mcnemar_p_vs_original"]].round(3).to_string())
    print(fid.drop(columns=["mean_p_original", "mean_p_rewrite"]).round(3).to_string())
    print(t1b.round(4).to_string())
    print(t1[["question", "condition", "NotInject_fp_at_thr1pct", "NotInject_fp_at_thr5pct"]].to_string())
    print(sens[["subset", "question", "n", "pair_ko", "TPR_a", "TPR_b", "dTPR_b_minus_a", "dTPR_lo", "dTPR_hi",
                "mcnemar_p"]].round(3).to_string())
    print(t6.round(3).to_string())
    print(t8a.round(3).to_string())
    print(t8b.round(3).to_string())
    print(t8c[t8c.condition.isin(["plain_request", "polite"])].round(3).to_string())
    print(t9.to_string())
    print(rt.groupby("question").agg(n=("uid", "size"), mean_abs=("abs_diff", "mean"), max_abs=("abs_diff", "max"),
                                     same=("same_decision", "sum")).to_string())
    print(t10.pivot_table(index=["question", "factor", "level"], columns="condition", values=["TPR", "n"]).round(2).to_string())
    print(t10[t10.factor == "risk_level"][["question", "level", "condition", "n", "tp", "TPR", "TPR_lo", "TPR_hi",
                                            "sources"]].round(3).to_string())
    print(ex[["base_uid", "source", "span_plain_request"]].to_string())
    print("\n".join(figs))


# ------------------------------------------------------------------ figures
def dodge(q, w=0.18):
    return -w if q == "Q2" else w


def err(v, lo, hi, s=1.0):
    """Error-bar lengths, clipped at 0 (Wilson bounds at 0/1 and percentile CIs can sit a hair inside the estimate)."""
    return [[max(0.0, (v - lo) * s)], [max(0.0, (hi - v) * s)]]


def errbar(ax, x, y, lo, hi, color, **kw):
    ax.errorbar([x], [y], yerr=err(y, lo, hi), fmt="o", color=color, ecolor=color, elinewidth=1.6, capsize=3,
                markersize=6.5, **kw)


def q_legend(ax, loc="lower left", extra=(), **kw):
    h = [Line2D([], [], marker="o", color=Q_COLORS[q], lw=0, markersize=7, label=Q_NAME[q]) for q in QS] + list(extra)
    ax.legend(handles=h, loc=loc, **kw)


def make_figures(V):
    t1, t2, t3, t4, t5, t6, t9, sens, rt = (V[k] for k in ("t1", "t2", "t3", "t4", "t5", "t6", "t9", "sens", "rt"))
    P, D, BEN_P, Dq, ctx, ratio = V["P"], V["D"], V["BEN_P"], V["Dq"], V["ctx"], V["ratio"]
    nB = V["nB"]
    out = []
    xs = np.arange(len(CONDS))

    # f01 detection by condition
    fig, ax = plt.subplots(figsize=S.SIZE_WIDE)
    for q in QS:
        sub = t1[t1.question == q].set_index("condition").loc[CONDS]
        bars = ax.bar(xs + dodge(q), sub["TPR"], width=0.34, color=Q_COLORS[q], alpha=0.9)
        S.bar_gap(bars)
        ax.errorbar(xs + dodge(q), sub["TPR"], yerr=[(sub["TPR"] - sub["TPR_lo"]).clip(lower=0), (sub["TPR_hi"] - sub["TPR"]).clip(lower=0)], fmt="none",
                    ecolor=S.INK, elinewidth=1.1, capsize=3)
        for xi, (_, r) in zip(xs, sub.iterrows()):
            ax.text(xi + dodge(q), r["TPR_hi"] + 0.02, f"{r['TPR']:.0%}\n{r['tp']}/{r['n']}", ha="center", va="bottom",
                    fontsize=8.5, color=S.INK_2, bbox=dict(facecolor=S.SURFACE, edgecolor="none", pad=0.6))
        en_tpr = ctx.set_index("question").loc[q, "EN_TPR"]
        ax.axhline(en_tpr, color=Q_COLORS[q], ls=(0, (4, 3)), lw=1.1, alpha=0.8)
    ax.set_xticks(xs, [f"{C_LONG[c]}\n(n={nB})" for c in CONDS])
    ax.set_ylim(0, 1.22)
    ax.set_yticks(np.arange(0, 1.01, 0.2), [f"{v:.0%}" for v in np.arange(0, 1.01, 0.2)])
    ax.set_ylabel("탐지율 (TPR, 임계값 0.5)")
    q_legend(ax, loc="upper right", ncols=3, extra=[Line2D([], [], color=S.MUTED, ls=(0, (4, 3)), lw=1.1,
                                                         label="참고: EN 주입 500 TPR (출처 구성 다름)")])
    t = t1.set_index(["question", "condition"])
    S.title(fig, "노골적 명령형은 150건을 모두 잡지만, 같은 의도를 평범·공손하게 쓰면 절반 정도만 잡는다",
            f"X1: base 인젝션 150개(출처당 30, AgentDojo 제외) × 표현 3가지 + 원문. 막대 = 탐지율, 오차 막대 = Wilson 95% CI. "
            f"평범한 요청 {t.loc[('Q2', 'plain_request'), 'TPR']:.0%}/{t.loc[('QL', 'plain_request'), 'TPR']:.0%}, "
            f"공손한 부탁 {t.loc[('Q2', 'polite'), 'TPR']:.0%}/{t.loc[('QL', 'polite'), 'TPR']:.0%} (Q2/QL).\n"
            "비교 기준은 같은 150개의 원문 막대다. 점선(EN 주입 500 전체)은 출처 구성이 달라 참고용이다.")
    out.append(S.save(fig, "f01_detection_by_condition", out_dir=FIG))

    # f02 p distribution vs EN benign (colour = label)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4), sharey=True)
    rng = np.random.default_rng(1)
    cats = CONDS + ["benign"]
    for ax, q in zip(axes, QS):
        for i, c in enumerate(cats):
            v = BEN_P[q] if c == "benign" else P[q][c]
            col = BEN if c == "benign" else INJ
            ax.scatter(i + rng.uniform(-0.28, 0.28, len(v)), v, s=7, color=col, alpha=0.35, lw=0)
            bp = ax.boxplot([v], positions=[i], widths=0.5, showfliers=False, patch_artist=True)
            for el in ("boxes", "whiskers", "caps", "medians"):
                for art in bp[el]:
                    art.set(color=S.INK, linewidth=1.1)
            for art in bp["boxes"]:
                art.set_facecolor("none")
            k = int((v >= THRESHOLD).sum())
            ax.text(i, 1.04, f"{'오탐' if c == 'benign' else '탐지'} {k}/{len(v)}", ha="center", fontsize=8.5,
                    color=S.INK_2)
        ax.axhline(THRESHOLD, color=S.INK_2, lw=0.9, ls="--")
        ax.text(len(cats) - 0.5, THRESHOLD + 0.015, "임계값 0.5", ha="right", va="bottom", fontsize=8, color=S.INK_2)
        ax.set_xticks(range(len(cats)), [C_SHORT[c] for c in CONDS] + ["EN 정상\n(기준선)"])
        ax.set_title(Q_NAME[q], color=Q_COLORS[q])
        ax.set_ylim(-0.03, 1.1)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("Jev p (3회 평균)")
    axes[1].legend(handles=[Patch(color=INJ, label="인젝션 (조건마다 150)"), Patch(color=BEN, label="정상 (EN 500)")],
                   loc="lower right", bbox_to_anchor=(1.0, 1.0), ncols=2)
    S.title(fig, "평범·공손 변형의 p는 0~1에 넓게 퍼져 절반 가까이 0.5 아래로 떨어진다. 그래도 정상 문서보다는 대체로 높다",
            "점 = 문서 1건(p는 3회 호출 평균), 상자 = 사분위. 색은 라벨만 나타낸다(인젝션 / 정상).")
    out.append(S.save(fig, "f02_p_distribution", out_dir=FIG))

    # f03 paired scatter: original p vs register p
    fig, axes = plt.subplots(2, 3, figsize=(11, 7.6), sharex=True, sharey=True)
    for i, q in enumerate(QS):
        for j, c in enumerate(REGS):
            ax = axes[i, j]
            ax.plot([0, 1], [0, 1], color=S.AXIS, lw=0.9)
            ax.axhline(THRESHOLD, color=S.GRID, lw=0.9)
            ax.axvline(THRESHOLD, color=S.GRID, lw=0.9)
            ax.scatter(P[q]["original"], P[q][c], s=13, color=Q_COLORS[q], alpha=0.55, lw=0)
            up = int((~D[q]["original"] & D[q][c]).sum())
            down = int((D[q]["original"] & ~D[q][c]).sum())
            box = dict(facecolor=S.SURFACE, edgecolor=S.GRID, alpha=0.9, pad=2.5)
            ax.text(0.03, 0.62, f"원문 놓침 → 탐지 {up}", ha="left", va="center", fontsize=8.5, color=S.INK_2,
                    transform=ax.transAxes, bbox=box)
            ax.text(0.90, 0.30, f"원문 탐지 → 놓침 {down}", ha="right", va="center", fontsize=8.5, color=S.INK_2,
                    transform=ax.transAxes, bbox=box)
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(-0.02, 1.02)
            if i == 0:
                ax.set_title(C_LONG[c], fontsize=11)
            if j == 0:
                ax.set_ylabel(f"{q}: 변형 문서 p")
            if i == 1:
                ax.set_xlabel("원문 문서 p")
    S.title(fig, "명령형으로 바꾸면 원문이 놓친 문서까지 모두 잡히고, 평범·공손 변형은 원문과 비슷한 자리에 머문다",
            "같은 base 문서 150개를 짝지어 비교. 점 = base 1개, 대각선 = 변화 없음, 회색 선 = 임계값 0.5. 위 줄 Q2, 아래 줄 QL.")
    out.append(S.save(fig, "f03_paired_scatter_vs_original", out_dir=FIG))

    # f04 paired differences (6 pairs) with McNemar
    pairs = list(itertools.combinations(CONDS, 2))
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.6), sharey=True)
    ys = np.arange(len(pairs))[::-1]
    for ax, (val, lo, hi, xlabel) in zip(axes, (("dTPR_b_minus_a", "dTPR_lo", "dTPR_hi", "탐지율 차이 (%p)"),
                                                ("dmean_p", "dmean_p_lo", "dmean_p_hi", "평균 p 차이"))):
        for q in QS:
            sub = t2[t2.question == q].set_index(["cond_a", "cond_b"]).loc[pairs]
            scale = 100 if val.startswith("dTPR") else 1
            for y, (_, r) in zip(ys, sub.iterrows()):
                yy = y + (0.15 if q == "Q2" else -0.15)
                ax.errorbar([r[val] * scale], [yy], xerr=err(r[val], r[lo], r[hi], scale),
                            fmt="o", color=Q_COLORS[q], elinewidth=1.6, capsize=2.5, markersize=6)
                if val.startswith("dTPR"):
                    ax.text(r[hi] * scale + 2, yy, fmt_p(r['mcnemar_p_holm']), va="center", fontsize=7.5,
                            color=Q_COLORS[q])
        ax.axvline(0, color=S.INK_2, lw=0.9)
        ax.set_xlabel(xlabel)
        ax.grid(axis="y", visible=False)
    axes[0].set_xlim(-75, 85)
    axes[1].set_xlim(-0.65, 0.65)
    labels = [f"{C_SHORT[b]} − {C_SHORT[a]}" for a, b in pairs]
    axes[0].set_yticks(ys, labels)
    q_legend(axes[1], loc="lower right")
    S.title(fig, "큰 차이는 모두 명령형에서 나온다. 평범 vs 공손은 차이 없음, 원문 대비 감소는 Q2에서만 5~7%p",
            "같은 150개 base의 짝 비교. 점 = 차이(뒤 − 앞), 막대 = 짝 부트스트랩 95% CI(1,000회). "
            "p = 정확 McNemar(Holm 보정, 질문별 6쌍).")
    out.append(S.save(fig, "f04_paired_differences", out_dir=FIG))

    # f05 threshold-free: AUC vs EN benign, and TPR at the thresholds where EN-benign FPR <= 1% / <= 5%
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.2))
    thr = t1.drop_duplicates("question").set_index("question")
    for q in QS:
        sub = t1[t1.question == q].set_index("condition").loc[CONDS]
        for xi, (_, r) in zip(xs, sub.iterrows()):
            xx = xi + dodge(q, 0.15)
            errbar(axes[0], xx, r["AUC_vs_EN_benign"], r["AUC_lo"], r["AUC_hi"], Q_COLORS[q])
            side = (-0.07, "right") if q == "Q2" else (0.07, "left")
            axes[0].text(xx + side[0], r["AUC_vs_EN_benign"], f"{r['AUC_vs_EN_benign']:.3f}", ha=side[1], va="center",
                         fontsize=7.5, color=Q_COLORS[q])
            for ax, tag in zip(axes[1:], ("1pct", "5pct")):
                v, lo, hi = r[f"TPR_at_EN_FPR{tag}"], r[f"TPR_at_EN_FPR{tag}_lo"], r[f"TPR_at_EN_FPR{tag}_hi"]
                errbar(ax, xx, v, lo, hi, Q_COLORS[q])
                ax.text(xx + side[0], v, f"{v:.0%}", ha=side[1], va="center", fontsize=7.5, color=Q_COLORS[q])
    for ax in axes:
        ax.set_xticks(xs, [C_SHORT[c] for c in CONDS], fontsize=8.5)
        ax.grid(axis="x", visible=False)
        ax.set_xlim(-0.6, 3.6)
    axes[0].set_ylim(0.9, 1.004)
    axes[0].set_ylabel("AUC (변형 150 vs EN 정상 500)")
    axes[0].set_title("AUC: 정상 문서보다 높게 매기는가", fontsize=11)
    for ax, tag, f in zip(axes[1:], ("1pct", "5pct"), ("1%", "5%")):
        ax.set_ylim(0, 1.05)
        ax.set_yticks(np.arange(0, 1.01, 0.2), [f"{v:.0%}" for v in np.arange(0, 1.01, 0.2)])
        ax.set_title(f"EN 정상 오탐 ≤{f} 임계값에서 탐지율", fontsize=11)
        ax.text(0.98, 0.03, "\n".join(
            f"{q}: p > {thr.loc[q, 'thr_EN_FPR' + tag]:.3f}, EN 정상 오탐 {thr.loc[q, 'EN_FPR_at_thr' + tag]:.1%}, "
            f"NotInject 오탐 {int(thr.loc[q, 'NotInject_fp_at_thr' + tag])}/{int(thr.loc[q, 'NotInject_n'])}" for q in QS),
            transform=ax.transAxes, ha="right", va="bottom", fontsize=7.5, color=S.INK_2,
            bbox=dict(facecolor=S.SURFACE, edgecolor="none", pad=1.5))
    axes[1].set_ylabel("탐지율")
    q_legend(axes[0], loc="lower left")
    tq = t1.set_index(["question", "condition"])
    q2_5 = [tq.loc[("Q2", c), "TPR_at_EN_FPR5pct"] for c in ("plain_request", "polite")]
    ql_5 = [tq.loc[("QL", c), "TPR_at_EN_FPR5pct"] for c in ("plain_request", "polite")]
    S.title(fig, f"임계값을 낮추면 QL은 평범·공손의 {min(ql_5):.0%}를 잡지만, Q2는 EN 오탐 5% 임계값에서도 "
                 f"{min(q2_5):.0%}~{max(q2_5):.0%}만 잡는다",
            "왼쪽: AUC(변형 150 vs EN 정상 500)와 부트스트랩 95% CI(1,000회). 가운데·오른쪽: EN 정상 500건의 오탐이 1% / 5% 이하가 "
            "되는 가장 낮은 임계값에서의 탐지율(Wilson 95% CI).\n임계값은 같은 EN 정상 500건에서 골랐다(in-sample이라 오탐이 "
            "낙관적). NotInject 25건은 바깥 확인용. Q2는 0.5에서 이미 오탐 2.2%라 1% 임계값이 0.5보다 높다.")
    out.append(S.save(fig, "f05_threshold_free", out_dir=FIG))

    # f06 source x condition heatmap per question (hue = question, lightness = TPR)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.4))
    for ax, q in zip(axes, QS):
        m = t4[t4.question == q].pivot(index="source", columns="condition", values="TPR").loc[SOURCES, CONDS]
        k = t4[t4.question == q].pivot(index="source", columns="condition", values="tp").loc[SOURCES, CONDS]
        cmap = LinearSegmentedColormap.from_list(q, ["#f6f6f3", Q_COLORS[q], "#14263f" if q == "Q2" else "#5a2208"])
        ax.imshow(m.to_numpy(), cmap=cmap, vmin=0, vmax=1, aspect="auto")
        for i in range(len(SOURCES)):
            for j in range(len(CONDS)):
                v = m.iloc[i, j]
                ax.text(j, i, f"{v:.0%}\n{int(k.iloc[i, j])}/30", ha="center", va="center", fontsize=9,
                        color="white" if v >= 0.45 else S.INK)
        ax.set_xticks(range(len(CONDS)), [C_SHORT[c] for c in CONDS])
        ax.set_yticks(range(len(SOURCES)), SOURCES)
        ax.grid(False)
        ax.tick_params(length=0)
        for sp in ax.spines.values():
            sp.set_visible(False)
        ax.set_title(Q_NAME[q], color=Q_COLORS[q])
    S.title(fig, "트리거 문구가 빠지면 SEP는 0%, BIPIA는 23~57%로 떨어진다. BrowseSafe는 어조와 무관하게 93% 이상",
            "출처 × 조건별 탐지율 (각 칸 n=30). 색이 진할수록 탐지율이 높다(색상 = 질문). 출처별 주의점은 tables/source_caveats.csv.")
    out.append(S.save(fig, "f06_source_heatmap", out_dir=FIG))

    # f07 original register facets (rows: all bases / without InjecAgent; columns: original register)
    orr_list = ["imperative_explicit", "plain_request"]
    sub_list = ["전체 150", "InjecAgent 제외 120"]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 8.2), sharey=True, sharex=True)
    for i, sname in enumerate(sub_list):
        for j, orr in enumerate(orr_list):
            ax = axes[i, j]
            notes = []
            for q in QS:
                sub = t5[(t5.question == q) & (t5.subset == sname) & (t5.original_register == orr)].set_index(
                    "condition").loc[CONDS]
                for xi, (_, r) in zip(xs, sub.iterrows()):
                    errbar(ax, xi + dodge(q, 0.13), r["TPR"], r["TPR_lo"], r["TPR_hi"], Q_COLORS[q])
                notes.append(f"{q}: 평범 {int(sub.loc['plain_request', 'original_only'])}/"
                             f"{int(sub.loc['plain_request', 'variant_only'])}, 공손 "
                             f"{int(sub.loc['polite', 'original_only'])}/{int(sub.loc['polite', 'variant_only'])}")
            n = int(t5[(t5.subset == sname) & (t5.original_register == orr)].iloc[0]["n"])
            ax.text(0.98, 0.03, "원문만 / 변형만 탐지한 base\n" + "\n".join(notes), transform=ax.transAxes,
                    ha="right", va="bottom", fontsize=8, color=S.INK_2,
                    bbox=dict(facecolor=S.SURFACE, edgecolor=S.GRID, pad=2.5))
            ax.set_title(f"원문 어조 {C_SHORT[orr]} · {'전체' if i == 0 else 'InjecAgent 제외'} (base {n}개)", fontsize=11)
            ax.set_xticks(xs, [C_SHORT[c] for c in CONDS], fontsize=9)
            ax.set_ylim(0, 1.05)
            ax.grid(axis="x", visible=False)
            ax.set_xlim(-0.5, 3.5)
        axes[i, 0].set_yticks(np.arange(0, 1.01, 0.2), [f"{v:.0%}" for v in np.arange(0, 1.01, 0.2)])
        axes[i, 0].set_ylabel("탐지율")
    q_legend(axes[0, 0], loc="lower left")
    S.title(fig, "원문 명령형 base에서 평범·공손 변형이 원문보다 덜 잡히는 것은 InjecAgent 15개(enhanced → base)에서만 나온다",
            "base를 원문 어조(작성자 판단)로 나눈 탐지율. 점 = 추정값, 막대 = Wilson 95% CI. 위: 전체, 아래: InjecAgent 제외.\n"
            "InjecAgent는 원문 명령형 15개가 'IMPORTANT!!! Ignore all previous instructions' 접두어를 가진 enhanced이고, "
            "원문 평범 15개는 평범 변형이 원문과 같은 텍스트다.\n공손 원문 4개(LLMail)는 표(original_register_by_condition.csv)에만 둔다.")
    out.append(S.save(fig, "f07_original_register", out_dir=FIG))

    # f08 variant_text_source slices
    slices = ["전체 150", "InjecAgent 제외 120 (전부 llm_rewrite)", "InjecAgent 30"]
    fig, axes = plt.subplots(1, 3, figsize=(12, 5), sharey=True)
    for ax, sl in zip(axes, slices):
        for q in QS:
            sub = t6[(t6.question == q) & (t6.slice == sl)]
            for xi, c in enumerate(CONDS):  # pool benchmark + llm_rewrite rows of a condition inside the slice
                g = sub[sub.condition == c]
                k, n = int(g["tp"].sum()), int(g["n"].sum())
                lo, hi = J.wilson(k, n)
                errbar(ax, xi + dodge(q, 0.13), k / n, lo, hi, Q_COLORS[q])
        ax.set_title(sl, fontsize=11)
        ax.set_xticks(xs, [C_SHORT[c] for c in CONDS], fontsize=8.5)
        ax.set_ylim(0, 1.05)
        ax.set_xlim(-0.5, 3.5)
        ax.grid(axis="x", visible=False)
    axes[2].text(0.5, 0.04, "명령형·평범 = 벤치마크 원문\n(15+15건은 원문 문서와 동일)", transform=axes[2].transAxes,
                 ha="center", va="bottom", fontsize=8, color=S.INK_2)
    axes[0].set_yticks(np.arange(0, 1.01, 0.2), [f"{v:.0%}" for v in np.arange(0, 1.01, 0.2)])
    axes[0].set_ylabel("탐지율")
    q_legend(axes[0], loc="lower left")
    S.title(fig, "LLM이 다시 쓴 문장만 남겨도(InjecAgent 제외) 같은 모양이 나온다",
            "variant_text_source: 벤치마크 원문은 InjecAgent의 명령형·평범 60행뿐. 점 = 탐지율, 막대 = Wilson 95% CI.")
    out.append(S.save(fig, "f08_variant_text_source", out_dir=FIG))

    # f09 span length ratio vs p
    fig, axes = plt.subplots(2, 3, figsize=(11.5, 7.4), sharex=True, sharey=True)
    t8b = V["t8b"]
    for i, q in enumerate(QS):
        for j, c in enumerate(REGS):
            ax = axes[i, j]
            ax.axvspan(0.7, 1.3, color=S.GRID, alpha=0.45, lw=0)
            ax.axhline(THRESHOLD, color=S.INK_2, lw=0.8, ls="--")
            ax.scatter(ratio[c], P[q][c], s=13, color=Q_COLORS[q], alpha=0.55, lw=0)
            r = t8b[(t8b.question == q) & (t8b.condition == c)].iloc[0]
            ax.text(0.97, 0.04, f"Spearman ρ = {r['spearman_ratio_vs_p']:.2f}\n({fmt_p(r['spearman_ratio_vs_p_pvalue'])})",
                    transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5, color=S.INK_2)
            ax.set_xscale("log")
            ax.set_xticks([0.5, 0.7, 1, 1.3, 2, 3], ["0.5", "0.7", "1", "1.3", "2", "3"])
            ax.minorticks_off()
            ax.set_ylim(-0.03, 1.03)
            if i == 0:
                ax.set_title(C_LONG[c], fontsize=11)
            if j == 0:
                ax.set_ylabel(f"{q}: p")
            if i == 1:
                ax.set_xlabel("구간 길이 비 (변형 / 원문)")
    S.title(fig, "구간 길이는 탐지를 설명하지 못한다: 같은 어조 안에서 길이 비와 p의 상관이 약하다",
            "점 = 변형 문서 1건, 회색 띠 = 원문 대비 ±30%. 명령형 구간이 조금 더 길지만(중앙값 1.11배 vs 0.99·1.05배), 길이를 맞춘 부분집합에서도 격차가 남는다(f13).")
    out.append(S.save(fig, "f09_span_length", out_dir=FIG))

    # f10 per-base patterns
    nz = t9.groupby("pattern", sort=False)["n"].sum()
    pats = [k for k, v in nz.items() if v > 0]
    empty = [k for k, v in nz.items() if v == 0]
    fig, ax = plt.subplots(figsize=(10, 4.6))
    ys = np.arange(len(pats))[::-1]
    for q in QS:
        sub = t9[t9.question == q].set_index("pattern").loc[pats]
        yy = ys + (0.19 if q == "Q2" else -0.19)
        bars = ax.barh(yy, sub["n"], height=0.36, color=Q_COLORS[q])
        S.bar_gap(bars)
        for y, v in zip(yy, sub["n"]):
            ax.text(v + 1, y, str(int(v)), va="center", fontsize=8.5, color=S.INK_2)
    ax.set_yticks(ys, pats)
    ax.set_xlabel("base 문서 수 (총 150)")
    ax.grid(axis="y", visible=False)
    q_legend(ax, loc="center right")
    nq ={q: int(t9[(t9.question == q) & (t9.pattern == "명령형만 탐지")]["n"].iloc[0]) for q in QS}
    S.title(fig, f"'명령형만 탐지'가 Q2 {nq['Q2']}개, QL {nq['QL']}개. 명령형을 놓치고 다른 변형을 잡은 base는 없다",
            "base 1개의 세 변형(명령형 / 평범한 요청 / 공손한 부탁)이 각각 잡혔는지의 조합 (총 150, 임계값 0.5). "
            f"나머지 조합({', '.join(empty)})은 두 질문 모두 0개.")
    out.append(S.save(fig, "f10_base_patterns", out_dir=FIG))

    # f11 Q2 vs QL
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 4.8), sharey=True)
    ys = np.arange(len(CONDS))[::-1]
    sub = t3.set_index("condition").loc[CONDS]
    for ax, (val, lo, hi, xl, sc) in zip(axes, (("dTPR_QL_minus_Q2", "dTPR_lo", "dTPR_hi", "탐지율 차이 QL − Q2 (%p)", 100),
                                               ("dAUC", "dAUC_lo", "dAUC_hi", "AUC 차이 QL − Q2 (vs EN 정상)", 1))):
        for y, (_, r) in zip(ys, sub.iterrows()):
            ax.errorbar([r[val] * sc], [y], xerr=err(r[val], r[lo], r[hi], sc), fmt="o",
                        color=S.INK, elinewidth=1.6, capsize=3, markersize=6.5)
            if val.startswith("dTPR"):
                ax.text(r[hi] * sc + 1, y + 0.18, f"Q2만 {r['Q2_only']} / QL만 {r['QL_only']}, {fmt_p(r['mcnemar_p'])}",
                        fontsize=8, color=S.INK_2, va="bottom")
        ax.axvline(0, color=S.INK_2, lw=0.9)
        ax.set_xlabel(xl)
        ax.grid(axis="y", visible=False)
    axes[0].set_yticks(ys, [C_LONG[c] for c in CONDS])
    axes[0].set_xlim(-12, 30)
    axes[1].set_xlim(-0.03, 0.06)
    S.title(fig, "정의형 질문(QL)이 원문·평범·공손을 6~9%p 더 잡지만, 명령형과의 격차(43~45%p)는 그대로다",
            "같은 문서에서 두 질문 비교. 점 = 차이, 막대 = 짝 부트스트랩 95% CI. p = 정확 McNemar(보정 전).")
    out.append(S.save(fig, "f11_q2_vs_ql", out_dir=FIG))

    # f12 measurement noise: identical texts re-scored + flips per condition
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.9), gridspec_kw={"width_ratios": [1, 1.25]})
    ax = axes[0]
    ax.plot([0, 1], [0, 1], color=S.AXIS, lw=0.9)
    for q in QS:
        g = rt[rt.question == q]
        ax.scatter(g["p_01_baseline"], g["p_X1"], s=22, color=Q_COLORS[q], alpha=0.7, lw=0,
                   label=f"{Q_NAME[q]}: 평균 |Δp| {g['abs_diff'].mean():.3f}, 판정 일치 {int(g.same_decision.sum())}/{len(g)}")
    ax.set_xlabel("01_baseline 실행의 p")
    ax.set_ylabel("X1 실행의 p (같은 텍스트)")
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_title(f"원문과 바이트 단위로 같은 X1 문서 {int((rt.question == 'Q2').sum())}건")
    ax.legend(loc="upper left", fontsize=8)
    ax = axes[1]
    for q in QS:
        sub = t1[t1.question == q].set_index("condition").loc[CONDS]
        bars = ax.bar(xs + dodge(q), sub["flip_count"], width=0.34, color=Q_COLORS[q])
        S.bar_gap(bars)
        for xi, v in zip(xs, sub["flip_count"]):
            ax.text(xi + dodge(q), v + 0.15, str(int(v)), ha="center", fontsize=8.5, color=S.INK_2)
    ax.set_xticks(xs, [C_SHORT[c] for c in CONDS])
    ax.set_ylabel("3회 호출 중 판정이 갈린 문서 수 (/150)")
    ax.set_title("반복 호출 사이 판정 뒤집힘")
    ax.grid(axis="x", visible=False)
    ax.set_ylim(0, max(t1["flip_count"]) + 2)
    S.title(fig, "측정 잡음은 어조 효과보다 훨씬 작다",
            "왼쪽: 다른 시각에 따로 잰 같은 텍스트의 p. 오른쪽: 3회 호출의 판정이 0.5를 사이에 두고 갈린 문서 수.")
    out.append(S.save(fig, "f12_measurement_noise", out_dir=FIG))

    # f13 sensitivity forest
    panels = [("imperative_explicit", "plain_request"), ("imperative_explicit", "polite"), ("original", "plain_request")]
    subset_order = ["전체 150", "InjecAgent 제외 (전부 llm_rewrite)", "BIPIA 제외", "LLMail-Inject 제외", "BrowseSafe-Bench 제외",
                    "SEP 제외", "세 변형 모두 길이 비 0.7–1.3", "명령형 구간 ≤ 비교 변형 구간"]
    fig, axes = plt.subplots(1, 3, figsize=(13, 6), sharey=True)
    ys = np.arange(len(subset_order))[::-1]
    for ax, (a, b) in zip(axes, panels):
        for q in QS:
            for y, sname in zip(ys, subset_order):
                if sname.startswith("명령형 구간"):
                    if a != "imperative_explicit":
                        continue
                    sname = f"명령형 구간 ≤ {C_SHORT[b]} 구간"
                g = sens[(sens.question == q) & (sens.subset == sname) & (sens.cond_a == a) & (sens.cond_b == b)]
                if g.empty:
                    continue
                r = g.iloc[0]
                yy = y + (0.15 if q == "Q2" else -0.15)
                ax.errorbar([r["dTPR_b_minus_a"] * 100], [yy], xerr=err(r["dTPR_b_minus_a"], r["dTPR_lo"], r["dTPR_hi"], 100),
                            fmt="o", color=Q_COLORS[q], elinewidth=1.5, capsize=2.5, markersize=5.5)
                if q == "QL":
                    ax.text(-98, y, f"n={int(r['n'])}", fontsize=7.5, color=S.MUTED, va="center")
        ax.axvline(0, color=S.INK_2, lw=0.9)
        ax.set_xlim(-100, 40)
        ax.set_title(f"{C_SHORT[b]} − {C_SHORT[a]}", fontsize=11)
        ax.set_xlabel("탐지율 차이 (%p)")
        ax.grid(axis="y", visible=False)
    axes[2].text(0.06, 0.06, "원문과의 비교에는\n길이 조건 행이 없다", transform=axes[2].transAxes, ha="left",
                 fontsize=8, color=S.MUTED)
    axes[0].set_yticks(ys, subset_order)
    q_legend(axes[2], loc="lower right")
    gap = sens[sens.cond_a == "imperative_explicit"]["dTPR_b_minus_a"] * 100
    S.title(fig, f"출처 하나를 빼거나 길이를 맞춰도 명령형보다 {-gap.max():.0f}~{-gap.min():.0f}%p 낮은 탐지율은 그대로다",
            "부분집합마다 다시 계산한 짝 비교. 점 = 탐지율 차이, 막대 = 짝 부트스트랩 95% CI(1,000회, seed 20261112).")
    out.append(S.save(fig, "f13_sensitivity", out_dir=FIG))
    return out


if __name__ == "__main__":
    main()
