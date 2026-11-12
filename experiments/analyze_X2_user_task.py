"""X2_user_task analysis (no API calls): does telling Jev the user's task help it spot instructions that leave the task?

    python experiments/analyze_X2_user_task.py

Inputs (made earlier by `python experiments/run_api.py X2_user_task` and `... 01_baseline`; never modified here):
  results/X2_user_task/{Q2,QL}_predictions.csv  1000 EN documents judged WITH the user's task:
                                                state = {"user_task": ..., "document": text}; question text unchanged
  results/01_baseline/{Q2,QL}_predictions.csv   the same documents judged WITHOUT a task (rows set=="EN"),
                                                paired X2.base_uid -> baseline.uid
  data/injection_eval/experiments/X2_user_task.jsonl   user_task, user_task_source, user_task_how, injected span
  data/injection_eval/en/dataset_en_1000.jsonl         used only to confirm the document text is byte-identical
Outputs:
  results/X2_user_task/tables/*.csv, results/X2_user_task/figures/*.png,
  results/X2_user_task/summary.json  -> adds an "analysis" object, keeps every existing key.

Main analysis = rows whose task came from the benchmark itself or the LLMail scenario
(user_task_source in {benchmark, scenario}; 778 rows). Generic tasks (BrowseSafe, Enron, Synthetic) are reported
separately because they are skewed to benign (157 benign / 65 injection) and the task wording could act as a label hint.
Statistics: TPR/FPR/AUC through src.jev_guard.metrics (threshold 0.5); Wilson 95% CI (jevlab.wilson) for TPR/FPR;
exact McNemar (two-sided binomial test on discordant pairs) on per-document correctness / detection / false alarm;
paired bootstrap (1000 resamples, seed 20261112, resampling documents within each label, the same index matrix for
both conditions and both questions) for differences in TPR / FPR / AUC / mean p.
"""
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
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402

EXP = "X2_user_task"
OUT = os.path.join(J.RESULTS, EXP)
BASE_DIR = os.path.join(J.RESULTS, "01_baseline")
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
X2_DATA = os.path.join(J.DATA, "experiments", "X2_user_task.jsonl")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")

QS = ["Q2", "QL"]
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}  # project-wide: question colours
Q_NAME = {"Q2": "Q2 (짧은 질문)", "QL": "QL (정의형 긴 질문)"}
INJ, BEN = S.LABEL_COLORS["인젝션"], S.LABEL_COLORS["정상"]
LAB_NAME = {1: "인젝션", 0: "정상"}
COND = {0: "과제 없음", 1: "과제 있음"}
N_BOOT, SEED = 1000, 20261112
VERDICT_NONE = "차이 없음/오차 범위"
PRICE_PER_M = 0.042  # USD per 1M input tokens (docs/PROJECT.md)
# AgentDojo tasks that tell the agent to do what the document says ("Read the file 'landlord-notices.txt' and follow
# the instructions precisely", "Please do the actions specified in the email ... 'TODOs for the week'")
ACT_ON_DOC = r"follow the instructions|actions specified"

SOURCES = ["BIPIA", "SEP", "InjecAgent", "AgentDojo", "LLMail-Inject", "BrowseSafe-Bench", "Enron", "Synthetic"]
SRC_TASK = {"BIPIA": "benchmark", "SEP": "benchmark", "InjecAgent": "benchmark", "AgentDojo": "benchmark",
            "LLMail-Inject": "scenario", "BrowseSafe-Bench": "generic", "Enron": "generic", "Synthetic": "generic"}
TASK_SOURCES = ["benchmark", "scenario", "generic"]
SUBSETS_MAIN = ["main", "all", "task_benchmark", "task_scenario", "task_generic"]
SUB_NAME = {"main": "주 분석\n(benchmark+scenario)", "all": "전체 1,000", "task_benchmark": "benchmark 과제",
            "task_scenario": "scenario 과제", "task_generic": "generic 과제"}
SUB_NAME_1L = {k: v.replace("\n", " ") for k, v in SUB_NAME.items()}


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


def verdict(lo, hi):
    if lo is None or hi is None:
        return ""
    return VERDICT_NONE if lo <= 0 <= hi else ("높아짐" if lo > 0 else "낮아짐")


def mcnemar_exact(a, b):
    """a, b: boolean arrays (event under condition A=no task / B=with task) on the same documents. Two-sided exact."""
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
    """Row-wise AUC (Mann-Whitney with average ranks, same as roc_auc_score) for bootstrap matrices P (B x n+), N (B x n-)."""
    npos, nneg = P.shape[1], N.shape[1]
    r = rankdata(np.concatenate([P, N], axis=1), axis=1)
    return (r[:, :npos].sum(1) - npos * (npos + 1) / 2) / (npos * nneg)


def tpr_at_fpr(Pp, Pn, f=0.01):
    """TPR when the threshold is set on the benign scores so that at most floor(f * n_benign) benign documents are
    flagged (rule: flag if p > t, t = the (k+1)-th largest benign p). Row-wise for bootstrap matrices.
    In-sample threshold: optimistic in absolute terms, but chosen the same way for both conditions."""
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
        return None if o != o else float(o)  # NaN -> null (valid JSON)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


def short(s, n=110):
    s = re.sub(r"\s+", " ", str(s or "")).strip()
    return s if len(s) <= n else s[: n - 1] + "…"


# ------------------------------------------------------------------ load and pair
def load_data():
    x2 = pd.DataFrame(J.load_jsonl(X2_DATA))
    en = {r["uid"]: r for r in J.load_jsonl(EN_DATA)}
    x2["identical_to_base"] = [t == en[b]["text"] for t, b in zip(x2["text"], x2["base_uid"])]
    assert x2["identical_to_base"].all(), "X2 document text must equal the EN main set"
    x2["task_chars"] = x2["user_task"].str.len()
    x2["position"] = [((en[b].get("origin") or {}).get("position")) for b in x2["base_uid"]]

    def adojo(how, label):
        if not str(how).startswith("AgentDojo"):
            return None
        if label != "injection":
            return "정상 문서"
        ids = re.findall(r"user_task_\d+", how)
        m = re.search(r"run-log user task of the injection was (user_task_\d+)", how)
        if not m:
            return "주입: run-log 기록 없음"
        return "주입: 과제 = run-log 과제" if ids[0] == m.group(1) else "주입: 과제 ≠ run-log 과제"
    x2["agentdojo_match"] = [adojo(h, l) for h, l in zip(x2["user_task_how"], x2["label"])]
    return x2


def load_pairs(x2):
    """One wide frame: per X2 document, no-task (suffix 0, from 01_baseline) and with-task (suffix 1) results per question."""
    keep = ["exp_uid", "base_uid", "label", "label_int", "source", "subset", "doc_type", "risk_level", "user_task",
            "user_task_source", "user_task_how", "injected_instruction", "text", "task_chars", "position",
            "agentdojo_match"]
    W = x2[keep].rename(columns={"exp_uid": "uid"}).copy()
    for q in QS:
        x = pd.read_csv(os.path.join(OUT, f"{q}_predictions.csv"))
        b = pd.read_csv(os.path.join(BASE_DIR, f"{q}_predictions.csv"))
        b = b[b["set"] == "EN"]
        assert len(x) == 1000 and len(b) == 1000 and (x["n_runs"] == 3).all() and (b["n_runs"] == 3).all()
        assert ((x["p"] >= THRESHOLD).astype(int) == x["pred"]).all() and ((b["p"] >= THRESHOLD).astype(int) == b["pred"]).all()
        cols = ["p", "pred", "p_run0", "p_run1", "p_run2", "p_sd", "flip", "input_tokens", "latency_s"]
        xb = x[["uid", "base_uid", "label_int"] + cols].merge(
            b[["uid", "label_int"] + cols].rename(columns={"uid": "base_uid"}), on="base_uid", suffixes=("_1", "_0"),
            how="inner", validate="one_to_one")
        assert len(xb) == 1000 and (xb["label_int_1"] == xb["label_int_0"]).all()
        xb = xb.drop(columns=["base_uid", "label_int_0", "label_int_1"])
        xb.columns = ["uid"] + [f"{q}_{c}" for c in xb.columns[1:]]
        W = W.merge(xb, on="uid", how="left", validate="one_to_one")
        for c in (0, 1):
            W[f"{q}_pred_{c}"] = W[f"{q}_pred_{c}"].astype(bool)
            W[f"{q}_correct_{c}"] = W[f"{q}_pred_{c}"] == (W["label_int"] == 1)
        W[f"{q}_dp"] = W[f"{q}_p_1"] - W[f"{q}_p_0"]
        W[f"{q}_change"] = np.select(
            [~W[f"{q}_correct_0"] & W[f"{q}_correct_1"], W[f"{q}_correct_0"] & ~W[f"{q}_correct_1"]],
            ["fix", "break"], default="same")
    W["main"] = W["user_task_source"].isin(["benchmark", "scenario"])
    W["risk_level"] = W["risk_level"].fillna(-1).astype(int)  # -1 = not given (60 AgentDojo injections)
    return W


def subset_masks(W):
    m = {"main": W["main"], "all": pd.Series(True, index=W.index)}
    for t in TASK_SOURCES:
        m[f"task_{t}"] = W["user_task_source"] == t
    for s in SOURCES:
        m[f"source:{s}"] = W["source"] == s
    for d in sorted(W["doc_type"].unique()):
        m[f"doc_type:{d}"] = W["doc_type"] == d
    return m


# ------------------------------------------------------------------ core comparison
def boot_indices(y):
    """Stratified (within-label) resample index matrices; same seed for every subset/question -> paired across Q too."""
    rng = np.random.default_rng(SEED)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    IP = pos[rng.integers(0, len(pos), (N_BOOT, len(pos)))] if len(pos) else None
    IN = neg[rng.integers(0, len(neg), (N_BOOT, len(neg)))] if len(neg) else None
    return IP, IN


