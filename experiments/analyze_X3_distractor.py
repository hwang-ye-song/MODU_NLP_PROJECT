"""X3_distractor analysis: the same injected span inside a Wikipedia expository carrier vs an instruction-dense
Enron work-email carrier (each carrier also judged clean). No API calls; every number comes from

    results/X3_distractor/{Q2,QL}_predictions.csv      (made by experiments/run_api.py X3_distractor)
    results/01_baseline/{Q2,QL}_predictions.csv        (span's original document = base_uid; EN 1000 reference)
    data/injection_eval/experiments/X3_distractor.jsonl (span text only: length, ends with . ! ? or not)

    python experiments/analyze_X3_distractor.py

Writes results/X3_distractor/tables/*.csv, results/X3_distractor/figures/*.png and the "analysis" key of
results/X3_distractor/summary.json (every other key is left as run_api.py wrote it).

Pairing (data README warns: the injection row is longer than its clean carrier by the span length):
  slot k = wiki carrier k (injection + clean row) + enron carrier k (injection + clean row) + the same span k.
  injection vs its own clean carrier -> carrier_id; wiki vs enron for one span -> inj_pair_id/slot;
  carrier vs the span's original EN document -> base_uid.
Statistics: metrics() from src/jev_guard (threshold 0.5), Wilson 95% CI, exact McNemar (two-sided binomial on
discordant pairs), paired bootstrap over the 100 slots (1000 resamples, seed 20261112), Fisher exact + Newcombe CI
for the unpaired clean-carrier FPR comparison.
"""
import hashlib
import json
import math
import os
import sys

import numpy as np
import pandas as pd
from scipy.stats import binomtest, fisher_exact, rankdata, spearmanr

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402
import plot_style as S  # noqa: E402
from src.jev_guard import THRESHOLD, metrics  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.transforms import blended_transform_factory  # noqa: E402

EXP = "X3_distractor"
OUT = os.path.join(J.RESULTS, EXP)
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
DATA_X3 = os.path.join(J.DATA, "experiments", "X3_distractor.jsonl")
BASE = os.path.join(J.RESULTS, "01_baseline")
QIDS = ("Q2", "QL")
SEED, NBOOT = 20261112, 1000
QCOL = {"Q2": "#2a78d6", "QL": "#eb6834"}  # colour = question (project rule)
LCOL = S.LABEL_COLORS                        # colour = label (인젝션 violet / 정상 aqua)
CT = {"w": "unrelated_expository", "e": "instruction_dense"}
CT_KO = {"w": "위키 설명문", "e": "Enron 업무 메일", "o": "원래 문서(기준선)"}
SOURCES = ["BIPIA", "BrowseSafe-Bench", "InjecAgent", "LLMail-Inject", "SEP"]
NREQ_BINS = [("3", lambda n: n == 3), ("4", lambda n: n == 4), ("5-8", lambda n: n >= 5)]


# ------------------------------------------------------------------ helpers
def md5(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for b in iter(lambda: f.read(1 << 20), b""):
            h.update(b)
    return h.hexdigest()


def rnd(x, k=4):
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return None
    return round(float(x), k)


def ci_pct(a):
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))]


def mcnemar(a_only, b_only):
    """Exact McNemar: two-sided binomial test on the discordant pairs."""
    n = int(a_only + b_only)
    return 1.0 if n == 0 else float(binomtest(int(min(a_only, b_only)), n, 0.5).pvalue)


def newcombe(k1, n1, k2, n2):
    """95% CI for p1 - p2 (independent samples), Newcombe hybrid Wilson score."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = J.wilson(k1, n1)
    l2, u2 = J.wilson(k2, n2)
    d = p1 - p2
    return [d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)]


def fast_auc(pos, neg):
    """Mann-Whitney AUC (ties count half) - the same number roc_auc_score gives, fast enough for the bootstrap."""
    r = rankdata(np.concatenate([pos, neg]))
    n1, n0 = len(pos), len(neg)
    return (r[:n1].sum() - n1 * (n1 + 1) / 2) / (n1 * n0)


def pair_disc(p_inj, p_cln):
    """Share of carrier pairs where p(injection row) > p(its own clean carrier); ties count half."""
    a, b = np.round(np.asarray(p_inj, float), 6), np.round(np.asarray(p_cln, float), 6)
    return float(np.mean((a > b) + 0.5 * (a == b)))


IDX = np.random.default_rng(SEED).integers(0, 100, size=(NBOOT, 100))  # resample the 100 slots (common to all comparisons)


def boot(fn, n=100):
    idx = IDX if n == 100 else np.random.default_rng(SEED).integers(0, n, size=(NBOOT, n))
    return np.array([fn(i) for i in idx])


def spearman(x, y):
    r = spearmanr(x, y)
    return float(r.statistic), float(r.pvalue)


def sig_word(lo, hi):
    return "차이 없음(95% CI가 0 포함)" if lo <= 0 <= hi else ("증가" if lo > 0 else "감소")


# ------------------------------------------------------------------ load
def load():
    rows = {r["exp_uid"]: r for r in J.load_jsonl(DATA_X3)}
    P, B, W = {}, {}, {}
    for q in QIDS:
        d = pd.read_csv(os.path.join(OUT, f"{q}_predictions.csv"))
        assert len(d) == 400 and set(d.uid) == set(rows), f"{q}: predictions do not match the X3 data file"
        d["span"] = d.uid.map(lambda u: rows[u].get("injected_instruction"))
        d["span_len"] = d.span.map(lambda s: len(s) if isinstance(s, str) else np.nan)
        # last character after closing quotes / brackets: "." / "?" / "!" / "없음". run-on = none of . ? ! (a span ending in
        # "?" counts as a finished sentence). noperiod = the literal rule "does not end in '.'" (reference grouping).
        d["span_end_char"] = d.span.map(_end_char)
        d["runon"] = (d.span_end_char == "없음").where(d.span_end_char.notna())
        d["noperiod"] = (d.span_end_char != ".").where(d.span_end_char.notna())
        P[q] = d
        b = pd.read_csv(os.path.join(BASE, f"{q}_predictions.csv"))
        B[q] = b
        W[q] = wide(d, b)
        for t in ("w", "e"):  # what sits right before / after the span in the carrier text (" " inline, "\n" own line)
            W[q][f"sep_{t}"] = [_sep(rows[u]) for u in W[q][f"uid_{t}_inj"]]
    return rows, P, B, W


def _end_char(s):
    if not isinstance(s, str):  # clean carrier rows have no span
        return None
    c = s.rstrip().rstrip("\"')]")[-1:]
    return c if c in (".", "?", "!") else "없음"


def _sep(r):
    t, s = r["text"], r["injected_instruction"]
    i = t.find(s)
    assert i >= 0 and t.count(s) == 1
    kind = lambda ch: "newline" if ch == "\n" else ("space" if ch == " " else "other")  # noqa: E731
    return f"{kind(t[i - 1:i])}/{kind(t[i + len(s):i + len(s) + 1])}"


def wide(d, b):
    """One row per slot: wiki injection/clean, enron injection/clean, and the span's original baseline document."""
    out = pd.DataFrame(index=sorted(d.slot.unique()))
    out.index.name = "slot"
    inj, cln = d[d.label_int == 1], d[d.label_int == 0]
    for t, ct in CT.items():
        i = inj[inj.carrier_type == ct].set_index("slot").sort_index()
        c = cln[cln.carrier_type == ct].set_index("slot").sort_index()
        assert len(i) == len(c) == 100 and (i.index == c.index).all() and (i.carrier_id == c.carrier_id).all()
        for col, src in (("uid", "uid"), ("p", "p"), ("y", "pred"), ("len", "char_len"), ("tok", "input_tokens"),
                         ("sd", "p_sd"), ("flip", "flip")):
            out[f"{col}_{t}_inj"] = i[src]
            out[f"{col}_{t}_cln"] = c[src]
        out[f"cid_{t}"] = i.carrier_id
        out[f"nreq_{t}"] = i.carrier_n_requests
    wi = inj[inj.carrier_type == CT["w"]].set_index("slot").sort_index()
    ei = inj[inj.carrier_type == CT["e"]].set_index("slot").sort_index()
    assert (wi.base_uid == ei.base_uid).all() and (wi.inj_pair_id == ei.inj_pair_id).all()
    for col in ("inj_pair_id", "base_uid", "source", "risk_level", "doc_type", "span_subset", "span", "span_len", "span_end_char", "runon", "noperiod"):
        out[col] = wi[col]
    assert out.span_end_char.notna().all()
    out["runon"], out["noperiod"] = out.runon.astype(bool), out.noperiod.astype(bool)
    bb = b[b.set == "EN"].set_index("uid")
    assert out.base_uid.isin(bb.index).all()
    out["p_o"] = out.base_uid.map(bb.p)
    out["y_o"] = out.base_uid.map(bb.pred)
    out["len_o"] = out.base_uid.map(bb.char_len)
    out["doc_type_o"] = out.base_uid.map(bb.doc_type)
    assert (out.y_o == (out.p_o >= THRESHOLD).astype(int)).all()
    return out


