"""01_baseline_definitions 분석: 우리가 인젝션을 직접 정의한 질문 3개(QS, Q3, QC)를 기준선 질문 Q2·QL 옆에 놓고 비교한다.
API를 부르지 않는다.

    python experiments/analyze_01_baseline_definitions.py

입력 (읽기만 함)
  results/01_baseline_definitions/{QS,Q3,QC}_predictions.csv, raw/{QS,Q3,QC}_raw.jsonl  (run_api.py 01_baseline_definitions)
  results/01_baseline/{Q2,QL}_predictions.csv, raw/{Q2,QL}_raw.jsonl                     (run_api.py 01_baseline)
  data/injection_eval/en/dataset_en_1000.jsonl, overdefense_ref_notinject.jsonl         (본문 md5 확인, 메타데이터)
출력
  results/01_baseline_definitions/tables/*.csv, results/01_baseline_definitions/figures/*.png,
  results/01_baseline_definitions/summary.json 의 "analysis" 키 (다른 키는 건드리지 않음)

질문 (원문은 experiments/jevlab.py QUESTIONS, summary.json "questions"와 같은지 확인함)
  Q2  팀 기준 짧은 질문 (src/jev_guard.INJECTION_QUESTION)          -> 이 실험의 비교 기준 (Δ = 질문 − Q2)
  QL  정의형 긴 질문 (docs/PROJECT.md "판정 질문 두 축")
  QS  첫 OpenJevX 시뮬레이션의 질문 ("hidden instruction aimed at an AI assistant or agent ...")
  Q3  src/jev_guard.QUESTION_RULE (팀 규칙형 참고 질문)
  QC  Q2 문장 그대로 + noul `criteria` (true / false 정의). judge()는 criteria를 못 보내므로 API 전용

규칙
  - 지표는 src.jev_guard.metrics() (임계값 0.5). 비율의 95% 신뢰구간은 Wilson (jevlab.wilson).
  - 주 지표는 set == "EN" 1,000건 (인젝션 500 / 정상 500). NotInject 25건은 과탐지 참고용 (FPR만).
  - 다섯 질문은 같은 문서 1,000건을 판정했으므로 모든 비교는 짝 비교다.
      0.5 판정의 차이: McNemar 정확검정 (불일치 쌍에 대한 양측 이항검정). Q2 대비 4개 비교는 지표마다 Holm 보정을 함께 적는다.
      TPR·FPR·AUC·평균 p·정확도의 차이: 짝 부트스트랩 (라벨별 층화 재표집 1,000회, seed 20261112, 다섯 질문에 같은 인덱스,
      백분위 구간). 구간이 0을 포함하면 "차이 없음 (오차 범위)".
  - 집단별 표(by_*_vs_q2.csv): 집단·라벨 안에서 짝 부트스트랩, McNemar p는 표 안(지표별)에서 Holm 보정.
    부트스트랩 구간이 0을 빼고 Holm p < 0.05일 때만 방향을 적고, 구간만 0을 빼면 "탐색적". 30건 미만이면 "표본 작음".
  - p 격자: p는 소수 둘째 자리 값 3개의 평균이라 정확히 1/300의 배수다. 읽자마자 round(300p)/300으로 맞춘다.
  - 오탐 1/5/10% 임계값: 각 질문의 정상 p에 같은 데이터에서 맞춘 값이라 낙관적이다 (참고용).
  - 다섯 질문 중 가장 좋은 것을 같은 데이터에서 고르면 낙관적이다. 그 크기를 반반 나누기로 잰다:
    출처×라벨로 층화해 EN을 반으로 1,000번 나누고(seed 20261112), 앞 절반에서 AUC 또는 0.5 정확도로 1등 질문을 고른 뒤
    뒤 절반에서 같은 질문의 값을 잰다. 차이(앞 − 뒤)가 "고르기 낙관"이다.
  - Q2·QL은 06:15–07:01 UTC, QS·Q3·QC는 07:08–07:51 UTC에 따로 실행했다. 응답 시간 차이는 질문 효과와 서버 상태가 섞여 있다.
"""
import datetime as dt
import hashlib
import html
import itertools
import json
import math
import os
import re
import sys

import numpy as np
import pandas as pd
from sklearn.metrics import cohen_kappa_score, roc_auc_score, roc_curve

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402
import plot_style as PS  # noqa: E402
from src.jev_guard import MODEL, THRESHOLD, metrics  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402  (plot_style already selected the Agg backend)

EXP = "01_baseline_definitions"
BASE_EXP = "01_baseline"
OUT = os.path.join(J.RESULTS, EXP)
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")
NI_DATA = os.path.join(J.DATA, "en", "overdefense_ref_notinject.jsonl")

QIDS = ("Q2", "QL", "QS", "Q3", "QC")
REF = "Q2"
OTHERS = tuple(q for q in QIDS if q != REF)
Q_EXP = {"Q2": BASE_EXP, "QL": BASE_EXP, "QS": EXP, "Q3": EXP, "QC": EXP}
# Question colours. Q2 / QL keep the project-wide colours; this experiment is the one place with five question colours.
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834", "QS": "#1baf7a", "Q3": "#6250d6", "QC": "#e87ba4"}
Q_NAMES = {"Q2": "Q2 짧은 질문", "QL": "QL 정의형 긴 질문", "QS": "QS 숨은 지시 질문", "Q3": "Q3 규칙형 질문",
           "QC": "QC Q2 + 판정 기준"}
INJ, BEN = PS.LABEL_COLORS["인젝션"], PS.LABEL_COLORS["정상"]  # label colours (whole project)

SEED = 20261112
B = 1000
N_SPLITS = 1000
GRID = 300
SMALL_N = 30
FPR_TARGETS = (0.01, 0.05, 0.10)
PRICE_IN = 0.042 / 1e6
RISK_KO = {1: "1 매우 낮음", 2: "2 낮음", 3: "3 중간", 4: "4 높음", 5: "5 매우 높음"}
SOURCE_ORDER = ["AgentDojo", "BrowseSafe-Bench", "InjecAgent", "LLMail-Inject", "BIPIA", "SEP", "Enron", "Synthetic"]
SOURCE_KO = {"Enron": "Enron (실제 메일)", "Synthetic": "합성 하드네거티브"}