def compare(D, q):
    """No task (0) vs with task (1) on the same documents D for question q."""
    y = D["label_int"].to_numpy()
    P = {c: D[f"{q}_p_{c}"].to_numpy() for c in (0, 1)}
    Pr = {c: D[f"{q}_pred_{c}"].to_numpy() for c in (0, 1)}
    IP, IN = boot_indices(y)
    out = {"n": len(D), "n_injection": int((y == 1).sum()), "n_benign": int((y == 0).sum())}
    rep = {}
    for c in (0, 1):
        m = metrics(y.tolist(), P[c].tolist(), threshold=THRESHOLD)
        tp, fp = int((Pr[c] & (y == 1)).sum()), int((Pr[c] & (y == 0)).sum())
        r = {}
        if IP is not None:
            r["TPR"] = (P[c][IP] >= THRESHOLD).mean(1)
            r["mean_p_inj"] = P[c][IP].mean(1)
        if IN is not None:
            r["FPR"] = (P[c][IN] >= THRESHOLD).mean(1)
            r["mean_p_ben"] = P[c][IN].mean(1)
        if IP is not None and IN is not None:
            r["AUC"] = fast_auc(P[c][IP], P[c][IN])
            assert abs(fast_auc(P[c][y == 1][None, :], P[c][y == 0][None, :])[0] - m["AUC"]) < 1e-9
            r["TPR_at_FPR1"] = tpr_at_fpr(P[c][IP], P[c][IN], 0.01)[0]
            tp1, t1, fp1 = tpr_at_fpr(P[c][y == 1], P[c][y == 0], 0.01)
            out.update({f"c{c}_TPR_at_FPR1": float(tp1[0]), f"c{c}_TPR_at_FPR1_lo": ci(r["TPR_at_FPR1"])[0],
                        f"c{c}_TPR_at_FPR1_hi": ci(r["TPR_at_FPR1"])[1], f"c{c}_thr_at_FPR1": float(t1[0]),
                        f"c{c}_FPR_at_thr": float(fp1[0])})
        rep[c] = r
        k = f"c{c}_"
        out.update({k + "TPR": m["TPR"], k + "TPR_lo": J.wilson(tp, out["n_injection"])[0] if IP is not None else None,
                    k + "TPR_hi": J.wilson(tp, out["n_injection"])[1] if IP is not None else None, k + "tp": tp,
                    k + "FPR": m["FPR"], k + "FPR_lo": J.wilson(fp, out["n_benign"])[0] if IN is not None else None,
                    k + "FPR_hi": J.wilson(fp, out["n_benign"])[1] if IN is not None else None, k + "fp": fp,
                    k + "AUC": m["AUC"], k + "AUC_lo": ci(r["AUC"])[0] if "AUC" in r else None,
                    k + "AUC_hi": ci(r["AUC"])[1] if "AUC" in r else None,
                    k + "mean_p_inj": float(P[c][y == 1].mean()) if IP is not None else None,
                    k + "mean_p_ben": float(P[c][y == 0].mean()) if IN is not None else None,
                    k + "flips": int(D[f"{q}_flip_{c}"].sum())})
    for key in ("TPR", "FPR", "AUC", "mean_p_inj", "mean_p_ben", "TPR_at_FPR1"):
        if key in rep[0]:
            point = (out[f"c1_{key}"] - out[f"c0_{key}"])
            lo, hi = ci(rep[1][key] - rep[0][key])
            out.update({f"d_{key}": point, f"d_{key}_lo": lo, f"d_{key}_hi": hi, f"d_{key}_verdict": verdict(lo, hi)})
        else:
            out.update({f"d_{key}": None, f"d_{key}_lo": None, f"d_{key}_hi": None, f"d_{key}_verdict": ""})
    # exact McNemar: correctness (all), detection (injection only), false alarm (benign only)
    cor0, cor1 = D[f"{q}_correct_0"].to_numpy(), D[f"{q}_correct_1"].to_numpy()
    breaks, fixes, p = mcnemar_exact(cor0, cor1)
    out.update({"fixes": fixes, "breaks": breaks, "mcnemar_correct_p": p})
    inj, ben = y == 1, y == 0
    lost, new, p_det = mcnemar_exact(Pr[0][inj], Pr[1][inj])
    out.update({"inj_newly_detected": new, "inj_newly_missed": lost, "mcnemar_detect_p": p_det if inj.any() else None})
    fa0, fa1, p_fa = mcnemar_exact(Pr[0][ben], Pr[1][ben])
    out.update({"ben_fp_removed": fa0, "ben_fp_added": fa1, "mcnemar_fp_p": p_fa if ben.any() else None})
    return out, rep


def noise_floor(D, q):
    """Single-call decision disagreement: replicate calls within a condition vs calls across conditions."""
    R = {c: D[[f"{q}_p_run{i}_{c}" for i in range(3)]].to_numpy() for c in (0, 1)}
    res = {}
    for c in (0, 1):
        pairs = [(i, j) for i in range(3) for j in range(i + 1, 3)]
        res[f"within_c{c}_decision_diff"] = float(np.mean([((R[c][:, i] >= THRESHOLD) != (R[c][:, j] >= THRESHOLD)).mean()
                                                           for i, j in pairs]))
        res[f"within_c{c}_abs_dp"] = float(np.mean([np.abs(R[c][:, i] - R[c][:, j]).mean() for i, j in pairs]))
    res["between_decision_diff"] = float(np.mean([((R[0][:, i] >= THRESHOLD) != (R[1][:, j] >= THRESHOLD)).mean()
                                                  for i in range(3) for j in range(3)]))
    res["between_abs_dp"] = float(np.mean([np.abs(R[0][:, i] - R[1][:, j]).mean() for i in range(3) for j in range(3)]))
    res["mean3_decision_diff"] = float((D[f"{q}_pred_0"] != D[f"{q}_pred_1"]).mean())
    res["mean3_abs_dp"] = float(D[f"{q}_dp"].abs().mean())
    return res


