"""④ 길이 (04_length) 분석: 저장된 예측표·raw 호출 -> 표, 그림, summary.json의 "analysis" 키. API를 부르지 않는다.

    python experiments/analyze_04_length.py

입력 (읽기만 함)
  results/04_length/inputs/length_docs.jsonl     판정한 문서 920개 (본문 md5 확인, 삽입 위치·carrier 정보)
  results/04_length/inputs/spans.csv, CARRIERS.md span 40개, stream별 위키 문서 길이 (삽입 지점이 몇 번째 문서인지 계산)
  results/04_length/{Q2,QL}_predictions.csv     문서별 3회 평균 p (experiments/run_04_length.py가 만든 것)
  results/04_length/raw/{Q2,QL}_raw.jsonl        호출별 p, 응답 시간, usage.input_tokens
  비교용 (읽기만): results/01_baseline/{Q2,QL}_predictions.csv, tables/thresholds_at_fpr.csv,
                  results/X3_distractor/{Q2,QL}_predictions.csv, data/injection_eval/en/dataset_en_1000.jsonl
출력
  results/04_length/tables/t*.csv, results/04_length/figures/f*.png,
  results/04_length/summary.json 의 "analysis" 키 (다른 키는 그대로 둠). tables/first_look_*.csv와 tokens_by_length.csv는
  run_04_length.py가 만든 것이라 건드리지 않는다.

설계 (build_04_length.py)
  span 40개 × {단독, 2k/4k/8k/16k/32k자 × 앞·중간·끝, 64k자 중간} = 인젝션 680, 깨끗한 carrier 40 × 6길이 = 정상 240.
  span i는 stream i(carrier Ci)와 짝이라, 모든 비교를 span(= stream) 40개 단위의 짝 비교로 한다.

규칙
  - 판정·지표: src.jev_guard.metrics() (임계값 0.5). p는 소수 둘째 자리 값 3개의 평균이라 1/300 격자로 맞춘 뒤 비교한다.
  - 비율의 95% 구간: Wilson. 0.5 판정의 짝 차이: exact McNemar (불일치 쌍의 양측 이항검정).
  - 차이의 95% 구간: span 단위 짝 부트스트랩 1,000회 (seed 20261112, 백분위). 모든 비교가 같은 재표집 인덱스를 쓴다.
    구간이 0을 포함하면 "차이 없음 (오차 범위)". 평균 p 차이의 검정은 Wilcoxon 부호순위.
  - 비교가 여러 개인 표(2k 대비 13개, 단독 대비 16개, 위치 15개, 정상 5개, 출처별)는 질문마다 Holm 보정하고,
    방향은 "구간이 0을 빼고 Holm p < 0.05"일 때만 적는다. 구간만 0을 빼면 "탐색적 (Holm p = …)".
  - 추세: 탐지(0/1)를 log2(글자 수 / 2,000)에 로지스틱 회귀 (span 무작위효과 대신 span 단위 cluster bootstrap 1,000회로
    구간). 위치별, 위치 고정효과로 합친 모형, 위치 × 길이 상호작용 모형. 평균 p는 (span, 위치) 안에서 뺀 기울기
    (span·위치 고정효과; 64k가 중간에만 있는 합친 모형에서 중간 위치의 높은 p가 길이 기울기로 새지 않게. 점추정과
    cluster bootstrap 모두 같은 블록). 같은 모형을 x = log2(Jev usage.input_tokens)로도 맞춘다. 검정은 (span, 위치) 안에서
    길이 라벨을 섞는 순열검정 (10,000회, span으로 층화한 로지스틱의 score 검정과 같음)이고 질문·x마다 모형 6개를 Holm
    보정한다 (참고로 두 질문 12개를 함께 Holm 보정한 값도 *_holm_both_q 열에 둔다). 바뀐 span이 모두 한 방향이면
    cluster bootstrap 백분위 구간은 0을 덮지 못하므로, 방향은 "구간이 0을 빼고 Holm 순열 p < 0.05"일 때만 적는다.
  - 중간 위치의 같은 문서 / 다른 문서 비교(t13)는 부분집합 평균을 같은 재표집 인덱스로 구한 구간(span 수가 재표집마다
    달라지는 domain bootstrap)과 Wilcoxon·Holm(질문마다 부분집합 비교 전체)으로 적는다. 32k 중간 → 64k 중간 짝 비교를
    32k와 64k에서 같은 위키 문서 안에 든 span / 아닌 span으로 나눈 것은 문서 변경을 일부 통제한 탐색 비교다.
  - AUC: 그 길이의 인젝션(위치 전부 또는 위치별) vs 같은 길이의 깨끗한 carrier 40개. 구간은 stream 단위 부트스트랩.
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
from scipy.stats import spearmanr, wilcoxon

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402
import plot_style as PS  # noqa: E402
from src.jev_guard import MODEL, THRESHOLD, metrics  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402  (plot_style selected the Agg backend)
from matplotlib.lines import Line2D  # noqa: E402

EXP = "04_length"
OUT = os.path.join(J.RESULTS, EXP)
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
DOCS = os.path.join(OUT, "inputs", "length_docs.jsonl")
SPANS = os.path.join(OUT, "inputs", "spans.csv")
CARRIERS_MD = os.path.join(OUT, "inputs", "CARRIERS.md")
BASE = os.path.join(J.RESULTS, "01_baseline")
X3 = os.path.join(J.RESULTS, "X3_distractor")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")

QIDS = ("Q2", "QL")
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}
Q_NAMES = {"Q2": "Q2 짧은 질문", "QL": "QL 정의형 긴 질문"}
INJ, BEN = PS.LABEL_COLORS["인젝션"], PS.LABEL_COLORS["정상"]
LENS = (2000, 4000, 8000, 16000, 32000, 64000)
LK = {0: "단독", 2000: "2k", 4000: "4k", 8000: "8k", 16000: "16k", 32000: "32k", 64000: "64k"}
POS = ("start", "middle", "end")
POS_KO = {"alone": "단독", "start": "앞", "middle": "중간", "end": "끝"}
POS_STYLE = {"start": dict(ls=":", marker="^"), "middle": dict(ls="-", marker="o"), "end": dict(ls="--", marker="s")}
SOURCES = ("AgentDojo", "BrowseSafe-Bench", "InjecAgent", "LLMail-Inject", "BIPIA", "SEP")
SEED, B = 20261112, 1000
GRID = 300
N_SPANS = 40
PRICE_IN = 0.042 / 1e6
ALONE_X = 1000          # where the span-alone point sits on the log length axis (not a length)


# ------------------------------------------------------------------ helpers
def md5_text(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def md5_file(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def snap(p, grid=GRID):
    p = np.asarray(p, dtype=float)
    k = np.rint(p * grid)
    assert np.abs(k / grid - p).max() < 1e-9, "scores are not on the expected grid"
    return k / grid


def mcnemar_exact(b, c):
    b, c = int(b), int(c)
    n = b + c
    if n == 0:
        return 1.0
    return float(min(1.0, 2 * sum(math.comb(n, i) for i in range(min(b, c) + 1)) / 2 ** n))


def holm(pvals):
    p = np.asarray(pvals, dtype=float)
    out = np.full(len(p), np.nan)
    ok = np.where(~np.isnan(p))[0]
    m, run = len(ok), 0.0
    for rank, i in enumerate(ok[np.argsort(p[ok], kind="stable")]):
        run = max(run, min(1.0, (m - rank) * p[i]))
        out[i] = run
    return out


def ci(v):
    v = np.asarray(v, dtype=float)
    v = v[~np.isnan(v)]
    return [float(np.percentile(v, 2.5)), float(np.percentile(v, 97.5))] if len(v) else [None, None]


def boot_p(v):
    """Two-sided bootstrap p for 'centre = 0' (share of resamples on the other side, doubled). Coarse; used with CIs."""
    v = np.asarray(v, dtype=float)
    return float(min(1.0, 2 * min((v <= 0).mean(), (v >= 0).mean())))


def wilcox_p(d):
    d = np.asarray(d, dtype=float)
    if np.allclose(d, 0):
        return 1.0
    try:
        return float(wilcoxon(d, zero_method="wilcox").pvalue)
    except ValueError:
        return 1.0


def verdict(lo, hi, higher="높음", lower="낮음"):
    if lo is None or hi is None:
        return "–"
    if lo > 0:
        return higher
    if hi < 0:
        return lower
    return "차이 없음 (오차 범위)"


def group_verdict(lo, hi, p_holm, higher="높음", lower="낮음", n=None, small=30):
    if lo is None or hi is None or lo != lo or hi != hi:
        return "–"
    tag = f" · 표본 작음 (n={int(n)})" if n is not None and n < small else ""
    if lo <= 0 <= hi:
        return "차이 없음 (오차 범위)" + tag
    if p_holm == p_holm and p_holm < 0.05:
        return (higher if lo > 0 else lower) + tag
    return f"탐색적 (Holm p = {p_holm:.2f})" + tag


def auc_mw(pos, neg):
    """AUC as P(pos > neg) + 0.5 P(tie) (Mann-Whitney); identical to roc_auc_score."""
    pos, neg = np.asarray(pos, float), np.asarray(neg, float)
    gt = (pos[:, None] > neg[None, :]).mean()
    eq = (pos[:, None] == neg[None, :]).mean()
    return float(gt + 0.5 * eq)


def short(s, n=90):
    if not isinstance(s, str):
        return None
    s = re.sub(r"\s+", " ", s).strip()
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


def save_table(df, name):
    df.to_csv(os.path.join(TAB, f"{name}.csv"), index=False, encoding="utf-8-sig")
    return df


def pct(x, d=1):
    return "–" if x is None or x != x else f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return "–" if x is None or x != x else f"{100 * x:+.{d}f}%p"


def cond_key(t, pos):
    return "alone" if pos == "alone" else f"{LK[t]}-{pos}"


# ------------------------------------------------------------------ load and check
def article_starts():
    """Per carrier id: start offsets of its Wikipedia articles in the stream (articles joined with a blank line)."""
    starts, cur = {}, None
    for line in open(CARRIERS_MD, encoding="utf-8"):
        m = re.match(r"## (C\d\d) ", line)
        if m:
            cur = m.group(1)
            starts[cur] = []
            continue
        m = re.match(r"\| (\d+) \| .* \| ([\d,]+) \| [^|]+ \|\s*$", line)
        if cur and m:
            starts[cur].append(int(m.group(2).replace(",", "")))
    out = {}
    for c, chars in starts.items():
        s, pos = [], 0
        for k in chars:
            s.append(pos)
            pos += k + 2
        out[c] = np.array(s)
    return out


def load():
    docs = J.load_jsonl(DOCS)
    summary = json.load(open(os.path.join(OUT, "summary.json"), encoding="utf-8"))
    assert md5_file(DOCS) == summary["inputs"]["md5"], "length_docs.jsonl differs from the judged file"
    text = {d["uid"]: d["text"] for d in docs}
    meta = pd.DataFrame([{k: v for k, v in d.items() if k not in ("text", "carrier_urls")} for d in docs])
    preds, raws = {}, {}
    for q in QIDS:
        d = pd.read_csv(os.path.join(OUT, f"{q}_predictions.csv"))
        raw = pd.DataFrame([r for r in J.load_jsonl(J.raw_path(EXP, q)) if r.get("http_status") == 200 and "noul" in r])
        bad = [u for u, h in zip(raw.uid, raw.text_md5) if md5_text(text[u]) != h]
        assert not bad, f"{q}: raw text_md5 differs from the input text for {len(set(bad))} uids"
        raw = raw.sort_values("started_at").drop_duplicates(["uid", "run", "text_md5"], keep="first")
        piv = raw.pivot(index="uid", columns="run", values="noul")
        chk = d.set_index("uid")
        for r in range(J.REPEATS):
            assert np.allclose(chk[f"p_run{r}"], piv.loc[chk.index, r]), f"{q}: p_run{r} differs from raw"
        assert np.allclose(chk.p, piv.loc[chk.index].mean(axis=1)), f"{q}: p is not the mean of the raw runs"
        assert (d.n_runs == J.REPEATS).all() and len(d) == len(docs) and (raw.model == MODEL).all()
        d["p"] = snap(d.p)
        assert (d.pred == (d.p >= THRESHOLD).astype(int)).all(), "snapping changed a 0.5 decision"
        tok = raw.groupby("uid").usage_input_tokens.agg(["mean", "min", "max"])
        assert (tok["min"] == tok["max"]).all(), "token counts differ between runs of the same text"
        preds[q], raws[q] = d.set_index("uid"), raw
    W = meta.copy()
    W["position"] = W.position.fillna("benign")
    for q in QIDS:
        d = preds[q]
        for c in ("p", "pred", "p_sd", "flip", "input_tokens", "latency_s", "p_run0", "p_run1", "p_run2"):
            W[f"{c}_{q}"] = W.uid.map(d[c])
    W["key"] = [("benign-" + LK[t]) if pos == "benign" else cond_key(t, pos) for t, pos in zip(W.target_chars, W.position)]
    W["idx"] = [int((s if isinstance(s, str) else c)[1:]) - 1 for s, c in zip(W.span_id, W.carrier_id)]
    assert (W.text_chars == W.uid.map(lambda u: len(text[u]))).all()
    # which Wikipedia article of the stream the span lands in (middle / end), from CARRIERS.md article lengths
    st = article_starts()
    for d_ in docs:   # check the article table against n_articles of the clean carriers
        if d_["label_int"] == 0:
            assert int((st[d_["carrier_id"]] < d_["actual_chars"]).sum()) == d_["n_articles"], d_["uid"]
    art = []
    for r in W.itertuples():
        if r.position in ("start", "middle", "end"):
            off = 0 if r.position == "start" else int(r.insert_offset) - (1 if r.position == "end" else 0)
            art.append(int((st[r.carrier_id] <= off).sum()))
        else:
            art.append(None)
    W["insert_article"] = art
    # local context: the 100 characters before and after the span
    nb_b, nb_a = [], []
    for r in W.itertuples():
        if r.label_int == 1 and r.position != "alone":
            t, o, s = text[r.uid], int(r.insert_offset), r.injected_instruction
            nb_b.append(t[max(0, o - 100):o])
            nb_a.append(t[o + len(s):o + len(s) + 100])
        else:
            nb_b.append(None)
            nb_a.append(None)
    W["before100"], W["after100"] = nb_b, nb_a
    spans = pd.read_csv(SPANS)
    return W, raws, spans, text, summary


# ------------------------------------------------------------------ per-condition matrices (span index 0..39)
class M:
    """p and 0/1 detection per condition as arrays ordered by span / stream index."""

    def __init__(self, W):
        self.W = W
        self.p, self.d, self.tok, self.chars = {}, {}, {}, {}
        for key, g in W.groupby("key"):
            g = g.sort_values("idx")
            assert list(g.idx) == list(range(N_SPANS)), key
            for q in QIDS:
                self.p[(q, key)] = g[f"p_{q}"].to_numpy()
                self.d[(q, key)] = g[f"pred_{q}"].to_numpy().astype(int)
                self.tok[(q, key)] = g[f"input_tokens_{q}"].to_numpy()
            self.chars[key] = g.text_chars.to_numpy()
        self.idx = np.random.default_rng(SEED).integers(0, N_SPANS, size=(B, N_SPANS))   # shared by every comparison

    def inj_keys(self):
        ks = ["alone"] + [cond_key(t, p) for t in LENS[:-1] for p in POS] + ["64k-middle"]
        return ks

    def boot_mean(self, a):
        return a[self.idx].mean(axis=1)


def paired(m, q, k_ref, k, kind="inj"):
    a, b = m.d[(q, k_ref)], m.d[(q, k)]
    pa, pb = m.p[(q, k_ref)], m.p[(q, k)]
    if kind == "inj":   # a = reference detection; lost = detected in ref, missed in k
        lost, gained = int(((a == 1) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    else:
        lost, gained = int(((a == 0) & (b == 1)).sum()), int(((a == 1) & (b == 0)).sum())
    dt_ = m.boot_mean(b) - m.boot_mean(a)
    dp_ = m.boot_mean(pb) - m.boot_mean(pa)
    lo, hi = ci(dt_)
    plo, phi = ci(dp_)
    return {"rate_ref": a.mean(), "rate": b.mean(), "d_rate": b.mean() - a.mean(), "d_rate_lo": lo, "d_rate_hi": hi,
            "lost": lost, "gained": gained, "mcnemar_p": mcnemar_exact(lost, gained),
            "mean_p_ref": pa.mean(), "mean_p": pb.mean(), "d_mean_p": (pb - pa).mean(), "d_mean_p_lo": plo, "d_mean_p_hi": phi,
            "wilcoxon_p": wilcox_p(pb - pa), "n_p_lower": int((pb < pa).sum()), "n_p_higher": int((pb > pa).sum())}


# ------------------------------------------------------------------ tables
def t01_conditions(m):
    rows = []
    for q in QIDS:
        for k in m.inj_keys() + [f"benign-{LK[t]}" for t in LENS]:
            p, d = m.p[(q, k)], m.d[(q, k)]
            lab = "benign" if k.startswith("benign") else "injection"
            n, x = len(d), int(d.sum())
            lo, hi = J.wilson(x, n)
            blo, bhi = ci(m.boot_mean(p))
            g = m.W[m.W.key == k]
            t = int(g.target_chars.iloc[0])
            rows.append({"question": q, "label": lab, "condition": k, "target_chars": t,
                         "position": g.position.iloc[0], "n": n, "detected": x,
                         "rate": x / n, "rate_lo": lo, "rate_hi": hi, "rate_name": "FPR" if lab == "benign" else "TPR",
                         "mean_p": p.mean(), "mean_p_lo": blo, "mean_p_hi": bhi, "median_p": float(np.median(p)),
                         "max_p": p.max(), "min_p": p.min(), "share_p_lt_0.1": float((p < 0.1).mean()),
                         "share_p_0.3_to_0.7": float(((p >= 0.3) & (p < 0.7)).mean()),
                         "mean_text_chars": m.chars[k].mean(), "min_text_chars": m.chars[k].min(), "max_text_chars": m.chars[k].max(),
                         "mean_input_tokens": m.tok[(q, k)].mean(), "min_input_tokens": m.tok[(q, k)].min(),
                         "max_input_tokens": m.tok[(q, k)].max(), "flips": int(g[f"flip_{q}"].sum()),
                         "mean_p_sd": float(g[f"p_sd_{q}"].mean()),
                         "mean_rel_insert": float(g.rel_insert.mean()) if g.rel_insert.notna().any() else None})
    return save_table(pd.DataFrame(rows), "t01_metrics_by_condition")


def t02_vs_2k(m):
    rows = []
    for q in QIDS:
        block = []
        for t in LENS[1:]:
            for pos in (POS if t != 64000 else ("middle",)):
                r = paired(m, q, cond_key(2000, pos), cond_key(t, pos))
                block.append({"question": q, "condition": cond_key(t, pos), "reference": cond_key(2000, pos),
                              "target_chars": t, "position": pos, **r})
        b = pd.DataFrame(block)
        b["mcnemar_p_holm"] = holm(b.mcnemar_p)
        b["wilcoxon_p_holm"] = holm(b.wilcoxon_p)
        b["dTPR_verdict"] = [group_verdict(lo, hi, ph) for lo, hi, ph in zip(b.d_rate_lo, b.d_rate_hi, b.mcnemar_p_holm)]
        b["dmean_p_verdict"] = [group_verdict(lo, hi, ph) for lo, hi, ph in zip(b.d_mean_p_lo, b.d_mean_p_hi, b.wilcoxon_p_holm)]
        b["holm_family"] = f"{len(b)} comparisons vs 2k ({q})"
        rows.append(b)
    return save_table(pd.concat(rows, ignore_index=True), "t02_paired_vs_2k")


def t03_vs_alone(m):
    rows = []
    for q in QIDS:
        block = []
        for k in m.inj_keys()[1:]:
            r = paired(m, q, "alone", k)
            g = m.W[m.W.key == k]
            block.append({"question": q, "condition": k, "reference": "alone", "target_chars": int(g.target_chars.iloc[0]),
                          "position": g.position.iloc[0], **r})
        b = pd.DataFrame(block)
        b["mcnemar_p_holm"] = holm(b.mcnemar_p)
        b["wilcoxon_p_holm"] = holm(b.wilcoxon_p)
        b["dTPR_verdict"] = [group_verdict(lo, hi, ph) for lo, hi, ph in zip(b.d_rate_lo, b.d_rate_hi, b.mcnemar_p_holm)]
        b["dmean_p_verdict"] = [group_verdict(lo, hi, ph) for lo, hi, ph in zip(b.d_mean_p_lo, b.d_mean_p_hi, b.wilcoxon_p_holm)]
        rows.append(b)
    return save_table(pd.concat(rows, ignore_index=True), "t03_paired_vs_alone")


# ---- logistic trend with span cluster bootstrap
def logit_fit(X, y, ridge=1e-6, iters=60):
    k = X.shape[1]
    b = np.zeros(k)
    for _ in range(iters):
        eta = np.clip(X @ b, -30, 30)
        mu = 1 / (1 + np.exp(-eta))
        w = mu * (1 - mu)
        g = X.T @ (y - mu) - ridge * b
        H = X.T @ (X * w[:, None]) + ridge * np.eye(k)
        step = np.linalg.solve(H, g)
        b += step
        if np.abs(step).max() < 1e-9:
            break
    return b


N_PERM = 10000


def perm_trend_p(x, y, blocks, seed=SEED, n_perm=N_PERM):
    """Exact-style within-span permutation test of 'y does not depend on x': the length labels are shuffled inside each
    (span, position) block, so span and position effects are kept. Statistic = sum x*y, centred on its permutation mean.
    For a 0/1 y this is the score test of conditional (span-stratified) logistic regression, which stays valid when the
    few spans that change all change in one direction (where the cluster-bootstrap percentile CI cannot cover 0)."""
    rng = np.random.default_rng(seed)
    x, y, blocks = np.asarray(x, float), np.asarray(y, float), np.asarray(blocks)
    t_obs, t_perm, expect = 0.0, np.zeros(n_perm), 0.0
    groups = {}
    for b in np.unique(blocks):
        idx = np.where(blocks == b)[0]
        groups.setdefault(len(idx), []).append(idx)
    for L, idxs in groups.items():
        I = np.array(idxs)                       # blocks x L
        xb, yb = x[I], y[I]
        t_obs += float((xb * yb).sum())
        expect += float((xb.mean(1) * yb.sum(1)).sum())
        perm = rng.random((n_perm, len(I), L)).argsort(axis=2)
        xp = xb[np.arange(len(I))[None, :, None], perm]
        t_perm += (xp * yb[None]).sum(axis=(1, 2))
    dev = abs(t_obs - expect)
    return float((1 + (np.abs(t_perm - expect) >= dev - 1e-9).sum()) / (n_perm + 1))


def design(m, q, keys, x_kind, interaction=False):
    """Rows = (span, condition). Columns: 1, position dummies (vs start; only if several positions), x [, x * dummies]."""
    rows_span, X, y, p, blocks = [], [], [], [], []
    poss = sorted({k.split("-")[1] for k in keys}, key=POS.index)
    for k in keys:
        pos = k.split("-")[1]
        if x_kind == "chars":
            x = np.log2(m.chars[k] / 2000.0)
        else:
            x = np.log2(m.tok[(q, k)] / m.tok[(q, cond_key(2000, "middle"))].mean())
        for i in range(N_SPANS):
            dummies = [1.0 if pos == pp_ else 0.0 for pp_ in poss[1:]]
            row = [1.0] + dummies + [x[i]]
            if interaction:
                row += [x[i] * dm for dm in dummies]
            X.append(row)
            y.append(m.d[(q, k)][i])
            p.append(m.p[(q, k)][i])
            rows_span.append(i)
            blocks.append(i * len(POS) + POS.index(pos))
    return np.array(X), np.array(y, float), np.array(p), np.array(rows_span), poss, np.array(blocks)


def within_slope(X, p, blocks, xcol):
    """OLS slope of p on x after removing each block's mean (block fixed effects). t04 passes (span, position) blocks so
    that, in the unbalanced pooled 2k–64k model, the higher middle-position p does not leak into the length slope."""
    x = X[:, xcol]
    lab = np.asarray(blocks, dtype=int)
    k = lab.max() + 1
    cnt = np.maximum(np.bincount(lab, minlength=k), 1)
    xd = x - (np.bincount(lab, x, k) / cnt)[lab]
    pd_ = p - (np.bincount(lab, p, k) / cnt)[lab]
    return float((xd * pd_).sum() / (xd ** 2).sum())


def t04_trend(m):
    specs = [("start 2k–32k", [cond_key(t, "start") for t in LENS[:-1]], False),
             ("middle 2k–32k", [cond_key(t, "middle") for t in LENS[:-1]], False),
             ("end 2k–32k", [cond_key(t, "end") for t in LENS[:-1]], False),
             ("middle 2k–64k", [cond_key(t, "middle") for t in LENS], False),
             ("pooled 2k–32k (위치 고정효과)", [cond_key(t, p) for t in LENS[:-1] for p in POS], False),
             ("pooled 2k–64k (위치 고정효과)", [cond_key(t, p) for t in LENS[:-1] for p in POS] + ["64k-middle"], False)]
    rows, inter_rows, boots = [], [], {}
    for q in QIDS:
        for x_kind in ("chars", "tokens"):
            block_rows = []
            for name, keys, _ in specs:
                X, y, p, spans, poss, blocks = design(m, q, keys, x_kind)
                xcol = X.shape[1] - 1
                b = logit_fit(X, y)
                ws = within_slope(X, p, blocks, xcol)          # (span, position) fixed effects, same blocks as the permutation
                perm_d = perm_trend_p(X[:, xcol], y, blocks)
                perm_p = perm_trend_p(X[:, xcol], p, blocks)
                n_changing = int(sum(np.ptp(y[blocks == bl]) > 0 for bl in np.unique(blocks)))
                by_span = [np.where(spans == s)[0] for s in range(N_SPANS)]
                pos_of = blocks % len(POS)
                bs, wss = [], []
                for r in range(B):
                    sel = np.concatenate([by_span[s] for s in m.idx[r]])
                    bb = logit_fit(X[sel], y[sel])
                    bs.append(bb[xcol])
                    # within-(span, position) slope: each resampled span is its own cluster (duplicates kept apart),
                    # and its rows are split by position as in the point estimate
                    lab = np.concatenate([j * len(POS) + pos_of[by_span[s]] for j, s in enumerate(m.idx[r])])
                    wss.append(within_slope(X[sel], p[sel], lab, xcol))
                bs, wss = np.array(bs), np.array(wss)
                boots[(q, x_kind, name)] = (bs, wss)
                lo, hi = ci(bs)
                wlo, whi = ci(wss)
                # fitted detection at the shortest and longest length in the model (positions averaged)
                xs = X[:, xcol]
                block_rows.append({"question": q, "x": "log2(글자 수/2,000)" if x_kind == "chars" else "log2(Jev 입력 토큰/2k 중간 평균)",
                                   "x_kind": x_kind, "model": name, "n_obs": len(y), "n_spans": N_SPANS, "positions": "+".join(poss),
                                   "n_blocks_with_changing_decision": n_changing,
                                   "slope_logodds_per_doubling": b[xcol], "slope_lo": lo, "slope_hi": hi,
                                   "OR_per_doubling": math.exp(b[xcol]), "OR_lo": math.exp(lo), "OR_hi": math.exp(hi),
                                   "boot_p": boot_p(bs), "perm_p": perm_d,
                                   "within_span_dp_per_doubling": ws, "within_dp_lo": wlo, "within_dp_hi": whi,
                                   "within_boot_p": boot_p(wss), "within_perm_p": perm_p,
                                   "x_min": xs.min(), "x_max": xs.max(), "spearman_rho_p_vs_x": spearmanr(xs, p).statistic})
            bl = pd.DataFrame(block_rows)
            bl["perm_p_holm"] = holm(bl.perm_p)
            bl["within_perm_p_holm"] = holm(bl.within_perm_p)
            bl["verdict"] = [group_verdict(l_, h_, ph, "길이에 따라 오름", "길이에 따라 내림") for l_, h_, ph in
                             zip(bl.slope_lo, bl.slope_hi, bl.perm_p_holm)]
            bl["within_verdict"] = [group_verdict(l_, h_, ph, "길이에 따라 오름", "길이에 따라 내림") for l_, h_, ph in
                                    zip(bl.within_dp_lo, bl.within_dp_hi, bl.within_perm_p_holm)]
            rows += bl.to_dict("records")
            # interaction: separate slope per position (2k–32k), contrasts vs start and middle vs end
            keys = [cond_key(t, p_) for t in LENS[:-1] for p_ in POS]
            X, y, p, spans, poss, _ = design(m, q, keys, x_kind, interaction=True)
            b = logit_fit(X, y)
            # columns: 0 const, 1 d_middle, 2 d_end, 3 x (start slope), 4 x*d_middle, 5 x*d_end
            by_span = [np.where(spans == s)[0] for s in range(N_SPANS)]
            bs = np.array([logit_fit(X[sel], y[sel]) for sel in
                           (np.concatenate([by_span[s] for s in m.idx[r]]) for r in range(B))])
            contr = {"middle − start": (b[4], bs[:, 4]), "end − start": (b[5], bs[:, 5]),
                     "middle − end": (b[4] - b[5], bs[:, 4] - bs[:, 5])}
            slopes = {"start": (b[3], bs[:, 3]), "middle": (b[3] + b[4], bs[:, 3] + bs[:, 4]), "end": (b[3] + b[5], bs[:, 3] + bs[:, 5])}
            for nm, (v, vb) in {**{f"기울기 {k}": s for k, s in slopes.items()}, **{f"기울기 차이 {k}": c for k, c in contr.items()}}.items():
                lo, hi = ci(vb)
                inter_rows.append({"question": q, "x_kind": x_kind, "term": nm, "estimate_logodds_per_doubling": v,
                                   "lo": lo, "hi": hi, "boot_p": boot_p(vb), "verdict": verdict(lo, hi, "양(+)", "음(−)")})
            # wald-type joint check of the two interaction terms with the bootstrap covariance
            cov = np.cov(bs[:, 4:6].T)
            w = float(b[4:6] @ np.linalg.solve(cov, b[4:6]))
            from scipy.stats import chi2
            inter_rows.append({"question": q, "x_kind": x_kind, "term": "상호작용 2개 동시 검정 (Wald, 부트스트랩 공분산, df=2)",
                               "estimate_logodds_per_doubling": w, "lo": None, "hi": None, "boot_p": float(chi2.sf(w, 2)),
                               "verdict": "상호작용 있음" if chi2.sf(w, 2) < 0.05 else "상호작용 근거 없음"})
    t4 = pd.DataFrame(rows)
    # reference: Holm over both questions' 6 models (12 per x); the README verdict family stays 6 per question and x
    for xk in ("chars", "tokens"):
        mk = t4.x_kind == xk
        t4.loc[mk, "perm_p_holm_both_q"] = holm(t4.loc[mk, "perm_p"])
        t4.loc[mk, "within_perm_p_holm_both_q"] = holm(t4.loc[mk, "within_perm_p"])
    t4["verdict_both_q"] = [group_verdict(l_, h_, ph, "길이에 따라 오름", "길이에 따라 내림") for l_, h_, ph in
                            zip(t4.slope_lo, t4.slope_hi, t4.perm_p_holm_both_q)]
    t4["within_verdict_both_q"] = [group_verdict(l_, h_, ph, "길이에 따라 오름", "길이에 따라 내림") for l_, h_, ph in
                                   zip(t4.within_dp_lo, t4.within_dp_hi, t4.within_perm_p_holm_both_q)]
    t4 = save_table(t4, "t04_trend_logistic")
    t5 = save_table(pd.DataFrame(inter_rows), "t05_position_x_length_interaction")
    return t4, t5, boots


def t06_position(m):
    """Position effects: per length (2k–32k) paired differences; pooled over lengths at span level."""
    rows = []
    for q in QIDS:
        block = []
        for t in LENS[:-1]:
            for a, b_ in (("start", "middle"), ("start", "end"), ("middle", "end")):
                r = paired(m, q, cond_key(t, a), cond_key(t, b_))
                block.append({"question": q, "target_chars": t, "comparison": f"{POS_KO[b_]} − {POS_KO[a]}", "ref": a, "other": b_, **r})
        bl = pd.DataFrame(block)
        bl["mcnemar_p_holm"] = holm(bl.mcnemar_p)
        bl["verdict"] = [group_verdict(lo, hi, ph) for lo, hi, ph in zip(bl.d_rate_lo, bl.d_rate_hi, bl.mcnemar_p_holm)]
        rows.append(bl)
        # pooled: per span, share of the 5 lengths detected at each position
        sh = {p_: np.mean([m.d[(q, cond_key(t, p_))] for t in LENS[:-1]], axis=0) for p_ in POS}
        mp = {p_: np.mean([m.p[(q, cond_key(t, p_))] for t in LENS[:-1]], axis=0) for p_ in POS}
        for a, b_ in (("start", "middle"), ("start", "end"), ("middle", "end")):
            d = m.boot_mean(sh[b_]) - m.boot_mean(sh[a])
            dpv = m.boot_mean(mp[b_]) - m.boot_mean(mp[a])
            lo, hi = ci(d)
            plo, phi = ci(dpv)
            rows.append(pd.DataFrame([{"question": q, "target_chars": "2k–32k 평균", "comparison": f"{POS_KO[b_]} − {POS_KO[a]}",
                                       "ref": a, "other": b_, "rate_ref": sh[a].mean(), "rate": sh[b_].mean(),
                                       "d_rate": sh[b_].mean() - sh[a].mean(), "d_rate_lo": lo, "d_rate_hi": hi,
                                       "mean_p_ref": mp[a].mean(), "mean_p": mp[b_].mean(), "d_mean_p": (mp[b_] - mp[a]).mean(),
                                       "d_mean_p_lo": plo, "d_mean_p_hi": phi, "wilcoxon_p": wilcox_p(mp[b_] - mp[a]),
                                       "n_spans_higher": int((sh[b_] > sh[a]).sum()), "n_spans_lower": int((sh[b_] < sh[a]).sum()),
                                       "verdict": verdict(lo, hi)}]))
        # difference in differences: (32k − 2k) of one position minus that of another
        for a, b_ in (("start", "middle"), ("start", "end"), ("middle", "end")):
            da = m.d[(q, cond_key(32000, a))] - m.d[(q, cond_key(2000, a))]
            db = m.d[(q, cond_key(32000, b_))] - m.d[(q, cond_key(2000, b_))]
            v = m.boot_mean(db) - m.boot_mean(da)
            lo, hi = ci(v)
            rows.append(pd.DataFrame([{"question": q, "target_chars": "(32k−2k) 차이의 차이", "comparison": f"{POS_KO[b_]} − {POS_KO[a]}",
                                       "ref": a, "other": b_, "d_rate": db.mean() - da.mean(), "d_rate_lo": lo, "d_rate_hi": hi,
                                       "verdict": verdict(lo, hi)}]))
    return save_table(pd.concat(rows, ignore_index=True), "t06_position_effect")


def t07_auc(m):
    rows = []
    for q in QIDS:
        for t in LENS:
            ben = m.p[(q, f"benign-{LK[t]}")]
            groups = [("전체 위치", [cond_key(t, p_) for p_ in (POS if t != 64000 else ("middle",))])]
            groups += [(POS_KO[p_], [cond_key(t, p_)]) for p_ in (POS if t != 64000 else ("middle",))]
            for gname, keys in groups:
                inj = np.stack([m.p[(q, k)] for k in keys])           # positions x spans
                a = auc_mw(inj.ravel(), ben)
                y = [1] * inj.size + [0] * len(ben)
                assert abs(metrics(y, list(inj.ravel()) + list(ben))["AUC"] - a) < 1e-9
                pair = float(((inj > ben[None, :]) + 0.5 * (inj == ben[None, :])).mean())
                gap = (inj - ben[None, :]).mean()
                ab, pb, gb = [], [], []
                for r in range(B):
                    ix = m.idx[r]
                    ab.append(auc_mw(inj[:, ix].ravel(), ben[ix]))
                    pb.append(((inj[:, ix] > ben[None, ix]) + 0.5 * (inj[:, ix] == ben[None, ix])).mean())
                    gb.append((inj[:, ix] - ben[None, ix]).mean())
                lo, hi = ci(ab)
                plo, phi = ci(pb)
                glo, ghi = ci(gb)
                inj_ch = np.concatenate([m.chars[k] for k in keys])
                len_auc = auc_mw(inj_ch, m.chars[f"benign-{LK[t]}"])
                rows.append({"question": q, "target_chars": t, "positions": gname, "n_injection": inj.size, "n_benign": len(ben),
                             "AUC": a, "AUC_lo": lo, "AUC_hi": hi, "paired_discrimination": pair, "paired_disc_lo": plo,
                             "paired_disc_hi": phi, "mean_gap_inj_minus_clean": gap, "gap_lo": glo, "gap_hi": ghi,
                             "max_benign_p": ben.max(), "n_injection_below_max_benign": int((inj.ravel() <= ben.max()).sum()),
                             "length_only_AUC": len_auc})
    return save_table(pd.DataFrame(rows), "t07_auc_by_length")


def t08_benign(m):
    rows = []
    for q in QIDS:
        block = []
        ref = f"benign-{LK[2000]}"
        for t in LENS:
            k = f"benign-{LK[t]}"
            p, d = m.p[(q, k)], m.d[(q, k)]
            lo, hi = J.wilson(int(d.sum()), len(d))
            blo, bhi = ci(m.boot_mean(p))
            r = {"question": q, "target_chars": t, "n": len(d), "fp": int(d.sum()), "FPR": d.mean(), "FPR_lo": lo, "FPR_hi": hi,
                 "mean_p": p.mean(), "mean_p_lo": blo, "mean_p_hi": bhi, "median_p": float(np.median(p)), "max_p": p.max(),
                 "n_p_ge_0.1": int((p >= 0.1).sum()), "n_p_ge_0.2": int((p >= 0.2).sum())}
            if t != 2000:
                pr = paired(m, q, ref, k, kind="ben")
                r.update({"d_mean_p_vs_2k": pr["d_mean_p"], "d_mean_p_lo": pr["d_mean_p_lo"], "d_mean_p_hi": pr["d_mean_p_hi"],
                          "wilcoxon_p": pr["wilcoxon_p"], "n_carriers_higher": pr["n_p_higher"], "n_carriers_lower": pr["n_p_lower"]})
            block.append(r)
        b = pd.DataFrame(block)
        b["wilcoxon_p_holm"] = holm(b.wilcoxon_p)
        b["d_mean_p_verdict"] = [group_verdict(lo, hi, ph) if lo == lo else "–" for lo, hi, ph in
                                 zip(b.d_mean_p_lo, b.d_mean_p_hi, b.wilcoxon_p_holm)]
        # within-carrier trend of benign p on log2 length (cluster bootstrap over carriers)
        X = np.array([[np.log2(m.chars[f"benign-{LK[t]}"][i] / 2000.0)] for t in LENS for i in range(N_SPANS)])
        pv = np.array([m.p[(q, f"benign-{LK[t]}")][i] for t in LENS for i in range(N_SPANS)])
        sp_ = np.array([i for t in LENS for i in range(N_SPANS)])
        s0 = within_slope(X, pv, sp_, 0)
        by = [np.where(sp_ == s)[0] for s in range(N_SPANS)]
        sb = []
        for r_ in range(B):
            sel = np.concatenate([by[s] for s in m.idx[r_]])
            lab = np.concatenate([np.full(len(by[s]), j) for j, s in enumerate(m.idx[r_])])
            sb.append(within_slope(X[sel], pv[sel], lab, 0))
        lo, hi = ci(sb)
        b["within_carrier_dp_per_doubling"] = s0
        b["within_dp_lo"], b["within_dp_hi"] = lo, hi
        b["spearman_rho_all"] = spearmanr(X[:, 0], pv).statistic
        rows.append(b)
    return save_table(pd.concat(rows, ignore_index=True), "t08_benign_by_length")


def t09_tokens(m, raws):
    rows, fits = [], {}
    for q in QIDS:
        r = raws[q].copy()
        W = m.W.set_index("uid")
        r["key"] = r.uid.map(W.key)
        r["text_chars"] = r.uid.map(W.text_chars)
        r["label_int"] = r.uid.map(W.label_int)
        slope, icpt = np.polyfit(r.text_chars.astype(float), r.usage_input_tokens.astype(float), 1)
        lslope, licpt = np.polyfit(r.usage_input_tokens.astype(float), r.latency_ms.astype(float), 1)
        fits[q] = {"tokens_per_char": slope, "overhead_tokens": icpt, "latency_ms_per_1k_tokens": 1000 * lslope, "latency_intercept_ms": licpt}
        for t in (0,) + LENS:
            for lab in (1, 0):
                g = r[(r.uid.map(W.target_chars) == t) & (r.label_int == lab)]
                if not len(g):
                    continue
                tk = g.usage_input_tokens.astype(float)
                rows.append({"question": q, "target_chars": t, "label": "injection" if lab else "benign", "calls": len(g),
                             "mean_text_chars": g.text_chars.mean(), "mean_input_tokens": tk.mean(), "min_input_tokens": tk.min(),
                             "max_input_tokens": tk.max(), "mean_text_tokens_est": tk.mean() - icpt,
                             "tokens_per_char_this_length": (tk - icpt).sum() / g.text_chars.sum(),
                             "latency_ms_mean": g.latency_ms.mean(), "latency_ms_median": g.latency_ms.median(),
                             "latency_ms_p90": g.latency_ms.quantile(0.9), "input_cost_usd": tk.sum() * PRICE_IN})
    t = pd.DataFrame(rows)
    for q in QIDS:
        t.loc[t.question == q, "fit_tokens_per_char"] = fits[q]["tokens_per_char"]
        t.loc[t.question == q, "fit_overhead_tokens"] = fits[q]["overhead_tokens"]
        t.loc[t.question == q, "fit_latency_ms_per_1k_tokens"] = fits[q]["latency_ms_per_1k_tokens"]
    return save_table(t, "t09_tokens_latency"), fits


def t10_by_source(m):
    rows = []
    W = m.W
    src = W[W.label_int == 1].groupby("idx").source.first()
    for q in QIDS:
        block = []
        for s in SOURCES:
            ii = np.array([i for i in range(N_SPANS) if src[i] == s])
            n = len(ii)
            r = {"question": q, "source": s, "n_spans": n}
            for k in m.inj_keys():
                r[f"TPR_{k}"] = m.d[(q, k)][ii].mean()
            pooled = np.concatenate([m.d[(q, cond_key(t, p_))][ii] for t in LENS[:-1] for p_ in POS])
            r["TPR_2k_32k_all_positions"] = pooled.mean()
            lo, hi = J.wilson(int(pooled.sum()), len(pooled))
            r["TPR_2k_32k_lo_approx"], r["TPR_2k_32k_hi_approx"] = lo, hi
            for p_ in POS:
                v = np.concatenate([m.d[(q, cond_key(t, p_))][ii] for t in LENS[:-1]])
                r[f"TPR_2k_32k_{p_}"] = v.mean()
            a, b_ = m.d[(q, "2k-middle")][ii], m.d[(q, "64k-middle")][ii]
            r["lost_64k_vs_2k_middle"], r["gained_64k_vs_2k_middle"] = int(((a == 1) & (b_ == 0)).sum()), int(((a == 0) & (b_ == 1)).sum())
            a2 = m.d[(q, "alone")][ii]
            r["gained_2k_middle_vs_alone"] = int(((a2 == 0) & (a == 1)).sum())
            r["lost_2k_middle_vs_alone"] = int(((a2 == 1) & (a == 0)).sum())
            r["mcnemar_p_2k_middle_vs_alone"] = mcnemar_exact(r["lost_2k_middle_vs_alone"], r["gained_2k_middle_vs_alone"])
            st, mi = m.d[(q, "2k-start")][ii], a
            r["start_vs_middle_2k_lost"] = int(((mi == 1) & (st == 0)).sum())
            r["start_vs_middle_2k_gained"] = int(((mi == 0) & (st == 1)).sum())
            # span-level average over 5 lengths: start minus middle
            sh = {p_: np.mean([m.d[(q, cond_key(t, p_))][ii] for t in LENS[:-1]], axis=0) for p_ in POS}
            r["start_minus_middle_2k_32k"] = (sh["start"] - sh["middle"]).mean()
            r["mean_p_alone"] = m.p[(q, "alone")][ii].mean()
            r["mean_p_2k_middle"] = m.p[(q, "2k-middle")][ii].mean()
            r["mean_p_64k_middle"] = m.p[(q, "64k-middle")][ii].mean()
            r["dmean_p_64k_vs_2k_middle"] = (m.p[(q, "64k-middle")][ii] - m.p[(q, "2k-middle")][ii]).mean()
            block.append(r)
        b = pd.DataFrame(block)
        b["mcnemar_p_2k_middle_vs_alone_holm"] = holm(b.mcnemar_p_2k_middle_vs_alone)
        rows.append(b)
    return save_table(pd.concat(rows, ignore_index=True), "t10_by_source")


def t11_per_span(m, spans):
    rows = []
    for i in range(N_SPANS):
        s = spans.iloc[i]
        r = {"span_id": s.span_id, "source": s.source, "base_uid": s.base_uid, "harm_type": s.harm_type,
             "span_chars": s.span_chars, "span_terminal_punct": s.span_terminal_punct, "span": short(s.injected_instruction, 120)}
        for q in QIDS:
            for k in m.inj_keys():
                r[f"p_{q}_{k}"] = m.p[(q, k)][i]
            r[f"n_detected_{q}_of_17"] = int(sum(m.d[(q, k)][i] for k in m.inj_keys()))
            r[f"benign_max_p_{q}"] = max(m.p[(q, f"benign-{LK[t]}")][i] for t in LENS)
        rows.append(r)
    return save_table(pd.DataFrame(rows), "t11_per_span")


def t12_middle_changes(m, spans):
    """Spans whose middle-position detection differs between 2k and 64k (either question), with the local context."""
    W = m.W.set_index(["key", "idx"])
    rows = []
    for i in range(N_SPANS):
        ch = {q: (m.d[(q, "2k-middle")][i], m.d[(q, "64k-middle")][i]) for q in QIDS}
        if all(a == b for a, b in ch.values()):
            continue
        s = spans.iloc[i]
        r = {"span_id": s.span_id, "source": s.source, "span_terminal_punct": s.span_terminal_punct,
             "span": short(s.injected_instruction, 100)}
        for q in QIDS:
            a, b = ch[q]
            r[f"{q}_change"] = "잃음 (잡음→놓침)" if (a, b) == (1, 0) else "얻음 (놓침→잡음)" if (a, b) == (0, 1) else "같음"
            for t in LENS:
                r[f"p_{q}_{LK[t]}_middle"] = m.p[(q, cond_key(t, "middle"))][i]
            r[f"p_{q}_2k_start"], r[f"p_{q}_2k_end"] = m.p[(q, "2k-start")][i], m.p[(q, "2k-end")][i]
        r["article_2k_middle"] = W.loc[("2k-middle", i), "insert_article"]
        r["article_64k_middle"] = W.loc[("64k-middle", i), "insert_article"]
        r["after_2k_middle"] = short(W.loc[("2k-middle", i), "after100"], 80)
        r["after_64k_middle"] = short(W.loc[("64k-middle", i), "after100"], 80)
        rows.append(r)
    return save_table(pd.DataFrame(rows), "t12_middle_2k_vs_64k_changes")


def t13_local_context(m):
    """Per position: how much a span's p moves across 2k–32k. Start keeps the same neighbouring text at every length;
    the middle span gets new neighbours at every length and the end span a new preceding sentence."""
    rows = []
    W = m.W
    for q in QIDS:
        sd = {p_: np.std(np.stack([m.p[(q, cond_key(t, p_))] for t in LENS[:-1]]), axis=0) for p_ in POS}
        rng_ = {p_: np.ptp(np.stack([m.p[(q, cond_key(t, p_))] for t in LENS[:-1]]), axis=0) for p_ in POS}
        chg = {p_: (np.stack([m.d[(q, cond_key(t, p_))] for t in LENS[:-1]]).std(axis=0) > 0) for p_ in POS}
        for p_ in POS:
            same_nb = {"start": "앞·뒤 모두 같음", "middle": "앞·뒤 모두 바뀜", "end": "뒤(문서 끝)는 같고 앞 문장이 바뀜"}[p_]
            lo, hi = ci(m.boot_mean(sd[p_]))
            rows.append({"question": q, "position": p_, "neighbour_text_across_lengths": same_nb,
                         "mean_sd_p_2k_32k": sd[p_].mean(), "sd_lo": lo, "sd_hi": hi, "median_sd_p": float(np.median(sd[p_])),
                         "mean_range_p": rng_[p_].mean(), "n_spans_decision_changes": int(chg[p_].sum())})
        for a, b_ in (("start", "middle"), ("start", "end"), ("end", "middle")):
            v = m.boot_mean(sd[b_]) - m.boot_mean(sd[a])
            lo, hi = ci(v)
            rows.append({"question": q, "position": f"{b_} − {a}", "neighbour_text_across_lengths": "평균 SD 차이",
                         "mean_sd_p_2k_32k": (sd[b_] - sd[a]).mean(), "sd_lo": lo, "sd_hi": hi,
                         "wilcoxon_p": wilcox_p(sd[b_] - sd[a]), "verdict": verdict(lo, hi, "더 흔들림", "덜 흔들림")})
        # middle: insertion in the same Wikipedia article as the reference length or a different one. Every length vs
        # 2k-middle, plus 32k-middle -> 64k-middle (a partial control: 15 spans sit in the same article at 32k and 64k).
        sub = []
        art = {k: W[W.key == k].sort_values("idx").insert_article.to_numpy() for k in [cond_key(t, "middle") for t in LENS]}
        pairs = [("2k-middle", cond_key(t, "middle")) for t in LENS[1:]] + [("32k-middle", "64k-middle")]
        for k_ref, k in pairs:
            same = art[k] == art[k_ref]
            groups = [(same, f"{k_ref.split('-')[0]}와 같은 위키 문서 안"),
                      (~same, "다른 위키 문서 안")]
            if k_ref == "32k-middle":
                groups.append((np.ones(N_SPANS, bool), "span 40개 전체"))
            for mk, nm in groups:
                if not mk.any():
                    continue
                sub.append({"question": q, "position": f"middle {k.split('-')[0]} vs {k_ref.split('-')[0]}",
                            "reference": k_ref, "condition": k, "neighbour_text_across_lengths": nm,
                            **sub_paired(m, q, k_ref, k, mk)})
            # same − different article (only where both groups have >= 3 spans)
            if same.sum() >= 3 and (~same).sum() >= 3:
                dp = m.p[(q, k)] - m.p[(q, k_ref)]
                v = []
                for r in range(B):
                    ix = m.idx[r]
                    s_, d_ = same[ix], ~same[ix]
                    v.append(dp[ix][s_].mean() - dp[ix][d_].mean() if s_.any() and d_.any() else np.nan)
                lo, hi = ci(v)
                sub.append({"question": q, "position": f"middle {k.split('-')[0]} vs {k_ref.split('-')[0]}", "reference": k_ref,
                            "condition": k, "neighbour_text_across_lengths": "같은 문서 − 다른 문서 (Δ평균 p의 차이)",
                            "n_spans": N_SPANS, "d_mean_p_vs_ref": dp[same].mean() - dp[~same].mean(),
                            "d_mean_p_lo": lo, "d_mean_p_hi": hi, "verdict": verdict(lo, hi, "같은 문서 쪽이 덜 내려감", "같은 문서 쪽이 더 내려감")})
        sb = pd.DataFrame(sub)
        fam = sb.wilcoxon_p.notna() & (sb.neighbour_text_across_lengths != "span 40개 전체")
        sb.loc[fam, "wilcoxon_p_holm"] = holm(sb.loc[fam, "wilcoxon_p"])
        sb.loc[fam, "holm_family"] = f"{int(fam.sum())} subgroup comparisons ({q})"
        for i in sb.index:
            r = sb.loc[i]
            if r.wilcoxon_p == r.wilcoxon_p:      # subgroup rows with n >= 3
                ph = r.wilcoxon_p_holm if fam[i] else r.wilcoxon_p
                sb.loc[i, "verdict"] = (("" if fam[i] else "탐색 비교 (보정 없음): ")
                                        + group_verdict(r.d_mean_p_lo, r.d_mean_p_hi, ph, n=r.n_spans))
            elif r.neighbour_text_across_lengths.startswith("같은 문서 −"):
                continue
            else:
                sb.loc[i, "verdict"] = "– (n < 3, 구간 없음)"
        rows += sb.to_dict("records")
    return save_table(pd.DataFrame(rows), "t13_local_context")


def sub_paired(m, q, k_ref, k, mk):
    """Paired change k_ref -> k inside the span subset `mk`; CIs from the shared index matrix (domain bootstrap: the
    subset mean over the resampled spans that fall in `mk`)."""
    a, b_ = m.d[(q, k_ref)], m.d[(q, k)]
    dp = m.p[(q, k)] - m.p[(q, k_ref)]
    dd = (b_ - a).astype(float)
    n = int(mk.sum())
    out = {"n_spans": n, "dTPR_vs_ref": dd[mk].mean(), "lost": int(((a == 1) & (b_ == 0) & mk).sum()),
           "gained": int(((a == 0) & (b_ == 1) & mk).sum()), "d_mean_p_vs_ref": dp[mk].mean(),
           "n_p_lower": int(((dp < 0) & mk).sum()), "n_p_higher": int(((dp > 0) & mk).sum())}
    out["mcnemar_p"] = mcnemar_exact(out["lost"], out["gained"])
    if n >= 3:
        vt, vp = [], []
        for r in range(B):
            ix = m.idx[r]
            s_ = mk[ix]
            vt.append(dd[ix][s_].mean() if s_.any() else np.nan)
            vp.append(dp[ix][s_].mean() if s_.any() else np.nan)
        out["dTPR_lo"], out["dTPR_hi"] = ci(vt)
        out["d_mean_p_lo"], out["d_mean_p_hi"] = ci(vp)
        out["wilcoxon_p"] = wilcox_p(dp[mk])
    return out


def t14_q2_vs_ql(m, boots):
    rows = []
    for k in m.inj_keys() + [f"benign-{LK[t]}" for t in LENS]:
        a, b_ = m.d[("Q2", k)], m.d[("QL", k)]
        pa, pb = m.p[("Q2", k)], m.p[("QL", k)]
        v = m.boot_mean(b_) - m.boot_mean(a)
        lo, hi = ci(v)
        plo, phi = ci(m.boot_mean(pb) - m.boot_mean(pa))
        q2o, qlo = int(((a == 1) & (b_ == 0)).sum()), int(((a == 0) & (b_ == 1)).sum())
        rows.append({"condition": k, "rate_Q2": a.mean(), "rate_QL": b_.mean(), "d_rate_QL_minus_Q2": b_.mean() - a.mean(),
                     "lo": lo, "hi": hi, "only_Q2": q2o, "only_QL": qlo, "mcnemar_p": mcnemar_exact(q2o, qlo),
                     "d_mean_p": (pb - pa).mean(), "d_mean_p_lo": plo, "d_mean_p_hi": phi})
    t = pd.DataFrame(rows)
    t["mcnemar_p_holm"] = holm(t.mcnemar_p)
    t["verdict"] = [group_verdict(lo, hi, ph, "QL 높음", "QL 낮음") for lo, hi, ph in zip(t.lo, t.hi, t.mcnemar_p_holm)]
    # difference of length effects between questions
    extra = []
    for k_ref, k in (("2k-middle", "64k-middle"), ("2k-start", "32k-start"), ("2k-middle", "32k-middle"), ("2k-end", "32k-end")):
        dq = {q: m.d[(q, k)] - m.d[(q, k_ref)] for q in QIDS}
        pq = {q: m.p[(q, k)] - m.p[(q, k_ref)] for q in QIDS}
        v = m.boot_mean(dq["QL"]) - m.boot_mean(dq["Q2"])
        w = m.boot_mean(pq["QL"]) - m.boot_mean(pq["Q2"])
        lo, hi = ci(v)
        plo, phi = ci(w)
        extra.append({"condition": f"({k} − {k_ref}) QL − Q2 (차이의 차이)", "d_rate_QL_minus_Q2": dq["QL"].mean() - dq["Q2"].mean(),
                      "lo": lo, "hi": hi, "d_mean_p": pq["QL"].mean() - pq["Q2"].mean(), "d_mean_p_lo": plo, "d_mean_p_hi": phi,
                      "verdict": verdict(lo, hi, "QL 쪽 길이 효과가 더 큼(+)", "QL 쪽 길이 효과가 더 작음(−)")})
    for name in ("middle 2k–64k", "pooled 2k–64k (위치 고정효과)"):
        d = boots[("QL", "chars", name)][0] - boots[("Q2", "chars", name)][0]
        lo, hi = ci(d)
        extra.append({"condition": f"추세 기울기 QL − Q2 ({name}, log-odds/2배)", "d_rate_QL_minus_Q2": float(np.median(d)),
                      "lo": lo, "hi": hi, "verdict": verdict(lo, hi, "QL 기울기 큼", "QL 기울기 작음")})
    t = pd.concat([t, pd.DataFrame(extra)], ignore_index=True)
    return save_table(t, "t14_q2_vs_ql")


def t15_stability(m):
    rows = []
    for q in QIDS:
        for k in m.inj_keys() + [f"benign-{LK[t]}" for t in LENS]:
            g = m.W[m.W.key == k]
            runs = np.stack([g[f"p_run{r}_{q}"].to_numpy() for r in range(3)])
            rr = {"question": q, "condition": k, "n": len(g), "flips": int(g[f"flip_{q}"].sum()), "mean_p_sd": g[f"p_sd_{q}"].mean(),
                  "max_p_range": float((runs.max(0) - runs.min(0)).max()), "share_identical_runs": float((runs.max(0) == runs.min(0)).mean())}
            for r in range(3):
                rr[f"rate_run{r}"] = float((runs[r] >= THRESHOLD).mean())
            rows.append(rr)
    t = pd.DataFrame(rows)
    # per-run check of the 64k middle drop (single calls instead of the mean)
    ex = []
    for q in QIDS:
        g2 = m.W[m.W.key == "2k-middle"].sort_values("idx")
        g64 = m.W[m.W.key == "64k-middle"].sort_values("idx")
        for r in range(3):
            a = (g2[f"p_run{r}_{q}"].to_numpy() >= THRESHOLD).astype(int)
            b = (g64[f"p_run{r}_{q}"].to_numpy() >= THRESHOLD).astype(int)
            lost, gained = int(((a == 1) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
            ex.append({"question": q, "condition": f"64k − 2k 중간, 회차 {r}", "dTPR_single_run": b.mean() - a.mean(),
                       "lost": lost, "gained": gained, "mcnemar_p": mcnemar_exact(lost, gained)})
    t = pd.concat([t, pd.DataFrame(ex)], ignore_index=True)
    return save_table(t, "t15_run_stability")


def t16_fixed_thresholds(m):
    th = pd.read_csv(os.path.join(BASE, "tables", "thresholds_at_fpr.csv"))
    rows = []
    for q in QIDS:
        for target in ("기준 0.5", "오탐 1% 이하", "오탐 5% 이하"):
            t_ = float(th[(th.question == q) & (th.target == target)].threshold.iloc[0])
            for k in m.inj_keys() + [f"benign-{LK[t]}" for t in LENS]:
                p = m.p[(q, k)]
                d = (p >= t_).astype(int)
                lo, hi = J.wilson(int(d.sum()), len(d))
                r = {"question": q, "threshold_source": f"01_baseline {target}", "threshold": t_, "condition": k, "n": len(d),
                     "detected": int(d.sum()), "rate": d.mean(), "rate_lo": lo, "rate_hi": hi}
                if k == "64k-middle":
                    a = (m.p[(q, "2k-middle")] >= t_).astype(int)
                    lost, gained = int(((a == 1) & (d == 0)).sum()), int(((a == 0) & (d == 1)).sum())
                    r.update({"d_vs_2k_middle": d.mean() - a.mean(), "lost_vs_2k_middle": lost, "gained_vs_2k_middle": gained,
                              "mcnemar_p_vs_2k_middle": mcnemar_exact(lost, gained)})
                rows.append(r)
    return save_table(pd.DataFrame(rows), "t16_fixed_baseline_thresholds")


def t17_other_experiments(m, spans):
    """The same 40 spans in their original EN documents (01_baseline) and, for 16 of them, inside X3's Wikipedia excerpts;
    plus the 01_baseline length-quartile AUC with and without BrowseSafe (the confounded observation)."""
    rows, auc_rows = [], []
    en = {r["uid"]: r for r in J.load_jsonl(EN_DATA)}
    for q in QIDS:
        b = pd.read_csv(os.path.join(BASE, f"{q}_predictions.csv")).set_index("uid")
        x3 = pd.read_csv(os.path.join(X3, f"{q}_predictions.csv"))
        x3w = x3[(x3.label == "injection") & (x3.carrier_type == "unrelated_expository")].set_index("base_uid")
        x3e = x3[(x3.label == "injection") & (x3.carrier_type == "instruction_dense")].set_index("base_uid")
        bu = spans.base_uid.to_numpy()
        orig_p = snap(b.loc[bu, "p"].to_numpy())
        orig_d = (orig_p >= THRESHOLD).astype(int)
        orig_len = b.loc[bu, "char_len"].to_numpy()
        for k in ("alone", "2k-start", "2k-middle", "2k-end", "32k-middle", "64k-middle"):
            d = m.d[(q, k)]
            lost, gained = int(((orig_d == 1) & (d == 0)).sum()), int(((orig_d == 0) & (d == 1)).sum())
            v = m.boot_mean(d) - m.boot_mean(orig_d)
            lo, hi = ci(v)
            rows.append({"question": q, "comparison": f"04 {k} − 01_baseline 원래 문서", "n_spans": N_SPANS,
                         "rate_ref": orig_d.mean(), "rate": d.mean(), "d_rate": d.mean() - orig_d.mean(), "lo": lo, "hi": hi,
                         "lost": lost, "gained": gained, "mcnemar_p": mcnemar_exact(lost, gained),
                         "mean_p_ref": orig_p.mean(), "mean_p": m.p[(q, k)].mean(),
                         "ref_doc_chars_median": float(np.median(orig_len)), "ref_doc_chars_min": int(orig_len.min()),
                         "ref_doc_chars_max": int(orig_len.max())})
        ov = np.array([i for i in range(N_SPANS) if bu[i] in x3w.index])
        for nm, tab in (("X3 위키 발췌 가운데", x3w), ("X3 Enron 메일 가운데", x3e)):
            xp = snap(tab.loc[bu[ov], "p"].to_numpy())
            xd = (xp >= THRESHOLD).astype(int)
            for k in ("2k-middle", "4k-middle"):
                d = m.d[(q, k)][ov]
                lost, gained = int(((xd == 1) & (d == 0)).sum()), int(((xd == 0) & (d == 1)).sum())
                rows.append({"question": q, "comparison": f"04 {k} − {nm} (겹치는 span)", "n_spans": len(ov),
                             "rate_ref": xd.mean(), "rate": d.mean(), "d_rate": d.mean() - xd.mean(), "lost": lost, "gained": gained,
                             "mcnemar_p": mcnemar_exact(lost, gained), "mean_p_ref": xp.mean(), "mean_p": m.p[(q, k)][ov].mean(),
                             "ref_doc_chars_median": float(np.median(tab.loc[bu[ov], "char_len"])),
                             "ref_doc_chars_min": int(tab.loc[bu[ov], "char_len"].min()),
                             "ref_doc_chars_max": int(tab.loc[bu[ov], "char_len"].max())})
        # 01_baseline length quartiles (bounds fixed in that analysis), all sources and without BrowseSafe
        e = b[b.set == "EN"].copy()
        e["p"] = snap(e.p)
        cuts = (333, 623, 1254)
        e["quart"] = np.where(e.char_len <= cuts[0], 0, np.where(e.char_len <= cuts[1], 1, np.where(e.char_len <= cuts[2], 2, 3)))
        for nm, sub in (("01_baseline 전체 출처", e), ("01_baseline BrowseSafe 제외", e[e.source != "BrowseSafe-Bench"])):
            for qq in range(4):
                g = sub[sub.quart == qq]
                mm = metrics(g.label_int.tolist(), g.p.tolist(), threshold=THRESHOLD)
                auc_rows.append({"question": q, "set": nm, "quartile": ["≤333자", "334–623자", "624–1254자", ">1254자"][qq],
                                 "median_chars": float(g.char_len.median()), "n": len(g), "n_injection": int(g.label_int.sum()),
                                 "TPR": mm["TPR"], "FPR": mm["FPR"], "AUC": mm["AUC"],
                                 "share_BrowseSafe_benign": float(((g.source == "BrowseSafe-Bench") & (g.label_int == 0)).sum() / max(1, (g.label_int == 0).sum())),
                                 "share_BIPIA_injection": float(((g.source == "BIPIA") & (g.label_int == 1)).sum() / max(1, g.label_int.sum()))})
    t = pd.DataFrame(rows)
    t["mcnemar_p_holm"] = np.nan
    for q in QIDS:
        mk = t.question == q
        t.loc[mk, "mcnemar_p_holm"] = holm(t.loc[mk, "mcnemar_p"])
    # original document position of the span (01_baseline rel. position, thirds) for context
    pos_rows = []
    for i, uid in enumerate(spans.base_uid):
        r = en[uid]
        txt, ins = r["text"], r["injected_instruction"]
        o = txt.find(ins)
        rp = o / max(1, len(txt) - len(ins))
        pos_rows.append({"span_id": spans.span_id.iloc[i], "base_uid": uid, "orig_chars": len(txt), "orig_rel_pos": rp,
                         "orig_position": "start" if rp < 1 / 3 else "middle" if rp < 2 / 3 else "end"})
    pos = pd.DataFrame(pos_rows)
    save_table(pos, "t17b_span_original_documents")
    return save_table(t, "t17_vs_baseline_and_x3"), save_table(pd.DataFrame(auc_rows), "t18_baseline_length_quartile_auc"), pos


# ------------------------------------------------------------------ figures
def fig_save(fig, name, out):
    """Same layout fix as analyze_01_baseline.save: remove the double headline reservation of tight_layout."""
    top = fig._viz_top
    st = fig._suptitle
    fig.tight_layout(rect=(0, 0, 1, top))
    y_with = max(a.get_position().y1 for a in fig.axes)
    st.set_in_layout(False)
    fig.tight_layout(rect=(0, 0, 1, top))
    y_without = max(a.get_position().y1 for a in fig.axes)
    st.set_in_layout(True)
    out.append(PS.save(fig, name, top=min(0.995, top + (y_without - y_with)), out_dir=FIG))


def len_axis(ax, with_alone=True, top_tokens=None, label=True):
    """Log length axis; with `top_tokens` ({target: mean Jev input tokens}) each tick gets the token count as a 2nd line."""
    ax.set_xscale("log")
    ticks = ([ALONE_X] if with_alone else []) + list(LENS)
    tl = (["단독"] if with_alone else []) + [LK[t] for t in LENS]
    if top_tokens is not None:
        tok = ([top_tokens[0]] if with_alone else []) + [top_tokens[t] for t in LENS]
        tl = [f"{a}\n{v:,.0f}" if v < 1000 else f"{a}\n{v / 1000:.1f}k" for a, v in zip(tl, tok)]
    elif with_alone:
        tl[0] = "span\n단독"
    ax.set_xticks(ticks, tl)
    ax.minorticks_off()
    ax.set_xlim(ALONE_X * 0.8 if with_alone else 1700, 78000)
    if with_alone:
        ax.axvline(1420, color=PS.AXIS, lw=0.8, ls=(0, (2, 2)))
    if label:
        ax.set_xlabel("carrier 길이 (글자, 로그 축)" if top_tokens is None else
                      "carrier 길이 (윗줄: 글자, 아랫줄: Jev 입력 토큰 · 호출 1건, 질문 포함)")
    return None


def repel(ys, gap):
    """Spread label y positions so neighbours are at least `gap` apart (keeps order)."""
    order = np.argsort(ys)
    out = np.array(ys, float)
    for j in range(1, len(order)):
        a, b = order[j - 1], order[j]
        if out[b] - out[a] < gap:
            out[b] = out[a] + gap
    return out


POS_XOFF = {"start": 0.94, "middle": 1.0, "end": 1.06}


def eb(ax, x, y, yerr=None, xerr=None, **kw):
    """ax.errorbar with the error lengths clipped at 0 (a Wilson bound can sit 1e-17 past a 0% point)."""
    def clip(e):
        if e is None:
            return None
        return [np.maximum(np.asarray(v, dtype=float), 0) for v in e]
    return ax.errorbar(x, y, yerr=clip(yerr), xerr=clip(xerr), **kw)


def figures(m, R):
    PS.setup()
    out = []
    c1 = R["t01"]
    tk = {q: {int(r.target_chars): r.mean_input_tokens for r in c1[(c1.question == q) & ((c1.label == "benign") | (c1.condition == "alone"))].itertuples()} for q in QIDS}
    SUB = f"span 40개 × 조건 · 위키백과 carrier · {MODEL} · 임계값 0.5 · 문서당 3회 호출 평균 p"

    def row(q, k):
        return c1[(c1.question == q) & (c1.condition == k)].iloc[0]

    v2k = R["t02"]
    # ---------------- f01 main figure (PLAN D4)
    fig, mos = plt.subplot_mosaic([["Q2", "QL", "F"], ["Q2", "QL", "P"]], figsize=(17, 7.0),
                                  gridspec_kw={"width_ratios": [1, 1, 0.72]})
    axes = [mos["Q2"], mos["QL"]]
    for ax, q in zip(axes, QIDS):
        col = Q_COLORS[q]
        a = row(q, "alone")
        eb(ax, [ALONE_X], [a.rate], yerr=[[a.rate - a.rate_lo], [a.rate_hi - a.rate]], fmt="D", ms=8, mfc=PS.SURFACE,
                    mec=col, mew=1.8, color=col, elinewidth=1, capsize=3)
        ax.text(ALONE_X * 1.07, a.rate, pct(a.rate), va="center", ha="left", fontsize=8.5, color=PS.INK_2)
        labels = []
        for pos in POS:
            ts = [t for t in LENS if t != 64000 or pos == "middle"]
            rr = [row(q, cond_key(t, pos)) for t in ts]
            x = np.array(ts, float) * POS_XOFF[pos]
            y = np.array([r.rate for r in rr])
            eb(ax, x, y, yerr=[y - np.array([r.rate_lo for r in rr]), np.array([r.rate_hi for r in rr]) - y], color=col,
                        lw=1.8, ms=7, mfc=col if pos == "middle" else PS.SURFACE, mec=col, mew=1.5, elinewidth=0.8, capsize=2,
                        **POS_STYLE[pos])
            labels.append((pos, x[-1], y[-1]))
        ys = repel([l[2] for l in labels], 0.06)
        for (pos, x, y), yl in zip(labels, ys):
            ax.annotate(f"{POS_KO[pos]} {pct(y)}", (x, y), xytext=(x * 1.13 if x > 40000 else 41000, yl), va="center", ha="left",
                        fontsize=9, color=PS.INK, arrowprops=dict(arrowstyle="-", color=PS.MUTED, lw=0.6))
        len_axis(ax, True, tk[q])
        ax.set_xlim(ALONE_X * 0.8, 130000)
        ax.set_ylim(0, 1.02)
        ax.set_yticks(np.linspace(0, 1, 6), [pct(v, 0) for v in np.linspace(0, 1, 6)])
        ax.set_title(Q_NAMES[q], fontsize=11.5, color=col)
        r64 = v2k[(v2k.question == q) & (v2k.condition == "64k-middle")].iloc[0]
        ax.text(0.02, 0.03, f"64k 중간 − 2k 중간 {pp(r64.d_rate)} [{100 * r64.d_rate_lo:.1f}, {100 * r64.d_rate_hi:.1f}] · "
                            f"잃음 {int(r64.lost)} / 얻음 {int(r64.gained)} · McNemar p = {r64.mcnemar_p:.3f} (Holm {r64.mcnemar_p_holm:.2f})",
                transform=ax.transAxes, fontsize=8, color=PS.INK_2)
    axes[0].set_ylabel("인젝션 탐지율 TPR (p ≥ 0.5)")
    handles = [Line2D([0], [0], color=PS.INK_2, lw=1.6, mfc=PS.INK_2 if p_ == "middle" else PS.SURFACE, mec=PS.INK_2, **POS_STYLE[p_],
                      label=f"{POS_KO[p_]}") for p_ in POS]
    handles.append(Line2D([0], [0], color=PS.INK_2, marker="D", ls="none", mfc=PS.SURFACE, mec=PS.INK_2, label="span 단독"))
    axes[0].legend(handles=handles, title="span 위치", loc="lower right", bbox_to_anchor=(1.0, 0.08), fontsize=8.5, title_fontsize=8.5,
                   frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    # benign panels
    b8 = R["t08"]
    axf, axp = mos["F"], mos["P"]
    for q, off in (("Q2", 0.95), ("QL", 1.05)):
        s = b8[b8.question == q]
        x = s.target_chars.to_numpy() * off
        eb(axf, x, s.FPR, yerr=[s.FPR - s.FPR_lo, s.FPR_hi - s.FPR], fmt="s", color=Q_COLORS[q], ms=6, mfc=PS.SURFACE,
                     mec=Q_COLORS[q], elinewidth=1, capsize=2, label=q)
        eb(axp, x, s.mean_p, yerr=[s.mean_p - s.mean_p_lo, s.mean_p_hi - s.mean_p], fmt="-o", color=Q_COLORS[q], ms=5,
                     elinewidth=0.9, capsize=2, label=q)
        axp.scatter(x, s.max_p, marker="_", s=60, color=Q_COLORS[q], lw=1.5)
    for ax in (axf, axp):
        len_axis(ax, False, None, label=False)
    axf.set_ylim(-0.005, 0.12)
    axf.set_yticks([0, 0.04, 0.08, 0.12], ["0%", "4%", "8%", "12%"])
    axf.set_title("정상 carrier 오탐률 FPR", fontsize=10.5)
    axf.text(0.03, 0.88, "모든 길이 0/40 · 선 = Wilson 95% 상한 8.8%", transform=axf.transAxes, fontsize=8, color=PS.INK_2)
    axf.legend(loc="upper right", fontsize=8, ncol=2)
    axp.set_ylim(0, 0.2)
    axp.set_yticks([0, 0.05, 0.1, 0.15, 0.2])
    axp.set_title("정상 carrier 평균 p (— = 최대 p)", fontsize=10.5)
    axp.set_xlabel("carrier 길이 (글자, 로그 축)")
    t4c = R["t04"][(R["t04"].x_kind == "chars")].set_index(["question", "model"])
    u32 = v2k[v2k.target_chars <= 32000]
    tq = t4c.loc[("Q2", "middle 2k–64k")]
    r64 = v2k[v2k.condition == "64k-middle"].set_index("question")
    PS.title(fig, f"32k자({tk['Q2'][32000]:,.0f}토큰)까지 0.5 판정 TPR은 2k 대비 Holm 후 달라진 곳이 없다 ({100 * u32.d_rate.min():+.1f} ~ "
                  f"{100 * u32.d_rate.max():+.1f}%p). 64k자 중간은 Q2 {pp(r64.loc['Q2', 'd_rate'])}, QL {pp(r64.loc['QL', 'd_rate'])}",
             SUB + "\n점 하나 = span 40개, 선 = Wilson 95% 구간 (위치별로 좌우로 조금 비켜 그림) · 같은 span을 같은 stream의 앞부분"
                   "(2k ⊂ 4k ⊂ … ⊂ 64k)에 넣음 · 64k는 중간만 잼 · 정상 = 같은 길이의 깨끗한 carrier 40개\n"
                   f"span 40개라 2k 대비 짝 구간의 하한이 {100 * u32.d_rate_lo.min():.0f}%p까지 내려가 그만한 하락은 배제하지 못함 · "
                   f"Q2 중간 2k–64k 추세: 길이 2배당 탐지 오즈 ×{tq.OR_per_doubling:.2f} [{tq.OR_lo:.2f}, {tq.OR_hi:.2f}], "
                   f"순열 Holm p = {tq.perm_p_holm:.3f} (질문 안 6개 모형), {tq.perm_p_holm_both_q:.3f} (두 질문 12개)")
    fig_save(fig, "f01_tpr_by_length", out)

    # ---------------- f02 mean injection p by length x position
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6), sharey=True)
    for ax, q in zip(axes, QIDS):
        col = Q_COLORS[q]
        a = row(q, "alone")
        eb(ax, [ALONE_X], [a.mean_p], yerr=[[a.mean_p - a.mean_p_lo], [a.mean_p_hi - a.mean_p]], fmt="D", ms=8, mfc=PS.SURFACE,
                    mec=col, mew=1.8, color=col, elinewidth=1, capsize=3)
        labels = []
        for pos in POS:
            ts = [t for t in LENS if t != 64000 or pos == "middle"]
            rr = [row(q, cond_key(t, pos)) for t in ts]
            x = np.array(ts, float) * POS_XOFF[pos]
            y = np.array([r.mean_p for r in rr])
            eb(ax, x, y, yerr=[y - np.array([r.mean_p_lo for r in rr]), np.array([r.mean_p_hi for r in rr]) - y], color=col, lw=1.8,
                        ms=7, mfc=col if pos == "middle" else PS.SURFACE, mec=col, mew=1.5, elinewidth=0.8, capsize=2, **POS_STYLE[pos])
            labels.append((pos, x[-1], y[-1]))
        ys = repel([l[2] for l in labels], 0.045)
        for (pos, x, y), yl in zip(labels, ys):
            ax.annotate(f"{POS_KO[pos]} {y:.2f}", (x, y), xytext=(x * 1.13 if x > 40000 else 41000, yl), va="center", ha="left",
                        fontsize=9, color=PS.INK, arrowprops=dict(arrowstyle="-", color=PS.MUTED, lw=0.6))
        len_axis(ax, True)
        ax.set_xlim(ALONE_X * 0.8, 130000)
        ax.axhline(0.5, color=PS.INK_2, lw=0.8, ls="--")
        ax.set_title(Q_NAMES[q], fontsize=11.5, color=col)
        r64 = v2k[(v2k.question == q) & (v2k.condition == "64k-middle")].iloc[0]
        ax.text(0.02, 0.03, f"64k 중간 − 2k 중간: Δp {r64.d_mean_p:+.3f} [{r64.d_mean_p_lo:+.3f}, {r64.d_mean_p_hi:+.3f}], "
                            f"p가 내려간 span {int(r64.n_p_lower)} / 오른 span {int(r64.n_p_higher)}",
                transform=ax.transAxes, fontsize=8, color=PS.INK_2)
    axes[0].set_ylabel("인젝션 평균 p (3회 평균의 span 평균)")
    axes[0].set_ylim(0.2, 0.9)
    axes[0].legend(handles=handles, title="span 위치", loc="lower right", bbox_to_anchor=(1.0, 0.07), fontsize=8.5, title_fontsize=8.5,
                   frameon=True, facecolor=PS.SURFACE, edgecolor=PS.GRID)
    t4c = R["t04"][(R["t04"].x_kind == "chars")].set_index(["question", "model"])
    wm = {q: t4c.loc[(q, "middle 2k–64k")] for q in QIDS}
    ws_ = {q: t4c.loc[(q, "start 2k–32k")] for q in QIDS}
    PS.title(fig, f"평균 p는 중간 위치에서 길이 2배마다 Q2 {wm['Q2'].within_span_dp_per_doubling:+.3f}, QL {wm['QL'].within_span_dp_per_doubling:+.3f}씩 "
                  f"내려가고, 앞 위치에서는 {ws_['Q2'].within_span_dp_per_doubling:+.3f} / {ws_['QL'].within_span_dp_per_doubling:+.3f}로 거의 그대로다",
             SUB + " · 선 = span 단위 부트스트랩 95% 구간 (1,000회) · 점선 = 임계값 0.5\n"
                   "기울기 = span 안에서 뺀 p를 log2(글자 수)에 회귀한 값 (중간 2k–64k, 앞 2k–32k), 순열검정·구간은 tables/t04_trend_logistic.csv")
    fig_save(fig, "f02_mean_p_by_length", out)

    # ---------------- f03 paired differences vs 2k (forest)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.8), sharey=True)
    conds = [cond_key(t, p_) for p_ in POS for t in LENS[1:] if t != 64000 or p_ == "middle"]
    ylab = [f"{POS_KO[c.split('-')[1]]} {c.split('-')[0]}" for c in conds]
    yy = np.arange(len(conds))[::-1].astype(float)
    for j, (met, lo_, hi_, ttl) in enumerate((("d_rate", "d_rate_lo", "d_rate_hi", "ΔTPR (같은 위치 2k 대비, %p)"),
                                              ("d_mean_p", "d_mean_p_lo", "d_mean_p_hi", "Δ평균 p (같은 위치 2k 대비)"))):
        ax = axes[j]
        for q, dy in (("Q2", 0.17), ("QL", -0.17)):
            s = v2k[v2k.question == q].set_index("condition").loc[conds]
            eb(ax, s[met], yy + dy, xerr=[s[met] - s[lo_], s[hi_] - s[met]], fmt="o", color=Q_COLORS[q], ms=5.5, elinewidth=1.2,
                        capsize=2, label=Q_NAMES[q])
            if j == 0:
                for yi, (_, r) in zip(yy + dy, s.iterrows()):
                    ax.text(0.29, yi, f"{int(r.lost)}/{int(r.gained)}", va="center", ha="left", fontsize=7.5, color=Q_COLORS[q])
        ax.axvline(0, color=PS.INK_2, lw=0.9)
        ax.set_title(ttl, fontsize=10.5)
        ax.grid(axis="y", visible=False)
        for b_ in (3.5, 8.5):
            ax.axhline(b_ + 0.0, color=PS.GRID, lw=0.8)
    axes[0].set_xlim(-0.35, 0.37)
    axes[0].set_xticks([-0.3, -0.2, -0.1, 0, 0.1, 0.2], ["−30", "−20", "−10", "0", "+10", "+20"])
    axes[0].text(0.28, len(conds) - 0.45, "잃음/얻음", fontsize=7.5, color=PS.INK_2)
    axes[1].set_xlim(-0.2, 0.1)
    axes[0].set_yticks(yy, ylab)
    axes[1].legend(loc="lower left", fontsize=8.5)
    sd = v2k[v2k.dmean_p_verdict == "낮음"]
    sd_txt = ", ".join(f"{r.question} {POS_KO[r.position]} {LK[int(r.target_chars)]}" for r in sd.itertuples()) or "없음"
    n_holm = int((v2k.dTPR_verdict.isin(["낮음", "높음"])).sum())
    PS.title(fig, f"2k 대비 차이: 질문마다 13개 비교 중 0.5 판정이 Holm 보정 후 달라진 곳은 {n_holm}개. "
                  f"평균 p가 보정 후에도 내려간 곳: {sd_txt}",
             SUB + " · 같은 span끼리 짝 비교 · 선 = span 단위 짝 부트스트랩 95% 구간 · 잃음/얻음 = 2k에서 잡던 span을 놓친 수 / 새로 잡은 수\n"
                   "64k 중간은 2k 중간과 비교 · McNemar·Wilcoxon p와 Holm 보정값은 tables/t02_paired_vs_2k.csv")
    fig_save(fig, "f03_paired_vs_2k", out)

    # ---------------- f04 trend slopes
    t4, t5 = R["t04"], R["t05"]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.6), sharey=True)
    models = ["start 2k–32k", "middle 2k–32k", "end 2k–32k", "middle 2k–64k", "pooled 2k–32k (위치 고정효과)", "pooled 2k–64k (위치 고정효과)"]
    mlab = ["앞 (2k–32k)", "중간 (2k–32k)", "끝 (2k–32k)", "중간 (2k–64k)", "세 위치 합침 (2k–32k)", "세 위치 합침 + 64k 중간"]
    yy = np.arange(len(models))[::-1].astype(float)
    for q, dy in (("Q2", 0.16), ("QL", -0.16)):
        s = t4[(t4.question == q) & (t4.x_kind == "chars")].set_index("model").loc[models]
        eb(axes[0], s.OR_per_doubling, yy + dy, xerr=[s.OR_per_doubling - s.OR_lo, s.OR_hi - s.OR_per_doubling], fmt="o",
                         color=Q_COLORS[q], ms=6, elinewidth=1.2, capsize=2, label=Q_NAMES[q])
        eb(axes[1], s.within_span_dp_per_doubling, yy + dy, xerr=[s.within_span_dp_per_doubling - s.within_dp_lo,
                                                                      s.within_dp_hi - s.within_span_dp_per_doubling],
                         fmt="o", color=Q_COLORS[q], ms=6, elinewidth=1.2, capsize=2)
        for yi, (_, r) in zip(yy + dy, s.iterrows()):
            axes[0].text(2.02, yi, f"{r.OR_per_doubling:.2f} [{r.OR_lo:.2f}, {r.OR_hi:.2f}]", va="center", fontsize=7.5, color=Q_COLORS[q])
            axes[1].text(0.052, yi, f"{r.within_span_dp_per_doubling:+.3f}", va="center", fontsize=7.5, color=Q_COLORS[q])
    axes[0].set_xscale("log")
    axes[0].axvline(1, color=PS.INK_2, lw=0.9)
    axes[0].set_xlim(0.45, 3.2)
    axes[0].set_xticks([0.5, 0.7, 1, 1.4, 2], ["0.5", "0.7", "1", "1.4", "2"])
    axes[0].minorticks_off()
    axes[0].set_xlabel("길이 2배당 탐지 오즈비 (로지스틱, 1 = 변화 없음)")
    axes[1].axvline(0, color=PS.INK_2, lw=0.9)
    axes[1].set_xlim(-0.06, 0.075)
    axes[1].set_xlabel("길이 2배당 평균 p 변화 (span·위치 안 기울기)")
    axes[0].set_yticks(yy, mlab)
    axes[0].legend(loc="lower left", fontsize=8.5)
    for ax in axes:
        ax.grid(axis="y", visible=False)
        ax.axhline(2.5, color=PS.GRID, lw=0.8)
    it = t5[(t5.x_kind == "chars") & t5.term.str.startswith("상호작용 2개")].set_index("question")
    sc = t4[t4.x_kind == "chars"]
    dn = sc[sc.verdict == "길이에 따라 내림"]
    dn_txt = " · ".join(f"{r.question} {mlab[models.index(r.model)]} ×{r.OR_per_doubling:.2f} (순열 Holm p = {r.perm_p_holm:.3f}, "
                        f"두 질문 12개 Holm {r.perm_p_holm_both_q:.3f})" for r in dn.itertuples()) or "없음"
    for ax, col_ in ((axes[0], "verdict"), (axes[1], "within_verdict")):
        for q, dy in (("Q2", 0.16), ("QL", -0.16)):
            s = sc[sc.question == q].set_index("model").loc[models]
            for yi, v in zip(yy + dy, s[col_]):
                if v in ("길이에 따라 내림", "길이에 따라 오름"):
                    ax.text(0.47 if ax is axes[0] else -0.058, yi, "*", fontsize=13, color=Q_COLORS[q], va="center", fontweight="bold")
    PS.title(fig, f"추세 검정: 탐지 오즈가 길이와 함께 유의하게 내려간 모형은 {dn_txt}뿐이다",
             SUB + " · 선 = span 단위 cluster bootstrap 95% 구간 (span 무작위효과 대신, 1,000회) · * = 구간이 0을 빼고 span 안 순열검정 Holm p < 0.05"
                   " (질문마다 6개)\n오른쪽 평균 p 기울기는 (span, 위치) 안에서 뺀 값 (합친 모형에서도 위치 차이가 길이 기울기에 섞이지 않음) · "
                   f"위치 × 길이 상호작용: Wald χ²(2) Q2 p = {it.loc['Q2', 'boot_p']:.2f}, QL p = {it.loc['QL', 'boot_p']:.2f}"
                   "\nx = log2(글자 수); Jev 토큰 수로 맞춘 결과와 두 질문 12개 모형을 함께 Holm 보정한 값은 tables/t04_trend_logistic.csv "
                   "(x_kind = tokens, *_holm_both_q)")
    fig_save(fig, "f04_trend_slopes", out)

    # ---------------- f05 middle position per span trajectories
    t12 = R["t12"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.2), sharey=True)
    xs = np.array(LENS, float)
    src = m.W[m.W.label_int == 1].groupby("idx").source.first()
    sid = m.W[m.W.label_int == 1].groupby("idx").span_id.first()
    for ax, q in zip(axes, QIDS):
        col = Q_COLORS[q]
        P = np.stack([m.p[(q, cond_key(t, "middle"))] for t in LENS])      # lengths x spans
        D2, D64 = m.d[(q, "2k-middle")], m.d[(q, "64k-middle")]
        lost = np.where((D2 == 1) & (D64 == 0))[0]
        for i in range(N_SPANS):
            if i in lost:
                continue
            ax.plot(xs, P[:, i], color=PS.AXIS, lw=0.8, alpha=0.9, zorder=1)
        for i in lost:
            ax.plot(xs, P[:, i], color=col, lw=1.8, marker="o", ms=4, zorder=3)
        lab_y = repel([P[-1, i] for i in lost], 0.04)
        for i, yl in zip(lost, lab_y):
            ax.annotate(f"{sid[i]} {src[i].replace('-Bench', '').replace('-Inject', '')}", (xs[-1], P[-1, i]), xytext=(xs[-1] * 1.12, yl),
                        va="center", fontsize=8, color=col, arrowprops=dict(arrowstyle="-", color=PS.MUTED, lw=0.5))
        ax.plot(xs, P.mean(axis=1), color=PS.INK, lw=2.4, zorder=4, label="40개 평균")
        ax.axhline(0.5, color=PS.INK_2, lw=0.9, ls="--")
        len_axis(ax, False)
        ax.set_xlim(1700, 150000)
        ax.set_title(f"{Q_NAMES[q]} · 2k→64k 중간에서 잃은 span {len(lost)}개 (색), 얻은 span "
                     f"{int(((D2 == 0) & (D64 == 1)).sum())}개", fontsize=10.5, color=col)
    axes[0].set_ylabel("중간 위치 p (3회 평균)")
    axes[0].set_ylim(-0.02, 1.02)
    axes[0].legend(loc="lower left", fontsize=8.5)
    n_art = int((t12.article_64k_middle != t12.article_2k_middle).sum()) if len(t12) else 0
    PS.title(fig, "중간 위치의 p는 span마다 길이를 따라 오르내린다. 64k에서 0.5 아래로 내려간 span은 Q2 6개, QL 3개",
             SUB + " · 회색 = 나머지 span · 중간 삽입 지점은 길이마다 다른 문장 옆이라(64k는 40개 중 39개가 2k와 다른 위키 문서 안)\n"
                   f"길이 효과와 주변 문장 효과가 섞여 있음 · 바뀐 span의 앞뒤 문장은 tables/t12_middle_2k_vs_64k_changes.csv ({len(t12)}개, 그중 다른 문서 {n_art}개)")
    fig_save(fig, "f05_middle_per_span", out)

    # ---------------- f06 span alone vs inside a carrier
    t3 = R["t03"]
    fig, axes = plt.subplots(1, 3, figsize=(17, 5.8), gridspec_kw={"width_ratios": [1, 1, 1.15]})
    for ax, q in zip(axes[:2], QIDS):
        col = Q_COLORS[q]
        a, b_ = m.p[(q, "alone")], m.p[(q, "2k-middle")]
        ax.scatter(a, b_, s=34, color=col, alpha=0.75, edgecolor=PS.SURFACE, linewidth=0.8)
        ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=0.8)
        ax.axvline(0.5, color=PS.INK_2, lw=0.8, ls="--")
        ax.axhline(0.5, color=PS.INK_2, lw=0.8, ls="--")
        da, db = (a >= 0.5).astype(int), (b_ >= 0.5).astype(int)
        for (x0, y0, ha, va, cnt, txt) in ((0.25, 0.98, "center", "top", int(((da == 0) & (db == 1)).sum()), "단독 놓침 → 2k 중간 잡음"),
                                           (0.75, 0.02, "center", "bottom", int(((da == 1) & (db == 0)).sum()), "단독 잡음 → 2k 중간 놓침"),
                                           (0.75, 0.98, "center", "top", int(((da == 1) & (db == 1)).sum()), "둘 다 잡음"),
                                           (0.25, 0.02, "center", "bottom", int(((da == 0) & (db == 0)).sum()), "둘 다 놓침")):
            ax.text(x0, y0, f"{txt}\n{cnt}개", ha=ha, va=va, fontsize=8.5, color=PS.INK,
                    bbox=dict(boxstyle="round,pad=0.3", fc=PS.SURFACE, ec=PS.GRID, lw=0.8, alpha=0.7))
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        ax.set_xlabel("span 단독 p")
        r = t3[(t3.question == q) & (t3.condition == "2k-middle")].iloc[0]
        ax.set_title(f"{Q_NAMES[q]} · McNemar p = {r.mcnemar_p:.1e}", fontsize=10.5, color=col)
    axes[0].set_ylabel("같은 span, 2k 중간 p")
    # by source: alone vs 2k middle vs 2k start TPR
    ax = axes[2]
    t10 = R["t10"]
    yy = np.arange(len(SOURCES))[::-1].astype(float)
    for q, dy in (("Q2", 0.17), ("QL", -0.17)):
        s = t10[t10.question == q].set_index("source").loc[list(SOURCES)]
        for k, mk, fc in (("alone", "D", PS.SURFACE), ("2k-start", "^", PS.SURFACE), ("2k-middle", "o", Q_COLORS[q])):
            ax.scatter(s[f"TPR_{k}"], yy + dy, marker=mk, s=42, facecolor=fc, edgecolor=Q_COLORS[q], linewidth=1.4, zorder=3)
        for yi, (_, r) in zip(yy + dy, s.iterrows()):
            lo, hi = sorted([r["TPR_alone"], r["TPR_2k-middle"]])
            ax.plot([lo, hi], [yi, yi], color=Q_COLORS[q], lw=1, alpha=0.6, zorder=2)
    ax.set_yticks(yy, [f"{s.replace('-Bench', '').replace('-Inject', '')} (n={int(t10[(t10.question == 'Q2') & (t10.source == s)].n_spans.iloc[0])})" for s in SOURCES])
    ax.set_xlim(-0.03, 1.03)
    ax.set_xticks(np.linspace(0, 1, 5), [pct(v, 0) for v in np.linspace(0, 1, 5)])
    ax.set_xlabel("탐지율 (출처별 span 6–7개)")
    ax.grid(axis="y", visible=False)
    ax.set_title("출처별: ◇ 단독 · △ 2k 앞 · ● 2k 중간 (파랑 Q2 / 주황 QL)", fontsize=10)
    r2, rl = (t3[(t3.question == q) & (t3.condition == "2k-middle")].iloc[0] for q in QIDS)
    PS.title(fig, f"span만 따로 판정하면 오히려 덜 잡는다: 단독에서 놓친 span을 2k 글 가운데에서는 Q2 {int(r2.gained)}개, QL {int(rl.gained)}개 잡고 반대는 "
                  f"{int(r2.lost)}개 / {int(rl.lost)}개",
             SUB + "\n출처별 단독 탐지 (Q2 · QL): " + " / ".join(
                 f"{s_.replace('-Bench', '').replace('-Inject', '')} {int(round(t10[(t10.question == 'Q2') & (t10.source == s_)].TPR_alone.iloc[0] * n_))}/{n_}"
                 f" · {int(round(t10[(t10.question == 'QL') & (t10.source == s_)].TPR_alone.iloc[0] * n_))}/{n_}"
                 for s_, n_ in ((s_, int(t10[(t10.question == 'Q2') & (t10.source == s_)].n_spans.iloc[0])) for s_ in SOURCES)))
    fig_save(fig, "f06_alone_vs_carrier", out)

    # ---------------- f07 position effect
    t6 = R["t06"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), gridspec_kw={"width_ratios": [1.25, 1]})
    ax = axes[0]
    comps = ["중간 − 앞", "끝 − 앞", "끝 − 중간"]
    rows_ = [(c, t) for c in comps for t in list(LENS[:-1]) + ["2k–32k 평균"]]
    yy = np.arange(len(rows_))[::-1].astype(float)
    for q, dy in (("Q2", 0.17), ("QL", -0.17)):
        s = t6[t6.question == q]
        vals = [s[(s.comparison == c) & (s.target_chars.astype(str) == str(t))].iloc[0] for c, t in rows_]
        v = np.array([r.d_rate for r in vals])
        lo = np.array([r.d_rate_lo for r in vals])
        hi = np.array([r.d_rate_hi for r in vals])
        eb(ax, v, yy + dy, xerr=[v - lo, hi - v], fmt="o", color=Q_COLORS[q], ms=5, elinewidth=1.1, capsize=2, label=Q_NAMES[q])
    ax.set_yticks(yy, [f"{c}  {LK[t] if isinstance(t, int) else t}" for c, t in rows_], fontsize=8.5)
    ax.axvline(0, color=PS.INK_2, lw=0.9)
    for b_ in (5.5, 11.5):
        ax.axhline(b_, color=PS.GRID, lw=0.8)
    ax.set_xlim(-0.25, 0.6)
    ax.set_xticks([-0.2, 0, 0.2, 0.4, 0.6], ["−20", "0", "+20", "+40", "+60"])
    ax.set_xlabel("TPR 차이 (%p, 같은 길이·같은 span 짝 비교)")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="lower right", fontsize=8.5)
    ax.set_title("위치 사이의 탐지율 차이", fontsize=10.5)
    ax = axes[1]
    yy = np.arange(len(SOURCES))[::-1].astype(float)
    for q, dy in (("Q2", 0.17), ("QL", -0.17)):
        s = t10[t10.question == q].set_index("source").loc[list(SOURCES)]
        for p_, mk, fc in (("start", "^", PS.SURFACE), ("middle", "o", Q_COLORS[q]), ("end", "s", PS.SURFACE)):
            ax.scatter(s[f"TPR_2k_32k_{p_}"], yy + dy, marker=mk, s=40, facecolor=fc, edgecolor=Q_COLORS[q], linewidth=1.4, zorder=3)
        for yi, (_, r) in zip(yy + dy, s.iterrows()):
            ax.plot([r.TPR_2k_32k_start, max(r.TPR_2k_32k_middle, r.TPR_2k_32k_end)], [yi, yi], color=Q_COLORS[q], lw=1, alpha=0.6)
    ax.set_yticks(yy, [s.replace("-Bench", "").replace("-Inject", "") for s in SOURCES])
    ax.set_xlim(-0.03, 1.03)
    ax.set_xticks(np.linspace(0, 1, 5), [pct(v, 0) for v in np.linspace(0, 1, 5)])
    ax.set_xlabel("탐지율 (2k–32k 5개 길이 평균, 출처별 span 6–7개)")
    ax.grid(axis="y", visible=False)
    ax.set_title("출처별: △ 앞 · ● 중간 · □ 끝", fontsize=10.5)
    ps = t6[t6.target_chars.astype(str) == "2k–32k 평균"].set_index(["question", "comparison"])
    PS.title(fig, f"문서 맨 앞의 span은 덜 잡힌다: 중간 − 앞 {pp(ps.loc[('Q2', '중간 − 앞'), 'd_rate'])} (Q2), "
                  f"{pp(ps.loc[('QL', '중간 − 앞'), 'd_rate'])} (QL), 끝 − 중간은 차이 없음",
             SUB + " · 선 = span 단위 짝 부트스트랩 95% 구간 · '2k–32k 평균' = span마다 5개 길이에서 잡힌 비율의 차이\n"
                   "앞 위치는 span 바로 뒤 문장이 길이와 관계없이 같아, 길이만 바뀌는 가장 깨끗한 비교이기도 함")
    fig_save(fig, "f07_position_effect", out)

    # ---------------- f08 AUC by length + 01_baseline quartiles
    t7, t18 = R["t07"], R["t18"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), sharey=True)
    for ax, q in zip(axes, QIDS):
        col = Q_COLORS[q]
        s = t7[(t7.question == q) & (t7.positions == "전체 위치")]
        eb(ax, s.target_chars, s.AUC, yerr=[s.AUC - s.AUC_lo, s.AUC_hi - s.AUC], fmt="-o", color=col, ms=6, elinewidth=1, capsize=2,
                    label="04_length: 같은 span, 위키 carrier (인젝션 120 vs 정상 40, 64k는 40 vs 40)")
        for nm, mk, ls in (("01_baseline 전체 출처", "s", "--"), ("01_baseline BrowseSafe 제외", "^", ":")):
            b = t18[(t18.question == q) & (t18.set == nm)]
            ax.plot(b.median_chars, b.AUC, marker=mk, ls=ls, color=col, mfc=PS.SURFACE, mec=col, ms=7, lw=1.4,
                    label=f"{nm} (길이 사분위, 점 = 구간 중앙값 글자 수)")
        b = t18[(t18.question == q) & (t18.set == "01_baseline 전체 출처")]
        last = b.iloc[-1]
        ax.annotate(f">1254자 {last.AUC:.3f}\n(정상 중 BrowseSafe {pct(last.share_BrowseSafe_benign, 0)})", (last.median_chars, last.AUC),
                    xytext=(last.median_chars * 1.45, last.AUC + 0.012), va="bottom", fontsize=8, color=PS.INK_2,
                    arrowprops=dict(arrowstyle="-", color=PS.MUTED, lw=0.6))
        ax.set_xscale("log")
        ax.set_xticks([200, 500, 1000, 2000, 4000, 8000, 16000, 32000, 64000], ["200", "500", "1k", "2k", "4k", "8k", "16k", "32k", "64k"])
        ax.minorticks_off()
        ax.set_xlim(120, 90000)
        ax.set_xlabel("문서 길이 (글자, 로그 축)")
        ax.set_title(Q_NAMES[q], fontsize=11.5, color=col)
        ax.legend(loc="lower left", fontsize=7.8)
    axes[0].set_ylim(0.86, 1.005)
    axes[0].set_ylabel("AUC (인젝션 vs 같은 길이 정상)")
    mn = t7[t7.positions == "전체 위치"].AUC.min()
    PS.title(fig, f"길이만 늘린 위키 carrier에서는 AUC가 64k자까지 {mn:.3f} 이상이다. 기준선의 긴 문서 AUC 하락은 길이만으로는 설명되지 않는다",
             f"04_length: {MODEL} · 임계값 무관 · 선 = stream 단위 부트스트랩 95% 구간 · 01_baseline: EN 1,000건을 결과 전에 고정한 글자 수 사분위로 나눔"
             "\n01_baseline >1254자 구간의 정상 문서에는 BrowseSafe HTML이 몰려 있고, 빼면 AUC가 다시 0.98 수준 (같은 문서·같은 출처가 아니므로 참고 비교)")
    fig_save(fig, "f08_auc_by_length", out)

    # ---------------- f09 benign p distribution
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4), sharey=True)
    rng = np.random.default_rng(SEED)
    for ax, q in zip(axes, QIDS):
        for j, t in enumerate(LENS):
            p = m.p[(q, f"benign-{LK[t]}")]
            x = t * np.exp(rng.uniform(-0.12, 0.12, len(p)))
            ax.scatter(x, p, s=16, color=BEN, alpha=0.75, edgecolor="none")
            ax.plot([t / 1.18, t * 1.18], [p.mean()] * 2, color=PS.INK, lw=2)
            ax.text(t, p.max() + 0.012, f"최대 {p.max():.2f}", ha="center", fontsize=7.5, color=PS.INK_2)
        len_axis(ax, False)
        ax.set_xlim(1500, 85000)
        ax.set_title(f"{Q_NAMES[q]} · 정상 carrier 길이마다 40개", fontsize=10.5, color=Q_COLORS[q])
        ax.axhline(0.5, color=PS.INK_2, lw=0.8, ls="--")
        b8q = R["t08"][R["t08"].question == q].iloc[0]
        ax.text(0.02, 0.95, f"carrier 안 기울기: 길이 2배당 p {b8q.within_carrier_dp_per_doubling:+.4f} [{b8q.within_dp_lo:+.4f}, {b8q.within_dp_hi:+.4f}]",
                transform=ax.transAxes, fontsize=8.5, color=PS.INK_2, va="top")
    axes[0].set_ylabel("정상 carrier p (3회 평균)")
    axes[0].set_ylim(0, 0.55)
    PS.title(fig, "정상 carrier의 p는 길이와 함께 조금 오르지만 최대 0.17로, 임계값 0.5와는 멀다 (오탐 0/240)",
             f"청록 점 = 깨끗한 위키 carrier 1개 · 검은 선 = 평균 · 점선 = 임계값 0.5 · {MODEL} · 3회 평균 p")
    fig_save(fig, "f09_benign_p_by_length", out)

    # ---------------- f10 tokens and latency
    t9, fits = R["t09"], R["fits"]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    ax = axes[0]
    for q in QIDS:
        g = m.W
        ax.scatter(g.text_chars.clip(lower=20), g[f"input_tokens_{q}"], s=9, color=Q_COLORS[q], alpha=0.55, edgecolor="none",
                   label=f"{Q_NAMES[q]}: {fits[q]['tokens_per_char']:.3f}토큰/자 + {fits[q]['overhead_tokens']:.0f}")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.axhline(64000, color=PS.INK_2, lw=0.8, ls="--")
    ax.text(40, 70000, "요청 상한 64k토큰", fontsize=8, color=PS.INK_2)
    ax.set_xlim(25, 90000)
    ax.set_ylim(200, 100000)
    ax.set_xlabel("문서 글자 수 (로그 축)")
    ax.set_ylabel("Jev usage.input_tokens (호출 1건, 로그 축)")
    ax.legend(loc="center left", bbox_to_anchor=(0, 0.6), fontsize=8.5)
    ax.set_xticks([30, 100, 300, 1000, 3000, 10000, 30000], ["30", "100", "300", "1k", "3k", "10k", "30k"])
    ax.set_yticks([300, 1000, 3000, 10000, 30000], ["300", "1k", "3k", "10k", "30k"])
    ax.minorticks_off()
    ax.set_title("입력 토큰 = 글자 수 × 0.23 + 질문 overhead", fontsize=10.5)
    ax = axes[1]
    for q, off in (("Q2", 0.95), ("QL", 1.05)):
        tq = t9[t9.question == q]
        s = pd.DataFrame([{"target_chars": t, "mean": (g.latency_ms_mean * g.calls).sum() / g.calls.sum(), "p90": g.latency_ms_p90.max()}
                          for t, g in tq.groupby("target_chars")])
        x = np.where(s.target_chars == 0, ALONE_X, s.target_chars) * off
        ax.plot(x, s["mean"], "-o", color=Q_COLORS[q], ms=6, label=f"{q} 평균")
        ax.plot(x, s["p90"], ":", marker="v", color=Q_COLORS[q], ms=5, label=f"{q} 상위 10% (길이별 최대)")
    len_axis(ax, True)
    ax.set_ylim(0, 2000)
    ax.set_ylabel("응답 시간 (ms, 한국 노트북 → 공식 API, 동시 6개)")
    ax.legend(loc="upper left", fontsize=8.5, ncol=2)
    ax.set_title(f"응답 시간: 1,000토큰당 +{fits['Q2']['latency_ms_per_1k_tokens']:.1f}ms (Q2), +{fits['QL']['latency_ms_per_1k_tokens']:.1f}ms (QL)", fontsize=10.5)
    tot = sum(R["raws"][q].usage_input_tokens.sum() for q in QIDS)
    PS.title(fig, f"64k자 문서도 약 15k토큰(상한의 4분의 1)이고, 응답 시간은 길이 32배에도 거의 그대로다",
             f"호출 {sum(len(R['raws'][q]) for q in QIDS):,}건 · 실제 입력 토큰 {tot:,} · 입력 비용 \\${tot * PRICE_IN:.3f} (\\$0.042 / 100만 토큰) · "
             "두 질문은 다른 시간대에 실행 (Q2 09:48, QL 09:57 UTC)")
    fig_save(fig, "f10_tokens_latency", out)

    # ---------------- f11 by source
    fig, axes = plt.subplots(2, 3, figsize=(15, 8.2), sharex=True, sharey=True)
    for ax, s in zip(axes.ravel(), SOURCES):
        ii = np.array([i for i in range(N_SPANS) if src[i] == s])
        for q, off in (("Q2", 0.96), ("QL", 1.04)):
            ys, los, his = [], [], []
            for t in LENS[:-1]:
                v = np.concatenate([m.d[(q, cond_key(t, p_))][ii] for p_ in POS])
                lo, hi = J.wilson(int(v.sum()), len(v))
                ys.append(v.mean()), los.append(lo), his.append(hi)
            x = np.array(LENS[:-1], float) * off
            ys, los, his = map(np.array, (ys, los, his))
            eb(ax, x, ys, yerr=[ys - los, his - ys], fmt="-o", color=Q_COLORS[q], ms=5, elinewidth=0.8, capsize=2, label=q)
            v64 = m.d[(q, "64k-middle")][ii]
            ax.scatter([64000 * off], [v64.mean()], marker="o", s=46, facecolor=PS.SURFACE, edgecolor=Q_COLORS[q], linewidth=1.6, zorder=4)
            va = m.d[(q, "alone")][ii]
            ax.scatter([ALONE_X * off], [va.mean()], marker="D", s=36, facecolor=PS.SURFACE, edgecolor=Q_COLORS[q], linewidth=1.4, zorder=4)
        len_axis(ax, True, label=False)
        ax.set_xlim(ALONE_X * 0.8, 85000)
        ax.set_title(f"{s} (span {len(ii)}개)", fontsize=10.5)
        ax.set_ylim(-0.03, 1.05)
        ax.set_yticks(np.linspace(0, 1, 5), [pct(v, 0) for v in np.linspace(0, 1, 5)])
    for ax in axes[1]:
        ax.set_xlabel("carrier 길이 (글자, 로그 축)")
    axes[0, 0].legend(loc="lower right", fontsize=8.5)
    PS.title(fig, "출처별로 보면 차이는 길이가 아니라 출처와 단독·위치에서 난다: BIPIA·SEP는 어느 길이에서도 낮고, 길이에 따른 방향은 일정하지 않다",
             SUB + "\n2k–32k 점 = 그 출처 span의 앞·중간·끝 판정을 합친 비율 (같은 span이 3번 들어가 Wilson 구간은 근사) · 64k 점 = 중간만 · "
                   "◇ = span 단독 · 출처마다 span 6–7개라 해석은 탐색적")
    fig_save(fig, "f11_by_source", out)

    # ---------------- f12 local-context noise
    t13 = R["t13"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 6.6), gridspec_kw={"width_ratios": [1, 1.1]})
    ax = axes[0]
    for j, q in enumerate(QIDS):
        for k, p_ in enumerate(POS):
            sd = np.std(np.stack([m.p[(q, cond_key(t, p_))] for t in LENS[:-1]]), axis=0)
            x0 = k + (j - 0.5) * 0.36
            ax.scatter(x0 + rng.uniform(-0.09, 0.09, len(sd)), sd, s=14, color=Q_COLORS[q], alpha=0.55, edgecolor="none")
            r = t13[(t13.question == q) & (t13.position == p_)].iloc[0]
            eb(ax, [x0], [r.mean_sd_p_2k_32k], yerr=[[r.mean_sd_p_2k_32k - r.sd_lo], [r.sd_hi - r.mean_sd_p_2k_32k]], fmt="_",
                        color=PS.INK, ms=18, mew=2.2, elinewidth=1.2, capsize=3, zorder=5)
            ax.text(x0, r.sd_hi + 0.012, f"{r.mean_sd_p_2k_32k:.3f}", ha="center", fontsize=8, color=PS.INK)
    ax.set_xticks(range(3), ["앞\n(앞뒤 문장 같음)", "중간\n(앞뒤 문장 바뀜)", "끝\n(앞 문장 바뀜)"])
    ax.set_ylabel("span 하나의 p 표준편차 (2k–32k 다섯 길이)")
    ax.set_ylim(0, 0.32)
    ax.grid(axis="x", visible=False)
    ax.legend(handles=[Line2D([0], [0], marker="o", ls="none", color=Q_COLORS[q], label=Q_NAMES[q]) for q in QIDS], loc="upper left", fontsize=8.5)
    ax.set_title("길이를 바꿀 때 span 하나의 p가 흔들리는 정도 (— = 평균, 95% 구간)", fontsize=10)
    ax = axes[1]
    sub = t13[t13.position.str.match(r"^middle \d") & ~t13.neighbour_text_across_lengths.str.startswith("같은 문서 −")]
    keys_ = list(dict.fromkeys(zip(sub.position, sub.neighbour_text_across_lengths)))
    yy = np.arange(len(keys_))[::-1].astype(float)
    labs = []
    for (pos_, nb_) in keys_:
        n_ = int(sub[(sub.position == pos_) & (sub.neighbour_text_across_lengths == nb_)].n_spans.iloc[0])
        a_, r_ = pos_.split()[1], pos_.split()[3]
        nb_s = "같은 문서" if nb_.endswith("같은 위키 문서 안") else "다른 문서" if nb_ == "다른 위키 문서 안" else "전체"
        labs.append(f"{r_}→{a_} · {nb_s} (n={n_})")
    for q, dy in (("Q2", 0.14), ("QL", -0.14)):
        s = sub[sub.question == q].set_index(["position", "neighbour_text_across_lengths"]).loc[keys_]
        has = s.d_mean_p_lo.notna().to_numpy()
        v = s.d_mean_p_vs_ref.to_numpy()
        eb(ax, v[has], (yy + dy)[has], xerr=[v[has] - s.d_mean_p_lo.to_numpy()[has], s.d_mean_p_hi.to_numpy()[has] - v[has]],
           fmt="o", color=Q_COLORS[q], ms=5, elinewidth=1.1, capsize=2, label=Q_NAMES[q], zorder=3)
        ax.scatter(v[~has], (yy + dy)[~has], marker="o", s=26, facecolor=PS.SURFACE, edgecolor=Q_COLORS[q], linewidth=1.3, zorder=3)
        for yi, (_, r) in zip(yy + dy, s.iterrows()):
            ax.text(0.112, yi, f"{int(r.lost)}/{int(r.gained)}", va="center", fontsize=7.5, color=Q_COLORS[q])
    ax.set_yticks(yy, labs, fontsize=8.2)
    ax.axvline(0, color=PS.INK_2, lw=0.9)
    n_ref2 = sum(1 for k_ in keys_ if k_[0].split()[3] == "2k")
    ax.axhline(yy[n_ref2 - 1] - 0.5, color=PS.GRID, lw=0.9)
    ax.set_xlim(-0.24, 0.15)
    ax.set_xlabel("Δ평균 p (같은 span, 기준 길이 중간 대비) · 선 = 95% 구간 · 오른쪽 = 잃음/얻음")
    ax.grid(axis="y", visible=False)
    ax.legend(loc="upper left", fontsize=8.5)
    ax.set_title("중간 위치: 기준 길이와 같은 위키 문서 안 vs 다른 문서 안 (○ = n < 3, 구간 없음)", fontsize=9.5)
    dd = t13[(t13.question == "Q2") & (t13.position == "middle − start")].iloc[0]
    sd_rows = t13[t13.neighbour_text_across_lengths.str.startswith("같은 문서 −")]
    n_sd_ci = int(sd_rows.verdict.str.startswith("차이 없음").sum())
    PS.title(fig, "주변 문장이 바뀌면 p가 더 흔들린다. 같은 문서 / 다른 문서로 나눈 중간 위치 하락은 방향이 섞여 있어 길이와 문서 변경을 가르지 못한다",
             SUB + f" · 중간 − 앞 평균 SD (Q2) {dd.mean_sd_p_2k_32k:+.3f} [{dd.sd_lo:+.3f}, {dd.sd_hi:+.3f}]"
                   f"\n오른쪽: 문서 구분은 CARRIERS.md의 문서 길이로 계산 · 구간 = span 단위 부트스트랩 (부분집합) · 같은 문서 − 다른 문서 차이 "
                   f"{len(sd_rows)}개 중 {n_sd_ci}개가 오차 범위 (tables/t13_local_context.csv) · 32k→64k는 탐색 비교")
    fig_save(fig, "f12_local_context", out)

    # ---------------- f13 vs 01_baseline original docs and X3
    t17 = R["t17"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), sharey=True)
    for ax, q in zip(axes, QIDS):
        col = Q_COLORS[q]
        s = t17[(t17.question == q) & t17.comparison.str.contains("01_baseline")]
        items = [("01_baseline 원래 문서", s.iloc[0].rate_ref, len(spans_glob), "s")]
        for r in s.itertuples():
            k = r.comparison.split()[1]
            items.append((f"04 {POS_KO[k.split('-')[1]] if '-' in k else '단독'} {k.split('-')[0] if '-' in k else ''}".strip(), r.rate, 40,
                          "D" if k == "alone" else POS_STYLE[k.split('-')[1]]["marker"]))
        x3s = t17[(t17.question == q) & t17.comparison.str.contains("X3")]
        r_w = x3s[x3s.comparison.str.contains("위키") & x3s.comparison.str.contains("2k-middle")].iloc[0]
        r_e = x3s[x3s.comparison.str.contains("Enron") & x3s.comparison.str.contains("2k-middle")].iloc[0]
        items += [("— 겹치는 span 16개 —", None, None, None), ("X3 위키 발췌 가운데 (약 1.4k자)", r_w.rate_ref, int(r_w.n_spans), "o"),
                  ("04 중간 2k (같은 16개)", r_w.rate, int(r_w.n_spans), "o"), ("X3 Enron 메일 가운데", r_e.rate_ref, int(r_e.n_spans), "s")]
        yy = np.arange(len(items))[::-1].astype(float)
        for yi, (nm, v, n, mk) in zip(yy, items):
            if v is None:
                continue
            k_ = int(round(v * n))
            lo, hi = J.wilson(k_, n)
            eb(ax, [v], [yi], xerr=[[v - lo], [hi - v]], fmt=mk, color=col, mfc=col if mk == "o" else PS.SURFACE, mec=col, ms=7,
                        elinewidth=1, capsize=2)
            ax.text(min(hi, 1.0) + 0.02, yi, f"{pct(v)} ({k_}/{n})", va="center", fontsize=8, color=PS.INK_2)
        ax.set_yticks(yy, [it[0] for it in items], fontsize=8.5)
        ax.set_xlim(0, 1.18)
        ax.set_xticks(np.linspace(0, 1, 6), [pct(v, 0) for v in np.linspace(0, 1, 6)])
        ax.set_xlabel("탐지율 (p ≥ 0.5) · 선 = Wilson 95% 구간")
        ax.grid(axis="y", visible=False)
        ax.set_title(Q_NAMES[q], fontsize=11.5, color=col)
    o = t17[(t17.question == "Q2") & (t17.comparison == "04 2k-middle − 01_baseline 원래 문서")].iloc[0]
    oq = t17[(t17.question == "QL") & (t17.comparison == "04 2k-middle − 01_baseline 원래 문서")].iloc[0]
    PS.title(fig, f"같은 span이 원래 문서에서는 Q2 {pct(o.rate_ref)} 잡혔고, 위키 글 가운데(2k)로 옮기면 {pct(o.rate)}로 높아지는 경향이다 "
                  f"(탐색적, Holm p = {o.mcnemar_p_holm:.2f} / QL {oq.mcnemar_p_holm:.2f})",
             f"같은 span 40개의 01_baseline 원래 문서(중앙값 {o.ref_doc_chars_median:.0f}자, {o.ref_doc_chars_min}–{o.ref_doc_chars_max}자) vs 04_length 조건 · "
             "X3와 겹치는 span 16개는 X3 carrier와 비교\n서로 다른 시각의 실행끼리 비교 (01_baseline·X3 06–08시 UTC, 04_length 09–10시 UTC) · 짝 McNemar는 tables/t17_vs_baseline_and_x3.csv")
    fig_save(fig, "f13_vs_baseline_x3", out)

    # ---------------- f14 thresholds fixed from 01_baseline
    t16 = R["t16"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.6), sharey=True)
    for ax, q in zip(axes, QIDS):
        col = Q_COLORS[q]
        fps = []
        for target, ls, mk in (("기준 0.5", "-", "o"), ("오탐 5% 이하", "--", "s")):
            s = t16[(t16.question == q) & (t16.threshold_source == f"01_baseline {target}")].set_index("condition")
            thr = s.threshold.iloc[0]
            ys = [s.loc[cond_key(t, "middle"), "rate"] for t in LENS]
            ax.plot(LENS, ys, ls=ls, marker=mk, color=col, ms=6, mfc=col if mk == "o" else PS.SURFACE, mec=col,
                    label=f"중간 · 임계값 {thr:.3f} ({target})")
            ysa = [s.loc[cond_key(t, "start"), "rate"] for t in LENS[:-1]]
            ax.plot(LENS[:-1], ysa, ls=ls, marker="^", color=col, ms=6, mfc=PS.SURFACE, mec=col, alpha=0.6,
                    label=f"앞 · 임계값 {thr:.3f}")
            ax.scatter([ALONE_X], [s.loc["alone", "rate"]], marker="D", s=46, facecolor=PS.SURFACE if ls == "-" else col, edgecolor=col,
                       linewidth=1.5, zorder=4)
            fp = sum(s.loc[f"benign-{LK[t]}", "detected"] for t in LENS)
            fps.append(f"{thr:.3f}에서 {int(fp)}/240")
            r64 = s.loc["64k-middle"]
            ax.text(64000 * 1.15, ys[-1], f"64k−2k {pp(r64.d_vs_2k_middle)}\n(잃음 {int(r64.lost_vs_2k_middle)} / 얻음 {int(r64.gained_vs_2k_middle)})",
                    fontsize=7.8, color=col, ha="left", va="center")
        len_axis(ax, True)
        ax.set_xlim(ALONE_X * 0.8, 200000)
        ax.set_ylim(0, 1.05)
        ax.set_yticks(np.linspace(0, 1, 6), [pct(v, 0) for v in np.linspace(0, 1, 6)])
        ax.set_title(f"{Q_NAMES[q]} · 정상 carrier 오탐 " + ", ".join(fps), fontsize=11, color=col)
        ax.legend(loc="lower center", fontsize=7.8, ncol=2)
    axes[0].set_ylabel("인젝션 탐지율")
    f5 = t16[(t16.threshold_source == "01_baseline 오탐 5% 이하") & (t16.condition == "64k-middle")].set_index("question")
    PS.title(fig, f"01_baseline에서 고정한 오탐 5% 임계값을 쓰면 탐지율이 모든 길이에서 오른다. 64k 중간 하락은 Q2 {pp(f5.loc['Q2', 'd_vs_2k_middle'])}로 "
                  f"남고 QL은 {pp(f5.loc['QL', 'd_vs_2k_middle'])}",
             SUB.replace(" · 임계값 0.5", "") + " · 임계값은 01_baseline EN 1,000건에서 맞춘 값을 그대로 씀 (이 데이터에서 다시 맞추지 않음)")
    fig_save(fig, "f14_fixed_baseline_thresholds", out)
    return out


spans_glob = []


# ------------------------------------------------------------------ main
def main():
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    W, raws, spans, text, summary = load()
    spans_glob[:] = list(spans.span_id)
    m = M(W)
    R = {"raws": raws}
    R["t01"] = t01_conditions(m)
    R["t02"] = t02_vs_2k(m)
    R["t03"] = t03_vs_alone(m)
    R["t04"], R["t05"], boots = t04_trend(m)
    R["t06"] = t06_position(m)
    R["t07"] = t07_auc(m)
    R["t08"] = t08_benign(m)
    R["t09"], R["fits"] = t09_tokens(m, raws)
    R["t10"] = t10_by_source(m)
    R["t11"] = t11_per_span(m, spans)
    R["t12"] = t12_middle_changes(m, spans)
    R["t13"] = t13_local_context(m)
    R["t14"] = t14_q2_vs_ql(m, boots)
    R["t15"] = t15_stability(m)
    R["t16"] = t16_fixed_thresholds(m)
    R["t17"], R["t18"], R["t17b"] = t17_other_experiments(m, spans)
    figs = figures(m, R)

    # ---------------- summary.json "analysis"
    sp = os.path.join(OUT, "summary.json")
    s = json.load(open(sp, encoding="utf-8"))
    t1, t2, t3, t4, t5, t6, t7, t8 = (R[k] for k in ("t01", "t02", "t03", "t04", "t05", "t06", "t07", "t08"))

    def rec(df, cols):
        return df[cols].to_dict("records")

    tok_rows = R["t09"][R["t09"].label == "benign"]
    ctx = {q: {"tokens_2k": float(tok_rows[(tok_rows.question == q) & (tok_rows.target_chars == 2000)].mean_input_tokens.iloc[0]),
               "tokens_32k": float(tok_rows[(tok_rows.question == q) & (tok_rows.target_chars == 32000)].mean_input_tokens.iloc[0]),
               "tokens_64k": float(tok_rows[(tok_rows.question == q) & (tok_rows.target_chars == 64000)].mean_input_tokens.iloc[0])} for q in QIDS}
    analysis = {
        "script": "experiments/analyze_04_length.py",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis_commit": J.git_commit(),
        "data_checks": {"inputs_md5": md5_file(DOCS), "text_md5": "every raw call's text_md5 equals md5(input text) (asserted)",
                        "predictions": "p_run0..2 equal the raw calls and p is their mean (asserted); p snapped to the 1/300 grid",
                        "tokens": "usage.input_tokens identical across the 3 runs of a text (asserted)",
                        "article_table": "CARRIERS.md article lengths reproduce n_articles of every clean carrier (asserted)"},
        "methods": {"metrics": "src.jev_guard.metrics(threshold=0.5)", "proportion_ci": "Wilson 95%",
                    "paired_unit": "span i <-> stream i (40); every comparison pairs the same spans / carriers",
                    "paired_test": "exact McNemar on 0.5 decisions; Wilcoxon signed-rank on p differences",
                    "bootstrap": {"resamples": B, "seed": SEED, "unit": "span (= stream) index, one shared index matrix", "ci": "percentile 95%"},
                    "holm_families": {"vs_2k": "13 per question", "vs_alone": "16 per question", "position": "15 per question",
                                      "benign_vs_2k": "5 per question", "q2_vs_ql": "23 conditions", "by_source": "6 per question",
                                      "trend": "6 models per question and x (reference: 12 over both questions)",
                                      "local_context_subgroups": "same / different article subgroups with n >= 3 per question (Wilcoxon)"},
                    "verdict": "direction only if bootstrap CI excludes 0 AND Holm p < 0.05; CI covers 0 -> 차이 없음 (오차 범위)",
                    "trend": ("logistic regression of detection on log2(text chars / 2000) (also log2 Jev input tokens), unpenalised IRLS; "
                              "span random effect approximated by span cluster bootstrap (1000, seed 20261112) for the CI; test = "
                              f"within-(span, position) permutation of the length labels ({N_PERM:,}, seed 20261112; score test of "
                              "span-stratified logistic regression), Holm over the 6 models per question and x; a direction needs CI "
                              "excluding 0 AND Holm permutation p < 0.05 (perm_p_holm_both_q: Holm over both questions' 12 "
                              "models, reference only). Interaction model with one slope per position, joint Wald "
                              "test with the bootstrap covariance. Mean p: OLS slope after removing (span, position) block means "
                              "(span and position fixed effects, in the point estimate and inside every bootstrap resample), same "
                              "blocks as the permutation test"),
                    "auc": "injected docs at a length (all positions or one) vs the 40 clean carriers of that length; stream bootstrap",
                    "local_context": ("start keeps the same following text at every length; end keeps the document end but gets a new "
                                      "preceding sentence; middle gets new neighbours at every length. Same / different Wikipedia "
                                      "article subgroups: domain bootstrap with the shared index matrix (subset mean over the "
                                      "resampled spans in the subset), Wilcoxon + Holm per question; 32k-middle -> 64k-middle split "
                                      "by article is an exploratory partial control for the article change")},
        "conditions": rec(t1, ["question", "condition", "n", "detected", "rate", "rate_lo", "rate_hi", "mean_p", "mean_p_lo", "mean_p_hi",
                               "mean_input_tokens", "flips"]),
        "vs_2k": rec(t2, ["question", "condition", "d_rate", "d_rate_lo", "d_rate_hi", "lost", "gained", "mcnemar_p", "mcnemar_p_holm",
                          "dTPR_verdict", "d_mean_p", "d_mean_p_lo", "d_mean_p_hi", "wilcoxon_p", "wilcoxon_p_holm", "dmean_p_verdict"]),
        "vs_alone": rec(t3, ["question", "condition", "d_rate", "d_rate_lo", "d_rate_hi", "lost", "gained", "mcnemar_p", "mcnemar_p_holm",
                             "dTPR_verdict", "d_mean_p", "d_mean_p_lo", "d_mean_p_hi"]),
        "trend": rec(t4, ["question", "x_kind", "model", "n_blocks_with_changing_decision", "slope_logodds_per_doubling", "slope_lo",
                          "slope_hi", "OR_per_doubling", "OR_lo", "OR_hi", "perm_p", "perm_p_holm", "verdict",
                          "within_span_dp_per_doubling", "within_dp_lo", "within_dp_hi", "within_perm_p", "within_perm_p_holm",
                          "within_verdict", "perm_p_holm_both_q", "verdict_both_q", "within_perm_p_holm_both_q",
                          "within_verdict_both_q"]),
        "position_x_length": rec(t5, ["question", "x_kind", "term", "estimate_logodds_per_doubling", "lo", "hi", "boot_p", "verdict"]),
        "position_effect_pooled": rec(t6[t6.target_chars.astype(str) == "2k–32k 평균"],
                                      ["question", "comparison", "rate_ref", "rate", "d_rate", "d_rate_lo", "d_rate_hi", "d_mean_p",
                                       "d_mean_p_lo", "d_mean_p_hi", "verdict"]),
        "auc_by_length": rec(t7[t7.positions == "전체 위치"], ["question", "target_chars", "AUC", "AUC_lo", "AUC_hi", "paired_discrimination",
                                                           "max_benign_p", "n_injection_below_max_benign", "length_only_AUC"]),
        "benign_by_length": rec(t8, ["question", "target_chars", "fp", "FPR", "FPR_hi", "mean_p", "mean_p_lo", "mean_p_hi", "max_p",
                                     "d_mean_p_vs_2k", "d_mean_p_lo", "d_mean_p_hi", "d_mean_p_verdict", "within_carrier_dp_per_doubling",
                                     "within_dp_lo", "within_dp_hi"]),
        "tokens_latency_fit": R["fits"], "tokens_by_length_benign": ctx,
        "local_context": rec(R["t13"], [c for c in R["t13"].columns if c in ("question", "position", "reference", "condition",
                                                                    "neighbour_text_across_lengths", "mean_sd_p_2k_32k",
                                                                    "sd_lo", "sd_hi", "n_spans", "dTPR_vs_ref", "dTPR_lo", "dTPR_hi",
                                                                    "lost", "gained", "mcnemar_p", "d_mean_p_vs_ref", "d_mean_p_lo",
                                                                    "d_mean_p_hi", "wilcoxon_p", "wilcoxon_p_holm", "verdict")]),
        "q2_vs_ql": rec(R["t14"], ["condition", "d_rate_QL_minus_Q2", "lo", "hi", "mcnemar_p", "mcnemar_p_holm", "d_mean_p",
                                   "d_mean_p_lo", "d_mean_p_hi", "verdict"]),
        "fixed_baseline_thresholds_64k_middle": rec(R["t16"][R["t16"].condition == "64k-middle"],
                                                    ["question", "threshold_source", "threshold", "rate", "d_vs_2k_middle",
                                                     "lost_vs_2k_middle", "gained_vs_2k_middle", "mcnemar_p_vs_2k_middle"]),
        "vs_other_experiments": rec(R["t17"], ["question", "comparison", "n_spans", "rate_ref", "rate", "d_rate", "lo", "hi", "lost",
                                               "gained", "mcnemar_p", "mcnemar_p_holm"]),
        "baseline_length_quartile_auc": rec(R["t18"], ["question", "set", "quartile", "median_chars", "n", "AUC", "FPR", "TPR"]),
        "context_rot_verdict": None,   # filled below from the numbers
        "tables": sorted(f for f in os.listdir(TAB) if re.match(r"t\d", f)),
        "figures": sorted(os.path.basename(p) for p in figs),
    }
    # context-rot verdict: any length effect that survives Holm (detection) or a downward trend whose CI excludes 0
    sig_drop = t2[(t2.dTPR_verdict == "낮음")]
    sig_dp = t2[(t2.dmean_p_verdict == "낮음")]
    trend_c = t4[(t4.x_kind == "chars")]
    down = trend_c[trend_c.verdict == "길이에 따라 내림"]
    down_ci = trend_c[trend_c.slope_hi < 0]
    down_p = trend_c[trend_c.within_verdict == "길이에 따라 내림"]
    upto32 = t2[(t2.target_chars <= 32000)]
    analysis["context_rot_verdict"] = {
        "detection_drop_vs_2k_surviving_holm": sig_drop[["question", "condition"]].to_dict("records"),
        "mean_p_drop_vs_2k_surviving_holm": sig_dp[["question", "condition", "d_mean_p"]].to_dict("records"),
        "detection_trend_down_ci_and_holm_perm": down[["question", "model"]].to_dict("records"),
        "detection_trend_down_ci_only": down_ci[["question", "model", "perm_p", "perm_p_holm"]].to_dict("records"),
        "mean_p_trend_down": down_p[["question", "model", "within_span_dp_per_doubling", "within_dp_lo", "within_dp_hi",
                                     "within_perm_p_holm"]].to_dict("records"),
        "detection_trend_down_holm_both_questions": trend_c[trend_c.verdict_both_q == "길이에 따라 내림"][["question", "model"]].to_dict("records"),
        "max_abs_dTPR_vs_2k_up_to_32k": float(upto32.d_rate.abs().max()),
        "min_dTPR_ci_lo_vs_2k_up_to_32k": float(upto32.d_rate_lo.min()),
        "dTPR_64k_vs_2k_middle": t2[t2.condition == "64k-middle"][["question", "d_rate", "d_rate_lo", "d_rate_hi", "lost", "gained",
                                                                    "mcnemar_p", "mcnemar_p_holm", "dTPR_verdict"]].to_dict("records"),
        "token_range": ctx,
    }
    tr = trend_c.set_index(["question", "model"])
    v64 = t2[t2.condition == "64k-middle"].set_index("question")
    did = R["t14"][R["t14"].condition.str.startswith("(64k-middle − 2k-middle)")].iloc[0]
    parts = [f"Paired 0.5 detection vs 2k: {len(sig_drop)} of {len(t2)} comparisons (13 per question) "
             f"show a change that survives Holm; up to 32k chars (Jev input {ctx['Q2']['tokens_32k']:,.0f} tokens with Q2) every paired "
             f"dTPR lies in {100 * float(upto32.d_rate.min()):+.1f} to {100 * float(upto32.d_rate.max()):+.1f} pp, but with 40 spans the "
             f"CIs reach {100 * float(upto32.d_rate_lo.min()):+.1f} pp, so drops of that size are not ruled out (no detectable change, "
             "not 'no change')."]
    parts.append("64k middle vs 2k middle: " + "; ".join(
        f"{q} {100 * v64.loc[q, 'd_rate']:+.1f} pp [{100 * v64.loc[q, 'd_rate_lo']:+.1f}, {100 * v64.loc[q, 'd_rate_hi']:+.1f}] "
        f"({int(v64.loc[q, 'lost'])} lost / {int(v64.loc[q, 'gained'])} gained, McNemar Holm {v64.loc[q, 'mcnemar_p_holm']:.2f})" for q in QIDS)
        + f". QL - Q2 difference of the drops {100 * did.d_rate_QL_minus_Q2:+.1f} pp [{100 * did.lo:+.1f}, {100 * did.hi:+.1f}] "
          f"(mean p: {did.d_mean_p:+.3f} [{did.d_mean_p_lo:+.3f}, {did.d_mean_p_hi:+.3f}]), so the questions are not shown to differ in TPR.")
    for q in QIDS:
        dn = down[down.question == q]
        if len(dn):
            for _, r in dn.iterrows():
                rr = tr.loc[(q, r.model)]
                parts.append(f"{q} {r.model}: detection odds x{rr.OR_per_doubling:.2f} per doubling [{rr.OR_lo:.2f}, {rr.OR_hi:.2f}], "
                             f"permutation p {rr.perm_p:.4f} (Holm {rr.perm_p_holm:.3f} within the question's 6 models, "
                             f"{rr.perm_p_holm_both_q:.3f} over both questions' 12): borderline.")
        else:
            parts.append(f"{q}: no detection trend survives the permutation test + Holm.")
    mp = "; ".join(f"{r.question} {r.model} {r.within_span_dp_per_doubling:+.4f}" for r in down_p.itertuples())
    up_p = trend_c[trend_c.within_verdict == "길이에 따라 오름"]
    parts.append(f"Mean p falls with length (CI excludes 0 and Holm p < 0.05) in: {mp or 'none'}"
                 + (f"; rises in: " + "; ".join(f"{r.question} {r.model} {r.within_span_dp_per_doubling:+.4f}" for r in up_p.itertuples())
                    if len(up_p) else "")
                 + f". Benign p rises slightly; AUC stays >= {t7[t7.positions == '전체 위치'].AUC.min():.3f}. The middle span also gets new "
                 "neighbouring sentences (39/40 in another article at 64k), so length and local context are mixed there.")
    analysis["context_rot_verdict"]["summary"] = " ".join(parts)
    s["analysis"] = clean(analysis)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(s, f, ensure_ascii=False, indent=1)

    # ---------------- console digest (README numbers come from here and the tables)
    pd.set_option("display.width", 250)
    print(t1[["question", "condition", "detected", "rate", "rate_lo", "rate_hi", "mean_p", "mean_p_lo", "mean_p_hi", "mean_input_tokens"]].round(3).to_string())
    print(t2[["question", "condition", "d_rate", "d_rate_lo", "d_rate_hi", "lost", "gained", "mcnemar_p", "mcnemar_p_holm", "dTPR_verdict",
              "d_mean_p", "d_mean_p_lo", "d_mean_p_hi", "wilcoxon_p_holm", "dmean_p_verdict"]].round(3).to_string())
    print(t3[["question", "condition", "d_rate", "lost", "gained", "mcnemar_p_holm", "dTPR_verdict"]].round(3).to_string())
    print(t4[["question", "x_kind", "model", "OR_per_doubling", "OR_lo", "OR_hi", "perm_p", "perm_p_holm", "perm_p_holm_both_q", "verdict",
              "within_span_dp_per_doubling", "within_dp_lo", "within_dp_hi", "within_perm_p_holm", "within_perm_p_holm_both_q",
              "within_verdict"]].round(4).to_string())
    print(t5.round(3).to_string())
    print(t6[["question", "target_chars", "comparison", "d_rate", "d_rate_lo", "d_rate_hi", "verdict"]].round(3).to_string())
    print(t7[t7.positions == "전체 위치"][["question", "target_chars", "AUC", "AUC_lo", "AUC_hi", "paired_discrimination", "length_only_AUC"]].round(4).to_string())
    print(t8[["question", "target_chars", "fp", "FPR_hi", "mean_p", "mean_p_lo", "mean_p_hi", "max_p", "d_mean_p_vs_2k", "d_mean_p_lo",
              "d_mean_p_hi", "d_mean_p_verdict", "within_carrier_dp_per_doubling", "within_dp_lo", "within_dp_hi"]].round(4).to_string())
    print(R["t13"].round(3).to_string())
    print(R["t14"].round(3).to_string())
    print(R["t16"][R["t16"].condition.isin(["alone", "2k-middle", "64k-middle", "2k-start", "32k-start"])].round(3).to_string())
    print(R["t17"].round(3).to_string())
    print(R["t18"].round(3).to_string())
    print(json.dumps(clean(analysis["context_rot_verdict"]), ensure_ascii=False, indent=1))
    print(f"wrote {len(analysis['tables'])} tables, {len(figs)} figures, summary.json['analysis']")


if __name__ == "__main__":
    main()