# ------------------------------------------------------------------ small helpers
def md5_file(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def md5_text(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def mcnemar_exact(b, c):
    """Two-sided exact McNemar: binomial test of b vs c discordant pairs with p = 0.5."""
    b, c = int(b), int(c)
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    return float(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n))


def holm(pvals):
    p = np.asarray(pvals, dtype=float)
    out = np.full(len(p), np.nan)
    ok = np.where(~np.isnan(p))[0]
    m, run = len(ok), 0.0
    for rank, i in enumerate(ok[np.argsort(p[ok], kind="stable")]):
        run = max(run, min(1.0, (m - rank) * p[i]))
        out[i] = run
    return out


def ci(vals):
    vals = np.asarray(vals, dtype=float)
    vals = vals[~np.isnan(vals)]
    if not len(vals):
        return [None, None]
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def verdict(lo, hi, higher="높음", lower="낮음"):
    if lo is None or hi is None:
        return "–"
    if lo > 0:
        return higher
    if hi < 0:
        return lower
    return "차이 없음 (오차 범위)"


def group_verdict(lo, hi, p_holm, n):
    if lo is None or hi is None or lo != lo or hi != hi:
        return "–"
    small = f" · 표본 작음 (n={int(n)})" if n < SMALL_N else ""
    if lo <= 0 <= hi:
        return "차이 없음 (오차 범위)" + small
    if p_holm == p_holm and p_holm < 0.05:
        return ("Q2보다 높음" if lo > 0 else "Q2보다 낮음") + small
    return f"탐색적 (Holm p = {p_holm:.2f})" + small


def snap(p, grid=GRID):
    p = np.asarray(p, dtype=float)
    k = np.rint(p * grid)
    assert np.abs(k / grid - p).max() < 1e-9, "scores are not on the expected grid"
    return k / grid


def thr_at_fpr(neg_scores, f):
    """Lowest threshold t with FPR(p >= t) <= f on these benign scores (same data -> optimistic); half a grid step
    above the highest benign score that must pass."""
    neg = np.sort(np.asarray(neg_scores, dtype=float))[::-1]
    k = int(math.floor(f * len(neg) + 1e-9))
    return float(neg[k] + 0.5 / GRID) if k < len(neg) else 0.0


def auc_fast(pos, neg):
    """Mann-Whitney AUC with ties counted 1/2 (same value as roc_auc_score); used only inside resampling loops."""
    ns = np.sort(neg)
    lt = np.searchsorted(ns, pos, "left")
    le = np.searchsorted(ns, pos, "right")
    return float((lt + 0.5 * (le - lt)).sum() / (len(pos) * len(neg)))


_TAG = re.compile(r"<[^>]+>")


def short(s, n=110):
    if not isinstance(s, str):
        return None
    s = re.sub(r"\s+", " ", _TAG.sub(" ", html.unescape(s))).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def clean(o):
    if isinstance(o, dict):
        return {str(k): clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, np.integer):
        return int(o)
    if isinstance(o, (np.floating, float)):
        return None if o != o else float(o)
    if isinstance(o, np.bool_):
        return bool(o)
    return o


RUN_CODE = ("experiments/jevlab.py", "experiments/run_api.py", "experiments/plot_style.py")


def run_code_history(recorded):
    """run_api.py writes `git rev-parse HEAD` into summary.json "commit", but the experiment code was not committed yet
    when the calls ran. Record (read-only git) whether that commit has the code, the first commit that adds it, and
    whether jevlab.py / run_api.py changed between that commit and HEAD. None when git or the history is unavailable."""
    import subprocess

    def git(*args):
        return subprocess.run(["git", "-C", REPO, *args], capture_output=True, text=True)

    try:
        has = {f: git("cat-file", "-e", f"{recorded}:{f}").returncode == 0 for f in RUN_CODE} if recorded else {}
        first = git("log", "--diff-filter=A", "--format=%h %cI", "--", "experiments/jevlab.py").stdout.strip().splitlines()
        first_h, first_t = first[-1].split() if first else (None, None)
        changed = (git("diff", "--name-only", first_h, "HEAD", "--", "experiments/jevlab.py", "experiments/run_api.py")
                   .stdout.split() if first_h else None)
        return {"recorded_commit": recorded, "recorded_commit_has_run_code": has,
                "first_commit_with_run_code": first_h, "first_commit_time": first_t,
                "run_code_changed_since_then_to_HEAD": changed, "HEAD": J.git_commit(),
                "note": "summary.json 'commit' is the HEAD at run time; jevlab.py / run_api.py / plot_style.py were uncommitted on top "
                        "of it, so checking it out cannot rerun this. The code first appears in first_commit_with_run_code."}
    except Exception as e:  # noqa: BLE001  (no git, shallow clone, ...)
        return {"recorded_commit": recorded, "error": repr(e)}


def save_table(df, name):
    df.to_csv(os.path.join(TAB, f"{name}.csv"), index=False, encoding="utf-8-sig")
    return df


def pct(x, d=0):
    return "–" if x is None or x != x else f"{100 * x:.{d}f}%"


# ------------------------------------------------------------------ load and check
def load():
    data = {r["uid"]: r for r in J.load_jsonl(EN_DATA)}
    ni_data = {r["uid"]: r for r in J.load_jsonl(NI_DATA)}
    meta = {**data, **ni_data}
    texts = {u: r["text"] for u, r in meta.items()}

    # the question texts recorded by run_api.py are the ones in jevlab.QUESTIONS
    for exp in (BASE_EXP, EXP):
        with open(os.path.join(J.RESULTS, exp, "summary.json"), encoding="utf-8") as f:
            s = json.load(f)
        for q, txt in s["questions"].items():
            assert txt == J.QUESTIONS[q], f"{exp}/summary.json question {q} differs from jevlab.QUESTIONS"
        assert s["model"] == MODEL

    preds, raws, raw_all = {}, {}, {}
    for q in QIDS:
        exp = Q_EXP[q]
        d = pd.read_csv(os.path.join(J.RESULTS, exp, f"{q}_predictions.csv"))
        recs = J.load_jsonl(J.raw_path(exp, q))
        raw_all[q] = recs
        raw = pd.DataFrame([r for r in recs if r.get("http_status") == 200 and "noul" in r])
        bad = [u for u, h in zip(raw["uid"], raw["text_md5"]) if md5_text(texts[u]) != h]
        assert not bad, f"{q}: raw text_md5 differs from the dataset text for {len(set(bad))} uids"
        raw = raw.sort_values("started_at").drop_duplicates(["uid", "run", "text_md5"], keep="first")
        piv = raw.pivot(index="uid", columns="run", values="noul")
        chk = d.set_index("uid")
        for r in range(J.REPEATS):
            assert np.allclose(chk[f"p_run{r}"], piv.loc[chk.index, r]), f"{q}: p_run{r} differs from raw"
        assert np.allclose(chk["p"], piv.loc[chk.index].mean(axis=1)), f"{q}: p is not the mean of the raw runs"
        assert (d["pred"] == (d["p"] >= THRESHOLD).astype(int)).all()
        assert (raw["model"] == MODEL).all() and (raw["question_id"] == q).all()
        assert (d["n_runs"] == J.REPEATS).all() and J.REPEATS * 100 == GRID
        d["p"] = snap(d["p"])
        for r in range(J.REPEATS):
            d[f"p_run{r}"] = snap(d[f"p_run{r}"], 100)
        assert (d["pred"] == (d["p"] >= THRESHOLD).astype(int)).all(), "snapping changed a 0.5 decision"
        preds[q], raws[q] = d, raw

    base_cols = ["uid", "label", "label_int", "set", "id", "source", "subset", "doc_type", "risk_level", "harm_type", "char_len"]
    W = preds[REF][base_cols].copy()
    for q in QIDS:
        d = preds[q].set_index("uid")
        assert set(d.index) == set(W.uid), f"{q}: different documents"
        assert (W.uid.map(d["label_int"]) == W.label_int).all() and (W.uid.map(d["set"]) == W.set).all()
        for c in ["p", "pred", "p_sd", "flip", "input_tokens", "latency_s", "p_run0", "p_run1", "p_run2"]:
            W[f"{c}_{q}"] = W["uid"].map(d[c])
        runs = W[[f"p_run{r}_{q}" for r in range(3)]]
        W[f"p_range_{q}"] = runs.max(axis=1) - runs.min(axis=1)
        W[f"correct_{q}"] = (W[f"pred_{q}"] == W["label_int"]).astype(int)
    W["text"] = W["uid"].map(texts)
    assert (W["char_len"] == W["text"].str.len()).all()
    W["injected_instruction"] = W["uid"].map(lambda u: meta[u].get("injected_instruction"))
    W["doc_type_ko"] = W["uid"].map(lambda u: meta[u].get("doc_type_ko"))
    W["harm_type_ko"] = W["uid"].map(lambda u: meta[u].get("harm_type_ko"))
    W["n_flag"] = W[[f"pred_{q}" for q in QIDS]].sum(axis=1)
    EN = W[W["set"] == "EN"].reset_index(drop=True)
    NI = W[W["set"] == "NOTINJECT"].reset_index(drop=True)
    assert len(EN) == 1000 and EN.label_int.sum() == 500 and len(NI) == 25 and NI.label_int.sum() == 0
    return EN, NI, raws, raw_all


# ------------------------------------------------------------------ metric blocks
def counts(y, pred):
    y, pred = np.asarray(y), np.asarray(pred)
    return {"tp": int(((y == 1) & (pred == 1)).sum()), "fn": int(((y == 1) & (pred == 0)).sum()),
            "fp": int(((y == 0) & (pred == 1)).sum()), "tn": int(((y == 0) & (pred == 0)).sum())}


def block(sub, q):
    y, p = sub["label_int"].tolist(), sub[f"p_{q}"].tolist()
    m = metrics(y, p, threshold=THRESHOLD)
    c = counts(y, sub[f"pred_{q}"])
    pos, neg = c["tp"] + c["fn"], c["fp"] + c["tn"]
    tl, th = J.wilson(c["tp"], pos) if pos else [None, None]
    fl, fh = J.wilson(c["fp"], neg) if neg else [None, None]
    return {"question": q, "n": m["n"], "n_injection": pos, "n_benign": neg, **c,
            "TPR": m["TPR"], "TPR_lo": tl, "TPR_hi": th, "FPR": m["FPR"], "FPR_lo": fl, "FPR_hi": fh, "AUC": m["AUC"],
            "mean_p_injection": float(sub.loc[sub.label_int == 1, f"p_{q}"].mean()) if pos else None,
            "mean_p_benign": float(sub.loc[sub.label_int == 0, f"p_{q}"].mean()) if neg else None}


BOOT_KEYS = ["TPR", "FPR", "AUC", "mean_p_injection", "mean_p_benign", "accuracy"] + [f"TPR_at_FPR{int(f * 100)}" for f in FPR_TARGETS]


def boot_index(y):
    """The label-stratified resample indices (B pairs of injection / benign row indices) used by every paired
    bootstrap on the EN set, so all comparisons share the same resamples (seed 20261112)."""
    rng = np.random.default_rng(SEED)
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    return [(rng.choice(pos, len(pos)), rng.choice(neg, len(neg))) for _ in range(B)]


def paired_bootstrap(EN):
    """Label-stratified resampling, the same indices for all five questions (paired)."""
    y = EN["label_int"].to_numpy()
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    P = {q: EN[f"p_{q}"].to_numpy() for q in QIDS}
    assert all(abs(auc_fast(P[q][pos], P[q][neg]) - roc_auc_score(y, P[q])) < 1e-12 for q in QIDS)
    dist = {q: {k: np.empty(B) for k in BOOT_KEYS} for q in QIDS}
    for b, (ip, ineg) in enumerate(boot_index(y)):
        for q in QIDS:
            pp, pn = P[q][ip], P[q][ineg]
            d = dist[q]
            d["TPR"][b] = (pp >= THRESHOLD).mean()
            d["FPR"][b] = (pn >= THRESHOLD).mean()
            d["AUC"][b] = auc_fast(pp, pn)
            d["mean_p_injection"][b] = pp.mean()
            d["mean_p_benign"][b] = pn.mean()
            d["accuracy"][b] = ((pp >= THRESHOLD).sum() + (pn < THRESHOLD).sum()) / (len(pp) + len(pn))
            for f in FPR_TARGETS:
                d[f"TPR_at_FPR{int(f * 100)}"][b] = (pp >= thr_at_fpr(pn, f)).mean()
    return dist


# ------------------------------------------------------------------ overall
def overall_tables(EN, NI, boot, raws):
    y = EN["label_int"].to_numpy()
    rows, thr_rows, point = [], [], {}
    for q in QIDS:
        b = block(EN, q)
        b["name"] = Q_NAMES[q]
        b["AUC_lo"], b["AUC_hi"] = ci(boot[q]["AUC"])
        for k in ("mean_p_injection", "mean_p_benign"):
            b[f"{k}_lo"], b[f"{k}_hi"] = ci(boot[q][k])
        b["accuracy"] = (b["tp"] + b["tn"]) / b["n"]
        b["accuracy_lo"], b["accuracy_hi"] = ci(boot[q]["accuracy"])
        b["brier"] = float(((EN[f"p_{q}"].to_numpy() - y) ** 2).mean())
        pp = EN.loc[EN.label_int == 1, f"p_{q}"].to_numpy()
        pn = EN.loc[EN.label_int == 0, f"p_{q}"].to_numpy()
        point[q] = {k: b[k] for k in ("TPR", "FPR", "AUC", "mean_p_injection", "mean_p_benign", "accuracy")}
        thr_rows.append({"question": q, "target": "기준 0.5", "target_FPR": None, "threshold": THRESHOLD,
                         "tp": int((pp >= THRESHOLD).sum()), "fp": int((pn >= THRESHOLD).sum()),
                         "TPR": (pp >= THRESHOLD).mean(), "FPR": (pn >= THRESHOLD).mean(),
                         "TPR_lo": b["TPR_lo"], "TPR_hi": b["TPR_hi"], "TPR_boot_lo": None, "TPR_boot_hi": None,
                         "fitted_on_same_data": False})
        for f in FPR_TARGETS:
            key = f"TPR_at_FPR{int(f * 100)}"
            t = thr_at_fpr(pn, f)
            t3 = round(t, 3)
            assert ((pp >= t3) == (pp >= t)).all() and ((pn >= t3) == (pn >= t)).all() and (pn >= t).mean() <= f + 1e-12
            k = int((pp >= t).sum())
            lo, hi = ci(boot[q][key])
            point[q][key] = k / len(pp)
            b[f"threshold_FPR{int(f * 100)}"] = t
            b[key] = k / len(pp)
            b[f"{key}_lo"], b[f"{key}_hi"] = lo, hi
            wl, wh = J.wilson(k, len(pp))
            thr_rows.append({"question": q, "target": f"오탐 {int(f * 100)}% 이하", "target_FPR": f, "threshold": t, "tp": k,
                             "fp": int((pn >= t).sum()), "TPR": k / len(pp), "FPR": (pn >= t).mean(), "TPR_lo": wl, "TPR_hi": wh,
                             "TPR_boot_lo": lo, "TPR_boot_hi": hi, "fitted_on_same_data": True})
        # NotInject (benign only)
        fp = int((NI[f"p_{q}"] >= THRESHOLD).sum())
        b["notinject_n"], b["notinject_fp"] = len(NI), fp
        b["notinject_FPR"] = fp / len(NI)
        b["notinject_FPR_lo"], b["notinject_FPR_hi"] = J.wilson(fp, len(NI))
        b["notinject_mean_p"], b["notinject_max_p"] = float(NI[f"p_{q}"].mean()), float(NI[f"p_{q}"].max())
        # cost and speed (EN docs: mean input tokens per call; latency over every successful call of this question)
        r = raws[q]
        b["input_tokens_per_call_EN"] = float(EN[f"input_tokens_{q}"].mean())
        b["extra_tokens_vs_Q2"] = float((EN[f"input_tokens_{q}"] - EN[f"input_tokens_{REF}"]).mean())
        b["latency_ms_median"] = float(r["latency_ms"].astype(float).median())
        b["latency_ms_mean"] = float(r["latency_ms"].astype(float).mean())
        b["docs_with_flip"] = int(EN[f"flip_{q}"].sum())
        rows.append(b)
    overall = save_table(pd.DataFrame(rows), "overall_5q")
    thresholds = save_table(pd.DataFrame(thr_rows), "thresholds_at_fpr")

    # ---- Δ vs Q2 (paired) ----
    names = {"TPR": "TPR (0.5)", "FPR": "FPR (0.5)", "AUC": "AUC", "accuracy": "정확도 (0.5)",
             "mean_p_injection": "평균 p (인젝션)", "mean_p_benign": "평균 p (정상)",
             "TPR_at_FPR1": "TPR @ 오탐 1% 임계값", "TPR_at_FPR5": "TPR @ 오탐 5% 임계값", "TPR_at_FPR10": "TPR @ 오탐 10% 임계값"}
    a = EN[f"pred_{REF}"].to_numpy()
    ca = EN[f"correct_{REF}"].to_numpy()
    drows = []
    for q in OTHERS:
        c = EN[f"pred_{q}"].to_numpy()
        cc = EN[f"correct_{q}"].to_numpy()
        mc = {"TPR": (int(((y == 1) & (a == 1) & (c == 0)).sum()), int(((y == 1) & (a == 0) & (c == 1)).sum())),
              "FPR": (int(((y == 0) & (a == 1) & (c == 0)).sum()), int(((y == 0) & (a == 0) & (c == 1)).sum())),
              "accuracy": (int(((ca == 1) & (cc == 0)).sum()), int(((ca == 0) & (cc == 1)).sum()))}
        for k, nm in names.items():
            lo, hi = ci(boot[q][k] - boot[REF][k])
            r = {"question": q, "metric": k, "name": nm, "Q2": point[REF][k], "value": point[q][k],
                 "delta": point[q][k] - point[REF][k], "delta_lo": lo, "delta_hi": hi,
                 "verdict": verdict(lo, hi, "Q2보다 높음", "Q2보다 낮음"), "boot_n": B, "boot_seed": SEED}
            if k in mc:
                r.update({"only_Q2": mc[k][0], "only_question": mc[k][1], "mcnemar_p": mcnemar_exact(*mc[k])})
            drows.append(r)
    delta = pd.DataFrame(drows)
    delta["mcnemar_p_holm4"] = np.nan
    for k in ("TPR", "FPR", "accuracy"):
        m = delta.metric == k
        delta.loc[m, "mcnemar_p_holm4"] = holm(delta.loc[m, "mcnemar_p"])
    for c in ("only_Q2", "only_question"):
        delta[c] = delta[c].astype("Int64")
    delta = save_table(delta, "delta_vs_q2")

    # ---- every pair (10) ----
    prow = []
    for qa, qb in itertools.combinations(QIDS, 2):
        pa, pb = EN[f"pred_{qa}"].to_numpy(), EN[f"pred_{qb}"].to_numpy()
        cra, crb = EN[f"correct_{qa}"].to_numpy(), EN[f"correct_{qb}"].to_numpy()
        r = {"a": qa, "b": qb}
        for k in ("TPR", "FPR", "AUC", "accuracy", "TPR_at_FPR1", "TPR_at_FPR5"):
            lo, hi = ci(boot[qb][k] - boot[qa][k])
            r.update({f"d{k}": point[qb][k] - point[qa][k], f"d{k}_lo": lo, f"d{k}_hi": hi})
        oa, ob = int(((cra == 1) & (crb == 0)).sum()), int(((cra == 0) & (crb == 1)).sum())
        ia, ib = int(((y == 1) & (pa == 1) & (pb == 0)).sum()), int(((y == 1) & (pa == 0) & (pb == 1)).sum())
        r.update({"correct_only_a": oa, "correct_only_b": ob, "mcnemar_p_accuracy": mcnemar_exact(oa, ob),
                  "caught_only_a": ia, "caught_only_b": ib, "mcnemar_p_TPR": mcnemar_exact(ia, ib)})
        prow.append(r)
    pairs = pd.DataFrame(prow)
    pairs["mcnemar_p_accuracy_holm10"] = holm(pairs["mcnemar_p_accuracy"])
    pairs["mcnemar_p_TPR_holm10"] = holm(pairs["mcnemar_p_TPR"])
    for k in ("dAUC", "daccuracy", "dTPR", "dFPR"):
        pairs[f"{k}_verdict"] = [verdict(lo, hi, "b 높음", "b 낮음") for lo, hi in zip(pairs[f"{k}_lo"], pairs[f"{k}_hi"])]
    pairs = save_table(pairs, "pairwise_all_questions")

    # NotInject paired vs Q2 (mean p)
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(NI), size=(B, len(NI)))
    nrow = []
    for q in QIDS:
        r = {"question": q, "n": len(NI), "fp": int((NI[f"p_{q}"] >= THRESHOLD).sum()),
             "FPR_hi": J.wilson(int((NI[f"p_{q}"] >= THRESHOLD).sum()), len(NI))[1],
             "mean_p": float(NI[f"p_{q}"].mean()), "max_p": float(NI[f"p_{q}"].max())}
        if q != REF:
            dd = NI[f"p_{q}"].to_numpy()[idx].mean(1) - NI[f"p_{REF}"].to_numpy()[idx].mean(1)
            lo, hi = ci(dd)
            r.update({"d_mean_p_vs_Q2": r["mean_p"] - float(NI[f"p_{REF}"].mean()), "d_lo": lo, "d_hi": hi,
                      "verdict": verdict(lo, hi, "Q2보다 높음", "Q2보다 낮음")})
        nrow.append(r)
    notinject = save_table(pd.DataFrame(nrow), "notinject_overdefense")
    return overall, thresholds, delta, pairs, notinject, point