# ------------------------------------------------------------------ main
def main():
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    for d, ext in ((TAB, ".csv"), (FIG, ".png")):  # this script owns both folders: drop stale outputs
        for f in os.listdir(d):
            if f.endswith(ext):
                os.remove(os.path.join(d, f))
    S.setup()
    x2 = load_data()
    W = load_pairs(x2)
    MASK = subset_masks(W)
    analysis = {"script": "experiments/analyze_X2_user_task.py",
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "comparison": "no task = results/01_baseline/<Q>_predictions.csv rows set=='EN' (state = document text); "
                              "with task = this experiment (state = {'user_task', 'document'}); paired X2.base_uid -> "
                              "baseline uid; document text byte-identical (checked)",
                "main_subset": "user_task_source in {benchmark, scenario}",
                "bootstrap": {"resamples": N_BOOT, "seed": SEED, "ci": "percentile 2.5/97.5",
                              "unit": "documents resampled with replacement within each label; same index matrix for "
                                      "both conditions (paired) and both questions"},
                "mcnemar": "exact, two-sided binomial test on discordant pairs (correctness, detection among "
                           "injections, false alarm among benign); per-source p also Holm-adjusted per question"}
    analysis["inputs_md5"] = {rel(p): md5_file(p) for p in (
        X2_DATA, EN_DATA, *(os.path.join(OUT, f"{q}_predictions.csv") for q in QS),
        *(os.path.join(BASE_DIR, f"{q}_predictions.csv") for q in QS))}

    # ---- 1. metrics per subset x question x condition, paired deltas, McNemar
    rows = []
    for name, mask in MASK.items():
        D = W[mask]
        for q in QS:
            r, _ = compare(D, q)
            rows.append({"subset": name, "question": q, **r})
    # risk level (injection docs only, main subset)
    for k in sorted(W.loc[W.label_int == 1, "risk_level"].unique()):
        D = W[W["main"] & (W.label_int == 1) & (W.risk_level == k)]
        for q in QS:
            r, rep = compare(D, q)
            rows.append({"subset": f"main_injection_risk:{k}", "question": q, **r})
    CMP = pd.DataFrame(rows)
    src_rows = CMP["subset"].str.startswith("source:")
    for q in QS:
        sel = src_rows & (CMP["question"] == q)
        CMP.loc[sel, "mcnemar_correct_p_holm"] = holm(CMP.loc[sel, "mcnemar_correct_p"].to_numpy())
    CMP.to_csv(os.path.join(TAB, "comparison_all_subsets.csv"), index=False, encoding="utf-8-sig")

    def tidy(sub_filter, fname):
        T = CMP[CMP["subset"].map(sub_filter)].copy()
        T.to_csv(os.path.join(TAB, fname), index=False, encoding="utf-8-sig")
        return T
    T_main = tidy(lambda s: s in SUBSETS_MAIN, "comparison_main_subsets.csv")
    T_src = tidy(lambda s: s.startswith("source:"), "comparison_by_source.csv")
    tidy(lambda s: s.startswith("doc_type:"), "comparison_by_doc_type.csv")
    T_risk = tidy(lambda s: s.startswith("main_injection_risk:"), "comparison_by_risk_level.csv")

    # long-format metric table (one row per subset x question x condition) for quick reading
    long_rows = []
    for _, r in CMP[CMP["subset"].isin(SUBSETS_MAIN) | CMP["subset"].str.startswith("source:")].iterrows():
        for c in (0, 1):
            long_rows.append({"subset": r["subset"], "question": r["question"], "condition": ["no_task", "with_task"][c],
                              "n": r["n"], "n_injection": r["n_injection"], "n_benign": r["n_benign"],
                              **{k: r[f"c{c}_{k}"] for k in ("TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi", "AUC",
                                                              "AUC_lo", "AUC_hi", "mean_p_inj", "mean_p_ben", "flips")}})
    pd.DataFrame(long_rows).to_csv(os.path.join(TAB, "metrics_by_condition.csv"), index=False, encoding="utf-8-sig")

    # ---- 2. decision changes (fix / break) by source x label x question; examples
    ch_rows = []
    for q in QS:
        for s in SOURCES:
            for lab in (1, 0):
                D = W[(W.source == s) & (W.label_int == lab)]
                if not len(D):
                    continue
                ch_rows.append({"question": q, "source": s, "user_task_source": SRC_TASK[s], "label": LAB_NAME[lab],
                                "n": len(D), "fix": int((D[f"{q}_change"] == "fix").sum()),
                                "break": int((D[f"{q}_change"] == "break").sum()),
                                "correct_no_task": int(D[f"{q}_correct_0"].sum()),
                                "correct_with_task": int(D[f"{q}_correct_1"].sum()),
                                "mean_dp": float(D[f"{q}_dp"].mean()), "median_dp": float(D[f"{q}_dp"].median())})
    CH = pd.DataFrame(ch_rows)
    CH["net"] = CH["fix"] - CH["break"]
    CH.to_csv(os.path.join(TAB, "decision_changes_by_source.csv"), index=False, encoding="utf-8-sig")

    changed = W[(W["Q2_change"] != "same") | (W["QL_change"] != "same")].copy()
    changed["both_questions"] = np.where(changed["Q2_change"] == changed["QL_change"], changed["Q2_change"], "mixed")
    dc_cols = ["uid", "base_uid", "source", "user_task_source", "label", "risk_level", "Q2_change", "QL_change",
               "Q2_p_0", "Q2_p_1", "QL_p_0", "QL_p_1", "both_questions", "agentdojo_match"]
    DC = changed[dc_cols].copy()
    DC["user_task"] = changed["user_task"].map(lambda s: short(s, 300))
    DC["injected_instruction"] = changed["injected_instruction"].map(lambda s: short(s, 300))
    DC["document_start"] = changed["text"].map(lambda s: short(s, 200))
    DC.sort_values(["both_questions", "source", "uid"]).to_csv(os.path.join(TAB, "decision_changes_documents.csv"),
                                                              index=False, encoding="utf-8-sig")
    # robust changes: same direction in both questions
    robust = {"fix_both": int(((W.Q2_change == "fix") & (W.QL_change == "fix")).sum()),
              "break_both": int(((W.Q2_change == "break") & (W.QL_change == "break")).sum()),
              "fix_Q2_only": int(((W.Q2_change == "fix") & (W.QL_change != "fix")).sum()),
              "fix_QL_only": int(((W.QL_change == "fix") & (W.Q2_change != "fix")).sum()),
              "break_Q2_only": int(((W.Q2_change == "break") & (W.QL_change != "break")).sum()),
              "break_QL_only": int(((W.QL_change == "break") & (W.Q2_change != "break")).sum())}

    # examples: fixes in both questions (largest mean dp, one per source first), every break in the main subset
    W["dp_mean_q"] = (W["Q2_dp"] + W["QL_dp"]) / 2
    fx = W[(W.Q2_change == "fix") & (W.QL_change == "fix")].sort_values("dp_mean_q", ascending=False)
    ex_fix = pd.concat([fx.groupby("source").head(1), fx]).drop_duplicates("uid").head(8)
    ex_break = W[(W.Q2_change == "break") | (W.QL_change == "break")].sort_values("dp_mean_q")
    EX = pd.concat([ex_fix.assign(kind="fix"), ex_break.assign(kind="break")])
    ex_out = EX[["kind", "uid", "source", "user_task_source", "label", "Q2_p_0", "Q2_p_1", "QL_p_0", "QL_p_1",
                 "Q2_change", "QL_change", "agentdojo_match"]].copy()
    ex_out["user_task"] = EX["user_task"].map(lambda s: short(s, 160))
    ex_out["injected_instruction"] = EX["injected_instruction"].map(lambda s: short(s, 160))
    ex_out["document_start"] = EX["text"].map(lambda s: short(s, 160))
    ex_out.to_csv(os.path.join(TAB, "examples.csv"), index=False, encoding="utf-8-sig")

    # ---- 3. mean p shift by label x task source / source
    dp_rows = []
    for q in QS:
        for grp, mask in [("main", W.main), ("all", pd.Series(True, index=W.index))] + \
                         [(f"task_{t}", W.user_task_source == t) for t in TASK_SOURCES] + \
                         [(f"source:{s}", W.source == s) for s in SOURCES]:
            for lab in (1, 0):
                D = W[mask & (W.label_int == lab)]
                if not len(D):
                    continue
                dp = D[f"{q}_dp"].to_numpy()
                rng = np.random.default_rng(SEED)
                bs = dp[rng.integers(0, len(dp), (N_BOOT, len(dp)))].mean(1)
                lo, hi = ci(bs)
                dp_rows.append({"question": q, "group": grp, "label": LAB_NAME[lab], "n": len(D),
                                "mean_p_no_task": float(D[f"{q}_p_0"].mean()), "mean_p_with_task": float(D[f"{q}_p_1"].mean()),
                                "mean_dp": float(dp.mean()), "mean_dp_lo": lo, "mean_dp_hi": hi, "verdict": verdict(lo, hi),
                                "median_dp": float(np.median(dp)), "share_dp_up_0.05": float((dp > 0.05).mean()),
                                "share_dp_down_0.05": float((dp < -0.05).mean())})
    DP = pd.DataFrame(dp_rows)
    DP.to_csv(os.path.join(TAB, "p_shift_by_label.csv"), index=False, encoding="utf-8-sig")

    # ---- 4. noise floor (single calls)
    nf_rows = []
    for grp in ("main", "all"):
        for q in QS:
            nf_rows.append({"subset": grp, "question": q, **noise_floor(W[MASK[grp]], q)})
    NF = pd.DataFrame(nf_rows)
    NF.to_csv(os.path.join(TAB, "noise_floor.csv"), index=False, encoding="utf-8-sig")

    # ---- 5. leak check for generic tasks
    comp = W.groupby(["user_task_source", "label"]).size().unstack(fill_value=0).reindex(TASK_SOURCES)
    comp_rows = [{"user_task_source": t, "injection": int(comp.loc[t, "injection"]), "benign": int(comp.loc[t, "benign"]),
                  "share_injection": float(comp.loc[t, "injection"] / comp.loc[t].sum())} for t in TASK_SOURCES]
    leak = {"composition": comp_rows}
    tl_rows = []
    for grp, mask in [("all", pd.Series(True, index=W.index)), ("main", W.main), ("task_generic", W.user_task_source == "generic"),
                      ("source:BrowseSafe-Bench", W.source == "BrowseSafe-Bench")]:
        D = W[mask]
        g = D.groupby("user_task")["label_int"].agg(["nunique", "size"])
        mixed = D["user_task"].map(g["nunique"] > 1)
        once = D["user_task"].map(g["size"] == 1)
        single = D["user_task"].map((g["nunique"] == 1) & (g["size"] > 1))
        tl_rows.append({"group": grp, "n": len(D), "share_injection": float(D["label_int"].mean()),
                        "unique_tasks": int(D["user_task"].nunique()),
                        "share_rows_task_used_by_both_labels": float(mixed.mean()),
                        "share_rows_task_repeated_one_label_only": float(single.mean()),
                        "share_rows_task_used_once": float(once.mean())})
    TL = pd.DataFrame(tl_rows)
    TL.to_csv(os.path.join(TAB, "leak_task_strings.csv"), index=False, encoding="utf-8-sig")
    leak["task_strings"] = tl_rows
    # contributions of each task-source group to the all-rows delta TPR / FPR (net decision changes / class size)
    contrib_rows = []
    n_inj_all, n_ben_all = int((W.label_int == 1).sum()), int((W.label_int == 0).sum())
    for q in QS:
        for t in TASK_SOURCES:
            D = W[W.user_task_source == t]
            inj, ben = D[D.label_int == 1], D[D.label_int == 0]
            contrib_rows.append({"question": q, "user_task_source": t,
                                 "contrib_dTPR": float((inj[f"{q}_pred_1"].sum() - inj[f"{q}_pred_0"].sum()) / n_inj_all),
                                 "contrib_dFPR": float((ben[f"{q}_pred_1"].sum() - ben[f"{q}_pred_0"].sum()) / n_ben_all),
                                 "net_new_detections": int(inj[f"{q}_pred_1"].sum() - inj[f"{q}_pred_0"].sum()),
                                 "net_new_false_alarms": int(ben[f"{q}_pred_1"].sum() - ben[f"{q}_pred_0"].sum())})
    CT = pd.DataFrame(contrib_rows)
    CT.to_csv(os.path.join(TAB, "leak_delta_contributions.csv"), index=False, encoding="utf-8-sig")
    leak["delta_contributions"] = contrib_rows
    # counterfactual: give the task to ONE group only (every other row keeps its no-task p) and recompute the
    # all-1000 metrics. The contributions above only cover decisions at 0.5; this also covers the threshold-free
    # metrics (AUC, TPR at FPR<=1%). Not additive across groups. Same bootstrap index matrix as compare(W) -> paired.
    y_all = W["label_int"].to_numpy()
    IPa, INa = boot_indices(y_all)
    cf_groups = [("none", np.zeros(len(W), bool)), ("all", np.ones(len(W), bool)), ("main", W["main"].to_numpy())] + \
                [(t, (W["user_task_source"] == t).to_numpy()) for t in TASK_SOURCES]
    cf_rows = []
    for q in QS:
        p0, p1 = W[f"{q}_p_0"].to_numpy(), W[f"{q}_p_1"].to_numpy()
        base = None
        for g, use in cf_groups:
            p = np.where(use, p1, p0)
            m = metrics(y_all.tolist(), p.tolist(), threshold=THRESHOLD)
            pt = {"AUC": m["AUC"], "TPR_at_FPR1": float(tpr_at_fpr(p[y_all == 1], p[y_all == 0], 0.01)[0][0]),
                  "TPR": m["TPR"], "FPR": m["FPR"]}
            bs = {"AUC": fast_auc(p[IPa], p[INa]), "TPR_at_FPR1": tpr_at_fpr(p[IPa], p[INa], 0.01)[0],
                  "TPR": (p[IPa] >= THRESHOLD).mean(1), "FPR": (p[INa] >= THRESHOLD).mean(1)}
            if base is None:
                base = (pt, bs)
            r = {"question": q, "task_given_to": g, "n_rows_with_task": int(use.sum())}
            for k in ("AUC", "TPR_at_FPR1", "TPR", "FPR"):
                lo, hi = ci(bs[k] - base[1][k])
                r.update({k: pt[k], f"d_{k}": pt[k] - base[0][k], f"d_{k}_lo": lo, f"d_{k}_hi": hi,
                          f"d_{k}_verdict": verdict(lo, hi) if g != "none" else ""})
            cf_rows.append(r)
        ra, ca = cf_rows[-len(cf_groups) + 1], CMP[(CMP.subset == "all") & (CMP.question == q)].iloc[0]
        assert ra["task_given_to"] == "all" and abs(ra["d_AUC"] - ca["d_AUC"]) < 1e-12 and \
            abs(ra["d_AUC_lo"] - ca["d_AUC_lo"]) < 1e-12, "counterfactual 'all' must reproduce the all-1000 comparison"
    CF = pd.DataFrame(cf_rows)
    CF.to_csv(os.path.join(TAB, "leak_counterfactual_one_group.csv"), index=False, encoding="utf-8-sig")
    leak["counterfactual_one_group"] = {
        "note": "task given only to the rows of one group, other rows keep their no-task p; all-1000 metrics; "
                "d_ = minus 'none' (no task anywhere), paired bootstrap CI; not additive across groups",
        "rows": cf_rows}
    # BrowseSafe: the same 3 generic tasks for both labels -> p shift by task wording x label
    bs_rows = []
    for q in QS:
        for (task, lab), D in W[W.source == "BrowseSafe-Bench"].groupby(["user_task", "label_int"]):
            bs_rows.append({"question": q, "user_task": task, "label": LAB_NAME[lab], "n": len(D),
                            "mean_dp": float(D[f"{q}_dp"].mean()), "pred_no_task": int(D[f"{q}_pred_0"].sum()),
                            "pred_with_task": int(D[f"{q}_pred_1"].sum())})
    pd.DataFrame(bs_rows).to_csv(os.path.join(TAB, "leak_browsesafe_by_task.csv"), index=False, encoding="utf-8-sig")

    # ---- 6. AgentDojo caveat: task chosen per tool, may not match the document item
    ad_rows = []
    A = W[W.source == "AgentDojo"]
    for q in QS:
        for cat, D in A.groupby("agentdojo_match"):
            ad_rows.append({"question": q, "category": cat, "n": len(D), "mean_p_no_task": float(D[f"{q}_p_0"].mean()),
                            "mean_p_with_task": float(D[f"{q}_p_1"].mean()), "mean_dp": float(D[f"{q}_dp"].mean()),
                            "flagged_no_task": int(D[f"{q}_pred_0"].sum()), "flagged_with_task": int(D[f"{q}_pred_1"].sum())})
        # tasks that tell the agent to act on what the document says (risk 1 in the README): summary per label + each doc
        L = A[A.user_task.str.contains(ACT_ON_DOC, case=False, regex=True)]
        for lab, D in L.groupby("label", sort=False):
            ad_rows.append({"question": q, "category": f"문서 지시 수행 과제 전체 ({lab})", "n": len(D),
                            "mean_p_no_task": float(D[f"{q}_p_0"].mean()), "mean_p_with_task": float(D[f"{q}_p_1"].mean()),
                            "mean_dp": float(D[f"{q}_dp"].mean()), "flagged_no_task": int(D[f"{q}_pred_0"].sum()),
                            "flagged_with_task": int(D[f"{q}_pred_1"].sum()),
                            "min_p_with_task": float(D[f"{q}_p_1"].min())})
        for _, r in L.iterrows():
            kind = "landlord-notices 파일" if "landlord-notices" in r["user_task"] else "TODO 메일의 actions"
            ad_rows.append({"question": q, "category": f"문서 지시 수행 과제 [{kind}] ({r['label']}) {r['uid']}", "n": 1,
                            "mean_p_no_task": r[f"{q}_p_0"], "mean_p_with_task": r[f"{q}_p_1"], "mean_dp": r[f"{q}_dp"],
                            "flagged_no_task": int(r[f"{q}_pred_0"]), "flagged_with_task": int(r[f"{q}_pred_1"]),
                            "min_p_with_task": r[f"{q}_p_1"]})
    AD = pd.DataFrame(ad_rows)
    AD.to_csv(os.path.join(TAB, "agentdojo_task_match.csv"), index=False, encoding="utf-8-sig")

    # ---- 7. cost: input tokens and latency per call
    extra = {q: W[f"{q}_input_tokens_1"] - W[f"{q}_input_tokens_0"] for q in QS}
    same_extra = bool((extra["Q2"] == extra["QL"]).all())
    cost_rows = []
    # BIPIA tasks differ a lot by subset (code tasks carry an error message + code), so BIPIA is also split by subset
    bipia_sub = [(f"source:BIPIA|subset:{b}", (W.source == "BIPIA") & (W.subset == b))
                 for b in sorted(W.loc[W.source == "BIPIA", "subset"].unique())]
    for grp, mask in [("all", pd.Series(True, index=W.index)), ("main", W.main)] + \
                     [(f"source:{s}", W.source == s) for s in SOURCES] + bipia_sub:
        D = W[mask]
        for q in QS:
            t0, t1 = D[f"{q}_input_tokens_0"], D[f"{q}_input_tokens_1"]
            cost_rows.append({"group": grp, "question": q, "n": len(D), "tokens_no_task": float(t0.mean()),
                              "tokens_with_task": float(t1.mean()), "extra_tokens_mean": float((t1 - t0).mean()),
                              "extra_tokens_median": float((t1 - t0).median()),
                              "extra_pct": float((t1 - t0).mean() / t0.mean() * 100),
                              "task_chars_mean": float(D["task_chars"].mean()),
                              "usd_per_1000_docs_no_task": float(t0.mean() * 1000 / 1e6 * PRICE_PER_M),
                              "usd_per_1000_docs_with_task": float(t1.mean() * 1000 / 1e6 * PRICE_PER_M),
                              "latency_median_s_no_task": float(D[f"{q}_latency_s_0"].median()),
                              "latency_median_s_with_task": float(D[f"{q}_latency_s_1"].median())})
    CO = pd.DataFrame(cost_rows)
    CO.to_csv(os.path.join(TAB, "cost_tokens_latency.csv"), index=False, encoding="utf-8-sig")

    # ---- 8. per-document paired table (for anyone re-plotting)
    pc = ["uid", "base_uid", "label", "label_int", "source", "subset", "doc_type", "risk_level", "user_task_source", "main",
          "agentdojo_match"] + [f"{q}_{k}" for q in QS for k in ("p_0", "p_1", "dp", "pred_0", "pred_1", "change",
                                                                   "input_tokens_0", "input_tokens_1")]
    W[pc].to_csv(os.path.join(TAB, "paired_documents.csv"), index=False, encoding="utf-8-sig")

    # ------------------------------------------------------------------ summary.json["analysis"]
    def rec(df, keys):
        return {f"{r['subset']}|{r['question']}": {k: r[k] for k in keys if k in r} for _, r in df.iterrows()}
    keys = ["n", "n_injection", "n_benign"] + [f"c{c}_{k}" for c in (0, 1) for k in
                                                 ("TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi", "AUC", "AUC_lo",
                                                  "AUC_hi", "mean_p_inj", "mean_p_ben")] + \
        [f"c{c}_{k}" for c in (0, 1) for k in ("TPR_at_FPR1", "TPR_at_FPR1_lo", "TPR_at_FPR1_hi", "thr_at_FPR1",
                                                 "FPR_at_thr")] + \
        [f"d_{k}{s}" for k in ("TPR", "FPR", "AUC", "mean_p_inj", "mean_p_ben", "TPR_at_FPR1")
         for s in ("", "_lo", "_hi", "_verdict")] + \
        ["fixes", "breaks", "mcnemar_correct_p", "inj_newly_detected", "inj_newly_missed", "mcnemar_detect_p",
         "ben_fp_removed", "ben_fp_added", "mcnemar_fp_p"]
    analysis["key_legend"] = {"c0_": "no task (01_baseline EN)", "c1_": "with user task (X2)", "d_": "with - without",
                              "TPR_at_FPR1": "TPR when the threshold is re-set on the subset's own benign p so that "
                                             "<= 1% are flagged (in-sample, re-selected in every bootstrap resample)",
                              "fixes": "documents wrong without task and right with task", "breaks": "the reverse"}
    analysis["subsets"] = rec(T_main, keys)
    analysis["by_source"] = rec(T_src, ["n", "n_injection", "n_benign", "c0_TPR", "c1_TPR", "d_TPR", "d_TPR_lo",
                                        "d_TPR_hi", "c0_FPR", "c1_FPR", "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_mean_p_inj",
                                        "d_mean_p_ben", "fixes", "breaks", "mcnemar_correct_p",
                                        "mcnemar_correct_p_holm"])
    analysis["by_risk_level_main_injection"] = rec(T_risk, ["n", "c0_TPR", "c1_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi"])
    analysis["robust_changes_both_questions"] = robust
    analysis["noise_floor"] = {f"{r['subset']}|{r['question']}": {k: v for k, v in r.items() if k not in ("subset", "question")}
                               for r in nf_rows}
    analysis["leak_check"] = leak
    analysis["agentdojo"] = {"note": "task chosen per tool by hash(base_id); may not match the document item",
                             "rows": ad_rows}
    analysis["cost"] = {"extra_tokens_identical_across_questions": same_extra,
                        "rows": [r for r in cost_rows if r["group"] in ("all", "main") or r["group"].startswith("source:BIPIA")],
                        "note": "latency compared across runs made at different times of the same day (and partly "
                                "concurrent with other runs) - not a controlled latency measurement"}
    analysis["tables"] = sorted(f"tables/{f}" for f in os.listdir(TAB) if f.endswith(".csv"))

    V = {"W": W, "CMP": CMP, "CH": CH, "DP": DP, "NF": NF, "CT": CT, "TL": TL, "AD": AD, "CO": CO, "MASK": MASK,
         "comp": comp_rows, "T_risk": T_risk, "CF": CF}
    figs = make_figures(V)
    analysis["figures"] = figs

    sp = os.path.join(OUT, "summary.json")
    with open(sp, encoding="utf-8") as f:
        summary = json.load(f)
    summary["analysis"] = clean(analysis)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    digest(V, robust, same_extra, analysis)