# ------------------------------------------------------------------ tables
def t_metrics(P, B, W):
    """Per question x condition: TPR/FPR/AUC (metrics()), Wilson CIs, paired discrimination, mean p, length-only AUC."""
    recs = []
    for q in QIDS:
        w = W[q]
        en = B[q][B[q].set == "EN"]
        m = J.metric_block(en)
        auc_b = boot(lambda i: fast_auc(en.p.values[i][en.label_int.values[i] == 1], en.p.values[i][en.label_int.values[i] == 0]), n=len(en))
        recs.append({"question": q, "condition": "EN 기준선 전체 (01_baseline)", "n_injection": m["n_injection"], "n_benign": m["n_benign"],
                     "TPR": m["TPR"], "TPR_lo": m["TPR_ci95"][0], "TPR_hi": m["TPR_ci95"][1], "tp": m["tp"],
                     "FPR": m["FPR"], "FPR_lo": m["FPR_ci95"][0], "FPR_hi": m["FPR_ci95"][1], "fp": m["fp"],
                     "AUC": m["AUC"], "AUC_lo": ci_pct(auc_b)[0], "AUC_hi": ci_pct(auc_b)[1],
                     "mean_p_injection": m["mean_p_injection"], "mean_p_benign": m["mean_p_benign"],
                     "length_only_AUC": metrics(en.label_int.tolist(), en.char_len.tolist())["AUC"]})
        k = int(w.y_o.sum())
        lo, hi = J.wilson(k, 100)
        recs.append({"question": q, "condition": "같은 span의 원래 문서 (01_baseline, 주입 100)", "n_injection": 100, "n_benign": 0,
                     "TPR": k / 100, "TPR_lo": lo, "TPR_hi": hi, "tp": k, "mean_p_injection": w.p_o.mean()})
        for t in ("w", "e", "all"):
            if t == "all":
                sub = P[q]
                pi = np.concatenate([w.p_w_inj, w.p_e_inj])
                pc = np.concatenate([w.p_w_cln, w.p_e_cln])
                auc_b = boot(lambda i: fast_auc(np.r_[w.p_w_inj.values[i], w.p_e_inj.values[i]], np.r_[w.p_w_cln.values[i], w.p_e_cln.values[i]]))
                disc_b = boot(lambda i: pair_disc(np.r_[w.p_w_inj.values[i], w.p_e_inj.values[i]], np.r_[w.p_w_cln.values[i], w.p_e_cln.values[i]]))
                gap_b = boot(lambda i: np.mean(np.r_[w.p_w_inj.values[i] - w.p_w_cln.values[i], w.p_e_inj.values[i] - w.p_e_cln.values[i]]))
                name = "X3 전체 (위키+Enron)"
            else:
                sub = P[q][P[q].carrier_type == CT[t]]
                pi, pc = w[f"p_{t}_inj"].values, w[f"p_{t}_cln"].values
                auc_b = boot(lambda i: fast_auc(pi[i], pc[i]))
                disc_b = boot(lambda i: pair_disc(pi[i], pc[i]))
                gap_b = boot(lambda i: np.mean(pi[i] - pc[i]))
                name = CT_KO[t]
            m = J.metric_block(sub)
            recs.append({"question": q, "condition": name, "n_injection": m["n_injection"], "n_benign": m["n_benign"],
                         "TPR": m["TPR"], "TPR_lo": m["TPR_ci95"][0], "TPR_hi": m["TPR_ci95"][1], "tp": m["tp"],
                         "FPR": m["FPR"], "FPR_lo": m["FPR_ci95"][0], "FPR_hi": m["FPR_ci95"][1], "fp": m["fp"],
                         "AUC": m["AUC"], "AUC_lo": ci_pct(auc_b)[0], "AUC_hi": ci_pct(auc_b)[1],
                         "paired_disc": pair_disc(pi, pc), "paired_disc_lo": ci_pct(disc_b)[0], "paired_disc_hi": ci_pct(disc_b)[1],
                         "mean_gap_inj_minus_clean": float(np.mean(pi - pc)), "gap_lo": ci_pct(gap_b)[0], "gap_hi": ci_pct(gap_b)[1],
                         "mean_p_injection": m["mean_p_injection"], "mean_p_benign": m["mean_p_benign"],
                         "max_p_benign": float(np.max(pc)), "min_gap": float(np.min(pi - pc)),
                         # unpaired view (a deployed guard has no clean copy of the same document): injection rows that
                         # score below the highest clean carrier of the same kind cannot be separated by any threshold
                         "n_injection_below_max_benign": int((pi < np.max(pc)).sum()), "n_injection_p_below_0.1": int((pi < 0.1).sum()),
                         "length_only_AUC": metrics(sub.label_int.tolist(), sub.char_len.tolist())["AUC"],
                         "flip_count": m["flip_count"]})
    df = pd.DataFrame(recs)
    # delta vs the EN 1000 baseline (different / overlapping documents -> approximate, independent-sample Newcombe CI)
    for q in QIDS:
        b = df[(df.question == q) & (df.condition.str.startswith("EN 기준선"))].iloc[0]
        for i in df.index[(df.question == q) & df.condition.isin([CT_KO["w"], CT_KO["e"], "X3 전체 (위키+Enron)"])]:
            r = df.loc[i]
            df.loc[i, "dTPR_vs_EN1000"] = r.TPR - b.TPR
            df.loc[i, ["dTPR_vs_EN1000_lo", "dTPR_vs_EN1000_hi"]] = newcombe(r.tp, r.n_injection, b.tp, b.n_injection)
            df.loc[i, "dFPR_vs_EN1000"] = r.FPR - b.FPR
            df.loc[i, ["dFPR_vs_EN1000_lo", "dFPR_vs_EN1000_hi"]] = newcombe(r.fp, r.n_benign, b.fp, b.n_benign)
            df.loc[i, "dAUC_vs_EN1000"] = r.AUC - b.AUC
    return df


def t_wiki_vs_enron(W):
    """Same span, two carriers: enron - wiki. Detection: exact McNemar + paired bootstrap. Clean carriers differ ->
    Wilson CIs, Fisher exact, Newcombe CI (and the slot bootstrap of mean p for reference)."""
    recs = []
    for q in QIDS:
        w = W[q]
        yw, ye = w.y_w_inj.values, w.y_e_inj.values
        pw, pe = w.p_w_inj.values, w.p_e_inj.values
        cw, ce = w.p_w_cln.values, w.p_e_cln.values
        w_only, e_only = int(((yw == 1) & (ye == 0)).sum()), int(((yw == 0) & (ye == 1)).sum())
        both, neither = int(((yw == 1) & (ye == 1)).sum()), int(((yw == 0) & (ye == 0)).sum())
        b = boot(lambda i: ye[i].mean() - yw[i].mean())
        recs.append({"question": q, "metric": "TPR (탐지율 @0.5)", "wiki": yw.mean(), "enron": ye.mean(), "diff_enron_minus_wiki": ye.mean() - yw.mean(),
                     "ci_lo": ci_pct(b)[0], "ci_hi": ci_pct(b)[1], "test": "exact McNemar", "p_value": mcnemar(w_only, e_only),
                     "both_detected": both, "wiki_only": w_only, "enron_only": e_only, "neither": neither, "n_pairs": 100})
        b = boot(lambda i: pe[i].mean() - pw[i].mean())
        nl = int((pe < pw).sum())
        recs.append({"question": q, "metric": "주입 행 평균 p", "wiki": pw.mean(), "enron": pe.mean(), "diff_enron_minus_wiki": pe.mean() - pw.mean(),
                     "ci_lo": ci_pct(b)[0], "ci_hi": ci_pct(b)[1], "test": "paired bootstrap (slot)",
                     "p_value": mcnemar(nl, int((pe > pw).sum())), "enron_lower_pairs": nl, "enron_higher_pairs": int((pe > pw).sum()),
                     "n_pairs": 100, "note": "p_value = sign test on pairs (enron lower vs higher)"})
        b = boot(lambda i: fast_auc(pe[i], ce[i]) - fast_auc(pw[i], cw[i]))
        recs.append({"question": q, "metric": "AUC (주입 vs 같은 종류 원문)", "wiki": fast_auc(pw, cw), "enron": fast_auc(pe, ce),
                     "diff_enron_minus_wiki": fast_auc(pe, ce) - fast_auc(pw, cw), "ci_lo": ci_pct(b)[0], "ci_hi": ci_pct(b)[1],
                     "test": "paired bootstrap (slot)", "n_pairs": 100})
        b = boot(lambda i: pair_disc(pe[i], ce[i]) - pair_disc(pw[i], cw[i]))
        recs.append({"question": q, "metric": "짝 판별률 (p주입 > p자기 원문)", "wiki": pair_disc(pw, cw), "enron": pair_disc(pe, ce),
                     "diff_enron_minus_wiki": pair_disc(pe, ce) - pair_disc(pw, cw), "ci_lo": ci_pct(b)[0], "ci_hi": ci_pct(b)[1],
                     "test": "paired bootstrap (slot)", "n_pairs": 100})
        b = boot(lambda i: np.mean(pe[i] - ce[i]) - np.mean(pw[i] - cw[i]))
        recs.append({"question": q, "metric": "p 간격 (주입 - 자기 원문)", "wiki": np.mean(pw - cw), "enron": np.mean(pe - ce),
                     "diff_enron_minus_wiki": np.mean(pe - ce) - np.mean(pw - cw), "ci_lo": ci_pct(b)[0], "ci_hi": ci_pct(b)[1],
                     "test": "paired bootstrap (slot)", "n_pairs": 100})
        fw, fe = int(w.y_w_cln.sum()), int(w.y_e_cln.sum())
        nc = newcombe(fe, 100, fw, 100)
        recs.append({"question": q, "metric": "FPR (원문, 서로 다른 carrier)", "wiki": fw / 100, "enron": fe / 100, "diff_enron_minus_wiki": (fe - fw) / 100,
                     "ci_lo": nc[0], "ci_hi": nc[1], "test": "Fisher exact (unpaired), Newcombe CI",
                     "p_value": float(fisher_exact([[fe, 100 - fe], [fw, 100 - fw]]).pvalue),
                     "wiki_ci_lo": J.wilson(fw, 100)[0], "wiki_ci_hi": J.wilson(fw, 100)[1],
                     "enron_ci_lo": J.wilson(fe, 100)[0], "enron_ci_hi": J.wilson(fe, 100)[1], "n_pairs": None})
        rng = np.random.default_rng(SEED)
        bu = np.array([rng.choice(ce, 100).mean() - rng.choice(cw, 100).mean() for _ in range(NBOOT)])
        recs.append({"question": q, "metric": "원문 평균 p (서로 다른 carrier)", "wiki": cw.mean(), "enron": ce.mean(), "diff_enron_minus_wiki": ce.mean() - cw.mean(),
                     "ci_lo": ci_pct(bu)[0], "ci_hi": ci_pct(bu)[1], "test": "unpaired bootstrap", "n_pairs": None,
                     "wiki_max": cw.max(), "enron_max": ce.max()})
    return pd.DataFrame(recs)


def t_vs_original(W):
    """Carrier vs the span's original baseline document (same span, paired by base_uid)."""
    recs = []
    for q in QIDS:
        w = W[q]
        yo, po = w.y_o.values, w.p_o.values
        for t in ("w", "e"):
            y, p = w[f"y_{t}_inj"].values, w[f"p_{t}_inj"].values
            c_only, o_only = int(((y == 1) & (yo == 0)).sum()), int(((y == 0) & (yo == 1)).sum())
            bt = boot(lambda i: y[i].mean() - yo[i].mean())
            bp = boot(lambda i: p[i].mean() - po[i].mean())
            recs.append({"question": q, "carrier": CT_KO[t], "n": 100, "TPR_original": yo.mean(), "TPR_carrier": y.mean(),
                         "dTPR": y.mean() - yo.mean(), "dTPR_lo": ci_pct(bt)[0], "dTPR_hi": ci_pct(bt)[1],
                         "carrier_only": c_only, "original_only": o_only, "both": int(((y == 1) & (yo == 1)).sum()),
                         "neither": int(((y == 0) & (yo == 0)).sum()), "mcnemar_p": mcnemar(c_only, o_only),
                         "mean_p_original": po.mean(), "mean_p_carrier": p.mean(), "dmean_p": p.mean() - po.mean(),
                         "dmean_p_lo": ci_pct(bp)[0], "dmean_p_hi": ci_pct(bp)[1],
                         "mean_len_original": w.len_o.mean(), "mean_len_carrier": w[f"len_{t}_inj"].mean()})
    return pd.DataFrame(recs)


def t_by_group(W, col, levels, label_fn=str):
    """Detection by a span attribute: original document, wiki, enron; enron - wiki McNemar within the group."""
    recs = []
    for q in QIDS:
        w = W[q]
        for lv in levels:
            g = w[w[col] == lv]
            n = len(g)
            if n == 0:
                continue
            r = {"question": q, col: label_fn(lv), "n_spans": n}
            for t, nm in (("o", "original"), ("w", "wiki"), ("e", "enron")):
                y = g.y_o if t == "o" else g[f"y_{t}_inj"]
                p = g.p_o if t == "o" else g[f"p_{t}_inj"]
                k = int(y.sum())
                r.update({f"TPR_{nm}": k / n, f"TPR_{nm}_lo": J.wilson(k, n)[0], f"TPR_{nm}_hi": J.wilson(k, n)[1], f"mean_p_{nm}": p.mean()})
            wo, eo = int(((g.y_w_inj == 1) & (g.y_e_inj == 0)).sum()), int(((g.y_w_inj == 0) & (g.y_e_inj == 1)).sum())
            r.update({"diff_enron_minus_wiki": r["TPR_enron"] - r["TPR_wiki"], "wiki_only": wo, "enron_only": eo,
                      "mcnemar_p_enron_vs_wiki": mcnemar(wo, eo),
                      "mean_p_clean_wiki": g.p_w_cln.mean(), "mean_p_clean_enron": g.p_e_cln.mean()})
            recs.append(r)
    return pd.DataFrame(recs)