# ------------------------------------------------------------------ groups
def by_group(df, col, keys, label=None):
    rows = []
    for k in keys:
        sub = df[df[col] == k]
        if not len(sub):
            continue
        for q in QIDS:
            rows.append({col: k, "group": (label or {}).get(k, k), **block(sub, q)})
    return pd.DataFrame(rows)


def group_vs_q2(df, col, keys, label=None):
    """Per group and label: each question vs Q2 on the same docs. ΔTPR (injection) / ΔFPR (benign)."""
    rng = np.random.default_rng(SEED)
    rows = []
    for k in keys:
        sub = df[df[col] == k]
        for lab, met in ((1, "TPR"), (0, "FPR")):
            s = sub[sub.label_int == lab]
            n = len(s)
            if n == 0:
                continue
            idx = rng.integers(0, n, size=(B, n))
            a = s[f"pred_{REF}"].to_numpy()
            for q in OTHERS:
                c = s[f"pred_{q}"].to_numpy()
                only_ref, only_q = int(((a == 1) & (c == 0)).sum()), int(((a == 0) & (c == 1)).sum())
                lo, hi = ci(c[idx].mean(1) - a[idx].mean(1))
                rows.append({col: k, "group": (label or {}).get(k, k), "metric": met, "question": q, "n": n,
                             "Q2": a.mean(), "value": c.mean(), "delta": c.mean() - a.mean(), "delta_lo": lo, "delta_hi": hi,
                             "only_Q2": only_ref, "only_question": only_q, "mcnemar_p": mcnemar_exact(only_ref, only_q),
                             "mean_dp": float((s[f"p_{q}"] - s[f"p_{REF}"]).mean())})
    t = pd.DataFrame(rows)
    t["mcnemar_p_holm"] = np.nan
    for met in ("TPR", "FPR"):
        m = t.metric == met
        if m.any():
            t.loc[m, "mcnemar_p_holm"] = holm(t.loc[m, "mcnemar_p"])
    t["verdict"] = [group_verdict(lo, hi, ph, n) for lo, hi, ph, n in zip(t.delta_lo, t.delta_hi, t.mcnemar_p_holm, t.n)]
    return t


# ------------------------------------------------------------------ agreement and overlap
def agreement(EN):
    inj, ben = EN.label_int == 1, EN.label_int == 0
    rows = []
    for a, b in itertools.combinations(QIDS, 2):
        pa, pb = EN[f"pred_{a}"], EN[f"pred_{b}"]
        same = pa == pb
        rows.append({"a": a, "b": b, "agree_all": same.mean(), "agree_injection": same[inj].mean(), "agree_benign": same[ben].mean(),
                     "n_disagree_all": int((~same).sum()), "n_disagree_injection": int((~same)[inj].sum()),
                     "n_disagree_benign": int((~same)[ben].sum()), "kappa_all": cohen_kappa_score(pa, pb),
                     "kappa_injection": cohen_kappa_score(pa[inj], pb[inj]),
                     "spearman_p_all": EN[f"p_{a}"].rank().corr(EN[f"p_{b}"].rank()),
                     "spearman_p_injection": EN.loc[inj, f"p_{a}"].rank().corr(EN.loc[inj, f"p_{b}"].rank()),
                     "spearman_p_benign": EN.loc[ben, f"p_{a}"].rank().corr(EN.loc[ben, f"p_{b}"].rank())})
    pairs = save_table(pd.DataFrame(rows), "agreement_pairs")
    mats = {}
    for key, col in (("all", "agree_all"), ("injection", "agree_injection"), ("benign", "agree_benign"), ("kappa_injection", "kappa_injection")):
        m = pd.DataFrame(np.eye(len(QIDS)), index=QIDS, columns=QIDS)
        for _, r in pairs.iterrows():
            m.loc[r.a, r.b] = m.loc[r.b, r.a] = r[col]
        mats[key] = m
        save_table(m.reset_index().rename(columns={"index": "question"}), f"agreement_matrix_{key}")
    return pairs, mats


def overlap(EN, NI):
    inj = EN[EN.label_int == 1]
    ben = EN[EN.label_int == 0]
    # how many questions catch each injection, overall and by source
    cc = []
    for s in ["전체"] + [x for x in SOURCE_ORDER if x in set(inj.source)]:
        g = inj if s == "전체" else inj[inj.source == s]
        r = {"source": s, "n_injection": len(g)}
        for k in range(len(QIDS) + 1):
            r[f"caught_by_{k}"] = int((g.n_flag == k).sum())
        r["share_caught_by_none"] = r["caught_by_0"] / len(g)
        r["share_caught_by_any"] = 1 - r["share_caught_by_none"]
        r["share_caught_by_all5"] = r[f"caught_by_{len(QIDS)}"] / len(g)
        some = len(g) - r["caught_by_0"] - r[f"caught_by_{len(QIDS)}"]
        r["caught_by_some_1to4"] = some
        r["share_caught_by_some_1to4"] = some / len(g)
        for key, k in (("none", r["caught_by_0"]), ("some_1to4", some), ("all5", r[f"caught_by_{len(QIDS)}"])):
            r[f"share_caught_by_{key}_lo"], r[f"share_caught_by_{key}_hi"] = J.wilson(int(k), len(g))
        cc.append(r)
    catch = save_table(pd.DataFrame(cc), "catch_count_by_source")

    # documents where exactly one question decides differently from the other four
    srows, drows = [], []
    for q in QIDS:
        others = [o for o in QIDS if o != q]
        only_caught = inj[(inj[f"pred_{q}"] == 1) & (inj[[f"pred_{o}" for o in others]].sum(axis=1) == 0)]
        only_missed = inj[(inj[f"pred_{q}"] == 0) & (inj[[f"pred_{o}" for o in others]].sum(axis=1) == len(others))]
        only_flag = ben[(ben[f"pred_{q}"] == 1) & (ben[[f"pred_{o}" for o in others]].sum(axis=1) == 0)]
        srows.append({"question": q, "injection_caught_only_by_this": len(only_caught),
                      "injection_missed_only_by_this": len(only_missed), "benign_flagged_only_by_this": len(only_flag),
                      "caught_only_sources": "; ".join(f"{k} {v}" for k, v in only_caught.source.value_counts().items()),
                      "missed_only_sources": "; ".join(f"{k} {v}" for k, v in only_missed.source.value_counts().items())})
        for kind, g in (("이 질문만 잡음", only_caught), ("이 질문만 놓침", only_missed), ("이 질문만 오탐", only_flag)):
            for _, r in g.iterrows():
                drows.append({"question": q, "kind": kind, "uid": r.uid, "id": r.id, "source": r.source, "label": r.label,
                              "harm_type": r.harm_type, "risk_level": r.risk_level,
                              **{f"p_{x}": r[f"p_{x}"] for x in QIDS},
                              "instruction_or_text": short(r.injected_instruction, 140) or short(r.text, 140)})
    only_sum = save_table(pd.DataFrame(srows), "only_one_question_summary")
    only_docs = save_table(pd.DataFrame(drows), "only_one_question_docs")

    # combinations (descriptive; picking a rule here is fitting on the same data)
    crow = []
    for name, rule in (("5개 중 하나라도 (합집합)", lambda d: d.n_flag >= 1), ("5개 중 3개 이상 (다수결)", lambda d: d.n_flag >= 3),
                       ("5개 모두 (교집합)", lambda d: d.n_flag == len(QIDS)),
                       ("Q2 또는 QL (팀의 두 축)", lambda d: (d.pred_Q2 + d.pred_QL) >= 1)):
        tp, fp = int(rule(inj).sum()), int(rule(ben).sum())
        nfp = int(rule(NI).sum())
        crow.append({"rule": name, "tp": tp, "TPR": tp / len(inj), "TPR_lo": J.wilson(tp, len(inj))[0], "TPR_hi": J.wilson(tp, len(inj))[1],
                     "fp": fp, "FPR": fp / len(ben), "FPR_lo": J.wilson(fp, len(ben))[0], "FPR_hi": J.wilson(fp, len(ben))[1],
                     "notinject_fp": nfp, "calls_per_doc": 2 if "Q2 또는" in name else len(QIDS)})
    combos = save_table(pd.DataFrame(crow), "combination_rules")
    combos_vs = save_table(combination_vs_ql(EN, (("5개 중 하나라도 (합집합)", lambda d: d.n_flag >= 1),
                                                  ("5개 중 3개 이상 (다수결)", lambda d: d.n_flag >= 3),
                                                  ("5개 모두 (교집합)", lambda d: d.n_flag == len(QIDS)),
                                                  ("Q2 또는 QL (팀의 두 축)", lambda d: (d.pred_Q2 + d.pred_QL) >= 1))),
                           "combination_vs_ql")

    # every benign doc flagged by at least one question (EN and NotInject)
    fpd = pd.concat([ben[ben.n_flag >= 1], NI[NI.n_flag >= 1]])
    fpd = fpd.assign(flagged_by=[" ".join(q for q in QIDS if r[f"pred_{q}"] == 1) for _, r in fpd.iterrows()],
                     snippet=fpd.text.map(lambda s: short(s, 160)))
    fps = save_table(fpd.sort_values(["n_flag", "source"], ascending=[False, True])[
        ["uid", "id", "set", "source", "doc_type", "n_flag", "flagged_by"] + [f"p_{q}" for q in QIDS] + ["char_len", "snippet"]],
        "false_positives_any_question")

    # injections no question catches: how far below 0.5 they are
    none = inj[inj.n_flag == 0].copy()
    none["max_p"] = none[[f"p_{q}" for q in QIDS]].max(axis=1)
    none["best_question"] = none[[f"p_{q}" for q in QIDS]].idxmax(axis=1).str[2:]
    save_table(none.sort_values(["source", "max_p"])[["uid", "id", "source", "harm_type", "risk_level", "max_p", "best_question"]
                                                      + [f"p_{q}" for q in QIDS]].assign(
        instruction=none.injected_instruction.map(lambda s: short(s, 140))), "missed_by_all_questions")
    return catch, only_sum, only_docs, combos, combos_vs, fps, none


def combination_vs_ql(EN, rules):
    """Each combination rule vs QL alone on the same documents: QL at 0.5, and QL at its 1%-FPR threshold
    (fitted on the same benign docs). ΔTPR / ΔFPR = rule − QL. Exact McNemar on the discordant docs and a paired
    bootstrap on the shared resamples (boot_index). For the fitted threshold there are two intervals: threshold held at
    the full-data value (`delta_lo/hi`) and threshold refitted inside every resample (`delta_lo_refit/hi_refit`, wider,
    since the threshold is itself an estimate)."""
    y = EN["label_int"].to_numpy()
    p_ql = EN["p_QL"].to_numpy()
    t1 = thr_at_fpr(p_ql[y == 0], 0.01)
    idx = boot_index(y)
    refs = (("QL 0.5", THRESHOLD, False), (f"QL 오탐 1% 임계값 ({t1:.3f}, 같은 데이터에서 맞춤)", t1, True))
    rows = []
    for name, rule in rules:
        r_flag = rule(EN).to_numpy().astype(int)
        for ref, t, fitted in refs:
            q_flag = (p_ql >= t).astype(int)
            for lab, met in ((1, "TPR"), (0, "FPR")):
                m = y == lab
                a, c = r_flag[m], q_flag[m]
                only_rule, only_ql = int(((a == 1) & (c == 0)).sum()), int(((a == 0) & (c == 1)).sum())
                dd, dr = np.empty(B), np.empty(B)
                for b, (ip, ineg) in enumerate(idx):
                    ii = ip if lab == 1 else ineg
                    dd[b] = r_flag[ii].mean() - q_flag[ii].mean()
                    if fitted:
                        tb = thr_at_fpr(p_ql[ineg], 0.01)
                        dr[b] = r_flag[ii].mean() - (p_ql[ii] >= tb).mean()
                lo, hi = ci(dd)
                lo_r, hi_r = ci(dr) if fitted else (None, None)
                row = {"rule": name, "reference": ref, "reference_threshold": t, "threshold_fitted_on_same_data": fitted,
                       "metric": met, "n": int(m.sum()), "rule_value": a.mean(), "QL_value": c.mean(),
                       "delta": a.mean() - c.mean(), "delta_lo": lo, "delta_hi": hi, "delta_lo_refit": lo_r, "delta_hi_refit": hi_r,
                       "only_rule": only_rule, "only_QL": only_ql, "mcnemar_p": mcnemar_exact(only_rule, only_ql),
                       "boot_n": B, "boot_seed": SEED}
                wide = (lo, hi) if not fitted else (min(lo, lo_r), max(hi, hi_r))
                row["verdict"] = verdict(*wide, "규칙이 높음", "규칙이 낮음")
                rows.append(row)
    return pd.DataFrame(rows)


