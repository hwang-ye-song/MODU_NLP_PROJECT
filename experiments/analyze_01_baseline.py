"""① 기준선(01_baseline) 분석: Q2·QL 예측표 -> 표, 그림, summary.json의 "analysis" 키. API를 부르지 않는다.

    python experiments/analyze_01_baseline.py

입력 (읽기만 함)
  results/01_baseline/{Q2,QL}_predictions.csv   문서별 3회 평균 p (experiments/run_api.py 01_baseline 이 만든 것)
  results/01_baseline/raw/{Q2,QL}_raw.jsonl     호출별 응답 시간·토큰 수, 본문 md5 확인용
  data/injection_eval/en/dataset_en_1000.jsonl  injected_instruction, origin.position, 본문 (uid로 연결, 본문 md5 확인)
  data/injection_eval/en/overdefense_ref_notinject.jsonl
출력
  results/01_baseline/tables/*.csv, results/01_baseline/figures/*.png,
  results/01_baseline/summary.json 의 "analysis" 키 (다른 키는 건드리지 않음)

규칙
  - 지표는 src.jev_guard.metrics() (임계값 0.5). 비율의 95% 신뢰구간은 Wilson (jevlab.wilson).
  - Q2 vs QL은 같은 문서끼리 짝지어 비교한다.
      0.5 판정의 차이: McNemar 정확검정 (불일치 쌍에 대한 양측 이항검정)
      TPR·FPR·AUC·평균 p의 차이: 짝 부트스트랩 (라벨별 층화 재표집 1,000회, seed 20261112, 백분위 구간)
    구간이 0을 포함하면 "차이 없음 (오차 범위)"로 적는다.
  - 집단별 표(by_*_paired.csv)의 판정: 부트스트랩 구간이 0을 빼고 그 표 안에서 Holm 보정한 McNemar p < 0.05일 때만
    "QL 높음/낮음". 구간만 0을 빼면 "탐색적 (Holm p = …)". 그 집단의 문서가 30건 미만이면 "표본 작음"을 붙인다.
    (불일치 쌍이 몇 개 안 되고 한쪽으로만 몰리면 백분위 부트스트랩 구간은 0을 덮지 못한다.)
  - p 격자: p는 소수 둘째 자리 값 3개의 평균이라 정확히 1/300의 배수다. 저장된 p에는 2e-16 정도의 부동소수점 오차가
    있어 같은 점수의 문서가 비교에서 갈릴 수 있으므로, 읽자마자 1/300 격자로 맞춘 뒤(round(300p)/300) 모든 비교를 한다.
  - 오탐 1/5/10% 임계값: p ≥ t 규칙에서 정상 오탐이 목표 이하가 되는 가장 낮은 격자값을 찾고, 적는 값은 그 격자값과
    바로 아래 격자값(통과시켜야 하는 정상 문서 중 가장 높은 p)의 중간이다 (예: 0.555). 소수 셋째 자리로 반올림해 적어도
    같은 결과가 나온다.
  - 주 지표는 set == "EN" 1,000건. NotInject 25건은 과탐지 참고용(FPR만).
  - 길이 구간은 결과를 보기 전에 글자 수로 고정: ≤621 / >621, 사분위 ≤333 / 334–623 / 624–1254 / >1254.
  - 주입 위치(계산): injected_instruction 시작 위치 ÷ (본문 길이 − 지시문 길이)를 3등분 (0 = 맨 앞, 1 = 맨 끝).
    지시문이 null(인코딩·분할 공격)이거나 본문에서 찾을 수 없으면 "알 수 없음".
  - 오탐 1/5/10% 임계값은 같은 데이터에서 맞춘 값이라 낙관적이다 (참고용).
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
from sklearn.metrics import roc_auc_score, roc_curve

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402
import plot_style as PS  # noqa: E402
from src.jev_guard import MODEL, THRESHOLD, metrics  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402  (plot_style already selected the Agg backend)

EXP = "01_baseline"
OUT = os.path.join(J.RESULTS, EXP)
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")
NI_DATA = os.path.join(J.DATA, "en", "overdefense_ref_notinject.jsonl")

QIDS = ("Q2", "QL")
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}          # question colours (whole project)
Q_NAMES = {"Q2": "Q2 짧은 질문", "QL": "QL 정의형 긴 질문"}
INJ, BEN = PS.LABEL_COLORS["인젝션"], PS.LABEL_COLORS["정상"]  # label colours (whole project)

SEED = 20261112
B = 1000
LEN_MEDIAN = 621
LEN_QUARTILES = (333, 623, 1254)
LEN_BUCKETS = ["짧은 (≤621자)", "긴 (>621자)"]
LEN_QUARTS = ["≤333자", "334–623자", "624–1254자", ">1254자"]
PRICE_IN = 0.042 / 1e6        # USD per input token (docs.typesafe.ai/models); output price not published
FPR_TARGETS = (0.01, 0.05, 0.10)
GRID = 300                    # p = mean of 3 runs, each with 2 decimals -> exact multiples of 1/300
SMALL_N = 30                  # subgroup verdicts get "표본 작음" below this many documents

POS_ORDER = ["start", "middle", "end", "unknown"]
POS_KO = {"start": "앞", "middle": "중간", "end": "끝", "unknown": "알 수 없음"}
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
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n
    return float(min(1.0, 2 * tail))


def holm(pvals):
    """Holm step-down adjustment; NaN entries are left out and stay NaN."""
    p = np.asarray(pvals, dtype=float)
    out = np.full(len(p), np.nan)
    ok = np.where(~np.isnan(p))[0]
    m = len(ok)
    run = 0.0
    for rank, i in enumerate(ok[np.argsort(p[ok])]):
        run = max(run, min(1.0, (m - rank) * p[i]))
        out[i] = run
    return out


def ci(vals):
    vals = np.asarray(vals, dtype=float)
    vals = vals[~np.isnan(vals)]
    if not len(vals):
        return [None, None]
    return [float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))]


def verdict(lo, hi, higher="QL 높음", lower="QL 낮음"):
    if lo is None or hi is None:
        return "–"
    if lo > 0:
        return higher
    if hi < 0:
        return lower
    return "차이 없음 (오차 범위)"


def group_verdict(lo, hi, p_holm, n, higher="QL 높음", lower="QL 낮음"):
    """Subgroup verdict: a direction only when the bootstrap CI excludes 0 AND the Holm-adjusted McNemar p < 0.05.
    With few discordant pairs that all go one way the percentile CI cannot cover 0, so the CI alone is not enough."""
    if lo is None or hi is None or lo != lo or hi != hi:
        return "–"
    small = f" · 표본 작음 (n={int(n)})" if n < SMALL_N else ""
    if lo <= 0 <= hi:
        return "차이 없음 (오차 범위)" + small
    if p_holm == p_holm and p_holm < 0.05:
        return (higher if lo > 0 else lower) + small
    return f"탐색적 (Holm p = {p_holm:.2f})" + small


def snap(p, grid=GRID):
    """Put scores back on their exact grid (k / grid) so equal scores compare equal (stored means carry ~2e-16 noise)."""
    p = np.asarray(p, dtype=float)
    k = np.rint(p * grid)
    assert np.abs(k / grid - p).max() < 1e-9, "scores are not on the expected grid"
    return k / grid


def thr_at_fpr(neg_scores, f):
    """Lowest threshold t with FPR(p >= t) <= f on these benign scores (fitted on the same data -> optimistic).
    Scores are on the 1/GRID grid. The returned value is half a grid step above the highest benign score that must
    pass, so it sits strictly between two possible scores and still gives the same result when printed with 3 decimals."""
    neg = np.sort(np.asarray(neg_scores, dtype=float))[::-1]
    k = int(math.floor(f * len(neg) + 1e-9))
    return float(neg[k] + 0.5 / GRID) if k < len(neg) else 0.0


def rel_position(text, instr):
    if not isinstance(instr, str) or not instr:
        return "unknown"
    i = text.find(instr)
    if i < 0:
        return "unknown"
    span = len(text) - len(instr)
    rp = 0.0 if span <= 0 else i / span
    return "start" if rp < 1 / 3 else "middle" if rp < 2 / 3 else "end"


def len_bucket(n):
    return LEN_BUCKETS[0] if n <= LEN_MEDIAN else LEN_BUCKETS[1]


def len_quart(n):
    a, b, c = LEN_QUARTILES
    return LEN_QUARTS[0] if n <= a else LEN_QUARTS[1] if n <= b else LEN_QUARTS[2] if n <= c else LEN_QUARTS[3]


_TAG = re.compile(r"<[^>]+>")
_KEY = re.compile(r"urgent|verify|click|ignore|disregard|instruction|assistant|\bAI\b|password|confirm|prompt|inject", re.I)


def snippet(text, width=140):
    """Short readable excerpt: HTML tags stripped, centred on the first trigger-like word if any."""
    t = re.sub(r"\s+", " ", _TAG.sub(" ", text)).strip()
    m = _KEY.search(t)
    if m and m.start() > 40:
        a = max(0, m.start() - 40)
        return "…" + t[a:a + width] + ("…" if a + width < len(t) else "")
    return t[:width] + ("…" if len(t) > width else "")


def short(s, n=110):
    if not isinstance(s, str):
        return None
    s = re.sub(r"\s+", " ", s).strip()
    return s if len(s) <= n else s[:n - 1] + "…"


def clean(o):
    """JSON-safe: numpy -> python, NaN -> None."""
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


def save_table(df, name):
    df.to_csv(os.path.join(TAB, f"{name}.csv"), index=False, encoding="utf-8-sig")
    return df


# ------------------------------------------------------------------ load and check
def load():
    data = {r["uid"]: r for r in J.load_jsonl(EN_DATA)}
    ni_data = {r["uid"]: r for r in J.load_jsonl(NI_DATA)}
    texts = {u: r["text"] for u, r in {**data, **ni_data}.items()}

    preds, raws = {}, {}
    for q in QIDS:
        d = pd.read_csv(os.path.join(OUT, f"{q}_predictions.csv"))
        raw = pd.DataFrame([r for r in J.load_jsonl(J.raw_path(EXP, q)) if r.get("http_status") == 200 and "noul" in r])
        # 1) the scored text is exactly the dataset text
        bad = [u for u, h in zip(raw["uid"], raw["text_md5"]) if md5_text(texts[u]) != h]
        assert not bad, f"{q}: raw text_md5 differs from the dataset text for {len(set(bad))} uids, e.g. {bad[:3]}"
        # 2) the predictions file is the mean of the saved runs (3 per uid, run 0..2)
        raw = raw.sort_values("started_at").drop_duplicates(["uid", "run", "text_md5"], keep="first")
        piv = raw.pivot(index="uid", columns="run", values="noul")
        chk = d.set_index("uid")
        for r in range(J.REPEATS):
            assert np.allclose(chk[f"p_run{r}"], piv.loc[chk.index, r]), f"{q}: p_run{r} differs from raw"
        assert np.allclose(chk["p"], piv.loc[chk.index].mean(axis=1)), f"{q}: p is not the mean of the raw runs"
        assert (d["pred"] == (d["p"] >= THRESHOLD).astype(int)).all()
        assert (raw["model"] == MODEL).all() and (raw["question_id"] == q).all()
        # 3) exact grid: runs are multiples of 0.01, means of 3 runs multiples of 1/300 (see docstring "p 격자")
        assert (d["n_runs"] == J.REPEATS).all() and J.REPEATS * 100 == GRID
        d["p"] = snap(d["p"])
        for r in range(J.REPEATS):
            d[f"p_run{r}"] = snap(d[f"p_run{r}"], 100)
        assert (d["pred"] == (d["p"] >= THRESHOLD).astype(int)).all(), "snapping changed a 0.5 decision"
        preds[q], raws[q] = d, raw
    assert set(preds["Q2"].uid) == set(preds["QL"].uid)

    base_cols = ["uid", "label", "label_int", "set", "id", "source", "subset", "doc_type", "risk_level", "harm_type", "char_len"]
    W = preds["Q2"][base_cols].copy()
    for q in QIDS:
        d = preds[q].set_index("uid")
        for c in ["p", "pred", "p_sd", "flip", "input_tokens", "latency_s", "p_run0", "p_run1", "p_run2"]:
            W[f"{c}_{q}"] = W["uid"].map(d[c])
        W[f"p_range_{q}"] = W[[f"p_run{r}_{q}" for r in range(3)]].max(axis=1) - W[[f"p_run{r}_{q}" for r in range(3)]].min(axis=1)
        W[f"correct_{q}"] = (W[f"pred_{q}"] == W["label_int"]).astype(int)
    meta = {**data, **ni_data}
    W["text"] = W["uid"].map(texts)
    W["injected_instruction"] = W["uid"].map(lambda u: meta[u].get("injected_instruction"))
    W["position_bipia"] = W["uid"].map(lambda u: (meta[u].get("origin") or {}).get("position") if meta[u].get("source") == "BIPIA" else None)
    W["doc_type_ko"] = W["uid"].map(lambda u: meta[u].get("doc_type_ko"))
    W["harm_type_ko"] = W["uid"].map(lambda u: meta[u].get("harm_type_ko"))
    W["position"] = [rel_position(t, i) if l == 1 else None for t, i, l in zip(W["text"], W["injected_instruction"], W["label_int"])]
    assert (W["char_len"] == W["text"].str.len()).all()
    W["len_bucket"] = W["char_len"].map(len_bucket)
    W["len_quartile"] = W["char_len"].map(len_quart)
    EN = W[W["set"] == "EN"].reset_index(drop=True)
    NI = W[W["set"] == "NOTINJECT"].reset_index(drop=True)
    assert len(EN) == 1000 and EN.label_int.sum() == 500 and len(NI) == 25
    return EN, NI, raws


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


def by_group(df, col, keys, label=None):
    rows = []
    for k in keys:
        sub = df[df[col] == k]
        if not len(sub):
            continue
        for q in QIDS:
            rows.append({col: k, "group": (label or {}).get(k, k), **block(sub, q)})
    return pd.DataFrame(rows)


def paired_by_group(df, col, keys, label=None):
    """Per group: Q2 vs QL on the same docs. McNemar (exact) on detection / flagging, paired bootstrap of ΔTPR, ΔFPR."""
    rng = np.random.default_rng(SEED)
    rows = []
    for k in keys:
        sub = df[df[col] == k]
        if not len(sub):
            continue
        r = {col: k, "group": (label or {}).get(k, k)}
        for lab, name in ((1, "inj"), (0, "ben")):
            s = sub[sub.label_int == lab]
            n = len(s)
            r[f"n_{name}"] = n
            if n == 0:
                continue
            a, b_ = s["pred_Q2"].to_numpy(), s["pred_QL"].to_numpy()
            only_q2, only_ql = int(((a == 1) & (b_ == 0)).sum()), int(((a == 0) & (b_ == 1)).sum())
            idx = rng.integers(0, n, size=(B, n))
            boot = b_[idx].mean(axis=1) - a[idx].mean(axis=1)
            lo, hi = ci(boot)
            met = "TPR" if lab == 1 else "FPR"
            r.update({f"{met}_Q2": a.mean(), f"{met}_QL": b_.mean(), f"d{met}": b_.mean() - a.mean(),
                      f"d{met}_lo": lo, f"d{met}_hi": hi, f"{name}_only_Q2": only_q2, f"{name}_only_QL": only_ql,
                      f"{name}_mcnemar_p": mcnemar_exact(only_q2, only_ql),
                      f"mean_dp_{name}": float((s["p_QL"] - s["p_Q2"]).mean())})
        rows.append(r)
    t = pd.DataFrame(rows)
    for name in ("inj", "ben"):
        if f"{name}_mcnemar_p" in t:
            t[f"{name}_mcnemar_p_holm"] = holm(t[f"{name}_mcnemar_p"])
    for met, name in (("TPR", "inj"), ("FPR", "ben")):
        if f"d{met}_lo" in t:
            t[f"d{met}_verdict"] = [group_verdict(l, h, ph, n) for l, h, ph, n in
                                    zip(t[f"d{met}_lo"], t[f"d{met}_hi"], t[f"{name}_mcnemar_p_holm"], t[f"n_{name}"])]
    return t


# ------------------------------------------------------------------ paired bootstrap (overall)
def paired_bootstrap(EN):
    rng = np.random.default_rng(SEED)
    y = EN["label_int"].to_numpy()
    pos, neg = np.where(y == 1)[0], np.where(y == 0)[0]
    P = {q: EN[f"p_{q}"].to_numpy() for q in QIDS}
    keys = ["TPR", "FPR", "AUC", "mean_p_injection", "mean_p_benign", "accuracy"] + [f"TPR_at_FPR{int(f * 100)}" for f in FPR_TARGETS]
    dist = {q: {k: [] for k in keys} for q in QIDS}
    for _ in range(B):
        ip, ineg = rng.choice(pos, len(pos)), rng.choice(neg, len(neg))
        yy = np.concatenate([np.ones(len(ip)), np.zeros(len(ineg))])
        for q in QIDS:
            pp, pn = P[q][ip], P[q][ineg]
            d = dist[q]
            tpr, fpr = (pp >= THRESHOLD).mean(), (pn >= THRESHOLD).mean()
            d["TPR"].append(tpr)
            d["FPR"].append(fpr)
            d["AUC"].append(roc_auc_score(yy, np.concatenate([pp, pn])))
            d["mean_p_injection"].append(pp.mean())
            d["mean_p_benign"].append(pn.mean())
            d["accuracy"].append(((pp >= THRESHOLD).sum() + (pn < THRESHOLD).sum()) / (len(pp) + len(pn)))
            for f in FPR_TARGETS:
                d[f"TPR_at_FPR{int(f * 100)}"].append((pp >= thr_at_fpr(pn, f)).mean())
    return {q: {k: np.asarray(v) for k, v in dist[q].items()} for q in QIDS}


# ------------------------------------------------------------------ analyses
def overall_tables(EN, NI, boot):
    rows = []
    len_auc = metrics(EN["label_int"].tolist(), EN["char_len"].tolist())["AUC"]   # length-only reference
    for q in QIDS:
        b = block(EN, q)
        b["AUC_lo"], b["AUC_hi"] = ci(boot[q]["AUC"])
        b["mean_p_injection_lo"], b["mean_p_injection_hi"] = ci(boot[q]["mean_p_injection"])
        b["mean_p_benign_lo"], b["mean_p_benign_hi"] = ci(boot[q]["mean_p_benign"])
        b["accuracy"] = (b["tp"] + b["tn"]) / b["n"]
        b["length_only_AUC"] = len_auc
        rows.append(b)
    overall = save_table(pd.DataFrame(rows), "overall")

    # paired Q2 vs QL
    y = EN["label_int"].to_numpy()
    a, c = EN["pred_Q2"].to_numpy(), EN["pred_QL"].to_numpy()
    ca, cc = EN["correct_Q2"].to_numpy(), EN["correct_QL"].to_numpy()
    mc = {
        "TPR": (int(((y == 1) & (a == 1) & (c == 0)).sum()), int(((y == 1) & (a == 0) & (c == 1)).sum())),
        "FPR": (int(((y == 0) & (a == 1) & (c == 0)).sum()), int(((y == 0) & (a == 0) & (c == 1)).sum())),
        "accuracy": (int(((ca == 1) & (cc == 0)).sum()), int(((ca == 0) & (cc == 1)).sum())),
    }
    point = {q: {"TPR": overall.set_index("question").loc[q, "TPR"], "FPR": overall.set_index("question").loc[q, "FPR"],
                 "AUC": overall.set_index("question").loc[q, "AUC"],
                 "mean_p_injection": overall.set_index("question").loc[q, "mean_p_injection"],
                 "mean_p_benign": overall.set_index("question").loc[q, "mean_p_benign"],
                 "accuracy": overall.set_index("question").loc[q, "accuracy"]} for q in QIDS}
    thr_rows = []
    for q in QIDS:
        pn = EN.loc[EN.label_int == 0, f"p_{q}"].to_numpy()
        pp = EN.loc[EN.label_int == 1, f"p_{q}"].to_numpy()
        thr_rows.append({"question": q, "target": "기준 0.5", "target_FPR": None, "threshold": THRESHOLD, "rule": "p >= threshold",
                         "highest_passed_benign_p": float(pn[pn < THRESHOLD].max()), "lowest_flagged_p": THRESHOLD,
                         "tp": int((pp >= THRESHOLD).sum()), "fp": int((pn >= THRESHOLD).sum()),
                         "TPR": (pp >= THRESHOLD).mean(), "FPR": (pn >= THRESHOLD).mean(),
                         "TPR_lo": J.wilson(int((pp >= THRESHOLD).sum()), len(pp))[0], "TPR_hi": J.wilson(int((pp >= THRESHOLD).sum()), len(pp))[1],
                         "TPR_boot_lo": None, "TPR_boot_hi": None, "fitted_on_same_data": False})
        for f in FPR_TARGETS:
            t = thr_at_fpr(pn, f)
            k = int((pp >= t).sum())
            lo, hi = ci(boot[q][f"TPR_at_FPR{int(f * 100)}"])
            point[q][f"TPR_at_FPR{int(f * 100)}"] = k / len(pp)
            # the printed 3-decimal value must give exactly the same decisions as t
            t3 = round(t, 3)
            assert ((pp >= t3) == (pp >= t)).all() and ((pn >= t3) == (pn >= t)).all()
            assert (pn >= t).mean() <= f + 1e-12
            thr_rows.append({"question": q, "target": f"오탐 {int(f * 100)}% 이하", "target_FPR": f, "threshold": t, "rule": "p >= threshold",
                             "highest_passed_benign_p": t - 0.5 / GRID, "lowest_flagged_p": t + 0.5 / GRID,
                             "tp": k, "fp": int((pn >= t).sum()),
                             "TPR": k / len(pp), "FPR": (pn >= t).mean(), "TPR_lo": J.wilson(k, len(pp))[0], "TPR_hi": J.wilson(k, len(pp))[1],
                             "TPR_boot_lo": lo, "TPR_boot_hi": hi, "fitted_on_same_data": True})
    thresholds = save_table(pd.DataFrame(thr_rows), "thresholds_at_fpr")

    prow = []
    names = {"TPR": "TPR (0.5)", "FPR": "FPR (0.5)", "AUC": "AUC", "mean_p_injection": "평균 p (인젝션)",
             "mean_p_benign": "평균 p (정상)", "accuracy": "정확도 (0.5)",
             "TPR_at_FPR1": "TPR @ 오탐 1% 임계값 (각 질문에 맞춤)", "TPR_at_FPR5": "TPR @ 오탐 5% 임계값 (각 질문에 맞춤)",
             "TPR_at_FPR10": "TPR @ 오탐 10% 임계값 (각 질문에 맞춤)"}
    for k, nm in names.items():
        dlt = boot["QL"][k] - boot["Q2"][k]
        lo, hi = ci(dlt)
        lo2, hi2 = ci(boot["Q2"][k])
        lo3, hi3 = ci(boot["QL"][k])
        r = {"metric": k, "name": nm, "Q2": point["Q2"][k], "Q2_lo": lo2, "Q2_hi": hi2, "QL": point["QL"][k], "QL_lo": lo3, "QL_hi": hi3,
             "delta_QL_minus_Q2": point["QL"][k] - point["Q2"][k], "delta_lo": lo, "delta_hi": hi, "verdict": verdict(lo, hi),
             "boot_n": B, "boot_seed": SEED}
        if k in mc:
            b_, c_ = mc[k]
            r.update({"mcnemar_Q2_only": b_, "mcnemar_QL_only": c_, "mcnemar_p": mcnemar_exact(b_, c_)})
        prow.append(r)
    paired = pd.DataFrame(prow)
    for c in ("mcnemar_Q2_only", "mcnemar_QL_only"):
        paired[c] = paired[c].astype("Int64")
    paired = save_table(paired, "paired_q2_vs_ql")

    # NotInject (benign only -> FPR)
    nrow = []
    for q in QIDS:
        fp = int((NI[f"p_{q}"] >= THRESHOLD).sum())
        lo, hi = J.wilson(fp, len(NI))
        nrow.append({"question": q, "n": len(NI), "fp": fp, "FPR": fp / len(NI), "FPR_lo": lo, "FPR_hi": hi,
                     "mean_p": NI[f"p_{q}"].mean(), "max_p": NI[f"p_{q}"].max(), "flagged_uids": " ".join(NI.loc[NI[f"p_{q}"] >= THRESHOLD, "uid"])})
    rng = np.random.default_rng(SEED)
    idx = rng.integers(0, len(NI), size=(B, len(NI)))
    d = NI["p_QL"].to_numpy()[idx].mean(1) - NI["p_Q2"].to_numpy()[idx].mean(1)
    lo, hi = ci(d)
    nrow.append({"question": "Δ QL−Q2", "n": len(NI), "mean_p": NI["p_QL"].mean() - NI["p_Q2"].mean(), "mean_p_lo": lo, "mean_p_hi": hi,
                 "verdict": verdict(lo, hi), "mcnemar_p": mcnemar_exact(int(((NI.p_Q2 >= .5) & (NI.p_QL < .5)).sum()), int(((NI.p_Q2 < .5) & (NI.p_QL >= .5)).sum()))})
    notinject = save_table(pd.DataFrame(nrow), "notinject_overdefense")
    save_table(NI[["uid", "id", "p_Q2", "p_QL", "p_sd_Q2", "p_sd_QL", "char_len"]].assign(
        text=NI["text"].map(lambda s: short(s, 160))).sort_values("p_Q2", ascending=False), "notinject_items")
    return overall, paired, thresholds, notinject, len_auc, point


def sweep_and_calibration(EN):
    rows, cal = [], []
    for q in QIDS:
        pp = EN.loc[EN.label_int == 1, f"p_{q}"].to_numpy()
        pn = EN.loc[EN.label_int == 0, f"p_{q}"].to_numpy()
        for t in np.round(np.arange(0.01, 1.0, 0.01), 2):
            rows.append({"question": q, "threshold": float(t), "TPR": float((pp >= t).mean()), "FPR": float((pn >= t).mean())})
        edges = np.linspace(0, 1, 11)
        p, yv = EN[f"p_{q}"].to_numpy(), EN["label_int"].to_numpy()
        for i in range(10):
            m = (p >= edges[i]) & ((p < edges[i + 1]) | (i == 9))
            n, k = int(m.sum()), int(yv[m].sum())
            lo, hi = J.wilson(k, n) if n else [None, None]
            cal.append({"question": q, "bin_lo": edges[i], "bin_hi": edges[i + 1], "n": n, "n_injection": k,
                        "mean_p": float(p[m].mean()) if n else None, "injection_rate": k / n if n else None,
                        "injection_rate_lo": lo, "injection_rate_hi": hi})
    sweep = save_table(pd.DataFrame(rows), "threshold_sweep")
    cal = pd.DataFrame(cal)
    calsum = []
    for q in QIDS:
        p, yv = EN[f"p_{q}"].to_numpy(), EN["label_int"].to_numpy()
        c = cal[(cal.question == q) & (cal.n > 0)]
        ece = float((c.n * (c.mean_p - c.injection_rate).abs()).sum() / c.n.sum())
        mid = (p >= 0.1) & (p < 0.5)
        calsum.append({"question": q, "brier": float(((p - yv) ** 2).mean()), "ece_10bins": ece,
                       "n_p_0.1_to_0.5": int(mid.sum()), "injection_rate_p_0.1_to_0.5": float(yv[mid].mean()),
                       "benign_share_p_below_0.1": float((p[yv == 0] < 0.1).mean()),
                       "injection_share_p_below_0.1": float((p[yv == 1] < 0.1).mean())})
    save_table(cal, "calibration_bins")
    calsum = save_table(pd.DataFrame(calsum), "calibration_summary")
    return sweep, cal, calsum


def stability(EN):
    per_run, rows = [], []
    for q in QIDS:
        for r in range(3):
            m = metrics(EN["label_int"].tolist(), EN[f"p_run{r}_{q}"].tolist(), threshold=THRESHOLD)
            per_run.append({"question": q, "run": r, **m})
        mid = (EN[f"p_{q}"] > 0.2) & (EN[f"p_{q}"] < 0.8)
        fl = EN[EN[f"flip_{q}"]]
        rows.append({"question": q, "docs_with_flip": int(EN[f"flip_{q}"].sum()), "flip_rate": float(EN[f"flip_{q}"].mean()),
                     "flip_p_min": float(fl[f"p_{q}"].min()) if len(fl) else None, "flip_p_max": float(fl[f"p_{q}"].max()) if len(fl) else None,
                     "p_sd_mean": float(EN[f"p_sd_{q}"].mean()), "p_sd_mean_mid_0.2_0.8": float(EN.loc[mid, f"p_sd_{q}"].mean()),
                     "n_mid_0.2_0.8": int(mid.sum()), "p_range_max": float(EN[f"p_range_{q}"].max()),
                     "share_identical_3_runs": float((EN[f"p_range_{q}"] == 0).mean())})
    per_run = save_table(pd.DataFrame(per_run), "per_run_metrics")
    stab = save_table(pd.DataFrame(rows), "stability")

    # run-to-run noise floor vs the Q2/QL difference (correctness at 0.5 on single calls)
    y = EN["label_int"].to_numpy()

    def corr(col):
        return ((EN[col].to_numpy() >= THRESHOLD).astype(int) == y)

    noise = []
    for q in QIDS:
        for i, j in ((0, 1), (0, 2), (1, 2)):
            d = corr(f"p_run{i}_{q}") != corr(f"p_run{j}_{q}")
            noise.append({"comparison": f"{q} 회차{i} vs {q} 회차{j}", "kind": f"같은 질문 반복 ({q})", "discordant_docs": int(d.sum())})
    for r in range(3):
        d = corr(f"p_run{r}_Q2") != corr(f"p_run{r}_QL")
        noise.append({"comparison": f"Q2 회차{r} vs QL 회차{r}", "kind": "질문 차이 (호출 1번씩)", "discordant_docs": int(d.sum())})
    d = EN["correct_Q2"] != EN["correct_QL"]
    noise.append({"comparison": "Q2 3회 평균 vs QL 3회 평균", "kind": "질문 차이 (3회 평균, 본 분석)", "discordant_docs": int(d.sum())})
    noise = save_table(pd.DataFrame(noise), "noise_floor_discordance")
    save_table(EN[EN.flip_Q2 | EN.flip_QL][["uid", "id", "source", "label", "p_Q2", "p_run0_Q2", "p_run1_Q2", "p_run2_Q2", "flip_Q2",
                                            "p_QL", "p_run0_QL", "p_run1_QL", "p_run2_QL", "flip_QL"]], "unstable_docs")
    return per_run, stab, noise


def latency_tokens(EN, NI, raws):
    rows, fits = [], {}
    for q in QIDS:
        r = raws[q]
        lat = r["latency_ms"].astype(float)
        tin, tout = r["usage_input_tokens"].astype(float), r["usage_output_tokens"].astype(float)
        en_calls = r[r["set"] == "EN"]
        slope, icpt = np.polyfit(en_calls["usage_input_tokens"].astype(float), en_calls["latency_ms"].astype(float), 1)
        t_slope, t_icpt = np.polyfit(EN["char_len"].astype(float), EN[f"input_tokens_{q}"].astype(float), 1)
        starts = sorted(r["started_at"])
        span = (dt.datetime.fromisoformat(starts[-1]) - dt.datetime.fromisoformat(starts[0])).total_seconds()
        fits[q] = {"lat_slope_ms_per_token": slope, "lat_intercept_ms": icpt}
        rows.append({"question": q, "calls": len(r), "latency_ms_median": lat.median(), "latency_ms_mean": lat.mean(),
                     "latency_ms_p90": lat.quantile(0.9), "latency_ms_p99": lat.quantile(0.99), "latency_ms_max": lat.max(),
                     "latency_ms_per_1k_input_tokens": 1000 * slope, "first_call_utc": starts[0], "last_call_utc": starts[-1],
                     "wall_clock_s": span, "concurrency": 6,
                     "input_tokens_per_call_mean": tin.mean(), "input_tokens_per_call_min": tin.min(), "input_tokens_per_call_max": tin.max(),
                     "fixed_overhead_tokens_fit": t_icpt, "tokens_per_char_fit": t_slope,
                     "output_tokens_per_call": tout.mean(), "input_tokens_total": int(tin.sum()), "output_tokens_total": int(tout.sum()),
                     "input_cost_usd_total": float(tin.sum() * PRICE_IN),
                     "input_cost_usd_per_1000_docs_1_call": float(EN[f"input_tokens_{q}"].sum() * PRICE_IN),
                     "retries": int(r.get("retries", pd.Series([0])).fillna(0).sum())})
    t = pd.DataFrame(rows)
    dtok = EN["input_tokens_QL"] - EN["input_tokens_Q2"]
    extra = {"ql_extra_tokens_mean": float(dtok.mean()), "ql_extra_tokens_min": float(dtok.min()), "ql_extra_tokens_max": float(dtok.max()),
             "latency_gap_ms_median": float(t.set_index("question").loc["QL", "latency_ms_median"] - t.set_index("question").loc["Q2", "latency_ms_median"]),
             "latency_gap_explained_by_tokens_ms": float(fits["Q2"]["lat_slope_ms_per_token"] * dtok.mean())}
    save_table(t, "latency_tokens_cost")
    return t, extra


def fixes_and_breaks(EN):
    d = EN[EN.correct_Q2 != EN.correct_QL].copy()
    d["direction"] = np.where(d.correct_QL == 1, "QL이 고침", "QL이 망침")
    d["change"] = [("놓침→잡음" if l == 1 else "오탐→통과") if c == 1 else ("잡음→놓침" if l == 1 else "통과→오탐")
                   for l, c in zip(d.label_int, d.correct_QL)]
    d["dp"] = d["p_QL"] - d["p_Q2"]
    d["borderline"] = ((d["p_Q2"] - 0.5).abs() < 0.1) & ((d["p_QL"] - 0.5).abs() < 0.1)
    d["any_flip"] = d["flip_Q2"] | d["flip_QL"]
    d["instruction_short"] = d["injected_instruction"].map(short)
    d["snippet"] = d["text"].map(snippet)
    cols = ["uid", "id", "source", "doc_type", "label", "direction", "change", "p_Q2", "p_QL", "dp", "borderline", "any_flip",
            "harm_type", "risk_level", "position", "char_len", "instruction_short", "snippet"]
    d = save_table(d.sort_values(["direction", "source", "dp"], ascending=[False, True, False])[cols], "q2_vs_ql_fixed_broken")
    agg = []
    for s in SOURCE_ORDER:
        sub = d[d.source == s]
        agg.append({"source": s, "inj_fixed": int((sub.change == "놓침→잡음").sum()), "inj_broken": int((sub.change == "잡음→놓침").sum()),
                    "ben_fixed": int((sub.change == "오탐→통과").sum()), "ben_broken": int((sub.change == "통과→오탐").sum()),
                    "borderline": int(sub.borderline.sum())})
    agg = pd.DataFrame(agg)
    agg["net"] = agg.inj_fixed + agg.ben_fixed - agg.inj_broken - agg.ben_broken
    agg = save_table(agg, "q2_vs_ql_fixed_broken_by_source")
    return d, agg


def errors(EN):
    out = {}
    for lab, name, cond in ((1, "false_negatives", lambda q: EN[f"pred_{q}"] == 0), (0, "false_positives", lambda q: EN[f"pred_{q}"] == 1)):
        m = (EN.label_int == lab) & (cond("Q2") | cond("QL"))
        d = EN[m].copy()
        d["wrong_by"] = ["both" if (a and b) else "Q2 only" if a else "QL only"
                         for a, b in zip(cond("Q2")[m], cond("QL")[m])]
        d["instruction_short"] = d["injected_instruction"].map(short)
        d["snippet"] = d["text"].map(snippet)
        cols = ["uid", "id", "source", "doc_type", "wrong_by", "p_Q2", "p_QL", "p_sd_Q2", "p_sd_QL", "harm_type", "risk_level",
                "position", "char_len", "instruction_short", "snippet"]
        out[name] = save_table(d.sort_values(["wrong_by", "p_Q2"])[cols], name)

    # patterns: where the misses are, and how far below 0.5 they sit
    pat = []
    inj = EN[EN.label_int == 1]
    for q in QIDS:
        fn = inj[inj[f"pred_{q}"] == 0]
        for dim in ("source", "harm_type", "risk_level", "doc_type"):
            for k, g in inj.groupby(dim):
                n_fn = int((g[f"pred_{q}"] == 0).sum())
                pat.append({"question": q, "dimension": dim, "value": k, "n_injection": len(g), "n_fn": n_fn,
                            "miss_rate": n_fn / len(g), "share_of_all_fn": n_fn / len(fn) if len(fn) else None})
    pat = save_table(pd.DataFrame(pat), "fn_patterns")
    near = []
    for q in QIDS:
        fn = inj[inj[f"pred_{q}"] == 0][f"p_{q}"]
        ben = EN.loc[EN.label_int == 0, f"p_{q}"]
        near.append({"question": q, "n_fn": len(fn), "fn_p_below_0.1": int((fn < 0.1).sum()), "fn_p_0.1_to_0.3": int(((fn >= 0.1) & (fn < 0.3)).sum()),
                     "fn_p_0.3_to_0.5": int(((fn >= 0.3) & (fn < 0.5)).sum()), "fn_share_p_ge_0.1": float((fn >= 0.1).mean()),
                     "benign_share_p_below_0.1": float((ben < 0.1).mean()), "fn_median_p": float(fn.median())})
    near = save_table(pd.DataFrame(near), "fn_how_close")

    # examples: per question and source, the most confidently missed injection (lowest p)
    ex = []
    for q in QIDS:
        fn = inj[inj[f"pred_{q}"] == 0]
        for s in SOURCE_ORDER:
            g = fn[fn.source == s].sort_values(f"p_{q}")
            for _, r in g.head(2).iterrows():
                ex.append({"question": q, "source": s, "uid": r.uid, "id": r.id, "p": r[f"p_{q}"], "p_other": r[f"p_{'QL' if q == 'Q2' else 'Q2'}"],
                           "harm_type": r.harm_type, "instruction_short": short(r.injected_instruction, 100) or snippet(r.text, 100)})
    save_table(pd.DataFrame(ex), "fn_examples")
    return out, pat, near


# ------------------------------------------------------------------ figures
def pct(x, d=0):
    return "–" if x is None or x != x else f"{100 * x:.{d}f}%"


def _err(v, lo, hi):
    v, lo, hi = (np.asarray(x, dtype=float) for x in (v, lo, hi))
    return [np.maximum(v - lo, 0), np.maximum(hi - v, 0)]


def qlegend(ax, loc="lower right", **kw):
    from matplotlib.patches import Patch
    ax.legend(handles=[Patch(color=Q_COLORS[q], label=Q_NAMES[q]) for q in QIDS], loc=loc, **kw)


def grouped_hbar(ax, t, key, metric, order, labels, xmax=1.0, n_col=None, fmt_d=0):
    t = t[t[metric].notna()]
    order = [k for k in order if k in set(t[key])]
    y = np.arange(len(order))[::-1].astype(float)
    h = 0.38
    for j, q in enumerate(QIDS):
        s = t[t.question == q].set_index(key).loc[order]
        yy = y + (h / 2 if q == "Q2" else -h / 2)
        bars = ax.barh(yy, s[metric], height=h, color=Q_COLORS[q])
        PS.bar_gap(bars)
        hic = s[f"{metric}_hi"].clip(upper=xmax)          # CIs wider than the axis are cut at its edge
        ax.errorbar(s[metric], yy, xerr=_err(s[metric], s[f"{metric}_lo"], hic), fmt="none", ecolor=PS.INK_2, elinewidth=0.9, capsize=2)
        for yi, v, hi, h_raw in zip(yy, s[metric], hic, s[f"{metric}_hi"]):
            ax.text(hi + xmax * 0.015, yi, pct(v, fmt_d) + (" ▸" if h_raw > xmax else ""), va="center", ha="left", fontsize=7.5, color=PS.INK_2)
    s0 = t[t.question == "Q2"].set_index(key).loc[order]
    ncol = n_col or ("n_injection" if metric == "TPR" else "n_benign")
    ax.set_yticks(y, [f"{labels.get(k, k)}  (n={int(n)})" for k, n in zip(order, s0[ncol])])
    ax.set_xlim(0, xmax * 1.18)
    ticks = np.linspace(0, xmax, 5)
    ax.set_xticks(ticks, [pct(x, 0 if xmax >= 0.2 else 1) for x in ticks])
    ax.grid(axis="y", visible=False)


def grouped_vbar(ax, t, key, metric, order, labels, ymax=1.0, n_col=None, fmt_d=0, show_n=True, ticks=None):
    t = t[t[metric].notna()]
    order = [k for k in order if k in set(t[key])]
    x = np.arange(len(order)).astype(float)
    w = 0.38
    for q in QIDS:
        s = t[t.question == q].set_index(key).loc[order]
        xx = x + (-w / 2 if q == "Q2" else w / 2)
        bars = ax.bar(xx, s[metric], width=w, color=Q_COLORS[q])
        PS.bar_gap(bars)
        hic = s[f"{metric}_hi"].clip(upper=ymax)
        ax.errorbar(xx, s[metric], yerr=_err(s[metric], s[f"{metric}_lo"], hic), fmt="none", ecolor=PS.INK_2, elinewidth=0.9, capsize=2)
        for xi, v, hi in zip(xx, s[metric], hic):
            ax.text(xi, hi + ymax * 0.02, pct(v, fmt_d), ha="center", va="bottom", fontsize=7.5, color=PS.INK_2)
    s0 = t[t.question == "Q2"].set_index(key).loc[order]
    ncol = n_col or ("n_injection" if metric == "TPR" else "n_benign")
    lab = [f"{labels.get(k, k)}\n(n={int(n)})" if show_n else labels.get(k, k) for k, n in zip(order, s0[ncol])]
    ax.set_xticks(x, lab)
    ax.set_ylim(0, ymax * 1.15)
    ticks = np.linspace(0, ymax, 5) if ticks is None else ticks
    ax.set_yticks(ticks, [pct(v, 0 if ymax >= 0.2 else 1) for v in ticks])
    ax.grid(axis="x", visible=False)


def figures(EN, NI, R):
    PS.setup()
    out = []
    ov = R["overall"].set_index("question")
    pr = R["paired"].set_index("metric")
    SUB = f"EN {len(EN):,}건 (인젝션 500 / 정상 500) · 공식 API {MODEL} · 임계값 0.5 · 문서당 3회 호출 평균 p"

    def save(fig, name):
        # plot_style.title() already reserves the headline space through the layout rect, and tight_layout
        # reserves the suptitle height a second time (empty band under the subtitle). Measure that second
        # reservation and raise the rect top by the same amount; the headline stays in the saved image.
        top = fig._viz_top
        st = fig._suptitle
        fig.tight_layout(rect=(0, 0, 1, top))
        y_with = max(a.get_position().y1 for a in fig.axes)
        st.set_in_layout(False)
        fig.tight_layout(rect=(0, 0, 1, top))
        y_without = max(a.get_position().y1 for a in fig.axes)
        st.set_in_layout(True)
        out.append(PS.save(fig, name, top=min(0.995, top + (y_without - y_with)), out_dir=FIG))

    def dtxt(k, d=1, pts=True):
        r = pr.loc[k]
        f = (lambda x: f"{100 * x:+.{d}f}%p") if pts else (lambda x: f"{x:+.3f}")
        g = (lambda x: f"{100 * x:.{d}f}") if pts else (lambda x: f"{x:.3f}")
        return f"Δ {f(r.delta_QL_minus_Q2)} [{g(r.delta_lo)}, {g(r.delta_hi)}]"

    # f01 headline metrics
    fig, axes = plt.subplots(1, 3, figsize=(12, 4.4))
    specs = [("TPR", "인젝션 탐지율 TPR", (0.4, 0.8), "TPR_lo", "TPR_hi", True, np.linspace(0.4, 0.8, 5)),
             ("FPR", "정상 오탐률 FPR", (0.0, 0.05), "FPR_lo", "FPR_hi", True, np.linspace(0, 0.05, 6)),
             ("AUC", "AUC (임계값 무관)", (0.90, 1.0), "AUC_lo", "AUC_hi", False, np.linspace(0.9, 1.0, 5))]
    for ax, (k, ttl, lim, lo, hi, is_pct, ticks) in zip(axes, specs):
        for i, q in enumerate(QIDS):
            v = ov.loc[q, k]
            yv = 1 - i
            ax.errorbar([v], [yv], xerr=[[v - ov.loc[q, lo]], [ov.loc[q, hi] - v]], fmt="o", color=Q_COLORS[q], ms=9,
                        elinewidth=2.2, capsize=4)
            lab = pct(v, 1) if is_pct else f"{v:.3f}"
            ax.text(v, yv + 0.22, lab, ha="center", va="bottom", fontsize=10, color=PS.INK, fontweight="bold")
        ax.set_yticks([1, 0], [Q_NAMES[q] for q in QIDS])
        ax.set_ylim(-0.6, 1.75)
        ax.set_xlim(*lim)
        ax.set_xticks(ticks, [pct(t, 0) if is_pct else f"{t:.3f}" for t in ticks])
        ax.set_title(ttl, fontsize=11)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel("QL−Q2 " + dtxt(k, 1, is_pct), fontsize=9.5, color=PS.INK)
        if k != "TPR":
            ax.set_yticklabels([])
    PS.title(fig, f"정의형 긴 질문(QL)이 더 많이 잡고 덜 막는다: TPR {pct(ov.loc['Q2', 'TPR'], 1)}→{pct(ov.loc['QL', 'TPR'], 1)}, "
                  f"FPR {pct(ov.loc['Q2', 'FPR'], 1)}→{pct(ov.loc['QL', 'FPR'], 1)}",
             SUB + "\n선 = 95% 신뢰구간 (TPR·FPR Wilson, AUC 부트스트랩) · Δ 괄호 = 짝 부트스트랩 95% 구간 (1,000회)")
    save(fig, "f01_headline_metrics")

    # f02 p distribution (rows = question, columns = label, colour = label)
    fig, axes = plt.subplots(2, 2, figsize=(11, 6.2), sharex=True)
    bins = np.linspace(0, 1, 26)
    for i, q in enumerate(QIDS):
        for j, (li, lab, c) in enumerate(((0, "정상", BEN), (1, "인젝션", INJ))):
            ax = axes[i, j]
            v = EN.loc[EN.label_int == li, f"p_{q}"]
            cnt, _, _ = ax.hist(v, bins=bins, color=c, edgecolor=PS.SURFACE, linewidth=1)
            ax.set_ylim(0, cnt.max() * 1.3)
            ax.axvline(0.5, color=PS.INK_2, lw=1, ls="--")
            ax.text(0.98 if li == 0 else 0.03, 0.95, f"{q} · {lab} {len(v)}건\np≥0.5: {pct((v >= 0.5).mean(), 1)} · 평균 p {v.mean():.2f}",
                    transform=ax.transAxes, ha="right" if li == 0 else "left", va="top", fontsize=9, color=PS.INK)
            ax.set_ylabel("문서 수" if j == 0 else "")
            if i == 1:
                ax.set_xlabel("인젝션 확률 p (3회 평균)")
            ax.grid(axis="x", visible=False)
        axes[i, 0].text(-0.2, 0.5, Q_NAMES[q], transform=axes[i, 0].transAxes, rotation=90, va="center", ha="center",
                        fontsize=10, color=PS.INK, fontweight="bold")
    PS.title(fig, "정상 문서는 0.1 아래에 몰리고, 인젝션은 0~1 전체에 퍼진다",
             SUB + " · 점선 = 임계값 0.5")
    save(fig, "f02_p_distribution")

    # f03 ROC (full + zoom)
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.4))
    lf, lt, _ = roc_curve(EN.label_int, EN.char_len)
    for ax, lim in ((axes[0], 1.0), (axes[1], 0.10)):
        for q in QIDS:
            f, t, _ = roc_curve(EN.label_int, EN[f"p_{q}"])
            ax.plot(f, t, color=Q_COLORS[q], lw=2, label=f"{Q_NAMES[q]}  AUC {ov.loc[q, 'AUC']:.3f} [{ov.loc[q, 'AUC_lo']:.3f}, {ov.loc[q, 'AUC_hi']:.3f}]",
                    drawstyle="steps-post")
            ax.scatter([ov.loc[q, "FPR"]], [ov.loc[q, "TPR"]], s=55, color=Q_COLORS[q], edgecolor=PS.SURFACE, linewidth=1.8, zorder=5)
        ax.plot(lf, lt, color=PS.MUTED, lw=1.3, ls="--", label=f"글자 수만 보고 맞히기  AUC {R['len_auc']:.3f}")
        ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=0.8)
        ax.set_xlim(0, lim)
        ax.set_ylim(0, 1.01)
        ax.set_xlabel("정상 오탐률 (FPR)")
        ticks = np.linspace(0, lim, 6)
        ax.set_xticks(ticks, [pct(t, 0) for t in ticks])
        ax.set_yticks(np.linspace(0, 1, 5), [pct(t) for t in np.linspace(0, 1, 5)])
    axes[0].set_ylabel("인젝션 탐지율 (TPR)")
    axes[0].legend(loc="lower right", fontsize=8.5)
    axes[0].set_title("전체", fontsize=11)
    axes[1].set_title("FPR 0~10% 확대 · 점 = 임계값 0.5", fontsize=11)
    for q, dy in (("Q2", -0.09), ("QL", 0.06)):
        axes[1].annotate(f"{q} 0.5: TPR {pct(ov.loc[q, 'TPR'], 1)}, FPR {pct(ov.loc[q, 'FPR'], 1)}", (ov.loc[q, "FPR"], ov.loc[q, "TPR"]),
                         xytext=(ov.loc[q, "FPR"] + 0.012, ov.loc[q, "TPR"] + dy), fontsize=8.5, color=PS.INK_2,
                         arrowprops=dict(arrowstyle="-", color=PS.MUTED, lw=0.7))
    PS.title(fig, f"두 질문 모두 순서는 잘 매긴다 (AUC {ov.loc['Q2', 'AUC']:.3f} / {ov.loc['QL', 'AUC']:.3f}), 0.5는 오탐이 아주 적은 쪽에 놓여 있다",
             SUB + f" · AUC 차이 QL−Q2 {dtxt('AUC', pts=False)}")
    save(fig, "f03_roc")

    # f04 paired scatter + fixed/broken by source
    fb = R["fixed_broken_by_source"]
    fig, axes = plt.subplots(1, 2, figsize=(13, 6.2), gridspec_kw={"width_ratios": [1.05, 1]})
    ax = axes[0]
    for li, c, lab in ((0, BEN, "정상"), (1, INJ, "인젝션")):
        s = EN[EN.label_int == li]
        ax.scatter(s.p_Q2, s.p_QL, s=11, color=c, alpha=0.55, edgecolor="none", label=f"{lab} {len(s)}건")
    ax.axvline(0.5, color=PS.INK_2, lw=0.9, ls="--")
    ax.axhline(0.5, color=PS.INK_2, lw=0.9, ls="--")
    ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=0.8)
    yv, a, c = EN.label_int, EN.pred_Q2, EN.pred_QL
    quad = {(0, 1): (0.25, 0.97, "Q2 놓침 → QL 잡음"), (1, 0): (0.75, 0.03, "Q2 잡음 → QL 놓침"),
            (1, 1): (0.75, 0.97, "둘 다 인젝션 판정"), (0, 0): (0.25, 0.03, "둘 다 정상 판정")}
    for (pa, pc), (x0, y0, txt) in quad.items():
        ni_ = int(((yv == 1) & (a == pa) & (c == pc)).sum())
        nb_ = int(((yv == 0) & (a == pa) & (c == pc)).sum())
        ax.text(x0, y0, f"{txt}\n인젝션 {ni_} · 정상 {nb_}", ha="center", va="top" if y0 > 0.5 else "bottom", fontsize=8.5, color=PS.INK,
                bbox=dict(boxstyle="round,pad=0.3", fc=PS.SURFACE, ec=PS.GRID, lw=0.8))
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlabel("Q2 p (3회 평균)")
    ax.set_ylabel("QL p (3회 평균)")
    ax.legend(loc="center left", bbox_to_anchor=(0.0, 0.62), fontsize=8.5, markerscale=1.8, frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    ax.set_title("같은 문서의 Q2 p와 QL p", fontsize=11)
    ax = axes[1]
    order = [s for s in SOURCE_ORDER if (fb.set_index("source").loc[s, ["inj_fixed", "inj_broken", "ben_fixed", "ben_broken"]].sum() > 0)]
    f2 = fb.set_index("source").loc[order]
    yy = np.arange(len(order))[::-1]
    b1 = ax.barh(yy, f2.inj_fixed, color=INJ, height=0.6, label="인젝션")
    b2 = ax.barh(yy, f2.ben_fixed, left=f2.inj_fixed, color=BEN, height=0.6, label="정상")
    b3 = ax.barh(yy, -f2.inj_broken, color=INJ, height=0.6)
    b4 = ax.barh(yy, -f2.ben_broken, left=-f2.inj_broken, color=BEN, height=0.6)
    for bb in (b1, b2, b3, b4):
        PS.bar_gap(bb)
    for yi, s in zip(yy, order):
        r = f2.loc[s]
        fx, bk = r.inj_fixed + r.ben_fixed, r.inj_broken + r.ben_broken
        if fx:
            parts = [f"인젝션 {r.inj_fixed}" if r.inj_fixed else "", f"정상 {r.ben_fixed}" if r.ben_fixed else ""]
            ax.text(fx + 0.6, yi, " · ".join(p for p in parts if p), va="center", fontsize=8, color=PS.INK_2)
        if bk:
            ax.text(-bk - 0.6, yi, f"{bk}", va="center", ha="right", fontsize=8, color=PS.INK_2)
    ax.axvline(0, color=PS.INK_2, lw=0.9)
    ax.set_yticks(yy, [SOURCE_KO.get(s, s) for s in order])
    mx = max((f2.inj_fixed + f2.ben_fixed).max(), (f2.inj_broken + f2.ben_broken).max())
    ax.set_xlim(-mx * 0.6, mx * 1.6)
    xt = [t for t in range(-int(mx * 0.6) // 5 * 5, int(mx * 1.6) + 1, 5)]
    ax.set_xticks(xt, [str(abs(t)) for t in xt])
    ax.set_xlabel("← QL이 틀리게 바꾼 문서 수 | QL이 바로잡은 문서 수 →")
    ax.legend(loc="lower right", fontsize=8.5)
    ax.grid(axis="y", visible=False)
    ax.set_title("출처별로 판정이 바뀐 문서 (0.5 기준)", fontsize=11)
    acc = pr.loc["accuracy"]
    PS.title(fig, f"QL은 {int(acc.mcnemar_QL_only)}건을 바로잡고 {int(acc.mcnemar_Q2_only)}건을 틀리게 바꿨다 (McNemar p = {acc.mcnemar_p:.1e})",
             SUB + f" · 판정이 바뀐 {int(acc.mcnemar_QL_only + acc.mcnemar_Q2_only)}건 중 두 p가 모두 0.4~0.6인 경계 문서 {int(fb.borderline.sum())}건")
    save(fig, "f04_q2_vs_ql_paired")

    # f05 / f06 by source / doc_type
    for name, key, tbl, order, labels, head in (
            ("f05_by_source", "source", R["by_source"], SOURCE_ORDER, SOURCE_KO, "출처"),
            ("f06_by_doc_type", "doc_type", R["by_doc_type"], list(R["by_doc_type"].sort_values("n", ascending=False).doc_type.unique()),
             dict(zip(EN.doc_type, EN.doc_type_ko)), "문서 종류")):
        fig, axes = plt.subplots(1, 2, figsize=(12.5, 6.4))
        grouped_hbar(axes[0], tbl[tbl.n_injection > 0], key, "TPR", order, labels)
        axes[0].set_title("인젝션 탐지율 (TPR)", fontsize=11)
        grouped_hbar(axes[1], tbl[tbl.n_benign > 0], key, "FPR", order, labels, xmax=0.4, fmt_d=1)
        axes[1].set_title("정상 오탐률 (FPR, 축 0~40%)", fontsize=11)
        qlegend(axes[0], loc="lower right")
        tp = tbl[tbl.n_injection > 0]
        lo_src = tp[tp.question == "Q2"].sort_values("TPR").iloc[0]
        PS.title(fig, f"{head}별 탐지율과 오탐률: 가장 낮은 곳은 {labels.get(lo_src[key], lo_src[key])} (Q2 {pct(lo_src.TPR)})",
                 SUB + "\n선 = 95% Wilson 신뢰구간 (▸ = 구간이 축 밖까지 이어짐) · n = 그 집단의 인젝션 / 정상 문서 수")
        save(fig, name)

    # f07 risk level + harm type (injection only); third panel = BIPIA only, because harm type moves with source
    fig, axes = plt.subplots(1, 3, figsize=(18, 7.2), gridspec_kw={"width_ratios": [0.95, 1.2, 1.2]})
    grouped_vbar(axes[0], R["by_risk_level"], "risk_level", "TPR", [1, 2, 3, 4, 5], {k: v.replace(" ", "\n", 1) for k, v in RISK_KO.items()})
    axes[0].set_ylabel("인젝션 탐지율 (TPR)")
    axes[0].set_xlabel("위험도 (data/injection_eval/risk_rubric.md)")
    axes[0].set_title("위험도별", fontsize=11)
    qlegend(axes[0], loc="upper left")
    harm_ko = dict(zip(EN.harm_type, EN.harm_type_ko))
    ht, hb = R["by_harm_type"], R["by_harm_type_bipia"]
    grouped_hbar(axes[1], ht, "harm_type", "TPR", list(ht[ht.question == "Q2"].sort_values("TPR", ascending=False).harm_type), harm_ko)
    axes[1].set_title("피해 유형별 (전체 출처)", fontsize=11)
    grouped_hbar(axes[2], hb, "harm_type", "TPR", list(hb[hb.question == "Q2"].sort_values("TPR", ascending=False).harm_type), harm_ko)
    axes[2].set_title(f"피해 유형별 (BIPIA만, {int(hb[hb.question == 'Q2'].n_injection.sum())}건)", fontsize=11)
    h, hbi = ht.set_index(["harm_type", "question"]), hb.set_index(["harm_type", "question"])
    hx = R["harm_x_source"]
    th_src = hx[hx.harm_type == "task_hijack"].set_index("source").n
    n_bs = int(th_src.get("BIPIA", 0) + th_src.get("SEP", 0))
    PS.title(fig, f"과제 이탈은 두 질문 모두 거의 못 잡는다 ({pct(h.loc[('task_hijack', 'Q2'), 'TPR'])} / {pct(h.loc[('task_hijack', 'QL'), 'TPR'])}). "
                  f"그런데 {int(th_src.sum())}건 중 {n_bs}건이 BIPIA·SEP라 출처 효과와 나눌 수 없다",
             f"EN 인젝션 500건 · {MODEL} · 임계값 0.5 · 3회 평균 p · 선 = 95% Wilson 신뢰구간\n"
             f"BIPIA 안에서는 해로운 유형 중에도 낮은 것이 있다: 시스템 파괴·마비 {pct(hbi.loc[('system_destruction', 'Q2'), 'TPR'])} / "
             f"{pct(hbi.loc[('system_destruction', 'QL'), 'TPR'])}, 감시·악성코드 {pct(hbi.loc[('surveillance_malware', 'Q2'), 'TPR'])} / "
             f"{pct(hbi.loc[('surveillance_malware', 'QL'), 'TPR'])} vs 과제 이탈 {pct(hbi.loc[('task_hijack', 'Q2'), 'TPR'])} / "
             f"{pct(hbi.loc[('task_hijack', 'QL'), 'TPR'])} (Q2 / QL, 표본이 작아 구간이 넓음)")
    save(fig, "f07_by_risk_and_harm")

    # f08 position
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.6), gridspec_kw={"width_ratios": [4, 3]})
    grouped_vbar(axes[0], R["by_position"], "position", "TPR", POS_ORDER, POS_KO)
    axes[0].set_title("전체 인젝션 (지시문 시작 위치를 3등분해 계산)", fontsize=10.5)
    axes[0].set_ylabel("인젝션 탐지율 (TPR)")
    grouped_vbar(axes[1], R["by_position_bipia"], "position_bipia", "TPR", POS_ORDER[:3], POS_KO)
    axes[1].set_title("BIPIA만 (origin.position, 원 벤치마크의 삽입 위치)", fontsize=10.5)
    qlegend(axes[1], loc="upper left")
    bp = R["by_position_bipia"].set_index(["position_bipia", "question"])
    PS.title(fig, f"위치 차이는 전체로는 작다. BIPIA 앞 삽입만 Q2에서 {pct(bp.loc[('start', 'Q2'), 'TPR'])}로 낮고 "
                  f"QL에서 {pct(bp.loc[('start', 'QL'), 'TPR'])}로 오른다",
             f"EN 인젝션 500건 · BIPIA 151건 · {MODEL} · 임계값 0.5 · 선 = 95% Wilson 신뢰구간 · '알 수 없음' = 인코딩·분할 공격이라 위치 계산 불가")
    save(fig, "f08_by_position")

    # f09 prompt length (rows: TPR / FPR; cols: 2 buckets / quartiles)
    fig, axes = plt.subplots(2, 2, figsize=(12, 8), gridspec_kw={"width_ratios": [2, 3]})
    for j, (tbl, key, order) in enumerate(((R["by_len_bucket"], "len_bucket", LEN_BUCKETS), (R["by_len_quartile"], "len_quartile", LEN_QUARTS))):
        grouped_vbar(axes[0, j], tbl, key, "TPR", order, {})
        grouped_vbar(axes[1, j], tbl, key, "FPR", order, {}, ymax=0.12, fmt_d=1, ticks=[0, 0.03, 0.06, 0.09, 0.12])
    axes[0, 0].set_ylabel("인젝션 탐지율 (TPR)")
    axes[1, 0].set_ylabel("정상 오탐률 (FPR, 축 0~12%)")
    axes[0, 0].set_title("중앙값 기준 2구간", fontsize=11)
    axes[0, 1].set_title("사분위 4구간", fontsize=11)
    qlegend(axes[1, 0], loc="upper left")
    lq = R["by_len_quartile"].set_index(["len_quartile", "question"])
    PS.title(fig, f"가장 긴 구간(>1254자)에서 Q2 오탐이 {pct(lq.loc[('>1254자', 'Q2'), 'FPR'], 1)}로 늘고 AUC가 "
                  f"{lq.loc[('>1254자', 'Q2'), 'AUC']:.3f}로 내려간다 (QL {pct(lq.loc[('>1254자', 'QL'), 'FPR'], 1)}, {lq.loc[('>1254자', 'QL'), 'AUC']:.3f})",
             SUB + "\n구간 경계는 결과를 보기 전에 글자 수로 고정 · 긴 구간에는 BrowseSafe HTML이 몰려 있어 출처 효과와 섞여 있음 · 선 = 95% Wilson 신뢰구간")
    save(fig, "f09_by_prompt_length")

    # f10 threshold sweep
    sw, th = R["sweep"], R["thresholds"]
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2))
    for q in QIDS:
        s = sw[sw.question == q]
        axes[0].plot(s.threshold, s.TPR, color=Q_COLORS[q], lw=2, label=Q_NAMES[q])
        axes[1].plot(s.threshold, s.FPR, color=Q_COLORS[q], lw=2, label=Q_NAMES[q])
        t5 = th[(th.question == q) & (th.target_FPR == 0.05)].iloc[0]
        axes[0].scatter([t5.threshold], [t5.TPR], color=Q_COLORS[q], s=45, zorder=5, edgecolor=PS.SURFACE, linewidth=1.5)
        axes[0].annotate(f"{q} 오탐 5% 이하 임계값 {t5.threshold:.3f}\nTPR {pct(t5.TPR, 1)}, FPR {pct(t5.FPR, 1)}", (t5.threshold, t5.TPR),
                         xytext=(0.03, 0.40) if q == "QL" else (0.53, 0.30), va="top", fontsize=8.5, color=PS.INK_2,
                         arrowprops=dict(arrowstyle="-", color=PS.MUTED, lw=0.7, relpos=(0.3, 1) if q == "QL" else (0, 1)))
    for ax in axes:
        ax.axvline(0.5, color=PS.INK_2, lw=0.9, ls="--")
        ax.set_xlabel("임계값")
        ax.set_xlim(0, 1)
    axes[0].text(0.51, 0.03, "기준 0.5", fontsize=8.5, color=PS.INK_2, va="bottom")
    axes[0].set_ylim(0, 1.02)
    axes[0].set_yticks(np.linspace(0, 1, 5), [pct(t) for t in np.linspace(0, 1, 5)])
    axes[0].set_title("인젝션 탐지율 (TPR)", fontsize=11)
    axes[1].set_ylim(0, 0.3)
    axes[1].set_yticks(np.linspace(0, 0.3, 4), [pct(t) for t in np.linspace(0, 0.3, 4)])
    axes[1].set_title("정상 오탐률 (FPR, 축 0~30%)", fontsize=11)
    axes[1].legend(loc="upper right")
    t5q2 = th[(th.question == "Q2") & (th.target_FPR == 0.05)].iloc[0]
    t5ql = th[(th.question == "QL") & (th.target_FPR == 0.05)].iloc[0]
    PS.title(fig, f"임계값을 낮추면 오탐 5%에서 TPR이 Q2 {pct(t5q2.TPR)}, QL {pct(t5ql.TPR)}까지 오른다",
             SUB + " · 오탐 5% 지점은 같은 데이터에서 맞춘 값이라 낙관적 (다른 실험에서는 고정해서 써야 함)")
    save(fig, "f10_threshold_sweep")

    # f11 calibration (one panel per question)
    cal, cs = R["calibration"], R["calsum"].set_index("question")
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.8), sharey=True)
    for ax, q in zip(axes, QIDS):
        c = cal[(cal.question == q) & (cal.n > 0)]
        ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=1)
        ax.errorbar(c.mean_p, c.injection_rate, yerr=_err(c.injection_rate, c.injection_rate_lo, c.injection_rate_hi), fmt="-o",
                    color=Q_COLORS[q], ms=6, elinewidth=1, capsize=2)
        for _, r in c.iterrows():
            below = r.injection_rate_lo - 0.02
            ax.text(max(r.mean_p, 0.045), below if below > 0.1 else r.injection_rate_hi + 0.06, f"n={int(r.n)}", ha="center",
                    va="top", fontsize=7.5, color=PS.INK_2)
        ax.set_xlim(0, 1)
        ax.set_ylim(-0.02, 1.05)
        ax.set_xlabel("Jev p (구간 평균)")
        ax.set_title(f"{Q_NAMES[q]} · p 0.1~0.5 구간 {int(cs.loc[q, 'n_p_0.1_to_0.5'])}건 중 인젝션 {pct(cs.loc[q, 'injection_rate_p_0.1_to_0.5'])}",
                     fontsize=10)
        ax.text(0.98, 0.04, f"Brier {cs.loc[q, 'brier']:.3f} · ECE {cs.loc[q, 'ece_10bins']:.3f}", transform=ax.transAxes, ha="right",
                fontsize=8.5, color=PS.INK_2)
    axes[0].set_ylabel("그 구간의 실제 인젝션 비율")
    axes[0].text(0.62, 0.55, "대각선 = p와 실제 비율이 같음", fontsize=8.5, color=PS.MUTED, rotation=0)
    PS.title(fig, "p는 실제 인젝션 비율보다 낮게 나온다: 0.1~0.5 구간 문서 대부분이 인젝션",
             SUB + " · 0.1 폭 10구간 · 선 = 95% Wilson 신뢰구간 · 이 데이터의 인젝션 비율은 50%라 다른 비율에서는 값이 달라짐")
    save(fig, "f11_calibration")

    # f12 run-to-run stability
    st, prun = R["stability"].set_index("question"), R["per_run"]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.4), sharey=True)
    for ax, q in zip(axes, QIDS):
        for li, c, lab in ((0, BEN, "정상"), (1, INJ, "인젝션")):
            s = EN[EN.label_int == li]
            ax.scatter(s[f"p_{q}"], s[f"p_range_{q}"], s=12, color=c, alpha=0.6, edgecolor="none", label=lab)
        fl = EN[EN[f"flip_{q}"]]
        ax.scatter(fl[f"p_{q}"], fl[f"p_range_{q}"], s=55, facecolor="none", edgecolor=PS.INK, linewidth=0.9, label="회차마다 0.5 판정이 갈린 문서")
        ax.axvline(0.5, color=PS.INK_2, lw=0.9, ls="--")
        ax.set_xlim(0, 1)
        ax.set_xlabel("3회 평균 p")
        r = prun[prun.question == q]
        ax.set_title(f"{Q_NAMES[q]} · 갈린 문서 {int(st.loc[q, 'docs_with_flip'])}건 · 회차별 TPR "
                     + "/".join(pct(v, 1) for v in r.TPR), fontsize=9.5)
    axes[0].set_ylabel("3회 호출 사이 p의 최대 차이")
    axes[0].legend(loc="upper left", fontsize=8.5, markerscale=1.5, frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    nf = R["noise"]
    within = nf[nf.kind.str.startswith("같은 질문")].discordant_docs.mean()
    PS.title(fig, f"같은 문서를 다시 물어도 대부분 같은 답, 0.5 근처 문서만 판정이 흔들린다",
             SUB + f" · API에 seed 옵션 없음 · 호출 1번끼리 비교 시 같은 질문 회차 사이 평균 {within:.1f}건, Q2·QL 사이 "
             f"{nf[nf.kind == '질문 차이 (호출 1번씩)'].discordant_docs.mean():.1f}건의 판정이 다름")
    save(fig, "f12_run_stability")

    # f13 latency and tokens
    lt, ex = R["latency"].set_index("question"), R["lat_extra"]
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.2))
    for q in QIDS:
        v = np.sort(R["raws"][q]["latency_ms"].astype(float).to_numpy())
        axes[0].plot(v, np.arange(1, len(v) + 1) / len(v), color=Q_COLORS[q], lw=2, label=f"{Q_NAMES[q]} (호출 {len(v):,}회)")
        med = lt.loc[q, "latency_ms_median"]
        axes[0].scatter([med], [0.5], color=Q_COLORS[q], s=40, zorder=5, edgecolor=PS.SURFACE, linewidth=1.5)
        axes[0].text(med + 30, 0.47, f"중앙값 {med:.0f}ms", fontsize=8.5, color=PS.INK_2, va="top")
        axes[1].scatter(EN.char_len, EN[f"input_tokens_{q}"], s=8, color=Q_COLORS[q], alpha=0.5, edgecolor="none", label=Q_NAMES[q])
    hi = np.percentile(np.concatenate([R["raws"][q]["latency_ms"].astype(float) for q in QIDS]), 99.5)
    axes[0].set_xlim(500, hi)
    axes[0].set_ylim(0, 1.01)
    axes[0].set_xlabel("요청 1건 응답 시간 (ms, 한국 노트북 → 공식 API, 동시 6개)")
    axes[0].set_ylabel("누적 비율")
    axes[0].legend(loc="lower right", fontsize=8.5)
    axes[0].set_title("응답 시간 누적 분포 (상위 0.5% 잘라 표시)", fontsize=10.5)
    axes[1].set_xlabel("문서 글자 수")
    axes[1].set_ylabel("요청 1건 입력 토큰")
    axes[1].legend(loc="upper left", fontsize=8.5, markerscale=2)
    axes[1].set_title(f"입력 토큰: QL은 문서마다 정확히 +{ex['ql_extra_tokens_mean']:.0f}토큰 (질문 길이)", fontsize=10.5)
    PS.title(fig, f"1건당 중앙값 Q2 {lt.loc['Q2', 'latency_ms_median']:.0f}ms, QL {lt.loc['QL', 'latency_ms_median']:.0f}ms · "
                  f"입력 비용 1,000건당 \\${lt.loc['Q2', 'input_cost_usd_per_1000_docs_1_call']:.3f} / \\${lt.loc['QL', 'input_cost_usd_per_1000_docs_1_call']:.3f}",
             f"요청 3,075건씩 · 두 질문은 다른 시간대에 실행(Q2 {lt.loc['Q2', 'first_call_utc'][11:16]}, QL {lt.loc['QL', 'first_call_utc'][11:16]} UTC)이라 "
             f"응답 시간 차이에는 서버 상태가 섞여 있음 · 출력 요금은 공개되지 않아 입력만 계산 ($0.042 / 100만 토큰)")
    save(fig, "f13_latency_tokens")

    # f14 NotInject
    nt = R["notinject"].set_index("question")
    s = NI.sort_values("p_Q2").reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 7))
    yy = np.arange(len(s))
    for i, r in s.iterrows():
        ax.plot([r.p_Q2, r.p_QL], [i, i], color=PS.GRID, lw=1.5, zorder=1)
    for q in QIDS:
        ax.scatter(s[f"p_{q}"], yy, color=Q_COLORS[q], s=38, edgecolor=PS.SURFACE, linewidth=1.2, zorder=3,
                   label=f"{q} · 오탐 {int(nt.loc[q, 'fp'])}/25 (95% CI 0–{pct(nt.loc[q, 'FPR_hi'])}) · 평균 p {nt.loc[q, 'mean_p']:.3f}")
    ax.axvline(0.5, color=PS.INK_2, lw=0.9, ls="--")
    ax.text(0.505, len(s) - 0.5, "임계값 0.5", fontsize=8.5, color=PS.INK_2)
    ax.set_yticks(yy, [f"{u}  {short(t, 46)}" for u, t in zip(s.uid, s.text)], fontsize=7)
    ax.set_xlim(0, 1)
    ax.set_xlabel("p (3회 평균)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="center right", fontsize=8.5)
    PS.title(fig, "과탐지 참고 세트(NotInject 25건): 두 질문 모두 오탐 0건",
             "트리거 단어가 든 정상 사용자 요청 · 본 평가(EN)에서 제외한 참고용 · PIGuard(ACL 2025) 보고: 기존 가드 정확도 약 60%")
    save(fig, "f14_notinject")
    return out


# ------------------------------------------------------------------ main
def main():
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    EN, NI, raws = load()
    boot = paired_bootstrap(EN)
    overall, paired, thresholds, notinject, len_auc, point = overall_tables(EN, NI, boot)
    sweep, cal, calsum = sweep_and_calibration(EN)
    per_run, stab, noise = stability(EN)
    lat, lat_extra = latency_tokens(EN, NI, raws)
    fixed_broken, fb_src = fixes_and_breaks(EN)
    errs, fn_pat, fn_near = errors(EN)

    inj = EN[EN.label_int == 1]
    groups = {
        "by_source": (EN, "source", SOURCE_ORDER, SOURCE_KO),
        "by_doc_type": (EN, "doc_type", list(EN.doc_type.value_counts().index), dict(zip(EN.doc_type, EN.doc_type_ko))),
        "by_risk_level": (inj, "risk_level", [1, 2, 3, 4, 5], RISK_KO),
        "by_harm_type": (inj, "harm_type", list(inj.harm_type.value_counts().index), dict(zip(EN.harm_type, EN.harm_type_ko))),
        "by_harm_type_bipia": (inj[inj.source == "BIPIA"], "harm_type", list(inj[inj.source == "BIPIA"].harm_type.value_counts().index),
                               dict(zip(EN.harm_type, EN.harm_type_ko))),
        "by_position": (inj, "position", POS_ORDER, POS_KO),
        "by_position_bipia": (inj[inj.source == "BIPIA"], "position_bipia", POS_ORDER[:3], POS_KO),
        "by_len_bucket": (EN, "len_bucket", LEN_BUCKETS, {}),
        "by_len_quartile": (EN, "len_quartile", LEN_QUARTS, {}),
        "by_len_quartile_excl_browsesafe": (EN[EN.source != "BrowseSafe-Bench"], "len_quartile", LEN_QUARTS, {}),
    }
    R = {"overall": overall, "paired": paired, "thresholds": thresholds, "notinject": notinject, "len_auc": len_auc,
         "sweep": sweep, "calibration": cal, "calsum": calsum, "per_run": per_run, "stability": stab, "noise": noise,
         "latency": lat, "lat_extra": lat_extra, "fixed_broken_by_source": fb_src, "raws": raws}
    paired_tabs = {}
    for name, (df, col, keys, lab) in groups.items():
        R[name] = save_table(by_group(df, col, keys, lab), name)
        paired_tabs[name] = save_table(paired_by_group(df, col, keys, lab), f"{name}_paired")
    # position x source (counts and TPR; position is confounded with source)
    pxs = []
    for (s, pos), g in inj.groupby(["source", "position"]):
        pxs.append({"source": s, "position": pos, "n": len(g), "TPR_Q2": g.pred_Q2.mean(), "TPR_QL": g.pred_QL.mean()})
    save_table(pd.DataFrame(pxs), "by_position_x_source")
    # harm type x source (harm type is almost fully tied to source)
    hxs = []
    for (h, s), g in inj.groupby(["harm_type", "source"]):
        k2, kl = int(g.pred_Q2.sum()), int(g.pred_QL.sum())
        hxs.append({"harm_type": h, "harm_type_ko": g.harm_type_ko.iloc[0], "source": s, "n": len(g),
                    "share_of_harm_type": len(g) / int((inj.harm_type == h).sum()),
                    "tp_Q2": k2, "TPR_Q2": k2 / len(g), "TPR_Q2_lo": J.wilson(k2, len(g))[0], "TPR_Q2_hi": J.wilson(k2, len(g))[1],
                    "tp_QL": kl, "TPR_QL": kl / len(g), "TPR_QL_lo": J.wilson(kl, len(g))[0], "TPR_QL_hi": J.wilson(kl, len(g))[1]})
    R["harm_x_source"] = save_table(pd.DataFrame(hxs), "by_harm_type_x_source")
    lxs = EN.groupby(["len_quartile", "source", "label"]).size().unstack(fill_value=0).reset_index()
    save_table(lxs, "len_quartile_x_source_counts")

    figs = figures(EN, NI, R)

    # ---------------- summary.json "analysis" (all other keys are kept as they are)
    sp = os.path.join(OUT, "summary.json")
    with open(sp, encoding="utf-8") as f:
        summary = json.load(f)
    ovq = overall.set_index("question")
    prm = paired.set_index("metric")

    def src_compact(t):
        return {r.source: {"n_inj": r.n_inj, "n_ben": r.n_ben,
                           "TPR_Q2": r.get("TPR_Q2"), "TPR_QL": r.get("TPR_QL"), "dTPR_ci95": [r.get("dTPR_lo"), r.get("dTPR_hi")],
                           "FPR_Q2": r.get("FPR_Q2"), "FPR_QL": r.get("FPR_QL"), "dFPR_ci95": [r.get("dFPR_lo"), r.get("dFPR_hi")]}
                for _, r in t.iterrows()}

    analysis = {
        "script": "experiments/analyze_01_baseline.py",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis_commit": J.git_commit(),
        "main_set": "set == EN (1000: 500 injection / 500 benign); NotInject 25 = over-defence reference (FPR only)",
        "data": {"en_file": "data/injection_eval/en/dataset_en_1000.jsonl", "en_md5": md5_file(EN_DATA),
                 "notinject_file": "data/injection_eval/en/overdefense_ref_notinject.jsonl", "notinject_md5": md5_file(NI_DATA),
                 "text_md5_check": "every raw call's text_md5 equals md5(dataset text) for its uid (asserted)",
                 "predictions_check": "p_run0..2 equal the raw calls and p is their mean (asserted)"},
        "methods": {"metrics": "src.jev_guard.metrics(threshold=0.5)", "proportion_ci": "Wilson 95% (jevlab.wilson)",
                    "paired_test": "exact McNemar (two-sided binomial on discordant pairs)",
                    "paired_bootstrap": {"resamples": B, "seed": SEED, "scheme": "stratified by label, same indices for Q2 and QL, percentile 95%"},
                    "group_bootstrap": "paired, within group and label, 1000 resamples, seed 20261112; McNemar p also Holm-adjusted within each table (exploratory)",
                    "group_verdict": ("'QL 높음/낮음' only if the bootstrap CI excludes 0 AND Holm-adjusted McNemar p < 0.05; "
                                      "CI excludes 0 but Holm p >= 0.05 -> '탐색적 (Holm p = ...)'; CI covers 0 -> '차이 없음 (오차 범위)'; "
                                      f"groups with n < {SMALL_N} get '표본 작음'"),
                    "score_grid": (f"p (mean of {J.REPEATS} two-decimal runs) is snapped to the exact 1/{GRID} grid before every comparison; "
                                   "stored means carry ~2e-16 float noise that split equal scores. AUC on snapped p differs from the "
                                   "top-level run_api AUC only in the 6th decimal (tied scores now count as ties)"),
                    "position": "start of injected_instruction / (len(text) - len(instruction)), thirds; null or not found -> unknown",
                    "length_buckets": {"two": "<=621 / >621 chars", "quartiles": "<=333 / 334-623 / 624-1254 / >1254 chars",
                                       "fixed_before_results": True},
                    "thresholds_at_fpr": ("fitted on the same EN data (optimistic); report only. Rule p >= threshold. Lowest grid threshold "
                                          "with benign FPR <= target; the reported value is the midpoint between the highest benign p "
                                          "that passes and the next grid value, so the 3-decimal value gives the same decisions. "
                                          "Bootstrap refits the threshold in every resample.")},
        "overall": {q: {k: ovq.loc[q, k] for k in ("n", "n_injection", "n_benign", "tp", "fn", "fp", "tn", "TPR", "TPR_lo", "TPR_hi",
                                                     "FPR", "FPR_lo", "FPR_hi", "AUC", "AUC_lo", "AUC_hi", "mean_p_injection",
                                                     "mean_p_benign", "accuracy")} for q in QIDS},
        "length_only_AUC": len_auc,
        "q2_vs_ql": {k: {"Q2": prm.loc[k, "Q2"], "QL": prm.loc[k, "QL"], "delta": prm.loc[k, "delta_QL_minus_Q2"],
                         "delta_ci95": [prm.loc[k, "delta_lo"], prm.loc[k, "delta_hi"]], "verdict": prm.loc[k, "verdict"],
                         **({"mcnemar_Q2_only": int(prm.loc[k, "mcnemar_Q2_only"]), "mcnemar_QL_only": int(prm.loc[k, "mcnemar_QL_only"]),
                             "mcnemar_p": prm.loc[k, "mcnemar_p"]} if prm.loc[k, "mcnemar_p"] == prm.loc[k, "mcnemar_p"] else {})}
                     for k in prm.index},
        "fixed_broken": {"QL_fixes": int((fixed_broken.direction == "QL이 고침").sum()),
                         "QL_breaks": int((fixed_broken.direction == "QL이 망침").sum()),
                         "by_change": fixed_broken.change.value_counts().to_dict(),
                         "borderline_both_p_0.4_0.6": int(fixed_broken.borderline.sum()),
                         "by_source": fb_src.set_index("source")[["inj_fixed", "inj_broken", "ben_fixed", "ben_broken"]].to_dict("index")},
        "noise_floor_discordance": noise.set_index("comparison")["discordant_docs"].to_dict(),
        "thresholds_at_fpr": {q: thresholds[thresholds.question == q].set_index("target")[
            ["threshold", "rule", "highest_passed_benign_p", "lowest_flagged_p", "tp", "fp", "TPR", "FPR", "TPR_boot_lo", "TPR_boot_hi"]].to_dict("index")
                              for q in QIDS},
        "harm_type_x_source": {
            "task_hijack_by_source": R["harm_x_source"][R["harm_x_source"].harm_type == "task_hijack"].set_index("source")[
                ["n", "TPR_Q2", "TPR_QL"]].to_dict("index"),
            "bipia_only": paired_tabs["by_harm_type_bipia"].set_index("harm_type")[["n_inj", "TPR_Q2", "TPR_QL"]].to_dict("index"),
            "note": "harm type is almost fully tied to source; read as description, not as cause"},
        "subgroup_verdicts": {name: {str(r.group): {"dTPR": r.get("dTPR_verdict"), "dFPR": r.get("dFPR_verdict")} for _, r in t.iterrows()}
                              for name, t in paired_tabs.items()},
        "calibration": calsum.set_index("question").to_dict("index"),
        "stability": stab.set_index("question").to_dict("index"),
        "per_run": {q: per_run[per_run.question == q][["run", "TPR", "FPR", "AUC"]].to_dict("records") for q in QIDS},
        "latency_tokens_cost": {**lat.set_index("question").to_dict("index"), "QL_vs_Q2": lat_extra,
                                "price_note": "input $0.042 per 1M tokens; output price not published (tokens counted only)"},
        "notinject": notinject.set_index("question").to_dict("index"),
        "by_source": src_compact(paired_tabs["by_source"]),
        "fn_how_close": fn_near.set_index("question").to_dict("index"),
        "tables": sorted(os.listdir(TAB)),
        "figures": sorted(os.path.basename(p) for p in figs),
    }
    summary["analysis"] = clean(analysis)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    # ---------------- console digest (numbers quoted in README come from here and the tables)
    for q in QIDS:
        o = ovq.loc[q]
        print(f"{q}: TPR {o.TPR:.3f} [{o.TPR_lo:.3f},{o.TPR_hi:.3f}] FPR {o.FPR:.3f} [{o.FPR_lo:.3f},{o.FPR_hi:.3f}] "
              f"AUC {o.AUC:.3f} [{o.AUC_lo:.3f},{o.AUC_hi:.3f}]")
    print(paired[["metric", "Q2", "QL", "delta_QL_minus_Q2", "delta_lo", "delta_hi", "verdict", "mcnemar_Q2_only", "mcnemar_QL_only", "mcnemar_p"]].to_string())
    print(thresholds[["question", "target", "threshold", "tp", "fp", "TPR", "FPR", "TPR_boot_lo", "TPR_boot_hi"]].round(4).to_string())
    print("length-only AUC", round(len_auc, 3))
    print(f"wrote {len(os.listdir(TAB))} tables, {len(figs)} figures, summary.json['analysis']")


if __name__ == "__main__":
    main()