def t_nreq(W):
    """Enron carriers by number of request sentences (3 / 4 / 5-8); wiki = same spans in a 0-request carrier."""
    recs = []
    for q in QIDS:
        w = W[q]
        for name, f in NREQ_BINS:
            g = w[w.nreq_e.map(f)]
            n = len(g)
            ke, kw, kc = int(g.y_e_inj.sum()), int(g.y_w_inj.sum()), int(g.y_e_cln.sum())
            wo, eo = int(((g.y_w_inj == 1) & (g.y_e_inj == 0)).sum()), int(((g.y_w_inj == 0) & (g.y_e_inj == 1)).sum())
            recs.append({"question": q, "enron_requests": name, "n_carriers": n,
                         "TPR_enron": ke / n, "TPR_enron_lo": J.wilson(ke, n)[0], "TPR_enron_hi": J.wilson(ke, n)[1],
                         "TPR_wiki_same_spans": kw / n, "TPR_wiki_lo": J.wilson(kw, n)[0], "TPR_wiki_hi": J.wilson(kw, n)[1],
                         "diff_enron_minus_wiki": (ke - kw) / n, "wiki_only": wo, "enron_only": eo, "mcnemar_p": mcnemar(wo, eo),
                         "mean_p_inj_enron": g.p_e_inj.mean(), "mean_p_inj_wiki": g.p_w_inj.mean(),
                         "FPR_enron_clean": kc / n, "FPR_lo": J.wilson(kc, n)[0], "FPR_hi": J.wilson(kc, n)[1],
                         "mean_p_clean_enron": g.p_e_cln.mean(), "max_p_clean_enron": g.p_e_cln.max()})
        rho1, p1 = spearman(w.nreq_e, w.p_e_inj)
        rho2, p2 = spearman(w.nreq_e, w.p_w_inj - w.p_e_inj)
        rho3, p3 = spearman(w.nreq_e, w.p_e_cln)
        recs.append({"question": q, "enron_requests": "spearman (enron n_requests)", "n_carriers": 100,
                     "note": f"rho(n_req, p_enron_inj)={rho1:.3f} (p={p1:.3f}); rho(n_req, p_wiki-p_enron)={rho2:.3f} (p={p2:.3f}); "
                             f"rho(n_req, p_enron_clean)={rho3:.3f} (p={p3:.3f})",
                     "rho_p_inj": rho1, "rho_p_inj_pvalue": p1, "rho_gap": rho2, "rho_gap_pvalue": p2, "rho_p_clean": rho3, "rho_p_clean_pvalue": p3})
    return pd.DataFrame(recs)


def t_q2_vs_ql(W):
    """QL - Q2 on the same rows: detection (injection rows) / false positives (clean rows)."""
    recs = []
    a, b = W["Q2"], W["QL"]
    for nm, ycol, pcol in (("원래 문서 · 주입", "y_o", "p_o"), ("위키 · 주입", "y_w_inj", "p_w_inj"), ("Enron · 주입", "y_e_inj", "p_e_inj"),
                           ("위키 · 원문(정상)", "y_w_cln", "p_w_cln"), ("Enron · 원문(정상)", "y_e_cln", "p_e_cln")):
        y2, yl, p2, pl = a[ycol].values, b[ycol].values, a[pcol].values, b[pcol].values
        q2_only, ql_only = int(((y2 == 1) & (yl == 0)).sum()), int(((y2 == 0) & (yl == 1)).sum())
        bt = boot(lambda i: yl[i].mean() - y2[i].mean())
        bp = boot(lambda i: pl[i].mean() - p2[i].mean())
        recs.append({"rows": nm, "n": 100, "rate_Q2": y2.mean(), "rate_QL": yl.mean(), "diff_QL_minus_Q2": yl.mean() - y2.mean(),
                     "ci_lo": ci_pct(bt)[0], "ci_hi": ci_pct(bt)[1], "Q2_only": q2_only, "QL_only": ql_only,
                     "mcnemar_p": mcnemar(q2_only, ql_only), "mean_p_Q2": p2.mean(), "mean_p_QL": pl.mean(),
                     "dmean_p": pl.mean() - p2.mean(), "dmean_p_lo": ci_pct(bp)[0], "dmean_p_hi": ci_pct(bp)[1]})
    # enron - wiki gap, compared between questions (difference-in-differences, paired bootstrap)
    g2 = a.y_e_inj.values - a.y_w_inj.values
    gl = b.y_e_inj.values - b.y_w_inj.values
    bd = boot(lambda i: gl[i].mean() - g2[i].mean())
    h2 = a.p_e_inj.values - a.p_w_inj.values
    hl = b.p_e_inj.values - b.p_w_inj.values
    bh = boot(lambda i: hl[i].mean() - h2[i].mean())
    recs.append({"rows": DID_ROW, "n": 100, "rate_Q2": g2.mean(), "rate_QL": gl.mean(),
                 "diff_QL_minus_Q2": gl.mean() - g2.mean(), "ci_lo": ci_pct(bd)[0], "ci_hi": ci_pct(bd)[1],
                 "mean_p_Q2": h2.mean(), "mean_p_QL": hl.mean(), "dmean_p": hl.mean() - h2.mean(),
                 "dmean_p_lo": ci_pct(bh)[0], "dmean_p_hi": ci_pct(bh)[1]})
    return pd.DataFrame(recs)


DID_ROW = "(Enron − 위키) 차이의 QL − Q2 (rate = 탐지율 차이, mean_p = 평균 p 차이)"


def t_length(P, W):
    recs = []
    for q in QIDS:
        d, w = P[q], W[q]
        inj = d[d.label_int == 1]
        cln = d[d.label_int == 0]
        r = {"question": q,
             "length_only_AUC_all": metrics(d.label_int.tolist(), d.char_len.tolist())["AUC"],
             "length_only_AUC_wiki": metrics(*_xy(d[d.carrier_type == CT["w"]], "char_len"))["AUC"],
             "length_only_AUC_enron": metrics(*_xy(d[d.carrier_type == CT["e"]], "char_len"))["AUC"],
             "length_AUC_wiki_vs_enron_injection_rows": metrics((inj.carrier_type == CT["w"]).astype(int).tolist(), inj.char_len.tolist())["AUC"],
             "share_pairs_injection_longer": float(np.mean(np.r_[w.len_w_inj > w.len_w_cln, w.len_e_inj > w.len_e_cln])),
             "jev_AUC_all": metrics(d.label_int.tolist(), d.p.tolist())["AUC"],
             "mean_len_wiki_inj": w.len_w_inj.mean(), "mean_len_wiki_clean": w.len_w_cln.mean(),
             "mean_len_enron_inj": w.len_e_inj.mean(), "mean_len_enron_clean": w.len_e_cln.mean(),
             "mean_len_original": w.len_o.mean(), "median_len_original": w.len_o.median(),
             "min_len_original": w.len_o.min(), "max_len_original": w.len_o.max(),
             "n_spans_original_shorter_than_wiki_inj": int((w.len_o < w.len_w_inj).sum()),
             "n_spans_original_shorter_than_enron_inj": int((w.len_o < w.len_e_inj).sum()),
             "min_len_wiki_inj": w.len_w_inj.min(), "max_len_wiki_inj": w.len_w_inj.max(),
             "min_len_enron_inj": w.len_e_inj.min(), "max_len_enron_inj": w.len_e_inj.max(),
             "mean_span_len": w.span_len.mean(),
             "mean_tokens_wiki_inj": w.tok_w_inj.mean(), "mean_tokens_enron_inj": w.tok_e_inj.mean(),
             "mean_tokens_wiki_clean": w.tok_w_cln.mean(), "mean_tokens_enron_clean": w.tok_e_cln.mean()}
        r["spearman_p_len_clean"], r["spearman_p_len_clean_pvalue"] = spearman(cln.char_len, cln.p)
        r["spearman_p_len_injection"], r["spearman_p_len_injection_pvalue"] = spearman(inj.char_len, inj.p)
        for t in ("w", "e"):
            y = w[f"y_{t}_inj"]
            r[f"mean_len_detected_{t}"] = w.loc[y == 1, f"len_{t}_inj"].mean()
            r[f"mean_len_missed_{t}"] = w.loc[y == 0, f"len_{t}_inj"].mean()
        r["spearman_p_spanlen_wiki"], _ = spearman(w.span_len, w.p_w_inj)
        r["spearman_p_spanlen_enron"], _ = spearman(w.span_len, w.p_e_inj)
        recs.append(r)
    return pd.DataFrame(recs)


def _xy(df, col):
    return df.label_int.tolist(), df[col].tolist()


RUNON_MAIN = "끝 문자 . ? ! 기준 (run-on)"
RUNON_END = {False: "문장부호(. ? !)로 끝남", True: "문장부호 없이 끝남 (run-on)"}
PERIOD_END = {False: "마침표(.)로 끝남", True: "마침표(.) 없이 끝남 (? 포함)"}