# ------------------------------------------------------------------ stability, cost, sweep
def stability(EN):
    per_run, rows, noise = [], [], []
    y = EN["label_int"].to_numpy()
    for q in QIDS:
        for r in range(3):
            m = metrics(EN["label_int"].tolist(), EN[f"p_run{r}_{q}"].tolist(), threshold=THRESHOLD)
            per_run.append({"question": q, "run": r, **m})
        mid = (EN[f"p_{q}"] > 0.2) & (EN[f"p_{q}"] < 0.8)
        band = (EN[f"p_{q}"] >= 0.4) & (EN[f"p_{q}"] < 0.6)       # near the threshold: where a 0.5 decision can flip
        fl = EN[EN[f"flip_{q}"]]
        nf, nb, nfb = int(EN[f"flip_{q}"].sum()), int(band.sum()), int(EN.loc[band, f"flip_{q}"].sum())
        fr_lo, fr_hi = J.wilson(nf, len(EN))
        fb_lo, fb_hi = J.wilson(nfb, nb)
        rows.append({"question": q, "docs_with_flip": nf, "flip_rate": nf / len(EN), "flip_rate_lo": fr_lo, "flip_rate_hi": fr_hi,
                     "flip_p_min": float(fl[f"p_{q}"].min()) if len(fl) else None,
                     "flip_p_max": float(fl[f"p_{q}"].max()) if len(fl) else None,
                     "n_band_0.4_0.6": nb, "flips_in_band_0.4_0.6": nfb, "flip_rate_in_band": nfb / nb if nb else None,
                     "flip_rate_in_band_lo": fb_lo, "flip_rate_in_band_hi": fb_hi,
                     "p_sd_mean": float(EN[f"p_sd_{q}"].mean()), "p_sd_mean_mid_0.2_0.8": float(EN.loc[mid, f"p_sd_{q}"].mean()),
                     "n_mid_0.2_0.8": int(mid.sum()), "p_range_max": float(EN[f"p_range_{q}"].max()),
                     "share_identical_3_runs": float((EN[f"p_range_{q}"] == 0).mean()),
                     "share_identical_3_runs_mid_0.2_0.8": float((EN.loc[mid, f"p_range_{q}"] == 0).mean()),
                     # p is a mean of 0.01-step runs; at the floor (p <= 0.02) three identical runs are the rule
                     "n_floor_p_le_0.02": int((EN[f"p_{q}"] <= 0.02 + 1e-9).sum()),
                     "share_identical_3_runs_floor": float((EN.loc[EN[f"p_{q}"] <= 0.02 + 1e-9, f"p_range_{q}"] == 0).mean())})
    # paired: does one question flip on more of the same documents than another? (exact McNemar on the flip indicator)
    frows = []
    for a, b in itertools.combinations(QIDS, 2):
        fa, fb = EN[f"flip_{a}"].astype(bool).to_numpy(), EN[f"flip_{b}"].astype(bool).to_numpy()
        oa, ob = int((fa & ~fb).sum()), int((~fa & fb).sum())
        frows.append({"a": a, "b": b, "flips_a": int(fa.sum()), "flips_b": int(fb.sum()), "flip_only_a": oa, "flip_only_b": ob,
                      "flip_both": int((fa & fb).sum()), "mcnemar_p": mcnemar_exact(oa, ob)})
    fpair = pd.DataFrame(frows)
    fpair["mcnemar_p_holm10"] = holm(fpair["mcnemar_p"])
    fpair["verdict"] = np.where(fpair["mcnemar_p_holm10"] < 0.05, "갈림 수 다름", "차이 없음 (오차 범위)")
    save_table(fpair, "flip_pairwise")

    def corr(col):
        return (EN[col].to_numpy() >= THRESHOLD).astype(int) == y

    for q in QIDS:
        v = [int((corr(f"p_run{i}_{q}") != corr(f"p_run{j}_{q}")).sum()) for i, j in ((0, 1), (0, 2), (1, 2))]
        noise.append({"comparison": f"{q} 회차 사이", "kind": "같은 질문 반복 (호출 1번씩)", "question": q,
                      "discordant_docs_mean": float(np.mean(v)), "discordant_docs_min": min(v), "discordant_docs_max": max(v)})
    for q in OTHERS:
        v = [int((corr(f"p_run{r}_{REF}") != corr(f"p_run{r}_{q}")).sum()) for r in range(3)]
        noise.append({"comparison": f"Q2 vs {q}", "kind": "질문 차이 (호출 1번씩, 같은 회차 번호)", "question": q,
                      "discordant_docs_mean": float(np.mean(v)), "discordant_docs_min": min(v), "discordant_docs_max": max(v),
                      "discordant_docs_3run_mean": int((EN[f"correct_{REF}"] != EN[f"correct_{q}"]).sum())})
    return (save_table(pd.DataFrame(per_run), "per_run_metrics"), save_table(pd.DataFrame(rows), "stability"),
            save_table(pd.DataFrame(noise), "noise_floor_discordance"), fpair)


def latency_tokens(EN, raws, raw_all):
    rows = []
    for q in QIDS:
        r = raws[q]
        lat = r["latency_ms"].astype(float)
        tin, tout = r["usage_input_tokens"].astype(float), r["usage_output_tokens"].astype(float)
        starts = sorted(x["started_at"] for x in raw_all[q])
        span = (dt.datetime.fromisoformat(starts[-1]) - dt.datetime.fromisoformat(starts[0])).total_seconds()
        dtok = EN[f"input_tokens_{q}"] - EN[f"input_tokens_{REF}"]
        rows.append({"question": q, "source_folder": f"results/{Q_EXP[q]}", "calls": len(raw_all[q]),
                     "errors": int(sum(1 for x in raw_all[q] if x.get("http_status") != 200)),
                     "retries": int(sum(int(x.get("retries") or 0) for x in raw_all[q])),
                     "latency_ms_median": lat.median(), "latency_ms_mean": lat.mean(), "latency_ms_p90": lat.quantile(0.9),
                     "latency_ms_p99": lat.quantile(0.99), "latency_ms_max": lat.max(),
                     "first_call_utc": starts[0], "last_call_utc": starts[-1], "wall_clock_s": span, "concurrency": 6,
                     "input_tokens_per_call_EN": float(EN[f"input_tokens_{q}"].mean()),
                     "extra_tokens_vs_Q2_mean": float(dtok.mean()), "extra_tokens_vs_Q2_min": float(dtok.min()),
                     "extra_tokens_vs_Q2_max": float(dtok.max()), "output_tokens_per_call": float(tout.mean()),
                     "input_tokens_total": int(tin.sum()), "input_cost_usd_total": float(tin.sum() * PRICE_IN),
                     "input_cost_usd_per_1000_EN_docs_1_call": float(EN[f"input_tokens_{q}"].sum() * PRICE_IN)})
    return save_table(pd.DataFrame(rows), "latency_tokens_cost")


def sweep(EN):
    rows = []
    for q in QIDS:
        pp = EN.loc[EN.label_int == 1, f"p_{q}"].to_numpy()
        pn = EN.loc[EN.label_int == 0, f"p_{q}"].to_numpy()
        for t in np.round(np.arange(0.01, 1.0, 0.01), 2):
            rows.append({"question": q, "threshold": float(t), "TPR": float((pp >= t).mean()), "FPR": float((pn >= t).mean())})
    return save_table(pd.DataFrame(rows), "threshold_sweep")


# ------------------------------------------------------------------ selection optimism (best of five on the same data)
CRITS = ("AUC", "accuracy")