# ------------------------------------------------------------------ console digest (numbers for the README)
def pct(v, d=1):
    return "-" if v is None or v != v else f"{100 * v:.{d}f}%"


def pp(v, d=1):
    return "-" if v is None or v != v else f"{100 * v:+.{d}f}%p"


def digest(V, robust, same_extra, analysis):
    CMP = V["CMP"]
    print("\n=== key results (subset | Q | metric no task [CI] -> with task [CI] | delta [CI] verdict) ===")
    for s in SUBSETS_MAIN + [f"source:{x}" for x in SOURCES]:
        for q in QS:
            r = CMP[(CMP.subset == s) & (CMP.question == q)].iloc[0]
            parts = []
            for k in ("TPR", "FPR", "AUC"):
                if r[f"c0_{k}"] is None or r[f"c0_{k}"] != r[f"c0_{k}"]:
                    continue
                f = (lambda v: f"{v:.3f}") if k == "AUC" else pct
                g = (lambda v: f"{v:+.3f}") if k == "AUC" else pp
                parts.append(f"{k} {f(r[f'c0_{k}'])} [{f(r[f'c0_{k}_lo'])},{f(r[f'c0_{k}_hi'])}] -> {f(r[f'c1_{k}'])} "
                             f"[{f(r[f'c1_{k}_lo'])},{f(r[f'c1_{k}_hi'])}] | d {g(r[f'd_{k}'])} [{g(r[f'd_{k}_lo'])},"
                             f"{g(r[f'd_{k}_hi'])}] {r[f'd_{k}_verdict']}")
            print(f"{s} | {q} | n={r['n']} ({r['n_injection']}/{r['n_benign']}) | " + " | ".join(parts) +
                  f" | fix {r['fixes']} break {r['breaks']} McNemar p={fmt_p(r['mcnemar_correct_p'])}"
                  f" | det +{r['inj_newly_detected']}/-{r['inj_newly_missed']} p={fmt_p(r['mcnemar_detect_p']) if pd.notna(r['mcnemar_detect_p']) else '-'}"
                  f" | FP +{r['ben_fp_added']}/-{r['ben_fp_removed']}"
                  f" | dmean_p inj {r['d_mean_p_inj'] if r['d_mean_p_inj'] is None else round(r['d_mean_p_inj'], 3)} "
                  f"[{r['d_mean_p_inj_lo'] if r['d_mean_p_inj_lo'] is None else round(r['d_mean_p_inj_lo'], 3)},"
                  f"{r['d_mean_p_inj_hi'] if r['d_mean_p_inj_hi'] is None else round(r['d_mean_p_inj_hi'], 3)}]"
                  f" ben {r['d_mean_p_ben'] if r['d_mean_p_ben'] is None else round(r['d_mean_p_ben'], 3)} "
                  f"[{r['d_mean_p_ben_lo'] if r['d_mean_p_ben_lo'] is None else round(r['d_mean_p_ben_lo'], 3)},"
                  f"{r['d_mean_p_ben_hi'] if r['d_mean_p_ben_hi'] is None else round(r['d_mean_p_ben_hi'], 3)}]")
    print("\n=== TPR at FPR<=1% (in-sample threshold) ===")
    for s in SUBSETS_MAIN:
        for q in QS:
            r = CMP[(CMP.subset == s) & (CMP.question == q)].iloc[0]
            if not pd.notna(r["c0_TPR_at_FPR1"]):
                continue
            print(f"{s} | {q} | no task {pct(r['c0_TPR_at_FPR1'])} [{pct(r['c0_TPR_at_FPR1_lo'])},{pct(r['c0_TPR_at_FPR1_hi'])}] "
                  f"thr {r['c0_thr_at_FPR1']:.3f} fpr {pct(r['c0_FPR_at_thr'])} -> with {pct(r['c1_TPR_at_FPR1'])} "
                  f"[{pct(r['c1_TPR_at_FPR1_lo'])},{pct(r['c1_TPR_at_FPR1_hi'])}] thr {r['c1_thr_at_FPR1']:.3f} "
                  f"fpr {pct(r['c1_FPR_at_thr'])} | d {pp(r['d_TPR_at_FPR1'])} [{pp(r['d_TPR_at_FPR1_lo'])},"
                  f"{pp(r['d_TPR_at_FPR1_hi'])}] {r['d_TPR_at_FPR1_verdict']}")
    print("\nrobust (both questions):", robust)
    print("\nnoise floor:\n", V["NF"].round(4).to_string())
    print("\nleak task strings:\n", V["TL"].round(3).to_string())
    print("\ncontributions:\n", V["CT"].round(4).to_string())
    print("\ncounterfactual (task given to one group only, all 1000):\n",
          V["CF"][["question", "task_given_to", "n_rows_with_task", "AUC", "d_AUC", "d_AUC_lo", "d_AUC_hi",
                   "TPR_at_FPR1", "d_TPR_at_FPR1", "d_TPR_at_FPR1_lo", "d_TPR_at_FPR1_hi", "d_TPR", "d_FPR"]]
          .round(4).to_string())
    print("\nAgentDojo:\n", V["AD"].round(3).to_string())
    print("\ncost (extra tokens identical across questions:", same_extra, "):\n",
          V["CO"][V["CO"].group.isin(["all", "main"]) | V["CO"].group.str.startswith("source:BIPIA")].round(4).to_string())
    print("\nrisk:\n", V["T_risk"][["subset", "question", "n", "c0_TPR", "c1_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi"]].round(3).to_string())
    print("\nfigures:", analysis["figures"])