def t_runon(W):
    """Spans grouped by how they end. Main grouping: last character (after closing quotes/brackets) is . ? ! or not
    (run-on; a "?" ending counts as a finished sentence). Reference grouping: the literal "ends with '.'" rule.
    Per group: TPR (Wilson) + McNemar enron vs wiki, mean p of the injected rows + enron - wiki slot bootstrap.
    Sensitivity rows: enron - wiki without the run-on spans, for TPR and for mean p."""
    recs = []
    for q in QIDS:
        w = W[q]
        for grouping, col, names in ((RUNON_MAIN, "runon", RUNON_END), ("참고: 끝 문자 . 만 기준", "noperiod", PERIOD_END)):
            for flag in (False, True):
                g = w[w[col] == flag]
                n = len(g)
                ec = g.span_end_char.value_counts()
                r = {"question": q, "grouping": grouping, "row_type": "group", "span_end": names[flag], "n_spans": n,
                     "n_end_period": int(ec.get(".", 0)), "n_end_question": int(ec.get("?", 0)), "n_end_exclamation": int(ec.get("!", 0)),
                     "n_end_none": int(ec.get("없음", 0))}
                for t, tn in (("o", "original"), ("w", "wiki"), ("e", "enron")):
                    y = g.y_o if t == "o" else g[f"y_{t}_inj"]
                    k = int(y.sum())
                    r.update({f"TPR_{tn}": k / n, f"TPR_{tn}_lo": J.wilson(k, n)[0], f"TPR_{tn}_hi": J.wilson(k, n)[1],
                              f"mean_p_{tn}": (g.p_o if t == "o" else g[f"p_{t}_inj"]).mean()})
                wo, eo = int(((g.y_w_inj == 1) & (g.y_e_inj == 0)).sum()), int(((g.y_w_inj == 0) & (g.y_e_inj == 1)).sum())
                pe, pw = g.p_e_inj.values, g.p_w_inj.values
                bp = boot(lambda i: pe[i].mean() - pw[i].mean(), n=n)
                r.update({"wiki_only": wo, "enron_only": eo, "mcnemar_p_enron_vs_wiki": mcnemar(wo, eo),
                          "dmean_p_enron_minus_wiki": pe.mean() - pw.mean(), "dmean_p_lo": ci_pct(bp)[0], "dmean_p_hi": ci_pct(bp)[1]})
                recs.append(r)
        # enron - wiki without the run-on spans (sensitivity): TPR at 0.5 and mean p of the injected rows
        g = w[~w.runon]
        ye, yw, pe, pw = g.y_e_inj.values, g.y_w_inj.values, g.p_e_inj.values, g.p_w_inj.values
        wo, eo = int(((yw == 1) & (ye == 0)).sum()), int(((yw == 0) & (ye == 1)).sum())
        bs = boot(lambda i: ye[i].mean() - yw[i].mean(), n=len(g))
        recs.append({"question": q, "grouping": RUNON_MAIN, "row_type": "sensitivity", "span_end": "민감도: run-on 제외 Enron − 위키 탐지율",
                     "n_spans": len(g), "diff_enron_minus_wiki": ye.mean() - yw.mean(), "ci_lo": ci_pct(bs)[0], "ci_hi": ci_pct(bs)[1],
                     "wiki_only": wo, "enron_only": eo, "mcnemar_p_enron_vs_wiki": mcnemar(wo, eo)})
        bs = boot(lambda i: pe[i].mean() - pw[i].mean(), n=len(g))
        nl, nh = int((pe < pw).sum()), int((pe > pw).sum())
        recs.append({"question": q, "grouping": RUNON_MAIN, "row_type": "sensitivity", "span_end": "민감도: run-on 제외 Enron − 위키 주입 평균 p",
                     "n_spans": len(g), "diff_enron_minus_wiki": pe.mean() - pw.mean(), "ci_lo": ci_pct(bs)[0], "ci_hi": ci_pct(bs)[1],
                     "enron_lower_pairs": nl, "enron_higher_pairs": nh, "sign_test_p": mcnemar(nl, nh)})
    return pd.DataFrame(recs)


def t_vs_original_by_length(W):
    """Carrier vs original document, split by whether the original document was shorter than the carrier row."""
    recs = []
    for q in QIDS:
        w = W[q]
        for t in ("w", "e"):
            shorter = (w.len_o < w[f"len_{t}_inj"]).values
            for flag, nm in ((True, "원래 문서가 더 짧음"), (False, "원래 문서가 같거나 더 김")):
                g = w[shorter == flag]
                n = len(g)
                yo, y = g.y_o.values, g[f"y_{t}_inj"].values
                c_only, o_only = int(((y == 1) & (yo == 0)).sum()), int(((y == 0) & (yo == 1)).sum())
                recs.append({"question": q, "carrier": CT_KO[t], "original_vs_carrier_length": nm, "n_spans": n,
                             "TPR_original": yo.mean(), "TPR_carrier": y.mean(), "dTPR": y.mean() - yo.mean(),
                             "carrier_only": c_only, "original_only": o_only, "mcnemar_p": mcnemar(c_only, o_only),
                             "median_len_original": float(np.median(g.len_o)), "median_len_carrier": float(np.median(g[f"len_{t}_inj"]))})
    return pd.DataFrame(recs)


def t_stability(P):
    recs = []
    for q in QIDS:
        d = P[q]
        for (ct, lab), g in d.groupby(["carrier_type", "label"]):
            recs.append({"question": q, "carrier": CT_KO["w" if ct == CT["w"] else "e"], "label": lab, "n": len(g),
                         "flip_count": int(g.flip.sum()), "p_sd_mean": g.p_sd.mean(), "p_sd_max": g.p_sd.max(),
                         "p_range_max": float((g[["p_run0", "p_run1", "p_run2"]].max(axis=1) - g[["p_run0", "p_run1", "p_run2"]].min(axis=1)).max()),
                         "rows_within_0.1_of_threshold": int((abs(g.p - THRESHOLD) < 0.1).sum()),
                         "latency_s_mean": g.latency_s.mean(), "input_tokens_mean": g.input_tokens.mean()})
    return pd.DataFrame(recs)


def t_threshold(P, B):
    """Reference only (the project threshold stays 0.5): TPR/FPR at lower thresholds, X3 carriers vs EN 1000."""
    recs = []
    for q in QIDS:
        en = B[q][B[q].set == "EN"]
        sets = [("EN 기준선 전체", en)] + [(CT_KO[t], P[q][P[q].carrier_type == CT[t]]) for t in ("w", "e")]
        for th in (0.5, 0.4, 0.3, 0.2, 0.1):
            for nm, d in sets:
                m = metrics(d.label_int.tolist(), d.p.tolist(), threshold=th)
                recs.append({"question": q, "threshold": th, "set": nm, "n": m["n"], "TPR": m["TPR"], "FPR": m["FPR"]})
    return pd.DataFrame(recs)


def t_slots(W):
    a, b = W["Q2"], W["QL"]
    cols = ["inj_pair_id", "base_uid", "source", "span_subset", "risk_level", "span_end_char", "runon", "span_len", "cid_w", "cid_e", "nreq_e",
            "uid_w_inj", "uid_w_cln", "uid_e_inj", "uid_e_cln", "len_o", "len_w_inj", "len_e_inj", "sep_w", "sep_e"]
    out = a[cols].copy()
    for q, w in (("Q2", a), ("QL", b)):
        for c in ("p_o", "p_w_inj", "p_e_inj", "p_w_cln", "p_e_cln"):
            out[f"{q}_{c}"] = w[c].round(4)
        out[f"{q}_pattern"] = (w.y_o.astype(str) + w.y_w_inj.astype(str) + w.y_e_inj.astype(str)).map(
            lambda s: f"원래{'O' if s[0] == '1' else 'X'}/위키{'O' if s[1] == '1' else 'X'}/Enron{'O' if s[2] == '1' else 'X'}")
    out["span"] = a.span
    return out.reset_index()


def t_examples(W):
    """Spans caught in wiki but missed in Enron under BOTH questions (and the reverse), largest p gap first."""
    a, b = W["Q2"], W["QL"]
    gap = ((a.p_w_inj - a.p_e_inj) + (b.p_w_inj - b.p_e_inj)) / 2
    recs = []
    for kind, mask in (("위키만 탐지 (두 질문 모두)", (a.y_w_inj == 1) & (a.y_e_inj == 0) & (b.y_w_inj == 1) & (b.y_e_inj == 0)),
                       ("Enron만 탐지 (두 질문 모두)", (a.y_w_inj == 0) & (a.y_e_inj == 1) & (b.y_w_inj == 0) & (b.y_e_inj == 1)),
                       ("둘 다 놓침 (두 질문 모두)", (a.y_w_inj == 0) & (a.y_e_inj == 0) & (b.y_w_inj == 0) & (b.y_e_inj == 0))):
        g = a[mask].assign(gap=gap[mask]).sort_values("gap", ascending=(kind.startswith("Enron")))
        for s, r in g.iterrows():
            recs.append({"kind": kind, "slot": s, "inj_pair_id": r.inj_pair_id, "source": r.source, "runon": r.runon,
                         "nreq_enron": r.nreq_e, "Q2_p_original": round(a.p_o[s], 3), "Q2_p_wiki": round(a.p_w_inj[s], 3),
                         "Q2_p_enron": round(a.p_e_inj[s], 3), "QL_p_original": round(b.p_o[s], 3), "QL_p_wiki": round(b.p_w_inj[s], 3),
                         "QL_p_enron": round(b.p_e_inj[s], 3), "span": r.span})
    return pd.DataFrame(recs)


# ------------------------------------------------------------------ figures
def pct(x):
    return f"{100 * x:.0f}%"


def fp(p):
    return "p<0.001" if p < 0.001 else f"p={p:.3f}"


def save(fig, name, lift=0.36):
    """plot_style.save, but tight_layout already reserves room for the suptitle inside rect, so raise the top
    by about the suptitle height; otherwise the gap under the subtitle doubles."""
    h = fig.get_size_inches()[1]
    return S.save(fig, name, top=min(0.97, getattr(fig, "_viz_top", 0.88) + lift / h), out_dir=FIG)


def bars_q(ax, xs, vals, los, his, width=0.36, labels=True, fmt=pct, horizontal=False, ns=None):
    """Grouped bars, one per question (colour = question), with 95% CI whiskers and value labels."""
    for j, q in enumerate(QIDS):
        off = (j - 0.5) * width
        v, lo, hi = np.array(vals[q], float), np.array(los[q], float), np.array(his[q], float)
        pos = np.asarray(xs, float) + off
        if horizontal:
            bs = ax.barh(pos, v, height=width, color=QCOL[q], label=q)
            ax.errorbar(v, pos, xerr=[v - lo, hi - v], fmt="none", ecolor=S.INK_2, elinewidth=1, capsize=2.5)
        else:
            bs = ax.bar(pos, v, width=width, color=QCOL[q], label=q)
            ax.errorbar(pos, v, yerr=[v - lo, hi - v], fmt="none", ecolor=S.INK_2, elinewidth=1, capsize=2.5)
        S.bar_gap(bs)
        if labels:
            for k, (pp, vv, hh) in enumerate(zip(pos, v, hi)):
                if horizontal:
                    ax.text(hh + 0.015, pp, fmt(vv), va="center", ha="left", fontsize=8, color=S.INK_2)
                else:
                    ax.text(pp, hh + 0.015, fmt(vv), ha="center", va="bottom", fontsize=8, color=S.INK_2)


def f01_rates(T1):
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.5, 5.4), gridspec_kw={"width_ratios": [4, 3]})
    cond = ["EN 기준선 전체 (01_baseline)", "같은 span의 원래 문서 (01_baseline, 주입 100)", CT_KO["w"], CT_KO["e"]]
    xl = ["EN 기준선\n전체 주입", "같은 span의\n원래 문서", "위키\n설명문 속", "Enron\n업무 메일 속"]
    v, lo, hi = {}, {}, {}
    for q in QIDS:
        t = T1[T1.question == q].set_index("condition").loc[cond]
        v[q], lo[q], hi[q] = t.TPR.values, t.TPR_lo.values, t.TPR_hi.values
    bars_q(a1, range(4), v, lo, hi)
    ns = T1[T1.question == "Q2"].set_index("condition").loc[cond].n_injection.astype(int).values
    a1.set_xticks(range(4), [f"{x}\n(n={n})" for x, n in zip(xl, ns)])
    a1.set_ylim(0, 1.05)
    a1.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: pct(y)))
    a1.set_ylabel("탐지율 (TPR, p ≥ 0.5)")
    a1.set_title("인젝션 탐지율")
    a1.legend(loc="upper left", ncols=2)
    cond2 = ["EN 기준선 전체 (01_baseline)", CT_KO["w"], CT_KO["e"]]
    xl2 = ["EN 기준선\n정상", "위키\n원문", "Enron\n원문"]
    for q in QIDS:
        t = T1[T1.question == q].set_index("condition").loc[cond2]
        v[q], lo[q], hi[q] = t.FPR.values, t.FPR_lo.values, t.FPR_hi.values
    bars_q(a2, range(3), v, lo, hi, fmt=lambda x: f"{100 * x:.1f}%")
    ns2 = T1[T1.question == "Q2"].set_index("condition").loc[cond2].n_benign.astype(int).values
    a2.set_xticks(range(3), [f"{x}\n(n={n})" for x, n in zip(xl2, ns2)])
    a2.set_ylim(0, 0.1)
    a2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: pct(y)))
    a2.set_ylabel("오탐률 (FPR, p ≥ 0.5)")
    a2.set_title("정상 문서 오탐률")
    w = T1.set_index(["question", "condition"])
    S.title(fig, f"같은 span이 Enron 메일 속에서 위키 속보다 덜 잡힌다: Q2 {pct(w.loc[('Q2', CT_KO['w']), 'TPR'])} → {pct(w.loc[('Q2', CT_KO['e']), 'TPR'])} (경계), "
                 f"QL {pct(w.loc[('QL', CT_KO['w']), 'TPR'])} → {pct(w.loc[('QL', CT_KO['e']), 'TPR'])}",
            "X3: 인젝션 span 100개를 위키 설명문과 Enron 업무 메일(1,200–1,600자) 가운데에 각각 넣음. 막대 = 3회 평균 p 기준, 선 = Wilson 95% CI.\n"
            "원문 carrier 200개는 두 질문 모두 오탐 0건. 원래 문서 = 같은 span이 들어 있던 EN 기준선 문서")
    return save(fig, "f01_rates_by_condition")