def selection_optimism(EN):
    rng = np.random.default_rng(SEED)
    y = EN["label_int"].to_numpy()
    P = {q: EN[f"p_{q}"].to_numpy() for q in QIDS}
    strata = [np.asarray(ix) for ix in EN.groupby(["source", "label_int"]).indices.values()]

    def score(ix, q, crit):
        yy, pp = y[ix], P[q][ix]
        if crit == "AUC":
            return auc_fast(pp[yy == 1], pp[yy == 0])
        return float(((pp >= THRESHOLD).astype(int) == yy).mean())

    draws = []
    for s in range(N_SPLITS):
        A = np.concatenate([rng.permutation(ix)[: (len(ix) + rng.integers(0, 2)) // 2] for ix in strata])
        mask = np.zeros(len(EN), bool)
        mask[A] = True
        Bx = np.where(~mask)[0]
        for crit in CRITS:
            sa = {q: score(A, q, crit) for q in QIDS}
            sb = {q: score(Bx, q, crit) for q in QIDS}
            best = max(QIDS, key=lambda q: sa[q])          # ties -> earlier in QIDS order
            bb = max(sb.values())
            draws.append({"split": s, "criterion": crit, "selected": best, "score_A": sa[best], "score_B": sb[best],
                          "best_B": bb, "selected_is_best_on_B": sb[best] >= bb - 1e-12,
                          "optimism": sa[best] - sb[best], "regret_on_B": bb - sb[best]})
    d = pd.DataFrame(draws)
    rows = []
    for crit in CRITS:
        g = d[d.criterion == crit]
        full = {q: (metrics(EN.label_int.tolist(), EN[f"p_{q}"].tolist())["AUC"] if crit == "AUC"
                    else float((EN[f"pred_{q}"] == EN.label_int).mean())) for q in QIDS}
        win = max(QIDS, key=lambda q: full[q])
        lo, hi = ci(g.optimism)
        rows.append({"criterion": crit, "splits": len(g), "full_data_winner": win, "full_data_winner_score": full[win],
                     **{f"selected_share_{q}": float((g.selected == q).mean()) for q in QIDS},
                     "optimism_mean": float(g.optimism.mean()), "optimism_lo": lo, "optimism_hi": hi,
                     "selected_is_best_on_B_share": float(g.selected_is_best_on_B.mean()),
                     "regret_on_B_mean": float(g.regret_on_B.mean())})
    return save_table(pd.DataFrame(rows), "selection_optimism"), d


# ------------------------------------------------------------------ figures
def _err(v, lo, hi):
    v, lo, hi = (np.asarray(x, dtype=float) for x in (v, lo, hi))
    return [np.maximum(v - lo, 0), np.maximum(hi - v, 0)]


def spread(ys, gap, lo=-np.inf, hi=np.inf):
    """Push label positions apart by at least `gap` (keeps order), then pull back inside [lo, hi]."""
    ys = np.asarray(ys, dtype=float)
    order = np.argsort(ys, kind="stable")
    s = ys[order].copy()
    for i in range(1, len(s)):
        s[i] = max(s[i], s[i - 1] + gap)
    if s[-1] > hi:
        s[-1] = hi
        for i in range(len(s) - 2, -1, -1):
            s[i] = min(s[i], s[i + 1] - gap)
    if s[0] < lo:
        s += lo - s[0]
    out = np.empty_like(s)
    out[order] = s
    return out


def tpr_at(f, t, x):
    return float(t[f <= x + 1e-12].max())


def dot_rows(ax, t, key, metric, order, labels, xmax=1.0, fmt_d=0, ncol=None, row_h=1.0, val_labels=True):
    """One row per group, five dots (one per question, offset vertically) with 95% CI lines, coloured by question."""
    t = t[t[metric].notna()]
    order = [k for k in order if k in set(t[key])]
    y0 = np.arange(len(order))[::-1] * row_h
    offs = np.linspace(0.32, -0.32, len(QIDS)) * row_h
    for q, off in zip(QIDS, offs):
        s = t[t.question == q].set_index(key).loc[order]
        yy = y0 + off
        hic = s[f"{metric}_hi"].clip(upper=xmax)
        ax.errorbar(s[metric], yy, xerr=_err(s[metric], s[f"{metric}_lo"], hic), fmt="o", color=Q_COLORS[q], ms=4.5,
                    elinewidth=1.1, capsize=0)
        if val_labels:
            for yi, v, h_, hr in zip(yy, s[metric], hic, s[f"{metric}_hi"]):
                ax.text(h_ + xmax * 0.012, yi, pct(v, fmt_d) + (" ▸" if hr > xmax else ""), va="center", ha="left", fontsize=6.8,
                        color=PS.INK_2)
    s0 = t[t.question == REF].set_index(key).loc[order]
    nc = ncol or ("n_injection" if metric == "TPR" else "n_benign")
    ax.set_yticks(y0, [f"{labels.get(k, k)}  (n={int(n)})" for k, n in zip(order, s0[nc])])
    for yb in y0[:-1] - row_h / 2:
        ax.axhline(yb, color=PS.GRID, lw=0.8)
    ax.set_ylim(y0[-1] - row_h * 0.55, y0[0] + row_h * 0.55)
    ax.set_xlim(0, xmax * 1.2)
    ticks = np.linspace(0, xmax, 5)
    ax.set_xticks(ticks, [pct(x, 0 if xmax >= 0.2 else 1) for x in ticks])
    ax.grid(axis="y", visible=False)


def qlegend(ax, loc="lower right", qs=QIDS, **kw):
    from matplotlib.lines import Line2D
    ax.legend(handles=[Line2D([], [], marker="o", ls="-", color=Q_COLORS[q], label=Q_NAMES[q], ms=5) for q in qs], loc=loc, **kw)


def figures(EN, NI, R):
    PS.setup()
    out = []
    ov = R["overall"].set_index("question")
    dl = R["delta"].set_index(["question", "metric"])
    SUB = f"EN {len(EN):,}건 (인젝션 500 / 정상 500) · 공식 API {MODEL} · 임계값 0.5 · 문서당 3회 호출 평균 p"

    def save(fig, name):
        top, st = fig._viz_top, fig._suptitle
        fig.tight_layout(rect=(0, 0, 1, top))
        y_with = max(a.get_position().y1 for a in fig.axes)
        st.set_in_layout(False)
        fig.tight_layout(rect=(0, 0, 1, top))
        y_without = max(a.get_position().y1 for a in fig.axes)
        st.set_in_layout(True)
        out.append(PS.save(fig, name, top=min(0.995, top + (y_without - y_with)), out_dir=FIG))

    def qticks(ax, ys, qs=QIDS, show=True):
        ax.set_yticks(ys, [Q_NAMES[q] for q in qs] if show else [""] * len(qs))
        if show:
            for lab, q in zip(ax.get_yticklabels(), qs):
                lab.set_color(Q_COLORS[q])
                lab.set_fontweight("bold")

    # ---------------- f01 headline metrics
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.8))
    specs = [("TPR", "인젝션 탐지율 TPR", (0.40, 0.80), True, np.linspace(0.4, 0.8, 5)),
             ("FPR", "정상 오탐률 FPR", (0.0, 0.05), True, np.linspace(0, 0.05, 6)),
             ("AUC", "AUC (임계값 무관)", (0.90, 1.0), False, np.linspace(0.9, 1.0, 5))]
    ys = np.arange(len(QIDS))[::-1]
    for j, (ax, (k, ttl, lim, is_pct, ticks)) in enumerate(zip(axes, specs)):
        for q, yv in zip(QIDS, ys):
            v = ov.loc[q, k]
            ax.errorbar([v], [yv], xerr=[[v - ov.loc[q, f"{k}_lo"]], [ov.loc[q, f"{k}_hi"] - v]], fmt="o", color=Q_COLORS[q], ms=8,
                        elinewidth=2, capsize=3)
            ax.text(v, yv + 0.2, pct(v, 1) if is_pct else f"{v:.3f}", ha="center", va="bottom", fontsize=9, color=PS.INK,
                    fontweight="bold")
        qticks(ax, ys, show=(j == 0))
        ax.set_ylim(-0.6, len(QIDS) - 0.25)
        ax.set_xlim(*lim)
        ax.set_xticks(ticks, [pct(t, 0) if is_pct else f"{t:.3f}" for t in ticks])
        ax.set_title(ttl, fontsize=11)
        ax.grid(axis="y", visible=False)
    tmax = ov.TPR.idxmax()
    amin = ov.AUC.idxmin()
    PS.title(fig, f"질문만 바꿔도 0.5에서 TPR이 {pct(ov.TPR.min(), 1)}~{pct(ov.TPR.max(), 1)}로 움직인다. "
                  f"TPR이 가장 높은 {tmax}는 AUC가 {'가장 낮다' if tmax == amin else '다른 질문과 비슷하다'} ({ov.loc[tmax, 'AUC']:.3f})",
             SUB + "\n선 = 95% 신뢰구간 (TPR·FPR Wilson, AUC 부트스트랩 1,000회) · Q2·QL은 01_baseline, QS·Q3·QC는 이 폴더의 호출")
    save(fig, "f01_headline_metrics")

    # ---------------- f02 Δ vs Q2 (paired)
    fig, axes = plt.subplots(1, 4, figsize=(15, 4.6))
    specs = [("TPR", "ΔTPR (%p)", True, "TPR"), ("FPR", "ΔFPR (%p)", True, "FPR"), ("AUC", "ΔAUC", False, None),
             ("accuracy", "Δ정확도 (%p)", True, "accuracy")]
    ys = np.arange(len(OTHERS))[::-1]
    for j, (ax, (k, ttl, is_pct, mck)) in enumerate(zip(axes, specs)):
        vals = []
        for q, yv in zip(OTHERS, ys):
            r = dl.loc[(q, k)]
            sc = 100 if is_pct else 1
            ax.errorbar([r.delta * sc], [yv], xerr=[[(r.delta - r.delta_lo) * sc], [(r.delta_hi - r.delta) * sc]], fmt="o",
                        color=Q_COLORS[q], ms=7, elinewidth=2, capsize=3)
            lab = f"{r.delta * sc:+.1f}" if is_pct else f"{r.delta:+.3f}"
            if mck:
                lab += f"\nMcNemar p={r.mcnemar_p:.1g}" if r.mcnemar_p < 0.001 else f"\nMcNemar p={r.mcnemar_p:.3f}"
            ax.text(r.delta * sc, yv + 0.16, lab, ha="center", va="bottom", fontsize=7.8, color=PS.INK,
                    bbox=dict(boxstyle="square,pad=0.1", fc=PS.SURFACE, ec="none"))
            vals += [r.delta_lo * sc, r.delta_hi * sc]
        ax.axvline(0, color=PS.INK_2, lw=1)
        m = max(abs(min(vals)), abs(max(vals))) * 1.25
        ax.set_xlim(-m, m)
        qticks(ax, ys, OTHERS, show=(j == 0))
        ax.set_ylim(-0.5, len(OTHERS) - 0.2)
        ax.set_title(ttl, fontsize=11)
        ax.grid(axis="y", visible=False)
    axes[0].set_xlabel("← Q2보다 적게 잡음 | 더 잡음 →", fontsize=8.5)
    axes[1].set_xlabel("← Q2보다 덜 막음 | 더 막음 →", fontsize=8.5)
    better = [q for q in OTHERS if dl.loc[(q, "accuracy"), "delta_lo"] > 0]
    worse = [q for q in OTHERS if dl.loc[(q, "accuracy"), "delta_hi"] < 0]
    PS.title(fig, f"같은 문서에서 Q2보다 정확도가 높은 질문: {', '.join(better) or '없음'}"
                  + (f" · 낮은 질문: {', '.join(worse)}" if worse else ""),
             "Δ = 질문 − Q2 (같은 문서 짝 비교) · 선 = 짝 부트스트랩 95% 구간 (라벨별 층화 1,000회, seed 20261112) · "
             "McNemar = 0.5 판정이 갈린 문서의 정확 이항검정 (보정 전)\n" + SUB)
    save(fig, "f02_delta_vs_q2")

    # ---------------- f03 ROC overlay with direct labels
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.8), gridspec_kw={"width_ratios": [1, 1.25]})
    rocs = {q: roc_curve(EN.label_int, EN[f"p_{q}"])[:2] for q in QIDS}
    for ax, lim, xl in ((axes[0], 1.0, 0.30), (axes[1], 0.10, 0.10)):
        for q in QIDS:
            f, t = rocs[q]
            ax.plot(f, t, color=Q_COLORS[q], lw=1.9, drawstyle="steps-post")
            ax.scatter([ov.loc[q, "FPR"]], [ov.loc[q, "TPR"]], s=42, color=Q_COLORS[q], edgecolor=PS.SURFACE, linewidth=1.5, zorder=5)
        ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=0.8)
        ax.set_xlim(0, lim)
        ax.set_ylim(0, 1.01)
        ax.set_xlabel("정상 오탐률 (FPR)")
        ticks = np.linspace(0, lim, 6)
        ax.set_xticks(ticks, [pct(t, 0) for t in ticks])
        ax.set_yticks(np.linspace(0, 1, 5), [pct(t) for t in np.linspace(0, 1, 5)])
    # left: the curves overlap near the top-left corner, so the labels sit in a block ordered by AUC (colour = question)
    for i, q in enumerate(ov.AUC.sort_values(ascending=False).index):
        axes[0].text(0.40, 0.42 - i * 0.07, f"{Q_NAMES[q]}  AUC {ov.loc[q, 'AUC']:.3f} [{ov.loc[q, 'AUC_lo']:.3f}, {ov.loc[q, 'AUC_hi']:.3f}]",
                     fontsize=8.8, color=Q_COLORS[q], fontweight="bold", va="center")
    axes[0].text(0.40, 0.49, "AUC 순 (괄호 = 부트스트랩 95% 구간)", fontsize=8.5, color=PS.INK_2, va="center")
    # right: labels at the right edge of the 0-10% window, outside the axes
    yr = [tpr_at(*rocs[q], 0.10) for q in QIDS]
    yrl = spread(yr, 0.042, lo=0.05, hi=1.0)
    for q, y, yt in zip(QIDS, yr, yrl):
        axes[1].annotate(f"{q} {pct(y, 1)}", (0.10, y), xytext=(0.104, yt), fontsize=9, color=Q_COLORS[q], fontweight="bold",
                         va="center", annotation_clip=False, arrowprops=dict(arrowstyle="-", color=Q_COLORS[q], lw=0.7))
    axes[1].text(0.104, 0.66, "FPR 10%에서\nTPR", fontsize=8.5, color=PS.INK_2, va="center")
    axes[1].set_xlim(0, 0.10)
    axes[0].set_ylabel("인젝션 탐지율 (TPR)")
    axes[0].set_title("전체 ROC", fontsize=11)
    axes[1].set_title("FPR 0~10% 확대 · 점 = 임계값 0.5", fontsize=11)
    order_auc = ov.AUC.sort_values(ascending=False)
    PS.title(fig, f"순서 매기기(AUC)는 {', '.join(order_auc.index[:3])}가 0.98대로 비슷하고, Q2 {ov.loc['Q2', 'AUC']:.3f}, "
                  f"Q3 {ov.loc['Q3', 'AUC']:.3f}가 뒤처진다",
             SUB + " · 같은 데이터의 ROC라 질문 고르기에 쓰면 낙관적")
    save(fig, "f03_roc_overlay")

    # ---------------- f04 p distribution (columns = question, rows = label, colour = label)
    fig, axes = plt.subplots(2, len(QIDS), figsize=(15, 6.2), sharex=True, sharey="row")
    bins = np.linspace(0, 1, 26)
    for j, q in enumerate(QIDS):
        for i, (li, lab, c) in enumerate(((0, "정상", BEN), (1, "인젝션", INJ))):
            ax = axes[i, j]
            v = EN.loc[EN.label_int == li, f"p_{q}"]
            ax.hist(v, bins=bins, color=c, edgecolor=PS.SURFACE, linewidth=0.8)
            ax.axvline(0.5, color=PS.INK_2, lw=0.9, ls="--")
            ax.text(0.97, 0.95, f"p≥0.5: {pct((v >= 0.5).mean(), 1)}\n평균 p {v.mean():.3f}", transform=ax.transAxes, ha="right",
                    va="top", fontsize=8.5, color=PS.INK)
            ax.grid(axis="x", visible=False)
            if i == 0:
                ax.set_title(Q_NAMES[q], fontsize=10.5)
            if i == 1:
                ax.set_xlabel("p (3회 평균)")
            if j == 0:
                ax.set_ylabel(f"{lab} 500건 · 문서 수")
    axes[0, 0].set_ylim(0, axes[0, 0].get_ylim()[1] * 1.15)
    axes[1, 0].set_ylim(0, axes[1, 0].get_ylim()[1] * 1.15)
    q3b = EN.loc[EN.label_int == 0, "p_Q3"]
    PS.title(fig, f"Q3는 정상 문서 p를 끌어올린다: 정상 평균 p {q3b.mean():.3f} (Q2 {ov.loc['Q2', 'mean_p_benign']:.3f}), "
                  f"0.1 이상 {pct((q3b >= 0.1).mean())}",
             SUB + " · 점선 = 임계값 0.5 · 위 = 정상(청록), 아래 = 인젝션(보라)")
    save(fig, "f04_p_distribution")

    # ---------------- f05 by source
    bs = R["by_source"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 7.6))
    dot_rows(axes[0], bs[bs.n_injection > 0], "source", "TPR", SOURCE_ORDER, SOURCE_KO)
    axes[0].set_title("인젝션 탐지율 (TPR)", fontsize=11)
    dot_rows(axes[1], bs[bs.n_benign > 0], "source", "FPR", SOURCE_ORDER, SOURCE_KO, xmax=0.4, fmt_d=1)
    axes[1].set_title("정상 오탐률 (FPR, 축 0~40%)", fontsize=11)
    qlegend(axes[0], loc="upper left", fontsize=8.5, frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    b_ = bs.set_index(["source", "question"])
    PS.title(fig, f"SEP는 Q3·QC만 일부 잡고({pct(b_.loc[('SEP', 'Q3'), 'TPR'])} / {pct(b_.loc[('SEP', 'QC'), 'TPR'])}, Q2 "
                  f"{pct(b_.loc[('SEP', 'Q2'), 'TPR'])}), BrowseSafe 정상 오탐은 Q2 {pct(b_.loc[('BrowseSafe-Bench', 'Q2'), 'FPR'], 1)} "
                  f"→ QL·QC 0%",
             SUB + "\n점 = 질문 (위에서부터 Q2, QL, QS, Q3, QC) · 선 = 95% Wilson 신뢰구간 (▸ = 축 밖까지 이어짐) · n = 그 출처의 인젝션 / 정상 문서 수")
    save(fig, "f05_by_source")

    # ---------------- f06 harmless task switches (colour = label only; questions on the axis)
    th = R["task_switch"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 5.6), gridspec_kw={"width_ratios": [1, 1, 1.5]})
    x = np.arange(len(QIDS))
    for ax, key, ttl in ((axes[0], "SEP", "SEP 인젝션 (전부 과제 이탈)"), (axes[1], "BIPIA", "BIPIA 과제 이탈 인젝션")):
        s = th[th.source == key].set_index("question").loc[list(QIDS)]
        bars = ax.bar(x, s.TPR, color=INJ, width=0.62)
        PS.bar_gap(bars)
        ax.errorbar(x, s.TPR, yerr=_err(s.TPR, s.TPR_lo, s.TPR_hi), fmt="none", ecolor=PS.INK_2, elinewidth=1, capsize=3)
        for xi, v, h_, k in zip(x, s.TPR, s.TPR_hi, s.tp):
            ax.text(xi, h_ + 0.015, f"{pct(v)}\n{int(k)}/{int(s.n_injection.iloc[0])}", ha="center", va="bottom", fontsize=8.5,
                    color=PS.INK)
        ax.set_xticks(x, list(QIDS))
        ax.set_ylim(0, 0.62)
        ax.set_yticks(np.linspace(0, 0.6, 4), [pct(v) for v in np.linspace(0, 0.6, 4)])
        ax.set_title(f"{ttl} (n={int(s.n_injection.iloc[0])})", fontsize=10.5)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("인젝션 탐지율 (TPR, 임계값 0.5)")
    ax = axes[2]
    sep = EN[EN.source == "SEP"]
    rng = np.random.default_rng(SEED)
    for j, q in enumerate(QIDS):
        for li, c, dx in ((0, BEN, -0.18), (1, INJ, 0.18)):
            v = sep.loc[sep.label_int == li, f"p_{q}"].to_numpy()
            ax.scatter(j + dx + rng.uniform(-0.1, 0.1, len(v)), v, s=11, color=c, alpha=0.75, edgecolor="none")
            ax.plot([j + dx - 0.13, j + dx + 0.13], [np.median(v)] * 2, color=PS.INK, lw=1.5)
    ax.axhline(0.5, color=PS.INK_2, lw=0.9, ls="--")
    ax.set_xticks(np.arange(len(QIDS)), list(QIDS))
    ax.set_ylim(-0.02, 1.02)
    ax.set_ylabel("p (3회 평균)")
    ax.grid(axis="x", visible=False)
    ax.set_title("SEP 문서의 p (정상 50 · 인젝션 50) · 가로선 = 중앙값", fontsize=10.5)
    ax.text(0.02, 0.97, "● 정상", color=BEN, transform=ax.transAxes, fontsize=9, va="top", fontweight="bold")
    ax.text(0.14, 0.97, "● 인젝션", color=INJ, transform=ax.transAxes, fontsize=9, va="top", fontweight="bold")
    t_ = th.set_index(["source", "question"])
    bip = th[th.source == "BIPIA"].set_index("question")
    sep_auc = R["by_source"][R["by_source"].source == "SEP"].set_index("question").AUC
    PS.title(fig, f"해롭지 않은 과제 전환: SEP는 Q3·QC가 50건 중 {int(t_.loc[('SEP', 'Q3'), 'tp'])}·{int(t_.loc[('SEP', 'QC'), 'tp'])}건을 "
                  f"잡지만(Q2 {int(t_.loc[('SEP', 'Q2'), 'tp'])}건), BIPIA 과제 이탈은 가장 높은 {bip.TPR.idxmax()}도 "
                  f"{pct(bip.TPR.max())}",
             "EN 인젝션 중 harm_type = task_hijack (SEP 50, BIPIA 55) · 막대 = TPR, 선 = 95% Wilson 신뢰구간 · 오른쪽 점 = 문서 하나 · "
             f"점선 = 임계값 0.5\nSEP 안 AUC는 다섯 질문 모두 {sep_auc.min():.3f} 이상: 정상보다 높은 p를 주지만 그 p가 0.5에 못 미친다")
    save(fig, "f06_task_switch")

    # ---------------- f07 harm type + risk level (injection only)
    ht, rl = R["by_harm_type"], R["by_risk_level"]
    fig, axes = plt.subplots(1, 2, figsize=(15, 9.2), gridspec_kw={"width_ratios": [1.35, 1]})
    harm_ko = dict(zip(EN.harm_type, EN.harm_type_ko))
    order = list(ht[ht.question == REF].sort_values("TPR", ascending=False).harm_type)
    dot_rows(axes[0], ht, "harm_type", "TPR", order, harm_ko)
    axes[0].set_title("피해 유형별 TPR (Q2 TPR 순)", fontsize=11)
    dot_rows(axes[1], rl, "risk_level", "TPR", [1, 2, 3, 4, 5], RISK_KO)
    axes[1].set_title("위험도별 TPR (data/injection_eval/risk_rubric.md)", fontsize=11)
    qlegend(axes[1], loc="upper right", fontsize=8.5, frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    h_ = ht.set_index(["harm_type", "question"])
    PS.title(fig, f"점추정으로는 Q3가 해로운 행동(무단 행동 {pct(h_.loc[('unauthorized_action', 'Q3'), 'TPR'])}, 시스템 파괴 "
                  f"{pct(h_.loc[('system_destruction', 'Q3'), 'TPR'])})에서, QL이 출력 형식 조작({pct(h_.loc[('output_manipulation', 'QL'), 'TPR'])})"
                  f"에서 가장 높다. 작은 유형은 구간이 겹친다",
             f"EN 인젝션 500건 · {MODEL} · 임계값 0.5 · 점 = 질문 (위에서부터 Q2, QL, QS, Q3, QC) · 선 = 95% Wilson 신뢰구간\n"
             "피해 유형과 위험도는 출처와 함께 움직인다 (예: 과제 이탈 = BIPIA·SEP, 무단 행동 = LLMail). 집단별 짝 비교는 tables/by_*_vs_q2.csv")
    save(fig, "f07_by_harm_and_risk")

    # ---------------- f08 every flagged benign document
    fpd = R["fps"].reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(13, 0.42 * len(fpd) + 2.2))
    yy = np.arange(len(fpd))[::-1]
    for j, q in enumerate(QIDS):
        v = fpd[f"p_{q}"].to_numpy()
        flag = v >= THRESHOLD
        ax.scatter(np.full(flag.sum(), j), yy[flag], s=260, color=Q_COLORS[q], zorder=3)
        ax.scatter(np.full((~flag).sum(), j), yy[~flag], s=260, facecolor="none", edgecolor=PS.AXIS, zorder=3)
        for yi, pv, fl in zip(yy, v, flag):
            ax.text(j, yi, f"{pv:.2f}", ha="center", va="center", fontsize=6.6, color=PS.SURFACE if fl else PS.INK_2, zorder=4,
                    fontweight="bold" if fl else "normal")
    ax.xaxis.tick_top()
    ax.set_xticks(np.arange(len(QIDS)), [Q_NAMES[q] for q in QIDS], fontsize=9)
    for lab, q in zip(ax.get_xticklabels(), QIDS):
        lab.set_color(Q_COLORS[q])
        lab.set_fontweight("bold")
    ax.set_yticks(yy, [f"{r.uid} · {SOURCE_KO.get(r.source, r.source) if r.set == 'EN' else 'NotInject'} · {short(r.snippet, 46)}"
                       for r in fpd.itertuples()], fontsize=7.6)
    ax.set_xlim(-0.6, len(QIDS) - 0.4)
    ax.set_ylim(-0.7, len(fpd) - 0.3)
    ax.grid(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_visible(False)
    ax.tick_params(length=0)
    nfp = {q: int(ov.loc[q, "fp"]) for q in QIDS}
    n_bs = int((fpd.source == "BrowseSafe-Bench").sum())
    PS.title(fig, f"오탐된 정상 문서 {len(fpd)}건 중 {n_bs}건이 BrowseSafe 웹페이지. 오탐 수 "
                  + " · ".join(f"{q} {nfp[q]}" for q in QIDS),
             "EN 정상 500건 + NotInject 25건 중 다섯 질문 가운데 하나라도 p ≥ 0.5를 준 문서 · 칸 안 숫자 = p (3회 평균) · 색칠 = 오탐 (p ≥ 0.5)")
    save(fig, "f08_false_positives")

    # ---------------- f09 agreement matrices (text only; colour reserved for questions)
    mats = R["agree_mats"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.9))
    for ax, (key, ttl) in zip(axes, (("all", "전체 1,000건"), ("injection", "인젝션 500건"), ("benign", "정상 500건"))):
        m = mats[key].loc[list(QIDS), list(QIDS)]
        n = len(QIDS)
        for i in range(n):
            for j in range(n):
                if i == j:
                    ax.text(j, i, "–", ha="center", va="center", color=PS.MUTED, fontsize=10)
                    continue
                v = m.iloc[i, j]
                low = v == min(m.values[np.triu_indices(n, 1)])
                ax.text(j, i, pct(v, 1), ha="center", va="center", fontsize=9.5, color=PS.INK,
                        fontweight="bold" if low else "normal")
        ax.set_xlim(-0.5, n - 0.5)
        ax.set_ylim(n - 0.5, -0.5)
        ax.set_xticks(range(n), list(QIDS))
        ax.set_yticks(range(n), list(QIDS))
        for labs in (ax.get_xticklabels(), ax.get_yticklabels()):
            for lab, q in zip(labs, QIDS):
                lab.set_color(Q_COLORS[q])
                lab.set_fontweight("bold")
        ax.set_xticks(np.arange(-0.5, n), minor=True)
        ax.set_yticks(np.arange(-0.5, n), minor=True)
        ax.grid(False)
        ax.grid(which="minor", color=PS.GRID, lw=0.8)
        ax.tick_params(which="both", length=0)
        ax.set_title(ttl, fontsize=11)
    ap = R["agree_pairs"]
    lo_ = ap.sort_values("agree_injection").iloc[0]
    PS.title(fig, f"정상 문서는 다섯 질문이 거의 같게 판정하고, 갈림은 인젝션에서 난다 "
                  f"(가장 다른 쌍 {lo_.a}–{lo_.b}: 인젝션 {int(lo_.n_disagree_injection)}건이 갈림)",
             "칸 = 두 질문의 0.5 판정이 같은 문서 비율 · 굵게 = 그 표에서 가장 낮은 값 · Cohen κ와 p의 순위상관은 tables/agreement_pairs.csv")
    save(fig, "f09_agreement")

    # ---------------- f10 catch overlap
    # colour = question only in the middle panel; the left panel and the three source facets are neutral gray
    # (the catch category is on the axis / facet title, not on colour)
    cs = R["catch"].set_index("source")
    osum = R["only_sum"].set_index("question")
    fig, axes = plt.subplots(1, 3, figsize=(16.5, 5.6), gridspec_kw={"width_ratios": [1.0, 1.0, 1.75]})
    ax = axes[0]
    k = np.arange(len(QIDS) + 1)
    v = [int(cs.loc["전체", f"caught_by_{i}"]) for i in k]
    bars = ax.bar(k, v, color=PS.MUTED, width=0.7)
    PS.bar_gap(bars)
    for xi, vi in zip(k, v):
        ax.text(xi, vi + 4, f"{vi}\n({pct(vi / 500)})", ha="center", va="bottom", fontsize=8.5, color=PS.INK)
    ax.set_xticks(k, [str(i) for i in k])
    ax.set_xlabel("인젝션을 잡은 질문 수 (0~5)")
    ax.set_ylabel("인젝션 문서 수")
    ax.set_ylim(0, max(v) * 1.22)
    ax.set_title("인젝션 500건: 몇 개 질문이 잡았나", fontsize=10.5)
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    x = np.arange(len(QIDS))
    w = 0.38
    b1 = ax.bar(x - w / 2, osum.loc[list(QIDS), "injection_caught_only_by_this"], width=w, color=[Q_COLORS[q] for q in QIDS])
    b2 = ax.bar(x + w / 2, osum.loc[list(QIDS), "injection_missed_only_by_this"], width=w, color=[Q_COLORS[q] for q in QIDS],
                hatch="////", alpha=0.45)
    PS.bar_gap(b1)
    for xi, q in zip(x, QIDS):
        ax.text(xi - w / 2, osum.loc[q, "injection_caught_only_by_this"] + 0.3, str(int(osum.loc[q, "injection_caught_only_by_this"])),
                ha="center", va="bottom", fontsize=8.5)
        ax.text(xi + w / 2, osum.loc[q, "injection_missed_only_by_this"] + 0.3, str(int(osum.loc[q, "injection_missed_only_by_this"])),
                ha="center", va="bottom", fontsize=8.5, color=PS.INK_2)
    ax.set_xticks(x, list(QIDS))
    for lab, q in zip(ax.get_xticklabels(), QIDS):
        lab.set_color(Q_COLORS[q])
        lab.set_fontweight("bold")
    ax.set_ylim(0, max(osum.injection_caught_only_by_this.max(), osum.injection_missed_only_by_this.max()) * 1.25 + 1)
    ax.set_ylabel("인젝션 문서 수")
    ax.set_title("혼자만 잡은 (채움) / 혼자만 놓친 (빗금) 인젝션", fontsize=10.5)
    ax.grid(axis="x", visible=False)
    # three facets (catch category) drawn side by side in one axes, each with its own 0-100% scale
    ax = axes[2]
    srcs = [s for s in SOURCE_ORDER if s in cs.index]
    yy = np.arange(len(srcs))[::-1]
    step = 1.45
    xt, xl = [], []
    for j, (key, ttl) in enumerate((("all5", "5개 모두 잡음"), ("some_1to4", "1~4개만 잡음"), ("none", "아무도 못 잡음"))):
        x0 = j * step
        sh = cs.loc[srcs, f"share_caught_by_{key}"].to_numpy()
        lo_, hi_ = cs.loc[srcs, f"share_caught_by_{key}_lo"].to_numpy(), cs.loc[srcs, f"share_caught_by_{key}_hi"].to_numpy()
        bb = ax.barh(yy, sh, left=x0, color=PS.AXIS, height=0.6)
        PS.bar_gap(bb)
        ax.errorbar(x0 + sh, yy, xerr=_err(sh, lo_, hi_), fmt="none", ecolor=PS.INK_2, elinewidth=1, capsize=2)
        for yi, v_, h_ in zip(yy, sh, hi_):
            ax.text(x0 + h_ + 0.03, yi, pct(v_), ha="left", va="center", fontsize=8, color=PS.INK)
        ax.axvline(x0, color=PS.AXIS, lw=0.8)
        ax.text(x0, yy[0] + 0.62, ttl, ha="left", va="bottom", fontsize=10, fontweight="bold", color=PS.INK)
        xt += [x0, x0 + 0.5, x0 + 1.0]
        xl += ["0%", "50%", "100%"]
    ax.set_xticks(xt, xl, fontsize=7.5)
    ax.set_xlim(-0.03, 2 * step + 1.3)
    ax.set_ylim(yy[-1] - 0.6, yy[0] + 1.15)
    ax.set_yticks(yy, [f"{s} (n={int(cs.loc[s, 'n_injection'])})" for s in srcs], fontsize=8.5)
    ax.tick_params(axis="y", length=0)
    ax.spines["left"].set_visible(False)
    ax.grid(False)
    ax.set_xlabel("출처별 인젝션 중 비율 (선 = 95% Wilson 신뢰구간)", fontsize=8.5)
    ax.set_title("출처별: 다섯 질문 중 몇 개가 잡았나", fontsize=10.5)
    PS.title(fig, f"인젝션 {int(cs.loc['전체', 'caught_by_0'])}건({pct(cs.loc['전체', 'share_caught_by_none'])})은 다섯 질문 모두 놓치고, "
                  f"{int(500 - cs.loc['전체', 'caught_by_0'] - cs.loc['전체', 'caught_by_5'])}건은 질문에 따라 갈린다",
             SUB + "\n혼자만 잡음 = 그 질문만 p ≥ 0.5, 나머지 4개는 모두 놓침 · 색 = 질문 (가운데 그림만), 나머지 막대는 회색")
    save(fig, "f10_catch_overlap")

    # ---------------- f11 TPR at fixed FPR (thresholds fitted per question on the same data)
    thr = R["thresholds"]
    fig, axes = plt.subplots(1, 4, figsize=(16, 4.6), sharey=True)
    ys = np.arange(len(QIDS))[::-1]
    for ax, tgt in zip(axes, ["기준 0.5", "오탐 1% 이하", "오탐 5% 이하", "오탐 10% 이하"]):
        s = thr[thr.target == tgt].set_index("question").loc[list(QIDS)]
        lo = s.TPR_lo if tgt == "기준 0.5" else s.TPR_boot_lo
        hi = s.TPR_hi if tgt == "기준 0.5" else s.TPR_boot_hi
        for q, yv in zip(QIDS, ys):
            ax.errorbar([s.loc[q, "TPR"]], [yv], xerr=[[s.loc[q, "TPR"] - lo[q]], [hi[q] - s.loc[q, "TPR"]]], fmt="o",
                        color=Q_COLORS[q], ms=7, elinewidth=2, capsize=3)
            ax.text(s.loc[q, "TPR"], yv + 0.2, f"{pct(s.loc[q, 'TPR'], 1)} (t={s.loc[q, 'threshold']:.3f})", ha="center",
                    va="bottom", fontsize=8, color=PS.INK)
        ax.set_xlim(0.3, 1.0)
        ax.set_xticks(np.linspace(0.3, 1.0, 8), [pct(t) for t in np.linspace(0.3, 1.0, 8)], fontsize=8)
        ax.set_title(tgt if tgt == "기준 0.5" else f"{tgt} (임계값을 질문마다 맞춤)", fontsize=10)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("TPR")
    qticks(axes[0], ys)
    axes[0].set_ylim(-0.6, len(QIDS) - 0.2)
    t5 = thr[thr.target == "오탐 5% 이하"].set_index("question")
    PS.title(fig, f"오탐을 같게 맞추면 순서가 바뀐다: 오탐 5%에서 {t5.TPR.idxmax()} {pct(t5.TPR.max(), 1)}, "
                  f"{t5.TPR.idxmin()} {pct(t5.TPR.min(), 1)}",
             SUB + "\n선 = 95% 구간 (0.5는 Wilson, 나머지는 임계값까지 다시 맞춘 부트스트랩) · 임계값은 같은 데이터에서 맞춘 값이라 낙관적")
    save(fig, "f11_tpr_at_fixed_fpr")

    # ---------------- f12 selection optimism (split half)
    so, draws = R["selopt"].set_index("criterion"), R["seldraws"]
    fig, axes = plt.subplots(1, 3, figsize=(15, 4.8), gridspec_kw={"width_ratios": [1, 1, 1.1]})
    for ax, crit, ttl in ((axes[0], "AUC", "AUC로 고를 때"), (axes[1], "accuracy", "0.5 정확도로 고를 때")):
        sh = [so.loc[crit, f"selected_share_{q}"] for q in QIDS]
        bars = ax.bar(np.arange(len(QIDS)), sh, color=[Q_COLORS[q] for q in QIDS], width=0.65)
        PS.bar_gap(bars)
        for xi, v in enumerate(sh):
            ax.text(xi, v + 0.015, pct(v), ha="center", va="bottom", fontsize=8.5)
        ax.set_xticks(np.arange(len(QIDS)), list(QIDS))
        for lab, q in zip(ax.get_xticklabels(), QIDS):
            lab.set_color(Q_COLORS[q])
            lab.set_fontweight("bold")
        ax.set_ylim(0, 1.1)
        ax.set_yticks(np.linspace(0, 1, 5), [pct(t) for t in np.linspace(0, 1, 5)])
        ax.set_title(f"{ttl}: 앞 절반에서 1등이 된 비율", fontsize=10.5)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("1,000번 나누기 중 비율")
    ax = axes[2]
    rng = np.random.default_rng(SEED)
    for i, crit in enumerate(CRITS):
        v = draws.loc[draws.criterion == crit, "optimism"].to_numpy() * 100      # both in points (AUC x 100, accuracy %p)
        ax.scatter(v, i + rng.uniform(-0.18, 0.18, len(v)), s=5, color=PS.MUTED, alpha=0.35, edgecolor="none")
        lo, hi = so.loc[crit, "optimism_lo"] * 100, so.loc[crit, "optimism_hi"] * 100
        m = so.loc[crit, "optimism_mean"] * 100
        ax.plot([lo, hi], [i, i], color=PS.INK, lw=2)
        ax.plot([m], [i], "o", color=PS.INK, ms=7)
        ax.text(m, i + 0.3, f"평균 {m:+.2f} · 95% [{lo:+.2f}, {hi:+.2f}]", ha="center", va="bottom", fontsize=8.5, color=PS.INK)
    ax.axvline(0, color=PS.INK_2, lw=0.9)
    ax.set_yticks([0, 1], ["AUC 기준\n(AUC × 100)", "정확도 기준\n(%p)"])
    ax.set_ylim(-0.5, 1.75)
    ax.set_xlabel("앞 절반 1등 값 − 같은 질문의 뒤 절반 값 (점 = 나누기 1번)")
    ax.set_title("고르기 낙관의 크기", fontsize=10.5)
    ax.grid(axis="y", visible=False)
    win_auc = [q for q in QIDS if so.loc["AUC", f"selected_share_{q}"] > 0.05]
    PS.title(fig, f"AUC 1등({'·'.join(win_auc)})은 나눌 때마다 바뀌어, 다른 절반에서도 1등인 경우가 "
                  f"{pct(so.loc['AUC', 'selected_is_best_on_B_share'])}뿐이다. 정확도 1등 {so.loc['accuracy', 'full_data_winner']}는 "
                  f"{pct(so.loc['accuracy', 'selected_is_best_on_B_share'])}",
             "EN을 출처×라벨로 층화해 반으로 1,000번 나눔 (seed 20261112) · 앞 절반에서 다섯 질문 중 1등을 고르고 뒤 절반에서 다시 잼 · "
             "절반(약 500건)끼리라 1,000건 전체의 흔들림은 이보다 작다")
    save(fig, "f12_selection_optimism")

    # ---------------- f13 stability, tokens, latency
    st, lt = R["stability"].set_index("question"), R["latency"].set_index("question")
    fig, axes = plt.subplots(1, 4, figsize=(17, 4.9), gridspec_kw={"width_ratios": [1, 1, 0.9, 0.9]})
    xq = np.arange(len(QIDS))
    # flip rates with 95% Wilson intervals: all EN docs, and only docs near the threshold (p in [0.4, 0.6))
    for ax, (key, lo_k, hi_k, ttl, n_of) in zip(axes[:2], (
            ("flip_rate", "flip_rate_lo", "flip_rate_hi", "회차마다 0.5 판정이 갈린 문서 (EN 1,000건 중)", None),
            ("flip_rate_in_band", "flip_rate_in_band_lo", "flip_rate_in_band_hi", "그중 0.5 근처 (p 0.4~0.6) 문서 안의 비율",
             "n_band_0.4_0.6"))):
        s = st.loc[list(QIDS)]
        bars = ax.bar(xq, s[key], color=[Q_COLORS[q] for q in QIDS], width=0.62)
        PS.bar_gap(bars)
        ax.errorbar(xq, s[key], yerr=_err(s[key], s[lo_k], s[hi_k]), fmt="none", ecolor=PS.INK_2, elinewidth=1, capsize=3)
        top_ = s[hi_k].max() * 1.3
        for xi, q in enumerate(QIDS):
            num = int(s.loc[q, "flips_in_band_0.4_0.6" if n_of else "docs_with_flip"])
            den = int(s.loc[q, n_of]) if n_of else len(EN)
            ax.text(xi, s.loc[q, hi_k] + top_ * 0.015, f"{pct(s.loc[q, key], 1)}\n{num}/{den}", ha="center",
                    va="bottom", fontsize=8, color=PS.INK)
        ax.set_ylim(0, top_)
        tk = np.linspace(0, 0.5 if n_of else 0.04, 6 if n_of else 5)
        ax.set_yticks(tk[tk <= top_], [pct(t, 0) for t in tk[tk <= top_]])
        ax.set_title(ttl, fontsize=10.5)
    specs = [(lt["input_tokens_per_call_EN"], "요청 1건 입력 토큰 (EN 평균)", "{:.0f}"),
             (lt["latency_ms_median"], "응답 시간 중앙값 (ms)", "{:.0f}ms")]
    for ax, (s, ttl, fmt) in zip(axes[2:], specs):
        v = s.loc[list(QIDS)].to_numpy()
        bars = ax.bar(xq, v, color=[Q_COLORS[q] for q in QIDS], width=0.62)
        PS.bar_gap(bars)
        for xi, vi in enumerate(v):
            ax.text(xi, vi * 1.02, fmt.format(vi), ha="center", va="bottom", fontsize=8.5)
        ax.set_ylim(0, v.max() * 1.2)
        ax.set_title(ttl, fontsize=10.5)
    for ax in axes:
        ax.set_xticks(xq, list(QIDS))
        ax.grid(axis="x", visible=False)
    axes[3].set_xticklabels([f"{q}\n{lt.loc[q, 'first_call_utc'][11:16]}" for q in QIDS])
    for ax in axes:
        for lab, q in zip(ax.get_xticklabels(), QIDS):
            lab.set_color(Q_COLORS[q])
            lab.set_fontweight("bold")
    fb = st.loc[list(QIDS)]
    fp_ = R["flip_pairwise"]
    assert (fb["flips_in_band_0.4_0.6"] == fb["docs_with_flip"]).all(), "a flip outside p 0.4-0.6: fix the f13 subtitle"
    head = (f"판정이 갈린 문서는 {int(fb.docs_with_flip.min())}~{int(fb.docs_with_flip.max())}건이고 "
            + ("같은 문서 짝 비교로 질문 사이 차이가 없다 (오차 범위)" if (fp_.mcnemar_p_holm10 >= 0.05).all()
               else "일부 질문 쌍은 갈림 수가 다르다")
            + f". 0.5 근처 문서 안에서 갈리는 비율은 {pct(fb.flip_rate_in_band.min())}~{pct(fb.flip_rate_in_band.max())}")
    PS.title(fig, head,
             "질문마다 3,075회 호출 (EN 1,000 + NotInject 25, × 3, 동시 6개) · 선 = 95% Wilson 신뢰구간 · 갈린 문서는 모두 p 0.4~0.6 안에 있음 · "
             f"갈림 여부의 짝 McNemar 10쌍: 보정 전 p ≥ {fp_.mcnemar_p.min():.2f}, Holm 보정 후 p ≥ {fp_.mcnemar_p_holm10.min():.2f} "
             "(tables/flip_pairwise.csv)\n"
             "응답 시간 그림의 질문 아래 시각 = 첫 호출 (UTC). 질문마다 다른 시간대에 실행해 응답 시간 차이에는 서버 상태가 섞여 있음")
    save(fig, "f13_stability_cost")

    # ---------------- f14 each question vs Q2, same documents (colour = label)
    fig, axes = plt.subplots(1, len(OTHERS), figsize=(16, 4.9), sharex=True, sharey=True)
    for ax, q in zip(axes, OTHERS):
        for li, c, lab in ((0, BEN, "정상"), (1, INJ, "인젝션")):
            s = EN[EN.label_int == li]
            ax.scatter(s[f"p_{REF}"], s[f"p_{q}"], s=8, color=c, alpha=0.5, edgecolor="none", label=lab)
        ax.axvline(0.5, color=PS.INK_2, lw=0.8, ls="--")
        ax.axhline(0.5, color=PS.INK_2, lw=0.8, ls="--")
        ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=0.8)
        r = dl.loc[(q, "TPR")]
        rf = dl.loc[(q, "FPR")]
        ax.text(0.03, 0.97, f"인젝션: {q}만 잡음 {int(r.only_question)} · Q2만 {int(r.only_Q2)}\n정상: {q}만 오탐 {int(rf.only_question)} · "
                            f"Q2만 {int(rf.only_Q2)}", transform=ax.transAxes, va="top", fontsize=8,
                bbox=dict(boxstyle="round,pad=0.3", fc=PS.SURFACE, ec=PS.GRID, lw=0.8))
        ax.set_xlabel("Q2 p")
        ax.set_title(f"{Q_NAMES[q]} p", fontsize=10.5)
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
    axes[0].set_ylabel("질문 p (3회 평균)")
    axes[-1].legend(loc="lower right", fontsize=8.5, markerscale=2, frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    down = [q for q in OTHERS if dl.loc[(q, "mean_p_benign"), "delta_hi"] < 0]
    up = [q for q in OTHERS if dl.loc[(q, "mean_p_benign"), "delta_lo"] > 0]
    PS.title(fig, f"같은 문서를 Q2와 나란히: 정상 문서 평균 p가 {'·'.join(down)}에서는 내려가고 "
                  + "·".join(f"{q}에서는 오른다 ({ov.loc['Q2', 'mean_p_benign']:.3f} → {ov.loc[q, 'mean_p_benign']:.3f})" for q in up),
             SUB + " · 점선 = 임계값 0.5 · 대각선 위 = Q2보다 높은 p")
    save(fig, "f14_vs_q2_scatter")
    return out


# ------------------------------------------------------------------ main
def main():
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    EN, NI, raws, raw_all = load()
    boot = paired_bootstrap(EN)
    overall, thresholds, delta, pairs, notinject, point = overall_tables(EN, NI, boot, raws)
    agree_pairs, agree_mats = agreement(EN)
    catch, only_sum, only_docs, combos, combos_vs, fps, none = overlap(EN, NI)
    per_run, stab, noise, flip_pairs = stability(EN)
    lat = latency_tokens(EN, raws, raw_all)
    sw = sweep(EN)
    selopt, seldraws = selection_optimism(EN)

    inj = EN[EN.label_int == 1]
    groups = {
        "by_source": (EN, "source", SOURCE_ORDER, SOURCE_KO),
        "by_harm_type": (inj, "harm_type", list(inj.harm_type.value_counts().index), dict(zip(EN.harm_type, EN.harm_type_ko))),
        "by_risk_level": (inj, "risk_level", [1, 2, 3, 4, 5], RISK_KO),
        "by_doc_type": (EN, "doc_type", list(EN.doc_type.value_counts().index), dict(zip(EN.doc_type, EN.doc_type_ko))),
    }
    R = {"overall": overall, "thresholds": thresholds, "delta": delta, "pairs": pairs, "notinject": notinject,
         "agree_pairs": agree_pairs, "agree_mats": agree_mats, "catch": catch, "only_sum": only_sum, "combos": combos,
         "fps": fps, "stability": stab, "flip_pairwise": flip_pairs, "latency": lat, "selopt": selopt, "seldraws": seldraws}
    vs = {}
    for name, (df, col, keys, lab) in groups.items():
        R[name] = save_table(by_group(df, col, keys, lab), name)
        vs[name] = save_table(group_vs_q2(df, col, keys, lab), f"{name}_vs_q2")
    th_inj = inj[inj.harm_type == "task_hijack"]
    R["task_switch"] = save_table(by_group(th_inj, "source", [s for s in SOURCE_ORDER if s in set(th_inj.source)]), "task_switch_by_source")
    vs["task_switch"] = save_table(group_vs_q2(th_inj, "source", [s for s in SOURCE_ORDER if s in set(th_inj.source)]),
                                   "task_switch_by_source_vs_q2")
    # how far above 0.5 the caught task-switch injections are (a rescue just above 0.5 is fragile)
    mrows = []
    for s in ("SEP", "BIPIA"):
        g = th_inj[th_inj.source == s]
        for q in QIDS:
            c = g[g[f"pred_{q}"] == 1]
            mrows.append({"source": s, "question": q, "n": len(g), "caught": len(c), "caught_p_below_0.55": int((c[f"p_{q}"] < 0.55).sum()),
                          "caught_with_flip": int(c[f"flip_{q}"].sum()), "caught_median_p": float(c[f"p_{q}"].median()) if len(c) else None,
                          "missed_p_0.4_to_0.5": int(((g[f"p_{q}"] >= 0.4) & (g[f"p_{q}"] < 0.5)).sum()),
                          "median_p_all": float(g[f"p_{q}"].median())})
    R["task_margin"] = save_table(pd.DataFrame(mrows), "task_switch_margin")
    # one row per document with all five scores (the per-sample record for this comparison)
    wide = EN[["uid", "id", "set", "label", "label_int", "source", "doc_type", "harm_type", "risk_level", "char_len"]].copy()
    wide = pd.concat([wide, NI[wide.columns]], ignore_index=True)
    allw = pd.concat([EN, NI], ignore_index=True)
    for q in QIDS:
        wide[f"p_{q}"] = allw[f"p_{q}"]
        wide[f"pred_{q}"] = allw[f"pred_{q}"]
    wide["n_questions_flagging"] = allw["n_flag"]
    save_table(wide, "predictions_5q_wide")

    figs = figures(EN, NI, R)

    # ---------------- summary.json "analysis" (all other keys are kept as they are)
    sp = os.path.join(OUT, "summary.json")
    with open(sp, encoding="utf-8") as f:
        summary = json.load(f)
    ovq = overall.set_index("question")
    keep = ["n", "n_injection", "n_benign", "tp", "fn", "fp", "tn", "TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi", "AUC", "AUC_lo",
            "AUC_hi", "mean_p_injection", "mean_p_injection_lo", "mean_p_injection_hi", "mean_p_benign", "mean_p_benign_lo",
            "mean_p_benign_hi", "accuracy", "accuracy_lo", "accuracy_hi", "brier", "threshold_FPR1", "TPR_at_FPR1", "threshold_FPR5",
            "TPR_at_FPR5", "threshold_FPR10", "TPR_at_FPR10", "notinject_fp", "notinject_FPR_hi", "notinject_mean_p",
            "input_tokens_per_call_EN", "extra_tokens_vs_Q2", "latency_ms_median", "docs_with_flip"]

    def vs_compact(t):
        return [{k: r[k] for k in t.columns if k in (t.columns[0], "metric", "question", "n", "Q2", "value", "delta", "delta_lo", "delta_hi",
                                                     "only_Q2", "only_question", "mcnemar_p", "mcnemar_p_holm", "verdict")}
                for _, r in t.iterrows()]

    analysis = {
        "script": "experiments/analyze_01_baseline_definitions.py",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis_commit": J.git_commit(),
        "run_code": run_code_history(summary.get("commit")),
        "main_set": "set == EN (1000: 500 injection / 500 benign); NotInject 25 = over-defence reference (FPR only)",
        "questions_compared": {q: {"name": Q_NAMES[q], "predictions": f"results/{Q_EXP[q]}/{q}_predictions.csv",
                                   "text": J.QUESTIONS[q]} for q in QIDS},
        "reference_question": REF,
        "data": {"en_file": "data/injection_eval/en/dataset_en_1000.jsonl", "en_md5": md5_file(EN_DATA),
                 "notinject_file": "data/injection_eval/en/overdefense_ref_notinject.jsonl", "notinject_md5": md5_file(NI_DATA),
                 "text_md5_check": "every raw call's text_md5 equals md5(dataset text) for its uid, all five questions (asserted)",
                 "predictions_check": "p_run0..2 equal the raw calls and p is their mean (asserted); question texts in both summary.json "
                                      "files equal jevlab.QUESTIONS (asserted)"},
        "methods": {"metrics": "src.jev_guard.metrics(threshold=0.5)", "proportion_ci": "Wilson 95% (jevlab.wilson)",
                    "paired_test": "exact McNemar (two-sided binomial on discordant pairs); Holm over the 4 comparisons vs Q2 per metric "
                                   "(mcnemar_p_holm4) and over the 10 pairs (pairwise table)",
                    "paired_bootstrap": {"resamples": B, "seed": SEED,
                                         "scheme": "stratified by label, the same indices for all five questions, percentile 95%"},
                    "group_tables": "within group and label, paired bootstrap 1000 (seed 20261112) + exact McNemar, Holm within table "
                                    "per metric; direction only if CI excludes 0 and Holm p < 0.05",
                    "thresholds_at_fpr": "fitted on the same EN data per question (optimistic); report only",
                    "selection_optimism": f"{N_SPLITS} random halves stratified by source x label (seed {SEED}); pick the best question on "
                                          "half A by AUC or accuracy at 0.5, score it on half B",
                    "run_times": "Q2/QL run 06:15-07:01 UTC (01_baseline), QS/Q3/QC 07:08-07:51 UTC; latency mixes question and server state"},
        "overall": {q: {k: ovq.loc[q, k] for k in keep} for q in QIDS},
        "delta_vs_Q2": {q: {r.metric: {"value": r.value, "Q2": r.Q2, "delta": r.delta, "delta_ci95": [r.delta_lo, r.delta_hi],
                                       "verdict": r.verdict,
                                       **({"only_Q2": int(r.only_Q2), "only_question": int(r.only_question), "mcnemar_p": r.mcnemar_p,
                                           "mcnemar_p_holm4": r.mcnemar_p_holm4} if r.mcnemar_p == r.mcnemar_p else {})}
                            for r in delta[delta.question == q].itertuples()} for q in OTHERS},
        "pairwise": pairs.to_dict("records"),
        "notinject": notinject.set_index("question").to_dict("index"),
        "by_source_vs_Q2": vs_compact(vs["by_source"]),
        "task_switch_vs_Q2": vs_compact(vs["task_switch"]),
        "task_switch_margin": R["task_margin"].to_dict("records"),
        "by_harm_type_vs_Q2": vs_compact(vs["by_harm_type"]),
        "by_risk_level_vs_Q2": vs_compact(vs["by_risk_level"]),
        "agreement": agree_pairs.to_dict("records"),
        "catch_count": catch.to_dict("records"),
        "only_one_question": only_sum.set_index("question").to_dict("index"),
        "combination_rules": combos.to_dict("records"),
        "combination_vs_QL": combos_vs.to_dict("records"),
        "false_positive_docs_any_question": fps[["uid", "source", "flagged_by"]].to_dict("records"),
        "stability": stab.set_index("question").to_dict("index"),
        "flip_pairwise": flip_pairs.to_dict("records"),
        "per_run": {q: per_run[per_run.question == q][["run", "TPR", "FPR", "AUC"]].to_dict("records") for q in QIDS},
        "noise_floor_discordance": noise.to_dict("records"),
        "thresholds_at_fpr": {q: thresholds[thresholds.question == q].set_index("target")[["threshold", "TPR", "FPR", "TPR_boot_lo",
                                                                                           "TPR_boot_hi"]].to_dict("index") for q in QIDS},
        "latency_tokens_cost": {**lat.set_index("question").to_dict("index"),
                                "price_note": "input $0.042 per 1M tokens; output price not published (tokens counted only)"},
        "selection_optimism": selopt.set_index("criterion").to_dict("index"),
        "tables": sorted(os.listdir(TAB)),
        "figures": sorted(os.path.basename(p) for p in figs),
    }
    summary["analysis"] = clean(analysis)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    # ---------------- console digest (README numbers come from here and the tables)
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    for q in QIDS:
        o = ovq.loc[q]
        print(f"{q}: TPR {o.TPR:.3f} [{o.TPR_lo:.3f},{o.TPR_hi:.3f}] FPR {o.FPR:.3f} [{o.FPR_lo:.3f},{o.FPR_hi:.3f}] "
              f"AUC {o.AUC:.3f} [{o.AUC_lo:.3f},{o.AUC_hi:.3f}] acc {o.accuracy:.3f} mean p inj {o.mean_p_injection:.3f} "
              f"ben {o.mean_p_benign:.3f} NI fp {int(o.notinject_fp)} tok {o.input_tokens_per_call_EN:.0f} lat {o.latency_ms_median:.0f}")
    print(delta[["question", "metric", "Q2", "value", "delta", "delta_lo", "delta_hi", "verdict", "only_Q2", "only_question",
                 "mcnemar_p", "mcnemar_p_holm4"]].to_string())
    print(combos_vs[["rule", "reference", "metric", "rule_value", "QL_value", "delta", "delta_lo", "delta_hi", "delta_lo_refit",
                     "delta_hi_refit", "only_rule", "only_QL", "mcnemar_p", "verdict"]].to_string())
    print(stab[["question", "docs_with_flip", "flip_rate_lo", "flip_rate_hi", "n_band_0.4_0.6", "flip_rate_in_band",
                "flip_rate_in_band_lo", "flip_rate_in_band_hi", "p_sd_mean_mid_0.2_0.8", "share_identical_3_runs",
                "share_identical_3_runs_mid_0.2_0.8"]].to_string())
    print(flip_pairs.to_string())
    print(json.dumps(analysis["run_code"], ensure_ascii=False))
    print(f"wrote {len(os.listdir(TAB))} tables, {len(figs)} figures, summary.json['analysis']")


if __name__ == "__main__":
    main()