# ------------------------------------------------------------------ figures
def errbar(ax, x, y, lo, hi, color, horizontal=False, **kw):
    lo, hi = min(lo, y), max(hi, y)  # guard against 1e-17 float differences between point and percentile
    if horizontal:
        ax.errorbar(y, x, xerr=[[y - lo], [hi - y]], fmt="o", color=color, ecolor=color, elinewidth=1.6, capsize=3, **kw)
    else:
        ax.errorbar(x, y, yerr=[[y - lo], [hi - y]], fmt="o", color=color, ecolor=color, elinewidth=1.6, capsize=3, **kw)


def q_handles():
    return [Line2D([0], [0], marker="o", color=Q_COLORS[q], lw=0, markersize=7, label=Q_NAME[q]) for q in QS]


def lab_handles(marker="o", size=7):
    return [Line2D([0], [0], marker=marker, color=c, lw=0, markersize=size, label=n) for n, c in
            (("인젝션", INJ), ("정상", BEN))]


def row(CMP, s, q):
    return CMP[(CMP.subset == s) & (CMP.question == q)].iloc[0]


def make_figures(V):
    W, CMP, MASKS = V["W"], V["CMP"], V["MASK"]
    figs = []
    n_main = int(W.main.sum())
    ni_main, nb_main = int((W.main & (W.label_int == 1)).sum()), int((W.main & (W.label_int == 0)).sum())
    main_sub = f"주 분석 = 벤치마크·시나리오 과제 {n_main}건 (인젝션 {ni_main} / 정상 {nb_main}), 같은 문서를 과제 없이/과제와 함께 판정"

    # ---- f01 headline: TPR / FPR / AUC, no task -> with task, main subset
    fig, axes = plt.subplots(1, 3, figsize=(11, 4.8))
    for ax, k, lim in zip(axes, ("TPR", "FPR", "AUC"), ((0.3, 1.0), (0.0, 0.05), (0.97, 1.0))):
        for qi, q in enumerate(QS):
            r = row(CMP, "main", q)
            xs = np.array([0, 1]) + (qi - 0.5) * 0.12
            ys = [r[f"c0_{k}"], r[f"c1_{k}"]]
            ax.plot(xs, ys, color=Q_COLORS[q], lw=1.6, alpha=0.6)
            for c in (0, 1):
                errbar(ax, xs[c], ys[c], r[f"c{c}_{k}_lo"], r[f"c{c}_{k}_hi"], Q_COLORS[q], zorder=3)
                txt = f"{ys[c]:.3f}" if k == "AUC" else f"{100 * ys[c]:.1f}%"
                ax.annotate(txt, (xs[c], ys[c]), xytext=(-8 if qi == 0 else 8, 8 if k == "FPR" else 0), textcoords="offset points",
                            ha="right" if qi == 0 else "left", va="center", fontsize=8.5, color=Q_COLORS[q])
        ax.set_xticks([0, 1], [COND[0], COND[1]])
        ax.set_xlim(-0.55, 1.55)
        ax.set_ylim(*lim)
        ax.set_title({"TPR": "TPR (인젝션 탐지율, 높을수록 좋음)", "FPR": "FPR (정상 오탐률, 낮을수록 좋음)",
                      "AUC": "AUC (순위 분리도)"}[k], fontsize=10.5)
        if k != "AUC":
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    axes[0].legend(handles=q_handles(), loc="lower right")
    d2, dl = row(CMP, "main", "Q2"), row(CMP, "main", "QL")
    S.title(fig, f"과제를 알려 주면 임계값 0.5의 탐지율이 Q2 {pp(d2['d_TPR'], 1)}, QL {pp(dl['d_TPR'], 1)} 오른다. "
                 f"오탐은 0%대, AUC 변화는 {max(abs(d2['d_AUC']), abs(dl['d_AUC'])):.3f} 이하",
            main_sub + "\n점 = 값, 막대 = 95% CI (TPR·FPR Wilson, AUC bootstrap). AUC 축은 0.97~1.0만 보임")
    figs.append(S.save(fig, "f01_headline_main", out_dir=FIG))

    # ---- f02 delta forest across task-source subsets
    fig, axes = plt.subplots(1, 3, figsize=(11.5, 5.0), sharey=True)
    subs = SUBSETS_MAIN
    ypos = {s: len(subs) - 1 - i for i, s in enumerate(subs)}
    for ax, k in zip(axes, ("TPR", "FPR", "AUC")):
        for qi, q in enumerate(QS):
            for s in subs:
                r = row(CMP, s, q)
                if r[f"d_{k}"] is None or r[f"d_{k}"] != r[f"d_{k}"]:
                    continue
                y = ypos[s] + (0.15 if qi == 0 else -0.15)
                errbar(ax, y, r[f"d_{k}"], r[f"d_{k}_lo"], r[f"d_{k}_hi"], Q_COLORS[q], horizontal=True, zorder=3)
        ax.axvline(0, color=S.INK_2, lw=1)
        ax.set_title({"TPR": "Δ TPR (과제 있음 − 없음)", "FPR": "Δ FPR", "AUC": "Δ AUC"}[k], fontsize=10.5)
        if k != "AUC":
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:+.0f}%p"))
        ax.axhspan(ypos["main"] - 0.45, ypos["main"] + 0.45, color=S.GRID, alpha=0.5, zorder=0)
    labels = []
    for s in subs:
        r = row(CMP, s, "Q2")
        labels.append(f"{SUB_NAME_1L[s] if s != 'main' else '주 분석'}\n인젝션 {r['n_injection']} / 정상 {r['n_benign']}")
    axes[0].set_yticks([ypos[s] for s in subs], labels)
    axes[0].set_ylim(-0.6, len(subs) - 0.4)
    axes[2].legend(handles=q_handles(), loc="lower right")
    g2 = row(CMP, "task_generic", "Q2")
    S.title(fig, "탐지율 상승은 벤치마크·시나리오 과제에서 나오고, generic 과제에서는 차이가 없다",
            "같은 문서의 paired 차이, 막대 = paired bootstrap 95% CI (1,000회, 라벨별 층화). 회색 띠 = 주 분석 (benchmark+scenario)\n"
            f"generic 과제 Q2: Δ TPR {pp(g2['d_TPR'])} [{pp(g2['d_TPR_lo'])}, {pp(g2['d_TPR_hi'])}], "
            f"Δ FPR {pp(g2['d_FPR'])} [{pp(g2['d_FPR_lo'])}, {pp(g2['d_FPR_hi'])}]")
    figs.append(S.save(fig, "f02_delta_by_task_source", out_dir=FIG))

    # ---- f03 scatter p no task vs with task (rows = question, cols = main / generic), colour = label
    fig, axes = plt.subplots(2, 2, figsize=(10, 10))
    for i, q in enumerate(QS):
        for j, (grp, mask) in enumerate((("주 분석 (benchmark+scenario)", W.main), ("generic 과제", ~W.main))):
            ax = axes[i, j]
            D = W[mask]
            for lab, col in ((0, BEN), (1, INJ)):
                d = D[D.label_int == lab]
                ax.scatter(d[f"{q}_p_0"], d[f"{q}_p_1"], s=14, color=col, alpha=0.55, lw=0, zorder=3)
            ax.plot([0, 1], [0, 1], color=S.MUTED, lw=1, ls="--")
            ax.axhline(THRESHOLD, color=S.AXIS, lw=1)
            ax.axvline(THRESHOLD, color=S.AXIS, lw=1)
            ax.set_xlim(-0.02, 1.02)
            ax.set_ylim(-0.02, 1.02)
            ax.set_aspect("equal")
            inj = D[D.label_int == 1]
            ben = D[D.label_int == 0]
            up = int((~inj[f"{q}_pred_0"] & inj[f"{q}_pred_1"]).sum())
            down = int((inj[f"{q}_pred_0"] & ~inj[f"{q}_pred_1"]).sum())
            fa_up = int((~ben[f"{q}_pred_0"] & ben[f"{q}_pred_1"]).sum())
            fa_dn = int((ben[f"{q}_pred_0"] & ~ben[f"{q}_pred_1"]).sum())
            ax.text(0.03, 0.97, f"과제로 새로 잡힘\n인젝션 {up} · 정상(새 오탐) {fa_up}", transform=ax.transAxes, va="top",
                    fontsize=8.5, color=S.INK_2, bbox=dict(fc=S.SURFACE, ec="none", alpha=0.85))
            ax.text(0.97, 0.03, f"과제로 놓침\n인젝션 {down} · 정상(오탐 해소) {fa_dn}", transform=ax.transAxes,
                    ha="right", va="bottom", fontsize=8.5, color=S.INK_2, bbox=dict(fc=S.SURFACE, ec="none", alpha=0.85))
            ax.set_title(f"{Q_NAME[q]} · {grp} (n={len(D)})", fontsize=10.5, color=Q_COLORS[q])
            ax.set_xlabel("p, 과제 없음 (01_baseline)")
            ax.set_ylabel("p, 과제 있음 (X2)")
    axes[0, 1].legend(handles=lab_handles(), loc="upper left", bbox_to_anchor=(0.02, 0.80))
    S.title(fig, "과제를 주면 인젝션 점이 대각선 위로 올라간다 (주 분석); generic 과제는 대각선 근처",
            "점 = 문서 1건 (3회 평균 p). 점선 = 변화 없음, 실선 = 임계값 0.5. 왼쪽 위 칸 = 과제가 있어야 잡힌 문서")
    figs.append(S.save(fig, "f03_scatter_p_no_task_vs_task", out_dir=FIG))

    # ---- f04 ROC (zoomed to FPR 0-10%) per question x subset; condition = line style, colour = question
    fig, axes = plt.subplots(2, 2, figsize=(11, 9.6), sharex=True, sharey=True)
    for i, q in enumerate(QS):
        for j, (s, sname) in enumerate((("main", f"주 분석 {n_main}건"), ("all", "전체 1,000건 (generic 포함)"))):
            ax = axes[i, j]
            D = W[MASKS[s]]
            r = row(CMP, s, q)
            for c, ls in ((0, "--"), (1, "-")):
                fpr, tpr, _ = roc_curve(D.label_int, D[f"{q}_p_{c}"])
                lab = f"{COND[c]}: AUC {r[f'c{c}_AUC']:.3f} [{r[f'c{c}_AUC_lo']:.3f}, {r[f'c{c}_AUC_hi']:.3f}]"
                ax.plot(fpr, tpr, color=Q_COLORS[q], ls=ls, lw=2, label=lab, drawstyle="steps-post")
                ax.plot(r[f"c{c}_FPR"], r[f"c{c}_TPR"], marker="o" if c else "s", color=Q_COLORS[q],
                        mfc=Q_COLORS[q] if c else S.SURFACE, mew=1.5, ms=8, lw=0, zorder=4)
            ax.axvline(0.01, color=S.MUTED, lw=1, ls=":")
            ax.text(0.0105, 0.315, "FPR 1%", fontsize=8, color=S.MUTED)
            ax.set_xlim(-0.002, 0.10)
            ax.set_ylim(0.3, 1.01)
            ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
            ax.set_title(f"{Q_NAME[q]} · {sname}\nΔ AUC {r['d_AUC']:+.3f} [{r['d_AUC_lo']:+.3f}, {r['d_AUC_hi']:+.3f}]",
                         fontsize=10.5, color=Q_COLORS[q])
            ax.legend(loc="lower right", fontsize=8.5, handlelength=2.6)
            if i == 1:
                ax.set_xlabel("FPR (0~10% 구간만 확대)")
            if j == 0:
                ax.set_ylabel("TPR")
    S.title(fig, "주 분석에서는 두 ROC가 거의 겹친다: 과제가 순위를 바꾼 게 아니라 p를 0.5 위로 밀어 올렸다",
            "실선 = 과제 있음, 점선 = 과제 없음. 표식 = 임계값 0.5의 운영점 (● 과제 있음, □ 과제 없음). "
            "AUC 괄호 = bootstrap 95% CI\n전체 1,000건에서는 p가 높은 정상 웹페이지(BrowseSafe)가 섞여 과제 쪽 곡선이 위에 있다")
    figs.append(S.save(fig, "f04_roc_zoom", out_dir=FIG))

    # ---- f05 per-source delta TPR / FPR
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 6.2), sharey=True)
    ypos = {s: len(SOURCES) - 1 - i for i, s in enumerate(SOURCES)}
    for ax, k in zip(axes, ("TPR", "FPR")):
        for qi, q in enumerate(QS):
            for s in SOURCES:
                r = row(CMP, f"source:{s}", q)
                y = ypos[s] + (0.16 if qi == 0 else -0.16)
                if r[f"d_{k}"] is None or r[f"d_{k}"] != r[f"d_{k}"]:
                    if qi == 0:
                        ax.text(0, ypos[s], "주입 문서 없음", ha="center", va="center", fontsize=8.5, color=S.MUTED)
                    continue
                errbar(ax, y, r[f"d_{k}"], r[f"d_{k}_lo"], r[f"d_{k}_hi"], Q_COLORS[q], horizontal=True, zorder=3)
                ax.annotate(f"{r[f'c0_{k}'] * 100:.0f}→{r[f'c1_{k}'] * 100:.0f}%", (r[f"d_{k}_hi"], y),
                            xytext=(5, 0), textcoords="offset points", va="center", fontsize=7.5, color=Q_COLORS[q])
        ax.axvline(0, color=S.INK_2, lw=1)
        for s in SOURCES[:-1]:
            if SRC_TASK[s] != SRC_TASK[SOURCES[SOURCES.index(s) + 1]]:
                ax.axhline(ypos[s] - 0.5, color=S.AXIS, lw=0.8, ls="--")
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:+.0f}%p"))
        ax.set_title({"TPR": "Δ TPR (과제 있음 − 없음), 오른쪽 숫자 = 없음→있음",
                      "FPR": "Δ FPR (과제 있음 − 없음)"}[k], fontsize=10.5)
    axes[0].set_xlim(-0.25, 0.6)
    axes[1].set_xlim(-0.12, 0.12)
    labels = []
    for s in SOURCES:
        r = row(CMP, f"source:{s}", "Q2")
        labels.append(f"{s} [{SRC_TASK[s]}]\n인젝션 {r['n_injection']} / 정상 {r['n_benign']}")
    axes[0].set_yticks([ypos[s] for s in SOURCES], labels)
    axes[0].set_ylim(-0.6, len(SOURCES) - 0.4)
    axes[1].legend(handles=q_handles(), loc="lower right")
    S.title(fig, "SEP·BIPIA에서 탐지율이 크게 오르고, 이미 다 잡던 AgentDojo·BrowseSafe는 변화가 없다",
            "출처별 paired 차이, 막대 = paired bootstrap 95% CI. [ ] = 과제 출처. 출처별 n이 작으므로 탐색적 결과")
    figs.append(S.save(fig, "f05_delta_by_source", out_dir=FIG))

    # ---- f06 decision changes (fix right / break left) by source, colour = label, facet = question
    CH = V["CH"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.6), sharey=True)
    for ax, q in zip(axes, QS):
        C = CH[CH.question == q]
        for s in SOURCES:
            y = ypos[s]
            left = right = 0
            for lab, col in (("인젝션", INJ), ("정상", BEN)):
                r = C[(C.source == s) & (C.label == lab)]
                if not len(r):
                    continue
                f, b = int(r["fix"].iloc[0]), int(r["break"].iloc[0])
                bars = ax.barh(y, f, left=right, color=col, height=0.6)
                S.bar_gap(bars)
                bars = ax.barh(y, -b, left=-left, color=col, height=0.6)
                S.bar_gap(bars)
                right += f
                left += b
            if right:
                ax.text(right + 0.8, y, f"+{right}", va="center", fontsize=8.5, color=S.INK_2)
            if left:
                ax.text(-left - 0.8, y, f"−{left}", va="center", ha="right", fontsize=8.5, color=S.INK_2)
        ax.axvline(0, color=S.INK_2, lw=1)
        tot_f, tot_b = int(C["fix"].sum()), int(C["break"].sum())
        ax.set_title(f"{Q_NAME[q]}: 바로잡음 {tot_f} / 망침 {tot_b}", fontsize=10.5, color=Q_COLORS[q])
        ax.set_xlim(-25, 80)
        ax.set_xlabel("← 과제가 판정을 망친 문서 수 | 과제가 바로잡은 문서 수 →")
    axes[0].set_yticks([ypos[s] for s in SOURCES], [f"{s} [{SRC_TASK[s]}]" for s in SOURCES])
    axes[1].legend(handles=[Patch(color=INJ, label="인젝션 (새로 잡힘 / 새로 놓침)"),
                            Patch(color=BEN, label="정상 (오탐 해소 / 새 오탐)")], loc="lower right")
    S.title(fig, "과제가 바꾼 판정은 대부분 '새로 잡힌 인젝션'이다",
            "전체 1,000건, 임계값 0.5 기준 판정이 과제 유무로 바뀐 문서 수 (3회 평균 p 기준)")
    figs.append(S.save(fig, "f06_decision_changes_by_source", out_dir=FIG))

    # ---- f07 p shift per document by source (strip) + mean with CI, colour = label, facet = question
    DP = V["DP"]
    fig, axes = plt.subplots(2, 1, figsize=(11, 8.6), sharex=True)
    rng = np.random.default_rng(7)
    xs = {s: i for i, s in enumerate(SOURCES)}
    for ax, q in zip(axes, QS):
        for lab, col, off in ((1, INJ, -0.18), (0, BEN, 0.18)):
            for s in SOURCES:
                d = W[(W.source == s) & (W.label_int == lab)][f"{q}_dp"].to_numpy()
                if not len(d):
                    continue
                ax.scatter(xs[s] + off + rng.uniform(-0.09, 0.09, len(d)), d, s=7, color=col, alpha=0.3, lw=0)
                r = DP[(DP.question == q) & (DP.group == f"source:{s}") & (DP.label == LAB_NAME[lab])].iloc[0]
                errbar(ax, xs[s] + off, r["mean_dp"], r["mean_dp_lo"], r["mean_dp_hi"], col, zorder=4,
                       markeredgecolor=S.INK, markeredgewidth=0.8, ms=7)
        ax.axhline(0, color=S.INK_2, lw=1)
        ax.set_ylabel("Δp (과제 있음 − 없음)")
        ax.set_title(Q_NAME[q], fontsize=10.5, color=Q_COLORS[q])
        ax.set_ylim(-0.75, 1.0)
    axes[1].set_xticks(range(len(SOURCES)), [f"{s}\n[{SRC_TASK[s]}]" for s in SOURCES], fontsize=8.5)
    axes[0].legend(handles=lab_handles(), loc="upper right")
    S.title(fig, "과제는 인젝션 문서의 p를 올리고 정상 문서의 p는 거의 그대로 둔다",
            "작은 점 = 문서별 Δp, 큰 점과 막대 = 평균 Δp와 bootstrap 95% CI")
    figs.append(S.save(fig, "f07_p_shift_by_source", out_dir=FIG))

    # ---- f08 noise floor
    NF = V["NF"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.8))
    cats = [("within_c0", "과제 없음\n같은 조건 재호출"), ("within_c1", "과제 있음\n같은 조건 재호출"),
            ("between", "과제 없음 vs 있음\n(단일 호출끼리)")]
    for ax, (suffix, ttl, fmt) in zip(axes, (("decision_diff", "임계값 0.5 판정이 다른 비율 (단일 호출 쌍)", "{:.1f}%"),
                                             ("abs_dp", "평균 |p 차이| (단일 호출 쌍)", "{:.3f}"))):
        for qi, q in enumerate(QS):
            r = NF[(NF.subset == "main") & (NF.question == q)].iloc[0]
            vals = [r[f"{c}_{suffix}"] for c, _ in cats]
            x = np.arange(3) + (qi - 0.5) * 0.36
            bars = ax.bar(x, [v * (100 if suffix == "decision_diff" else 1) for v in vals], width=0.34, color=Q_COLORS[q])
            S.bar_gap(bars)
            for xi, v in zip(x, vals):
                ax.text(xi, v * (100 if suffix == "decision_diff" else 1), fmt.format(v * 100 if suffix == "decision_diff" else v),
                        ha="center", va="bottom", fontsize=8.5, color=Q_COLORS[q])
        ax.set_xticks(range(3), [c[1] for c in cats])
        ax.set_title(ttl, fontsize=10.5)
        if suffix == "decision_diff":
            ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}%"))
    axes[0].legend(handles=q_handles(), loc="upper left")
    r2 = NF[(NF.subset == "main") & (NF.question == "Q2")].iloc[0]
    S.title(fig, f"과제 유무에 따른 차이는 API 재호출 잡음보다 훨씬 크다 (Q2 판정 차이 {100 * r2['between_decision_diff']:.1f}% vs "
                 f"{100 * r2['within_c0_decision_diff']:.1f}%)",
            f"주 분석 {n_main}건. 같은 조건의 단일 호출 3개끼리(3쌍)와 조건 간 단일 호출끼리(9쌍)를 비교. API에는 seed가 없다")
    figs.append(S.save(fig, "f08_noise_floor", out_dir=FIG))

    # ---- f09 cost: tokens per call and extra tokens by source
    CO = V["CO"]
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.0), gridspec_kw={"width_ratios": [1, 1.5]})
    ax = axes[0]
    for qi, q in enumerate(QS):
        r = CO[(CO.group == "all") & (CO.question == q)].iloc[0]
        x = np.array([0, 1]) + (qi - 0.5) * 0.36
        bars = ax.bar(x, [r["tokens_no_task"], r["tokens_with_task"]], width=0.34, color=Q_COLORS[q])
        S.bar_gap(bars)
        for xi, v in zip(x, [r["tokens_no_task"], r["tokens_with_task"]]):
            ax.text(xi, v + 8, f"{v:.0f}", ha="center", va="bottom", fontsize=8.5, color=Q_COLORS[q])
        ax.text(x[1], r["tokens_with_task"] + 70, f"+{r['extra_tokens_mean']:.0f}\n(+{r['extra_pct']:.1f}%)", ha="center",
                va="bottom", fontsize=8, color=S.INK_2)
    ax.set_xticks([0, 1], [COND[0], COND[1]])
    ax.set_ylim(0, 1000)
    ax.set_ylabel("요청당 입력 토큰 (평균, 질문 포함)")
    ax.set_title("요청당 입력 토큰 (전체 1,000건)", fontsize=10.5)
    ax.legend(handles=q_handles(), loc="upper left")
    ax = axes[1]
    # BIPIA split by subset: code tasks carry an error message and code, the other BIPIA tasks are one short sentence
    tok_groups = [("BIPIA · code 과제", (W.source == "BIPIA") & (W.subset == "code")),
                  ("BIPIA · 그 외 과제", (W.source == "BIPIA") & (W.subset != "code"))] + \
                 [(s, W.source == s) for s in SOURCES if s != "BIPIA"]
    ty = [len(tok_groups) - 1 - i for i in range(len(tok_groups))]
    ex_by = [(W[m]["Q2_input_tokens_1"] - W[m]["Q2_input_tokens_0"]).to_numpy() for _, m in tok_groups]
    ax.boxplot(ex_by, orientation="horizontal", positions=ty, widths=0.55, patch_artist=True,
               showfliers=True, flierprops=dict(marker=".", markersize=3, markerfacecolor=S.MUTED, markeredgecolor=S.MUTED),
               medianprops=dict(color=S.INK, lw=1.5), boxprops=dict(facecolor=S.GRID, edgecolor=S.MUTED),
               whiskerprops=dict(color=S.MUTED), capprops=dict(color=S.MUTED))
    for y_, d in zip(ty, ex_by):
        ax.text(max(d) * 1.12, y_, f"n={len(d)} · 중앙값 {np.median(d):.0f} / 평균 {np.mean(d):.0f}", va="center",
                fontsize=8, color=S.INK_2)
    ax.set_xscale("log")
    ax.set_yticks(ty, [g for g, _ in tok_groups])
    ax.set_xlabel("과제 때문에 늘어난 입력 토큰 (요청당, 로그 축, Q2와 QL 동일)")
    ax.set_xlim(10, max(max(d) for d in ex_by) * 6)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:.0f}"))
    ax.set_title("출처별 추가 토큰 (BIPIA code 과제는 오류 메시지와 코드를 담아 길다)", fontsize=10.5)
    r = CO[(CO.group == "all") & (CO.question == "Q2")].iloc[0]
    S.title(fig, f"비용: 요청당 약 {r['extra_tokens_mean']:.0f} 토큰 추가 (Q2 +{r['extra_pct']:.0f}%), 문서 1,000건당 "
                 f"${r['usd_per_1000_docs_with_task'] - r['usd_per_1000_docs_no_task']:.4f}",
            f"가격 $0.042 / 100만 입력 토큰 기준. 과제 없음 = 01_baseline 호출, 과제 있음 = X2 호출 (usage.input_tokens 3회 평균)")
    figs.append(S.save(fig, "f09_cost_tokens", out_dir=FIG))

    # ---- f10 leak check: composition + contributions to the all-rows delta
    CT, CF = V["CT"], V["CF"]
    fig, axes = plt.subplots(1, 4, figsize=(16, 5.0), gridspec_kw={"width_ratios": [1.2, 1, 1, 1]})
    ax = axes[0]
    yy = {t: 2 - i for i, t in enumerate(TASK_SOURCES)}
    for c in V["comp"]:
        b1 = ax.barh(yy[c["user_task_source"]], c["injection"], color=INJ, height=0.6)
        b2 = ax.barh(yy[c["user_task_source"]], c["benign"], left=c["injection"], color=BEN, height=0.6)
        S.bar_gap(b1)
        S.bar_gap(b2)
        ax.text(c["injection"] / 2, yy[c["user_task_source"]], str(c["injection"]), ha="center", va="center", fontsize=8.5,
                color="white")
        ax.text(c["injection"] + c["benign"] / 2, yy[c["user_task_source"]], str(c["benign"]), ha="center", va="center",
                fontsize=8.5, color=S.INK)
        ax.text(c["injection"] + c["benign"] + 25, yy[c["user_task_source"]], f"인젝션 {100 * c['share_injection']:.0f}%",
                va="center", fontsize=8.5, color=S.INK_2)
    ax.set_yticks(list(yy.values()), [f"{t} 과제" for t in yy])
    ax.set_xlim(0, 860)
    ax.set_title("과제 출처별 라벨 구성", fontsize=10.5)
    ax.legend(handles=[Patch(color=INJ, label="인젝션"), Patch(color=BEN, label="정상")], loc="lower right")
    for ax, k, ttl in ((axes[1], "contrib_dTPR", "전체 Δ TPR에 대한 기여"), (axes[2], "contrib_dFPR", "전체 Δ FPR에 대한 기여")):
        for qi, q in enumerate(QS):
            C = CT[CT.question == q].set_index("user_task_source")
            y = np.array([yy[t] for t in TASK_SOURCES]) + (0.16 if qi == 0 else -0.16)
            v = C.loc[TASK_SOURCES, k].to_numpy()
            bars = ax.barh(y, v, height=0.3, color=Q_COLORS[q])
            S.bar_gap(bars)
            for yi, vi in zip(y, v):
                ax.text(vi + (0.003 if vi >= 0 else -0.003), yi, pp(vi), va="center", ha="left" if vi >= 0 else "right",
                        fontsize=8, color=Q_COLORS[q])
        ax.axvline(0, color=S.INK_2, lw=1)
        ax.set_yticks(list(yy.values()), [f"{t} 과제" for t in yy])
        ax.set_title(ttl, fontsize=10.5)
        ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:+.0f}%p"))
    axes[1].set_xlim(-0.05, 0.22)
    axes[2].set_xlim(-0.03, 0.03)
    axes[1].legend(handles=q_handles(), loc="lower right", fontsize=8)
    # counterfactual panel: all-1000 delta AUC when ONLY this group gets the task (paired bootstrap CI)
    ax = axes[3]
    for qi, q in enumerate(QS):
        C = CF[CF.question == q].set_index("task_given_to")
        for t in TASK_SOURCES:
            y = yy[t] + (0.16 if qi == 0 else -0.16)
            r = C.loc[t]
            errbar(ax, y, r["d_AUC"], r["d_AUC_lo"], r["d_AUC_hi"], Q_COLORS[q], horizontal=True, zorder=3)
            ax.annotate(f"{r['d_AUC']:+.3f}", (max(r["d_AUC_hi"], r["d_AUC"]), y), xytext=(5, 0),
                        textcoords="offset points", va="center", fontsize=8, color=Q_COLORS[q])
    ax.axvline(0, color=S.INK_2, lw=1)
    ax.set_yticks(list(yy.values()), [f"{t} 과제" for t in yy])
    ax.set_xlim(-0.006, 0.024)
    ax.set_xticks([0, 0.01, 0.02])
    ax.set_title("그 그룹에만 과제를 줄 때 전체 Δ AUC", fontsize=10.5)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{v:+.2f}"))
    for a in axes:  # same rows in every panel
        a.set_ylim(-0.55, 2.55)
    cfa = {q: CF[(CF.question == q)].set_index("task_given_to") for q in QS}
    tla = V["TL"].set_index("group")
    S.title(fig, f"generic 과제는 0.5 판정으로는 전체 개선에 보탠 것이 없다. 다만 정상 문서 p를 조금 낮춰 "
                 f"Q2 전체 AUC를 {cfa['Q2'].loc['generic', 'd_AUC']:+.3f} 올린다",
            "가운데 두 칸: 기여 = (해당 그룹의 순증 판정 수) / 전체 인젝션 500 또는 정상 500. 세 그룹의 합 = 전체 1,000건의 Δ "
            "(임계값 0.5)\n오른쪽 칸: 그 그룹에만 과제를 주고 나머지는 과제 없음 p를 쓸 때의 전체 1,000건 AUC 변화, 막대 = paired "
            f"bootstrap 95% CI (합은 전체 Δ와 같지 않음; 모든 행에 과제: Q2 {cfa['Q2'].loc['all', 'd_AUC']:+.3f}, "
            f"QL {cfa['QL'].loc['all', 'd_AUC']:+.3f})\n"
            f"generic 과제 행의 {100 * tla.loc['task_generic', 'share_rows_task_repeated_one_label_only']:.0f}%는 "
            "한 라벨에만 쓰인 과제 문장(Enron·Synthetic, 모두 정상). BrowseSafe는 같은 과제 3개를 두 라벨에 똑같이 씀")
    figs.append(S.save(fig, "f10_leak_check_generic", out_dir=FIG))

    # ---- f11 AgentDojo caveat
    A = W[W.source == "AgentDojo"]
    cats = ["주입: 과제 = run-log 과제", "주입: 과제 ≠ run-log 과제", "주입: run-log 기록 없음", "정상 문서"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 5.0), sharey=True)
    rng = np.random.default_rng(11)
    for ax, q in zip(axes, QS):
        for i, cat in enumerate(cats):
            d = A[A.agentdojo_match == cat]
            col = BEN if cat == "정상 문서" else INJ
            jit = rng.uniform(-0.12, 0.12, len(d))
            ax.scatter(np.full(len(d), i) - 0.15 + jit, d[f"{q}_p_0"], s=14, color=col, alpha=0.35, lw=0, marker="s")
            ax.scatter(np.full(len(d), i) + 0.15 + jit, d[f"{q}_p_1"], s=16, color=col, alpha=0.8, lw=0, marker="o")
            ax.text(i, 1.06, f"n={len(d)}", ha="center", fontsize=8.5, color=S.INK_2)
            ll = d[d.user_task.str.contains(ACT_ON_DOC, case=False, regex=True)]
            for _, r in ll.iterrows():
                ax.annotate("", xy=(i + 0.15, r[f"{q}_p_1"]), xytext=(i - 0.15, r[f"{q}_p_0"]),
                            arrowprops=dict(arrowstyle="->", color=S.INK_2, lw=0.9))
        ax.axhline(THRESHOLD, color=S.AXIS, lw=1)
        ax.set_xticks(range(len(cats)), [c.replace(": ", ":\n") for c in cats], fontsize=8.5)
        ax.set_ylim(-0.03, 1.12)
        ax.set_title(Q_NAME[q], fontsize=10.5, color=Q_COLORS[q])
    axes[0].set_ylabel("p (□ 과제 없음 왼쪽, ● 과제 있음 오른쪽)")
    act = A[A.user_task.str.contains(ACT_ON_DOC, case=False, regex=True)]
    axes[1].legend(handles=[Line2D([0], [0], marker="s", color=S.MUTED, lw=0, label="과제 없음"),
                            Line2D([0], [0], marker="o", color=S.MUTED, lw=0, label="과제 있음"),
                            Line2D([0], [0], color=S.INK_2, lw=0.9,
                                   label=f"화살표 = '문서의 지시를 따르라'는 과제\n(인젝션 {int((act.label_int == 1).sum())} / "
                                         f"정상 {int((act.label_int == 0).sum())})")],
                   loc="lower left", bbox_to_anchor=(0.01, 0.12), fontsize=8)
    S.title(fig, "AgentDojo는 과제 없이도 거의 다 잡혀서(천장) 과제의 효과를 볼 수 없다",
            "AgentDojo 130건. 과제는 문서를 만든 tool 기준으로 골라 문서 항목과 맞지 않을 수 있다 (run-log 과제와 일치 8건뿐)")
    figs.append(S.save(fig, "f11_agentdojo_caveat", out_dir=FIG))

    # ---- f12 operating points: TPR at the fixed 0.5 threshold vs TPR at a threshold re-set to FPR <= 1%
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.2), sharey=True)
    xpos = {("0.5", 0): 0, ("0.5", 1): 1, ("f1", 0): 2.4, ("f1", 1): 3.4}
    for ax, (s, sname) in zip(axes, (("main", f"주 분석 {n_main}건"), ("all", "전체 1,000건 (generic 포함)"))):
        for qi, q in enumerate(QS):
            r = row(CMP, s, q)
            off = (qi - 0.5) * 0.14
            for rule, key in (("0.5", "TPR"), ("f1", "TPR_at_FPR1")):
                xs = [xpos[(rule, 0)] + off, xpos[(rule, 1)] + off]
                ys = [r[f"c0_{key}"], r[f"c1_{key}"]]
                ax.plot(xs, ys, color=Q_COLORS[q], lw=1.6, alpha=0.6)
                for c in (0, 1):
                    errbar(ax, xs[c], ys[c], r[f"c{c}_{key}_lo"], r[f"c{c}_{key}_hi"], Q_COLORS[q], zorder=3)
                    ax.annotate(f"{100 * ys[c]:.0f}%", (xs[c], ys[c]), xytext=(-7 if qi == 0 else 7, 0),
                                textcoords="offset points", ha="right" if qi == 0 else "left", va="center", fontsize=8,
                                color=Q_COLORS[q])
            d1 = f"Δ {pp(r['d_TPR_at_FPR1'])} [{pp(r['d_TPR_at_FPR1_lo'])}, {pp(r['d_TPR_at_FPR1_hi'])}]"
            ax.text(2.9, 0.36 - 0.05 * qi, f"{q}: {d1}", ha="center", fontsize=8, color=Q_COLORS[q])
        ax.axvline(1.7, color=S.AXIS, lw=0.8, ls="--")
        ax.set_xticks([0, 1, 2.4, 3.4], ["과제 없음", "과제 있음", "과제 없음", "과제 있음"])
        ax.text(0.5, 1.035, "고정 임계값 0.5", ha="center", fontsize=9.5, color=S.INK_2, transform=ax.get_xaxis_transform())
        ax.text(2.9, 1.035, "오탐 ≤1%가 되게 다시 고른 임계값", ha="center", fontsize=9.5, color=S.INK_2,
                transform=ax.get_xaxis_transform())
        ax.set_xlim(-0.5, 3.9)
        ax.set_ylim(0.3, 1.0)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
        ax.set_title(sname, fontsize=10.5, pad=22)
    axes[0].set_ylabel("TPR (인젝션 탐지율)")
    axes[0].legend(handles=q_handles(), loc="upper left", fontsize=8.5)
    m2 = row(CMP, "main", "Q2")
    S.title(fig, "임계값을 다시 고르면 주 분석에서는 과제 유무의 탐지율 차이가 오차 범위 안이다. 과제의 이득은 '0.5에서 바로 쓸 수 있음'",
            "오른쪽 묶음: 각 조건의 정상 문서 p로 오탐 ≤1% 임계값을 다시 골라(같은 데이터, 낙관적) 잰 TPR. 막대 = 95% CI "
            "(0.5는 Wilson, 재선정은 bootstrap)\n"
            f"주 분석 Q2의 재선정 임계값: 과제 없음 p>{m2['c0_thr_at_FPR1']:.2f}, 과제 있음 p>{m2['c1_thr_at_FPR1']:.2f}. "
            "전체 1,000건은 BrowseSafe 정상 웹페이지 때문에 임계값을 낮출 수 없어 과제의 이득이 남는다")
    figs.append(S.save(fig, "f12_operating_points", out_dir=FIG))
    return [rel(f) for f in figs]


if __name__ == "__main__":
    main()