def f02_scatter(W, T2):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.6), sharey=True)
    for ax, q in zip(axes, QIDS):
        w = W[q]
        ax.plot([0, 1], [0, 1], color=S.AXIS, lw=1, zorder=1)
        ax.axvline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        ax.axhline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        ax.scatter(w.p_w_inj, w.p_e_inj, s=26, color=QCOL[q], alpha=0.65, edgecolor="white", linewidth=0.5, zorder=3)
        r = T2[(T2.question == q) & (T2.metric.str.startswith("TPR"))].iloc[0]
        # 0.5-threshold combination counts sit above the plotting area so no point is hidden under a label box
        ax.text(0.0, 1.012, f"0.5 기준: 둘 다 탐지 {int(r.both_detected)} · 위키만 탐지 {int(r.wiki_only)} · "
                            f"Enron만 탐지 {int(r.enron_only)} · 둘 다 놓침 {int(r.neither)}",
                transform=ax.transAxes, ha="left", va="bottom", fontsize=9.5, color=S.INK_2)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_aspect("equal")
        ax.set_xlabel("위키 설명문 속 p")
        ax.set_title(f"{q}  (탐지율 {pct(r.wiki)} → {pct(r.enron)}, McNemar {fp(r.p_value)})", color=QCOL[q], pad=22)
    axes[0].set_ylabel("Enron 업무 메일 속 p")
    tt = T2[T2.metric.str.startswith("TPR")].set_index("question")
    S.title(fig, f"같은 span이 Enron 메일 속에서 p가 더 낮은 쪽이 많다 (위키만 탐지 {int(tt.loc['Q2', 'wiki_only'])}·{int(tt.loc['QL', 'wiki_only'])} "
                 f"vs Enron만 탐지 {int(tt.loc['Q2', 'enron_only'])}·{int(tt.loc['QL', 'enron_only'])})",
            "span 100개, 점 하나 = span 하나 (3회 평균 p). 대각선 아래 = Enron 속 p가 더 낮음. 점선 = 임계값 0.5. 패널 제목 아래 = 0.5 기준 판정 조합 개수")
    return save(fig, "f02_wiki_vs_enron_same_span", lift=0.2)


def f03_forest(T2, T3):
    rows = []
    for q in QIDS:
        t2 = T2[T2.question == q].set_index("metric")
        t3 = T3[T3.question == q].set_index("carrier")
        rows += [(q, "Enron − 위키\n탐지율", t2.loc["TPR (탐지율 @0.5)", "diff_enron_minus_wiki"], t2.loc["TPR (탐지율 @0.5)", "ci_lo"], t2.loc["TPR (탐지율 @0.5)", "ci_hi"], t2.loc["TPR (탐지율 @0.5)", "p_value"]),
                 (q, "Enron − 위키\n주입 평균 p", t2.loc["주입 행 평균 p", "diff_enron_minus_wiki"], t2.loc["주입 행 평균 p", "ci_lo"], t2.loc["주입 행 평균 p", "ci_hi"], None),
                 (q, "Enron − 위키\n원문 평균 p", t2.loc["원문 평균 p (서로 다른 carrier)", "diff_enron_minus_wiki"], t2.loc["원문 평균 p (서로 다른 carrier)", "ci_lo"], t2.loc["원문 평균 p (서로 다른 carrier)", "ci_hi"], None),
                 (q, "위키 − 원래 문서\n탐지율", t3.loc[CT_KO["w"], "dTPR"], t3.loc[CT_KO["w"], "dTPR_lo"], t3.loc[CT_KO["w"], "dTPR_hi"], t3.loc[CT_KO["w"], "mcnemar_p"]),
                 (q, "Enron − 원래 문서\n탐지율", t3.loc[CT_KO["e"], "dTPR"], t3.loc[CT_KO["e"], "dTPR_lo"], t3.loc[CT_KO["e"], "dTPR_hi"], t3.loc[CT_KO["e"], "mcnemar_p"]),
                 (q, "위키 − 원래 문서\n평균 p", t3.loc[CT_KO["w"], "dmean_p"], t3.loc[CT_KO["w"], "dmean_p_lo"], t3.loc[CT_KO["w"], "dmean_p_hi"], None),
                 (q, "Enron − 원래 문서\n평균 p", t3.loc[CT_KO["e"], "dmean_p"], t3.loc[CT_KO["e"], "dmean_p_lo"], t3.loc[CT_KO["e"], "dmean_p_hi"], None)]
    names = list(dict.fromkeys(r[1] for r in rows))
    fig, ax = plt.subplots(figsize=(10.5, 7.2))
    for (q, nm, d, lo, hi, p) in rows:
        y = names.index(nm) + (-0.17 if q == "Q2" else 0.17)
        ax.plot([lo, hi], [y, y], color=QCOL[q], lw=2.2, solid_capstyle="round")
        ax.scatter([d], [y], color=QCOL[q], s=46, zorder=3, edgecolor="white", linewidth=0.8, label=q if nm == names[0] else None)
        lab = f"{d:+.2f} [{lo:+.2f}, {hi:+.2f}]" + (f"  McNemar {fp(p)}" if p is not None else "")
        ax.text(1.01, y, lab, transform=blended_transform_factory(ax.transAxes, ax.transData), va="center", fontsize=8.5, color=QCOL[q])
    ax.axvline(0, color=S.INK_2, lw=1)
    for k in range(1, len(names)):
        ax.axhline(k - 0.5, color=S.GRID, lw=0.6)
    ax.set_yticks(range(len(names)), names)
    ax.invert_yaxis()
    ax.set_xlim(-0.45, 0.45)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("차이 (탐지율은 비율, 평균 p는 확률 단위). 0 = 차이 없음")
    ax.legend(loc="upper right", ncols=2)
    S.title(fig, "Enron 속 평균 p 하락은 두 질문 모두 뚜렷하고, 탐지율 하락은 QL에서만 CI가 0을 벗어난다",
            "같은 span끼리 짝지은 차이와 95% CI (span 100개 paired bootstrap 1,000회, seed 20261112). 원문 평균 p는 서로 다른\n"
            "carrier라 짝 없이 bootstrap. 원래 문서 = 같은 span이 있던 EN 기준선 문서. 오른쪽 = 차이 [95% CI]")
    path = os.path.join(FIG, "f03_paired_differences.png")
    top = min(0.97, getattr(fig, "_viz_top", 0.88) + 0.36 / fig.get_size_inches()[1])
    fig.tight_layout(rect=(0, 0, 0.72, top))
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def f04_strip(W, T1):
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4), sharey=True)
    rng = np.random.default_rng(SEED)
    groups = [("w", "inj", "인젝션"), ("w", "cln", "정상"), ("e", "inj", "인젝션"), ("e", "cln", "정상")]
    for ax, q in zip(axes, QIDS):
        w = W[q]
        for k, (t, l, lab) in enumerate(groups):
            x = k + (k >= 2) * 0.5
            vals = w[f"p_{t}_{l}"].values
            ax.scatter(x + rng.uniform(-0.18, 0.18, len(vals)), vals, s=14, color=LCOL[lab], alpha=0.55, edgecolor="none")
            m = vals.mean()
            ax.plot([x - 0.26, x + 0.26], [m, m], color=S.INK, lw=2)
            ax.text(x + 0.3, m, f"평균 {m:.2f}", va="center", fontsize=8.5, color=S.INK)
        ax.axhline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        t = T1[(T1.question == q)].set_index("condition")
        mx = t.loc[CT_KO["e"], "max_p_benign"]
        ax.plot([2.2, 3.8], [mx, mx], color=S.INK_2, lw=1, ls=":")  # highest clean Enron p
        ax.set_xticks([0, 1, 2.5, 3.5], ["위키\n+ span", "위키\n원문", "Enron\n+ span", "Enron\n원문"])
        ax.set_xlim(-0.5, 4.2)
        ax.set_title(f"{q}  (Enron 주입 {int(t.loc[CT_KO['e'], 'n_injection_below_max_benign'])}개가 Enron 원문 최고 p {mx:.2f}보다 낮음)",
                     color=QCOL[q], fontsize=11)
        ax.text(0.5, -0.17, f"짝 판별률 {t.loc[CT_KO['w'], 'paired_disc']:.3f}", transform=blended_transform_factory(ax.transData, ax.transAxes),
                ha="center", fontsize=8.5, color=S.INK_2)
        ax.text(3.0, -0.17, f"짝 판별률 {t.loc[CT_KO['e'], 'paired_disc']:.3f}", transform=blended_transform_factory(ax.transData, ax.transAxes),
                ha="center", fontsize=8.5, color=S.INK_2)
    axes[0].set_ylabel("Jev p (3회 평균)")
    axes[0].set_ylim(-0.03, 1.03)
    S.title(fig, "원문은 모두 0.5 아래, 놓친 인젝션은 0.5 바로 아래가 아니라 넓게 퍼져 있다",
            "carrier 200개 × (span 넣은 행, 원문 행). 가로선 = 평균, 점선 = 임계값 0.5, 짧은 점선 = Enron 원문 100개 중 최고 p.\n"
            "짝 판별률 = p(주입) > p(자기 원문)인 carrier 비율 (같은 문서의 깨끗한 사본이 있어야 쓸 수 있는 값)")
    return save(fig, "f04_p_by_carrier_and_label")


def f05_length(P, T7):
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.9), gridspec_kw={"width_ratios": [1.1, 1, 1]})
    d = P["Q2"]
    rng = np.random.default_rng(SEED)
    ax = axes[0]
    for k, (ct, lab, l) in enumerate([(CT["w"], "인젝션", 1), (CT["w"], "정상", 0), (CT["e"], "인젝션", 1), (CT["e"], "정상", 0)]):
        x = k + (k >= 2) * 0.5
        v = d[(d.carrier_type == ct) & (d.label_int == l)].char_len.values
        ax.scatter(x + rng.uniform(-0.18, 0.18, len(v)), v, s=12, color=LCOL[lab], alpha=0.55, edgecolor="none")
        ax.plot([x - 0.26, x + 0.26], [np.median(v)] * 2, color=S.INK, lw=2)
    ax.set_xticks([0, 1, 2.5, 3.5], ["위키\n+ span", "위키\n원문", "Enron\n+ span", "Enron\n원문"])
    ax.set_ylabel("글자 수")
    t = T7.set_index("question").loc["Q2"]
    ax.set_title(f"길이만으로 맞히는 AUC {t.length_only_AUC_all:.3f}")
    for ax, q in zip(axes[1:], QIDS):
        d = P[q]
        t = T7.set_index("question").loc[q]
        for lab, l in (("정상", 0), ("인젝션", 1)):
            g = d[d.label_int == l]
            ax.scatter(g.char_len, g.p, s=12, color=LCOL[lab], alpha=0.55, edgecolor="none", label=lab)
        ax.axhline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        ax.set_xlabel("글자 수")
        ax.set_title(f"{q}: Jev AUC {t.jev_AUC_all:.3f}", color=QCOL[q])
        ax.text(0.98, 0.33, f"길이-p Spearman ρ\n원문 행 {t.spearman_p_len_clean:+.2f}\n주입 행 {t.spearman_p_len_injection:+.2f}",
                transform=ax.transAxes, ha="right", va="center", fontsize=8.5, color=S.INK_2,
                bbox=dict(boxstyle="round,pad=0.3", fc=S.SURFACE, ec=S.GRID))
        ax.set_ylim(-0.03, 1.03)
    axes[1].set_ylabel("Jev p")
    axes[1].legend(loc="center right", bbox_to_anchor=(1.0, 0.62), frameon=True, facecolor=S.SURFACE, edgecolor=S.GRID)
    t = T7.set_index("question").loc["Q2"]
    S.title(fig, f"주입 행이 span 길이만큼 길어 길이만으로도 AUC {t.length_only_AUC_all:.2f}, 그래서 같은 carrier끼리 짝지어 비교했다",
            f"X3 400행. 주입 행은 자기 원문보다 항상 길다(100%). 원문 행은 길수록 p가 오히려 조금 낮고(ρ {t.spearman_p_len_clean:+.2f}), 주입 행의 양의 상관은\n"
            f"주로 span이 길수록 p가 높아서다(span 길이-p ρ: 위키 {t.spearman_p_spanlen_wiki:+.2f}, Enron {t.spearman_p_spanlen_enron:+.2f}, Q2). Jev AUC 0.99와 비교")
    return save(fig, "f05_length_confound")


def f06_vs_original(W, T3):
    fig, axes = plt.subplots(2, 2, figsize=(10.5, 10), sharex=True, sharey=True)
    for i, q in enumerate(QIDS):
        w = W[q]
        for j, t in enumerate(("w", "e")):
            ax = axes[i, j]
            r = T3[(T3.question == q) & (T3.carrier == CT_KO[t])].iloc[0]
            ax.plot([0, 1], [0, 1], color=S.AXIS, lw=1)
            ax.axvline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
            ax.axhline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
            ax.scatter(w.p_o, w[f"p_{t}_inj"], s=22, color=QCOL[q], alpha=0.65, edgecolor="white", linewidth=0.5)
            ax.text(0.0, 1.012, f"0.5 기준: carrier에서만 탐지 {int(r.carrier_only)} · 원래 문서에서만 탐지 {int(r.original_only)}",
                    transform=ax.transAxes, ha="left", va="bottom", fontsize=9, color=S.INK_2)
            ax.set_title(f"{q} · {CT_KO[t]}  (탐지율 {pct(r.TPR_original)} → {pct(r.TPR_carrier)}, McNemar {fp(r.mcnemar_p)})",
                         color=QCOL[q], fontsize=10.5, pad=20)
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(-0.02, 1.02)
            ax.set_aspect("equal")
            if i == 1:
                ax.set_xlabel("원래 문서(EN 기준선) 속 p")
            if j == 0:
                ax.set_ylabel("carrier 가운데 넣었을 때 p")
    w = W["Q2"]
    S.title(fig, "span을 원래 문서에서 꺼내 위키 설명문 가운데 넣으면 더 잘 잡힌다 (Enron 메일은 오차 범위)",
            f"span 100개. x = 같은 span이 들어 있던 EN 기준선 문서의 p, y = carrier 속 p. 대각선 위 = carrier에서 p 상승.\n"
            f"원래 문서 길이 중앙값 {w.len_o.median():,.0f}자 (범위 {w.len_o.min():,.0f}–{w.len_o.max():,.0f}), carrier 주입 행 "
            f"{min(w.len_w_inj.min(), w.len_e_inj.min()):,.0f}–{max(w.len_w_inj.max(), w.len_e_inj.max()):,.0f}자. "
            f"위치·길이·주변 내용이 함께 바뀐 비교")
    return save(fig, "f06_carrier_vs_original_document")


def f07_source(T4):
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.4), sharey=True)
    for ax, (nm, title_) in zip(axes, (("original", "원래 문서 (EN 기준선)"), ("wiki", "위키 설명문 속"), ("enron", "Enron 업무 메일 속"))):
        v, lo, hi = {}, {}, {}
        for q in QIDS:
            t = T4[T4.question == q].set_index("source").loc[SOURCES]
            v[q], lo[q], hi[q] = t[f"TPR_{nm}"].values, t[f"TPR_{nm}_lo"].values, t[f"TPR_{nm}_hi"].values
        bars_q(ax, range(len(SOURCES)), v, lo, hi, horizontal=True, width=0.38)
        ax.set_xlim(0, 1.18)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda x, _: pct(x) if x <= 1 else ""))
        ax.set_title(title_)
        ax.set_xlabel("탐지율 (p ≥ 0.5)")
    n = T4[T4.question == "Q2"].set_index("source").loc[SOURCES].n_spans.astype(int)
    axes[0].set_yticks(range(len(SOURCES)), [f"{s}\n(span {k})" for s, k in zip(SOURCES, n)])
    axes[0].invert_yaxis()
    axes[0].legend(loc="lower right")
    S.title(fig, "출처마다 방향이 반대다: LLMail·BrowseSafe·InjecAgent는 Enron 속에서 떨어지고 SEP는 오른다",
            "span 출처별 탐지율과 Wilson 95% CI. 같은 span이 세 조건에 모두 들어 있다. 출처당 span 16–24개라 CI가 넓다 (McNemar는 t04 표)")
    return save(fig, "f07_by_span_source")


def f08_nreq(T5):
    t5 = T5[~T5.enron_requests.str.startswith("spearman")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.0))
    bins = [b for b, _ in NREQ_BINS]
    n = t5[t5.question == "Q2"].set_index("enron_requests").loc[bins].n_carriers.astype(int).values
    xt = [f"{b}개\n(carrier {k})" for b, k in zip(bins, n)]
    for ax, (col, ttl) in zip(axes[:2], (("TPR_enron", "Enron 메일 속 탐지율"), ("TPR_wiki_same_spans", "같은 span을 위키에 넣었을 때"))):
        v, lo, hi = {}, {}, {}
        for q in QIDS:
            t = t5[t5.question == q].set_index("enron_requests").loc[bins]
            v[q] = t[col].values
            lo[q] = t["TPR_enron_lo" if col == "TPR_enron" else "TPR_wiki_lo"].values
            hi[q] = t["TPR_enron_hi" if col == "TPR_enron" else "TPR_wiki_hi"].values
        bars_q(ax, range(3), v, lo, hi)
        ax.set_ylim(0, 1.1)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: pct(y) if y <= 1 else ""))
        ax.set_xticks(range(3), xt)
        ax.set_title(ttl)
        ax.set_xlabel("Enron carrier의 요청 문장 수")
    axes[0].set_ylabel("탐지율 (p ≥ 0.5)")
    axes[0].legend(loc="upper left", ncols=2)
    ax = axes[2]
    for j, q in enumerate(QIDS):
        t = t5[t5.question == q].set_index("enron_requests").loc[bins]
        x = np.arange(3) + (j - 0.5) * 0.36
        bs = ax.bar(x, t.mean_p_clean_enron.values, width=0.36, color=QCOL[q], label=q)
        S.bar_gap(bs)
        ax.scatter(x, t.max_p_clean_enron.values, marker="_", s=160, color=S.INK, zorder=3)
        for xx, m, mx in zip(x, t.mean_p_clean_enron.values, t.max_p_clean_enron.values):
            ax.text(xx, mx + 0.012, f"최대\n{mx:.2f}", ha="center", va="bottom", fontsize=7.5, color=S.INK_2)
    ax.set_xticks(range(3), xt)
    ax.set_ylim(0, 0.5)
    ax.set_title("Enron 원문(정상)의 평균 p")
    ax.set_xlabel("Enron carrier의 요청 문장 수")
    ax.set_ylabel("p (막대 = 평균, 검은 선 = 최대)")
    rho = T5[T5.enron_requests.str.startswith("spearman")].set_index("question")
    S.title(fig, "요청 문장이 많을수록 더 놓치지는 않는다: 위키 대비 하락은 요청 3개짜리 메일에 몰려 있다",
            f"Enron carrier만 해당(위키는 모두 0개). Spearman ρ(요청 수, Enron 속 p): Q2 {rho.loc['Q2', 'rho_p_inj']:+.2f} (p={rho.loc['Q2', 'rho_p_inj_pvalue']:.2f}), "
            f"QL {rho.loc['QL', 'rho_p_inj']:+.2f} (p={rho.loc['QL', 'rho_p_inj_pvalue']:.2f}).\n가운데 = 같은 span을 위키에 넣었을 때의 탐지율(짝 비교 기준). 요청 수는 정규식으로 센 대략값")
    return save(fig, "f08_by_enron_request_count")


def f09_q2_ql(W, T6):
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.0), sharey=True)
    for ax, (t, ttl) in zip(axes, (("o", "원래 문서 (EN 기준선)"), ("w", "위키 설명문"), ("e", "Enron 업무 메일"))):
        ax.plot([0, 1], [0, 1], color=S.AXIS, lw=1)
        ax.axvline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        ax.axhline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        groups = [("인젝션", "p_o")] if t == "o" else [("정상", f"p_{t}_cln"), ("인젝션", f"p_{t}_inj")]
        for lab, col in groups:
            ax.scatter(W["Q2"][col], W["QL"][col], s=18, color=LCOL[lab], alpha=0.6, edgecolor="none", label=lab)
        nm = {"o": "원래 문서 · 주입", "w": "위키 · 주입", "e": "Enron · 주입"}[t]
        r = T6.set_index("rows").loc[nm]
        ax.text(0.02, 0.98, f"QL만 탐지 {int(r.QL_only)}\nQ2만 탐지 {int(r.Q2_only)}\nΔTPR {r.diff_QL_minus_Q2:+.2f} [{r.ci_lo:+.2f}, {r.ci_hi:+.2f}]\nMcNemar {fp(r.mcnemar_p)}",
                transform=ax.transAxes, ha="left", va="top", fontsize=8.5, bbox=dict(boxstyle="round,pad=0.3", fc=S.SURFACE, ec=S.GRID))
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_aspect("equal")
        ax.set_title(ttl)
        ax.set_xlabel("Q2 (짧은 질문) p")
    axes[0].set_ylabel("QL (정의형 긴 질문) p")
    axes[1].legend(loc="lower right")
    d = T6.set_index("rows").loc[DID_ROW]
    S.title(fig, "정의형 긴 질문(QL)은 세 조건 모두 탐지율을 조금 올리고(CI가 0 밖인 것은 위키뿐), 그 이득은 carrier에 따라 다르지 않다",
            f"같은 행을 두 질문으로 판정. 점 하나 = 행 하나(span 100개 / 원문 100개). 대각선 위 = QL에서 p 상승. ΔTPR CI = paired bootstrap.\n"
            f"(Enron − 위키) 탐지율 차이의 QL − Q2 = {d.diff_QL_minus_Q2:+.2f} [{d.ci_lo:+.2f}, {d.ci_hi:+.2f}]. "
            f"QL 문구에는 '동료에게 하는 요청은 AI 비서를 향한 것이 아니면 인젝션이 아니다'라는 기준이 이미 들어 있다")
    return save(fig, "f09_q2_vs_ql", lift=0.12)


def f10_runon(T8, W):
    t8 = T8[(T8.grouping == RUNON_MAIN) & (T8.row_type == "group")]
    ro = W["Q2"][W["Q2"].runon].source.value_counts()
    sep_w, sep_e = W["Q2"].sep_w.value_counts(), W["Q2"].sep_e.value_counts()
    sep_txt = (f"위키 {sep_w.get('space/space', 0)}개는 앞뒤가 공백(run-on이면 다음 문장과 한 문장처럼 읽힘), "
               f"Enron {sep_e.get('newline/newline', 0)}개는 앞뒤가 줄바꿈인 독립된 줄")
    fig, axes = plt.subplots(1, 4, figsize=(15.5, 5.3), gridspec_kw={"width_ratios": [1, 1, 1, 1.05]})
    ends = [RUNON_END[False], RUNON_END[True]]
    t0 = t8[t8.question == "Q2"].set_index("span_end").loc[ends]
    n = t0.n_spans.astype(int).values
    nq = int(t0.loc[RUNON_END[False], "n_end_question"])
    xt = [f"문장부호로 끝남\n(span {n[0]})", f"문장부호 없음\n(span {n[1]})"]
    for k, (ax, (nm, ttl)) in enumerate(zip(axes[:3], (("original", "원래 문서 (EN 기준선)"), ("wiki", "위키 설명문 속"), ("enron", "Enron 업무 메일 속")))):
        v, lo, hi = {}, {}, {}
        for q in QIDS:
            t = t8[t8.question == q].set_index("span_end").loc[ends]
            v[q], lo[q], hi[q] = t[f"TPR_{nm}"].values, t[f"TPR_{nm}_lo"].values, t[f"TPR_{nm}_hi"].values
        bars_q(ax, range(2), v, lo, hi)
        ax.set_xticks(range(2), xt)
        ax.set_ylim(0, 1.12)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: pct(y) if y <= 1 else ""))
        if k:
            ax.tick_params(labelleft=False)
        ax.set_title(ttl)
    axes[0].set_ylabel("탐지율 (p ≥ 0.5)")
    axes[0].legend(loc="upper left", ncols=2)
    # mean p of the injected rows, enron - wiki (paired, slot bootstrap within the group)
    ax = axes[3]
    for j, q in enumerate(QIDS):
        t = t8[t8.question == q].set_index("span_end").loc[ends]
        x = np.arange(2) + (j - 0.5) * 0.3
        d, lo, hi = t.dmean_p_enron_minus_wiki.values, t.dmean_p_lo.values, t.dmean_p_hi.values
        ax.errorbar(x, d, yerr=[d - lo, hi - d], fmt="o", color=QCOL[q], ecolor=QCOL[q], elinewidth=2, capsize=3, label=q)
        for xx, dd, ll, hh in zip(x, d, lo, hi):  # Q2 labels to the left of its point, QL to the right
            ax.text(xx + (-0.06 if j == 0 else 0.06), dd, f"{dd:+.3f}\n[{ll:+.3f}, {hh:+.3f}]", ha="right" if j == 0 else "left",
                    va="center", fontsize=7.8, color=QCOL[q])
    ax.axhline(0, color=S.INK_2, lw=1)
    ax.set_xticks(range(2), xt)
    ax.set_xlim(-0.75, 1.75)
    ax.set_ylim(-0.5, 0.1)
    ax.set_ylabel("Enron − 위키 주입 평균 p (짝 차이)")
    ax.set_title("주입 평균 p 차이 (95% CI)")
    S.title(fig, f"0.5 기준 탐지율 차이는 문장부호 없이 끝나는 span {n[1]}개에 몰려 있지만, 나머지 {n[0]}개에서도 Enron 속 평균 p는 낮다",
            f"run-on = span 끝 문자(닫는 따옴표·괄호 제외)가 . ? ! 가 아님. ?로 끝나는 {nq}개는 문장 끝으로 셌다. run-on {n[1]}개 중 {ro.iloc[0]}개가 {ro.index[0]}라 "
            f"출처와 겹친다.\n삽입 경계: {sep_txt}. 막대 = Wilson 95% CI, 오른쪽 = slot paired bootstrap 95% CI (seed 20261112)")
    return save(fig, "f10_run_on_spans")


def f11_gap(W, T1):
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.0), sharey=True)
    rng = np.random.default_rng(SEED)
    for ax, q in zip(axes, QIDS):
        w = W[q]
        for k, t in enumerate(("w", "e")):
            g = (w[f"p_{t}_inj"] - w[f"p_{t}_cln"]).values
            ax.scatter(k + rng.uniform(-0.2, 0.2, len(g)), g, s=16, color=QCOL[q], alpha=0.55, edgecolor="none")
            bp = ax.boxplot([g], positions=[k], widths=0.5, showfliers=False, patch_artist=True,
                            boxprops=dict(facecolor="none", edgecolor=S.INK, linewidth=1.2), medianprops=dict(color=S.INK, linewidth=2),
                            whiskerprops=dict(color=S.INK_2), capprops=dict(color=S.INK_2))
            r = T1[(T1.question == q) & (T1.condition == CT_KO[t])].iloc[0]
            ax.text(k, 1.04, f"평균 간격 {r.mean_gap_inj_minus_clean:.2f} [{r.gap_lo:.2f}, {r.gap_hi:.2f}]\n최소 {r.min_gap:+.2f}",
                    ha="center", va="bottom", fontsize=8.5, color=S.INK_2)
            del bp
        ax.axhline(0, color=S.INK_2, lw=1)
        ax.set_xticks([0, 1], ["위키 설명문", "Enron 업무 메일"])
        ax.set_xlim(-0.6, 1.6)
        ax.set_ylim(-0.08, 1.22)
        ax.set_title(q, color=QCOL[q], loc="left")
    axes[0].set_ylabel("p(span 넣은 행) − p(자기 원문)")
    t = T1.set_index(["question", "condition"])
    ke = [int(t.loc[(q, CT_KO["e"]), "n_injection_below_max_benign"]) for q in QIDS]
    me = [t.loc[(q, CT_KO["e"]), "max_p_benign"] for q in QIDS]
    S.title(fig, "같은 carrier 안에서는 span을 넣은 쪽 p가 거의 항상 높지만, 이 비교는 같은 문서의 깨끗한 사본이 있어야 가능하다",
            f"carrier 100개씩. 0보다 크면 span을 넣은 쪽 p가 높다. 평균 간격 [paired bootstrap 95% CI]. 다른 원문들과 비교하면 Enron 주입 행 "
            f"{ke[0]}개(Q2)·{ke[1]}개(QL)가\nEnron 원문 100개의 최고 p({me[0]:.2f}·{me[1]:.2f})보다 낮아, 원문 오탐 없이 이들을 잡는 임계값은 없다 (f04)")
    return save(fig, "f11_paired_gap_within_carrier")


def f12_stability(P):
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6), sharey=True)
    for ax, q in zip(axes, QIDS):
        d = P[q]
        for lab, l in (("정상", 0), ("인젝션", 1)):
            g = d[d.label_int == l]
            rr = g[["p_run0", "p_run1", "p_run2"]].max(axis=1) - g[["p_run0", "p_run1", "p_run2"]].min(axis=1)
            ax.scatter(g.p, rr, s=14, color=LCOL[lab], alpha=0.6, edgecolor="none", label=lab)
        ax.axvline(THRESHOLD, color=S.MUTED, lw=0.8, ls="--")
        ax.set_xlabel("3회 평균 p")
        ax.set_title(f"{q}: 3회 중 판정이 갈린 행 {int(d.flip.sum())}개 / 400", color=QCOL[q])
    axes[0].set_ylabel("3회 호출 p의 범위 (최대 − 최소)")
    axes[0].legend(loc="upper left")
    rmax = max(float((P[q][["p_run0", "p_run1", "p_run2"]].max(axis=1) - P[q][["p_run0", "p_run1", "p_run2"]].min(axis=1)).max()) for q in QIDS)
    flips = sorted(int(P[q].flip.sum()) for q in QIDS)
    S.title(fig, f"반복 호출 흔들림(3회 범위 최대 {rmax:.2f})은 400행 중 {flips[0]}–{flips[1]}행의 판정만 바꾼다",
            "X3 400행 × 3회 호출. API에 seed가 없어 같은 입력도 p가 조금씩 다르다. 판정 갈림 = 3회 중 0.5 위·아래가 섞인 행")
    return save(fig, "f12_repeat_stability")


# ------------------------------------------------------------------ main
def main():
    S.setup()
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    rows, P, B, W = load()

    T1 = t_metrics(P, B, W)
    T2 = t_wiki_vs_enron(W)
    T3 = t_vs_original(W)
    T4 = t_by_group(W, "source", SOURCES)
    T5 = t_nreq(W)
    T6 = t_q2_vs_ql(W)
    T7 = t_length(P, W)
    T8 = t_runon(W)
    T9 = t_by_group(W, "risk_level", sorted(W["Q2"].risk_level.unique()))
    T10 = t_stability(P)
    T11 = t_slots(W)
    T12 = t_examples(W)
    T13 = t_by_group(W, "doc_type_o", sorted(W["Q2"].doc_type_o.unique()))
    T14 = t_threshold(P, B)
    T15 = t_vs_original_by_length(W)
    tables = {"t01_metrics_by_condition": T1, "t02_wiki_vs_enron_paired": T2, "t03_carrier_vs_original_document": T3,
              "t04_by_span_source": T4, "t05_by_enron_request_count": T5, "t06_q2_vs_ql": T6, "t07_length_confound": T7,
              "t08_run_on_spans": T8, "t09_by_risk_level": T9, "t10_repeat_stability": T10, "t11_per_span": T11,
              "t12_examples": T12, "t13_by_original_doc_type": T13, "t14_threshold_reference": T14,
              "t15_vs_original_by_length": T15}
    for name, t in tables.items():
        t.round(6).to_csv(os.path.join(TAB, f"{name}.csv"), index=False, encoding="utf-8-sig")

    figs = [f01_rates(T1), f02_scatter(W, T2), f03_forest(T2, T3), f04_strip(W, T1), f05_length(P, T7), f06_vs_original(W, T3),
            f07_source(T4), f08_nreq(T5), f09_q2_ql(W, T6), f10_runon(T8, W), f11_gap(W, T1), f12_stability(P)]

    # ---- summary.json: keep every key run_api.py wrote, replace only "analysis"
    sp = os.path.join(OUT, "summary.json")
    s = json.load(open(sp, encoding="utf-8"))
    an = {"script": "experiments/analyze_X3_distractor.py", "commit": J.git_commit(),
          "inputs_md5": {os.path.relpath(p, J.REPO).replace("\\", "/"): md5(p) for p in
                         [DATA_X3] + [os.path.join(OUT, f"{q}_predictions.csv") for q in QIDS] + [os.path.join(BASE, f"{q}_predictions.csv") for q in QIDS]},
          "statistics": {"threshold": THRESHOLD, "ci": "Wilson 95% for rates; percentile 95% for bootstrap",
                         "paired_bootstrap": {"unit": "slot (span + its wiki and enron carriers)", "resamples": NBOOT, "seed": SEED},
                         "paired_test": "exact McNemar (two-sided binomial on discordant pairs)",
                         "unpaired_fpr_test": "Fisher exact + Newcombe hybrid score CI",
                         "paired_discrimination": "share of carriers with p(injection row) > p(own clean carrier), ties = 0.5"},
          "n": {"slots": 100, "rows": 400, "wiki_carriers": 100, "enron_carriers": 100, "run_on_spans": int(W["Q2"].runon.sum()),
                "run_on_rule": "last character after closing quotes/brackets is not one of . ? ! (a '?' ending counts as a sentence end)",
                "span_end_char": {k: int(v) for k, v in W["Q2"].span_end_char.value_counts().items()},
                "run_on_by_source": {k: int(v) for k, v in W["Q2"][W["Q2"].runon].source.value_counts().items()},
                "insert_boundary_wiki": {k: int(v) for k, v in W["Q2"].sep_w.value_counts().items()},
                "insert_boundary_enron": {k: int(v) for k, v in W["Q2"].sep_e.value_counts().items()}},
          "tables": [f"tables/{n}.csv" for n in tables], "figures": [os.path.relpath(f, OUT).replace("\\", "/") for f in figs]}
    for q in QIDS:
        t1 = T1[T1.question == q].set_index("condition")
        t2 = T2[T2.question == q].set_index("metric")
        t3 = T3[T3.question == q].set_index("carrier")
        t7 = T7.set_index("question").loc[q]
        t5 = T5[(T5.question == q) & (T5.enron_requests.str.startswith("spearman"))].iloc[0]
        by = {}
        for cond, key in ((CT_KO["w"], "wiki"), (CT_KO["e"], "enron"), ("X3 전체 (위키+Enron)", "all")):
            r = t1.loc[cond]
            by[key] = {"TPR": rnd(r.TPR), "TPR_ci95": [rnd(r.TPR_lo), rnd(r.TPR_hi)], "FPR": rnd(r.FPR), "FPR_ci95": [rnd(r.FPR_lo), rnd(r.FPR_hi)],
                       "AUC": rnd(r.AUC), "AUC_ci95": [rnd(r.AUC_lo), rnd(r.AUC_hi)], "paired_discrimination": rnd(r.paired_disc),
                       "paired_discrimination_ci95": [rnd(r.paired_disc_lo), rnd(r.paired_disc_hi)],
                       "mean_p_injection": rnd(r.mean_p_injection), "mean_p_clean": rnd(r.mean_p_benign), "max_p_clean": rnd(r.max_p_benign),
                       "n_injection_below_max_clean": int(r.n_injection_below_max_benign), "n_injection_p_below_0.1": int(r["n_injection_p_below_0.1"]),
                       "length_only_AUC": rnd(r.length_only_AUC), "dTPR_vs_EN1000": rnd(r.dTPR_vs_EN1000),
                       "dTPR_vs_EN1000_ci95_approx": [rnd(r.dTPR_vs_EN1000_lo), rnd(r.dTPR_vs_EN1000_hi)],
                       "dFPR_vs_EN1000": rnd(r.dFPR_vs_EN1000), "dAUC_vs_EN1000": rnd(r.dAUC_vs_EN1000)}
        r0 = t1.loc["EN 기준선 전체 (01_baseline)"]
        ro = t1.loc["같은 span의 원래 문서 (01_baseline, 주입 100)"]
        tp = t2.loc["TPR (탐지율 @0.5)"]
        mp = t2.loc["주입 행 평균 p"]
        an[q] = {"by_carrier": by,
                 "EN1000_baseline": {"TPR": rnd(r0.TPR), "FPR": rnd(r0.FPR), "AUC": rnd(r0.AUC)},
                 "original_documents_same_spans": {"TPR": rnd(ro.TPR), "TPR_ci95": [rnd(ro.TPR_lo), rnd(ro.TPR_hi)], "mean_p": rnd(ro.mean_p_injection)},
                 "enron_minus_wiki": {"dTPR": rnd(tp.diff_enron_minus_wiki), "dTPR_ci95": [rnd(tp.ci_lo), rnd(tp.ci_hi)],
                                      "mcnemar_p": rnd(tp.p_value), "wiki_only": int(tp.wiki_only), "enron_only": int(tp.enron_only),
                                      "both": int(tp.both_detected), "neither": int(tp.neither),
                                      "dmean_p": rnd(mp.diff_enron_minus_wiki), "dmean_p_ci95": [rnd(mp.ci_lo), rnd(mp.ci_hi)],
                                      "dAUC": rnd(t2.loc["AUC (주입 vs 같은 종류 원문)", "diff_enron_minus_wiki"]),
                                      "dAUC_ci95": [rnd(t2.loc["AUC (주입 vs 같은 종류 원문)", "ci_lo"]), rnd(t2.loc["AUC (주입 vs 같은 종류 원문)", "ci_hi"])],
                                      "dFPR": rnd(t2.loc["FPR (원문, 서로 다른 carrier)", "diff_enron_minus_wiki"]),
                                      "dFPR_fisher_p": rnd(t2.loc["FPR (원문, 서로 다른 carrier)", "p_value"]),
                                      "dmean_p_clean": rnd(t2.loc["원문 평균 p (서로 다른 carrier)", "diff_enron_minus_wiki"]),
                                      "dmean_p_clean_ci95": [rnd(t2.loc["원문 평균 p (서로 다른 carrier)", "ci_lo"]), rnd(t2.loc["원문 평균 p (서로 다른 carrier)", "ci_hi"])]},
                 "carrier_minus_original": {k: {"dTPR": rnd(t3.loc[CT_KO[t], "dTPR"]), "dTPR_ci95": [rnd(t3.loc[CT_KO[t], "dTPR_lo"]), rnd(t3.loc[CT_KO[t], "dTPR_hi"])],
                                                "mcnemar_p": rnd(t3.loc[CT_KO[t], "mcnemar_p"]), "carrier_only": int(t3.loc[CT_KO[t], "carrier_only"]),
                                                "original_only": int(t3.loc[CT_KO[t], "original_only"]),
                                                "dmean_p": rnd(t3.loc[CT_KO[t], "dmean_p"]), "dmean_p_ci95": [rnd(t3.loc[CT_KO[t], "dmean_p_lo"]), rnd(t3.loc[CT_KO[t], "dmean_p_hi"])]}
                                            for t, k in (("w", "wiki"), ("e", "enron"))},
                 "length": {"length_only_AUC_all": rnd(t7.length_only_AUC_all), "length_only_AUC_wiki": rnd(t7.length_only_AUC_wiki),
                            "length_only_AUC_enron": rnd(t7.length_only_AUC_enron),
                            "length_AUC_wiki_vs_enron_injection_rows": rnd(t7.length_AUC_wiki_vs_enron_injection_rows),
                            "share_pairs_injection_longer": rnd(t7.share_pairs_injection_longer),
                            "spearman_p_len_clean": rnd(t7.spearman_p_len_clean), "spearman_p_len_injection": rnd(t7.spearman_p_len_injection),
                            "original_doc_len": {"min": int(t7.min_len_original), "median": rnd(t7.median_len_original, 1),
                                                 "mean": rnd(t7.mean_len_original, 1), "max": int(t7.max_len_original)},
                            "n_spans_original_shorter_than_wiki_inj": int(t7.n_spans_original_shorter_than_wiki_inj),
                            "n_spans_original_shorter_than_enron_inj": int(t7.n_spans_original_shorter_than_enron_inj)},
                 "run_on_sensitivity": {row.span_end: {"n": int(row.n_spans), "diff_enron_minus_wiki": rnd(row.diff_enron_minus_wiki),
                                                       "ci95": [rnd(row.ci_lo), rnd(row.ci_hi)]}
                                        for _, row in T8[(T8.question == q) & (T8.row_type == "sensitivity")].iterrows()},
                 "run_on_groups_dmean_p_enron_minus_wiki": {row.span_end: {"n": int(row.n_spans), "dmean_p": rnd(row.dmean_p_enron_minus_wiki),
                                                                          "ci95": [rnd(row.dmean_p_lo), rnd(row.dmean_p_hi)],
                                                                          "TPR_wiki": rnd(row.TPR_wiki), "TPR_enron": rnd(row.TPR_enron),
                                                                          "mcnemar_p": rnd(row.mcnemar_p_enron_vs_wiki)}
                                                            for _, row in T8[(T8.question == q) & (T8.grouping == RUNON_MAIN) & (T8.row_type == "group")].iterrows()},
                 "enron_request_count_spearman": {"rho_p_injection": rnd(t5.rho_p_inj), "pvalue": rnd(t5.rho_p_inj_pvalue),
                                                  "rho_wiki_minus_enron_p": rnd(t5.rho_gap), "pvalue_gap": rnd(t5.rho_gap_pvalue)}}
    t6 = T6.set_index("rows")
    an["QL_minus_Q2"] = {nm: {"dTPR_or_dFPR": rnd(r.diff_QL_minus_Q2), "ci95": [rnd(r.ci_lo), rnd(r.ci_hi)],
                              "mcnemar_p": rnd(r.mcnemar_p), "dmean_p": rnd(r.dmean_p), "dmean_p_ci95": [rnd(r.dmean_p_lo), rnd(r.dmean_p_hi)]}
                         for nm, r in t6.iterrows()}
    s["analysis"] = an
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1, default=float)

    # ---- console digest (the README numbers are copied from these tables)
    pd.set_option("display.width", 250, "display.max_columns", 40, "display.max_colwidth", 60)
    print(T1[["question", "condition", "n_injection", "n_benign", "TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_hi", "AUC", "AUC_lo", "AUC_hi",
              "paired_disc", "mean_p_injection", "mean_p_benign", "length_only_AUC", "dTPR_vs_EN1000"]].round(3).to_string())
    print(T2[["question", "metric", "wiki", "enron", "diff_enron_minus_wiki", "ci_lo", "ci_hi", "p_value", "wiki_only", "enron_only"]].round(3).to_string())
    print(T3[["question", "carrier", "TPR_original", "TPR_carrier", "dTPR", "dTPR_lo", "dTPR_hi", "carrier_only", "original_only", "mcnemar_p",
              "mean_p_original", "mean_p_carrier", "dmean_p", "dmean_p_lo", "dmean_p_hi"]].round(3).to_string())
    print(f"wrote {len(tables)} tables to {TAB}, {len(figs)} figures to {FIG}, summary.json['analysis']")


if __name__ == "__main__":
    main()
