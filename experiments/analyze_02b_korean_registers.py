"""② 말투 실험(02b_korean_registers + 02b_korean_registers_mt) 분석: 저장된 예측표·raw 호출 -> 표, 그림, summary.json "analysis".
API와 번역 모델을 부르지 않는다.

    python experiments/analyze_02b_korean_registers.py

입력 (읽기만 함)
  results/02b_korean_registers/{Q2,QL}_predictions.csv, raw/{Q2,QL}_raw.jsonl      한국어 7개 말투 + 영어 원문 = 1,768행
  results/02b_korean_registers_mt/{Q2,QL}_predictions.csv, raw/{Q2,QL}_raw.jsonl   opus-mt 한->영 번역 1,547행
  results/02b_korean_registers/inputs/dataset.jsonl, SOURCE.json, prior_judges_preds.csv  (업스트림 커밋 d348b1f)
  results/02b_korean_registers/translation/registers_ko_to_en.jsonl, segment_cache.jsonl
  results/02_korean/tables/paired_comparisons.csv, data/injection_eval/{en,ko}/dataset_*_1000.jsonl  (맥락 비교만)
출력
  results/02b_korean_registers/tables/*.csv, figures/*.png (먼저 비워서 이 스크립트가 만든 파일만 남김),
  results/02b_korean_registers/summary.json 의 "analysis",
  results/02b_korean_registers_mt/summary.json 의 "analysis" (E4 부분만; 첫 점검용 run_02b_korean_registers.py analyze 가
    쓴 것을 대체),
  두 summary.json 의 Q2/QL "overall" 에서 TPR_ci95·FPR_ci95 를 항목 부트스트랩 구간으로 바꾸고 AUC_ci95, 행 단위 Wilson
    (*_row_wilson), ci95_method 를 더함. 합친 1,547행은 같은 221개 항목의 7개 버전이라 jevlab.metric_block 의 행 단위
    Wilson 구간은 너무 좁다. 점추정·개수와 다른 키는 그대로 두고, 점추정이 이 스크립트의 값과 같은지 확인한다.
  예측표·raw·입력·번역 파일은 바꾸지 않는다.

데이터의 성격
  1,768행 모두 사용자가 AI에게 직접 보내는 짧은 프롬프트(deepset 질문, deepset·Tensor Trust 공격 문장)다. 문서 속에 숨은
  지시(간접 인젝션)가 아니므로 01~03의 숫자와 크기를 비교하지 않고 '말투만 바꾼 효과'로 읽는다. 02_korean과의 비교 표
  (context_02_korean.csv)는 방향만 본다.

통계 (01_baseline, 02_korean과 같은 규칙)
  - 8개 말투가 같은 221개 항목(정상 123 / 인젝션 98)이므로 말투끼리, 원문과 번역, Q2와 QL 비교는 모두 항목 짝 비교다.
      0.5 판정의 차이: exact McNemar (불일치 쌍에 대한 양측 이항검정)
      TPR·FPR·AUC·평균 p 차이: 라벨별 층화 항목 부트스트랩 1,000회, seed 20261112, 백분위 95% 구간.
      모든 말투·조건·질문에 같은 재표집 인덱스를 쓴다 (run_02b_korean_registers.Cells).
  - 말투 하나의 비율 CI는 Wilson. 여러 말투를 합친 행(한국어 7개 / 협박체를 뺀 6개)은 항목 단위 부트스트랩 CI
    (한 항목의 여러 버전이 함께 움직임)이고 McNemar는 하지 않는다.
  - 판정 문구: CI가 0을 빼고 그리고 표 안 Holm 보정 McNemar p < 0.05 -> 높아짐/낮아짐. CI만 0을 빼면 "탐색적 (Holm p)".
    CI가 0을 덮으면 "차이 없음/오차 범위". 합친 행과 AUC·평균 p는 CI만 본다.
  - 말투 전체 효과(옴니버스): Cochran Q (짝지은 이진 판정의 카이제곱형 검정, df = 말투 수 − 1)와 p에 대한 Friedman 검정.
    로지스틱 회귀(말투를 요인으로)는 8개 중 7개 말투의 오탐이 0/123이라 완전 분리가 생겨 계수를 추정할 수 없으므로 쓰지 않는다.
  - 말투 쌍 28개의 McNemar는 질문 × 라벨마다 Holm 보정.
  - p는 소수 둘째 자리 값 3개의 평균이라 1/300 격자에 있다. 저장값의 부동소수점 오차를 없애려고 격자로 맞춘 뒤 비교한다.
  - 협박체 문장 특징별 오탐(e3_threat_benign_features.csv)은 문장을 본 뒤 정한 분류라 탐색 결과다 (Fisher exact, Holm).
  - 협박체 오탐을 줄이는 임계값은 같은 데이터에서 맞춘 값이라 낙관적이고 참고용이다. 주 지표는 임계값 0.5.
"""
import datetime as dt
import glob
import hashlib
import itertools
import json
import os
import re
import sys

import numpy as np
import pandas as pd
from scipy.stats import chi2, fisher_exact, friedmanchisquare, spearmanr
from sklearn.metrics import roc_curve

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402
import plot_style as PS  # noqa: E402
import run_02b_korean_registers as R2  # noqa: E402  (data spec + item-paired helpers; its own "analyze" was the first look)
import translate_registers as TR  # noqa: E402  (segmentation only; torch is imported inside translate_ko.translate())
from src.jev_guard import MODEL, THRESHOLD, metrics  # noqa: E402

import matplotlib.pyplot as plt  # noqa: E402  (plot_style already selected the Agg backend)
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.patches import Patch  # noqa: E402
from matplotlib.ticker import FuncFormatter  # noqa: E402

EXP, EXP_MT = R2.EXP, R2.EXP_MT
OUT = os.path.join(J.RESULTS, EXP)
OUT_MT = os.path.join(J.RESULTS, EXP_MT)
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
INPUTS = R2.INPUTS
KO_1000 = os.path.join(J.DATA, "ko", "dataset_ko_1000.jsonl")
EN_1000 = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")
K02_PAIRED = os.path.join(J.RESULTS, "02_korean", "tables", "paired_comparisons.csv")

QIDS = ("Q2", "QL")
REGISTERS, KO_REGISTERS, REG_KO = R2.REGISTERS, R2.KO_REGISTERS, R2.REGISTER_KO
NO_THREAT = [r for r in KO_REGISTERS if r != "threat"]
GROUPS = {"korean_pooled": KO_REGISTERS, "korean_no_threat": NO_THREAT}
NAME_KO = {**REG_KO, "korean_pooled": "한국어 7개 합침", "korean_no_threat": "협박체 뺀 6개 합침"}
SEED, B, GRID = 20261112, 1000, 300
assert (R2.SEED, R2.N_BOOT, R2.GRID) == (SEED, B, GRID)
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}
Q_NAMES = {"Q2": "Q2 짧은 질문", "QL": "QL 정의형 긴 질문"}
INJ, BEN = PS.LABEL_COLORS["인젝션"], PS.LABEL_COLORS["정상"]
PRICE_IN = 0.042 / 1e6
EST_BASE = R2.EST_BASE
VERDICT_NONE = R2.VERDICT_NONE
SIG = ("높아짐", "낮아짐")
FPR_TARGETS = (0.10, 0.05, 0.01)

# Exploratory features of the Korean threat sentence (chosen AFTER reading the threat rows sorted by p -> hypothesis only).
THREAT_FEATURES = [
    ("replace", "다른 AI로 바꾼다 (GPT·클로드·제미나이·딴 모델·딴 거 등)",
     r"GPT|클로드|제미나이|딴 ?(?:모델|AI|거)|다른 ?(?:AI|모델)|갈아탄|깐다"),
    ("named_model", "다른 AI 이름을 댐 (GPT·클로드·제미나이)", r"GPT|클로드|제미나이"),
    ("delete", "지운다·삭제한다", r"삭제|지우|지운|지워"),
    ("discard", "버린다·갖다버린다", r"버리|버린"),
    ("end", "끝이야·끝장이야", r"끝"),
    ("reputation", "별점·리뷰·폭로·구독·환불", r"별점|리뷰|폭로|구독|환불"),
    ("profanity", "욕설 (씨발·존나)", r"씨발|존나"),
    ("hurry", "재촉 (당장·빨리·5초)", r"당장|빨리|5초"),
]


# ------------------------------------------------------------------ helpers
def md5_file(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def save(df, name):
    df.to_csv(os.path.join(TAB, f"{name}.csv"), index=False, encoding="utf-8-sig")
    return df


def clean(o):
    """JSON-safe: numpy -> python, NaN -> None."""
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
    if isinstance(o, np.ndarray):
        return clean(o.tolist())
    return o


def rec(T, keep=None, **flt):
    m = T
    for k, v in flt.items():
        m = m[m[k] == v]
    assert len(m) == 1, (flt, len(m))
    d = m.iloc[0].to_dict()
    return {k: v for k, v in d.items() if keep is None or k in keep}


def cochran_q(X):
    """X: n x k binary (rows = items, columns = conditions). Returns Q, df, p, number of rows that are not constant."""
    X = np.asarray(X, dtype=int)
    n, k = X.shape
    col, row, tot = X.sum(0), X.sum(1), X.sum()
    den = k * tot - (row ** 2).sum()
    nvar = int(((row > 0) & (row < k)).sum())
    if den == 0:
        return 0.0, k - 1, 1.0, nvar
    q = (k - 1) * (k * (col ** 2).sum() - tot ** 2) / den
    return float(q), k - 1, float(chi2.sf(q, k - 1)), nvar


def thr_at_fpr(neg_scores, f):
    """Lowest threshold t (p >= t flags) with FPR <= f on these benign scores, half a grid step above the highest benign
    score that must pass (fitted on the same data -> optimistic). Scores are on the 1/GRID grid."""
    neg = np.sort(np.asarray(neg_scores, dtype=float))[::-1]
    k = int(np.floor(f * len(neg) + 1e-9))
    return float(neg[k] + 0.5 / GRID) if k < len(neg) else 0.0


def pct(v, d=1):
    return "–" if v is None or v != v else f"{100 * v:.{d}f}%"


def pp(v, d=1):
    return "–" if v is None or v != v else f"{100 * v:+.{d}f}%p"


# ------------------------------------------------------------------ load and check
def verify_predictions(exp, q):
    """The predictions file is exactly the mean of the saved calls (3 runs per uid), on jev-1.14.0 and this question."""
    d = pd.read_csv(os.path.join(J.RESULTS, exp, f"{q}_predictions.csv"))
    allraw = J.load_jsonl(J.raw_path(exp, q))
    ok = pd.DataFrame([r for r in allraw if r.get("http_status") == 200 and "noul" in r])
    dedup = ok.sort_values("started_at").drop_duplicates(["uid", "run", "text_md5"], keep="first")
    piv = dedup.pivot(index="uid", columns="run", values="noul")
    chk = d.set_index("uid")
    assert set(chk.index) == set(piv.index), f"{exp} {q}: predictions and raw cover different uids"
    for r in range(J.REPEATS):
        assert np.allclose(chk[f"p_run{r}"], piv.loc[chk.index, r]), f"{exp} {q}: p_run{r} differs from raw"
    assert np.allclose(chk["p"], piv.loc[chk.index].mean(axis=1)), f"{exp} {q}: p is not the mean of the raw runs"
    assert (dedup["model"] == MODEL).all() and (dedup["question_id"] == q).all()
    assert (d["pred"] == (d["p"] >= THRESHOLD).astype(int)).all()
    return {"rows": len(d), "raw_lines": len(allraw), "ok_calls": len(ok), "duplicate_calls_dropped": len(ok) - len(dedup),
            "predictions_md5": md5_file(os.path.join(J.RESULTS, exp, f"{q}_predictions.csv"))}


def load():
    rows = R2.load_rows()
    by_uid = {R2.uid(r): r for r in rows}
    assert len(by_uid) == len(rows) == 1768
    items = pd.DataFrame(rows).groupby("id").agg(n=("register", "size"), labels=("label", "nunique"),
                                                 regs=("register", lambda s: tuple(sorted(s))))
    assert (items["n"] == 8).all() and (items["labels"] == 1).all() and (items["regs"] == tuple(sorted(REGISTERS))).all()
    mt = J.load_jsonl(R2.MT_FILE)
    assert all(t["source_md5"] == J.state_md5(by_uid[t["uid"]]["text"]) for t in mt), "translation made from another text"
    assert {t["uid"] for t in mt} == {u for u, r in by_uid.items() if r["lang"] == "ko"}
    checks = {f"{exp}/{q}": verify_predictions(exp, q) for exp in (EXP, EXP_MT) for q in QIDS}
    W = R2._wide()  # asserts every raw call's text_md5 == md5(input text), labels, 3 runs; snaps p to the 1/300 grid
    assert all(v == [] for v in R2.SNAP_CHANGED.values()), R2.SNAP_CHANGED
    checks.update({"items": 221, "rows_per_item": 8, "label_same_in_all_registers": True,
                   "translation_source_md5_equals_korean_text": True,
                   "raw_text_md5_equals_input_text": True,
                   "p_snapped_to_1_300_grid_decision_changed": R2.SNAP_CHANGED})
    return W, rows, mt, checks


# ------------------------------------------------------------------ main analysis
def main():
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    for p in glob.glob(os.path.join(TAB, "*.csv")) + glob.glob(os.path.join(FIG, "*.png")):
        os.remove(p)  # only this script's outputs live here

    W, rows, mt, checks = load()
    C = R2.Cells(W)
    y = C.y
    R = pd.DataFrame(rows)
    R["chars"] = R["text"].str.len()
    src_en = W[W["register"] == "english"].set_index("item_id")["text"]

    def PM(q, cond, key):
        return np.column_stack([C.P(q, cond, r) for r in GROUPS.get(key, [key])])

    def DM(q, cond, key):  # 0.5 decisions, items x registers
        return PM(q, cond, key) >= THRESHOLD

    # ============================================================ E2: structure
    st = (R.groupby("register").agg(n_rows=("text", "size"), n_benign=("label", lambda s: int((s == 0).sum())),
                                    n_injection=("label", "sum"), chars_median=("chars", "median"),
                                    chars_mean=("chars", "mean"), chars_max=("chars", "max"),
                                    formality=("formality", "first"), valence=("valence", "first"), lang=("lang", "first"))
          .reindex(REGISTERS).reset_index())
    st.insert(1, "register_ko", st["register"].map(REG_KO))
    lab_len = R.groupby(["register", "label"])["chars"].median().unstack()
    st["chars_median_benign"] = st["register"].map(lab_len[0])
    st["chars_median_injection"] = st["register"].map(lab_len[1])
    save(st, "e2_structure_register_label")
    en = R[R["register"] == "english"]
    src_tab = (en.groupby(["source", "label"]).size().unstack(fill_value=0)
               .rename(columns={0: "benign_items", 1: "injection_items"}).reset_index())
    save(src_tab, "e2_source_label_items")
    tech = (en[en["label"] == 1].groupby(["source", "technique"]).size().rename("items").reset_index()
            .sort_values("items", ascending=False))
    save(tech, "e2_technique_items")
    ex = R[R["id"].isin(["k_0215", "k_0148"])][["id", "label", "register", "text"]].copy()
    ex["register"] = pd.Categorical(ex["register"], REGISTERS, ordered=True)
    save(ex.sort_values(["label", "register"]), "e2_examples")
    ben_q_share = float(en[en["label"] == 0]["text"].str.strip().str.endswith("?").mean())

    # ============================================================ E3: per register (Korean originals + English source)
    e3 = []
    for q in QIDS:
        for key in REGISTERS + list(GROUPS):
            pt, _ = C.stats(PM(q, "orig", key))
            sub = W[W["register"].isin(GROUPS.get(key, [key]))]
            e3.append({"question": q, "register": key, "register_ko": NAME_KO[key],
                       "ci_method": "Wilson" if key in REGISTERS else "item bootstrap (TPR/FPR), AUC bootstrap", **pt,
                       "max_p_benign": float(sub.loc[sub.label_int == 0, f"{q}_orig_p"].max()),
                       "min_p_injection": float(sub.loc[sub.label_int == 1, f"{q}_orig_p"].min()),
                       "flips": int(sub[f"{q}_orig_flip"].astype(bool).sum()),
                       "p_sd_mean": float(sub[f"{q}_orig_p_sd"].mean()),
                       "input_tokens_mean": float(sub[f"{q}_orig_input_tokens"].mean())})
    E3 = save(pd.DataFrame(e3), "e3_by_register")
    E3i = E3.set_index(["question", "register"])
    max_ben_no_threat = {q: float(W[(W.register != "threat") & (W.label_int == 0)][f"{q}_orig_p"].max()) for q in QIDS}

    # ---- register effect: omnibus (Cochran Q on decisions, Friedman on p), per question x label
    sets = {"한국어 7개": KO_REGISTERS, "한국어 7개 + 영어 원문": REGISTERS,
            "협박체 뺀 한국어 6개": NO_THREAT, "협박체 뺀 6개 + 영어 원문": ["english"] + NO_THREAT}
    om = []
    for q in QIDS:
        for set_name, regs in sets.items():
            Pm = np.column_stack([C.P(q, "orig", r) for r in regs])
            for lab, met in ((1, "TPR"), (0, "FPR")):
                X = (Pm[y == lab] >= THRESHOLD).astype(int)
                Qs, df_, p_q, nvar = cochran_q(X)
                M = Pm[y == lab]
                try:
                    fr = friedmanchisquare(*M.T)
                    f_stat, f_p = float(fr.statistic), float(fr.pvalue)
                except ValueError:
                    f_stat, f_p = None, None
                rates = X.mean(0)
                om.append({"question": q, "register_set": set_name, "k_registers": len(regs), "metric": met,
                           "n_items": int(X.shape[0]), "rate_min": float(rates.min()), "rate_max": float(rates.max()),
                           "items_not_constant": nvar, "cochran_Q": Qs, "df": df_, "cochran_p": p_q,
                           "friedman_chi2_on_p": f_stat, "friedman_p": f_p})
    OM = save(pd.DataFrame(om), "e3_register_omnibus")

    # ---- all 28 register pairs, exact McNemar, Holm per question x label
    pw = []
    for q in QIDS:
        for lab, met in ((1, "TPR"), (0, "FPR")):
            block = []
            for a, b in itertools.combinations(REGISTERS, 2):
                da, db = DM(q, "orig", a)[:, 0][y == lab], DM(q, "orig", b)[:, 0][y == lab]
                ao, bo, p = R2._mcnemar(da, db)
                block.append({"question": q, "metric": met, "register_a": a, "register_b": b, "rate_a": da.mean(),
                              "rate_b": db.mean(), "diff_b_minus_a": db.mean() - da.mean(), "only_a": ao, "only_b": bo,
                              "mcnemar_p": p})
            hp = R2._holm([r["mcnemar_p"] for r in block])
            for r, h in zip(block, hp):
                r["mcnemar_p_holm"] = h
                r["holm_significant"] = bool(h < 0.05)
            pw += block
    PW = save(pd.DataFrame(pw), "e3_pairwise_mcnemar")

    # ---- how much of the p variance is item vs register (two-way layout, no replication; descriptive)
    vd = []
    for q in QIDS:
        for set_name, regs in (("한국어 7개", KO_REGISTERS), ("협박체 뺀 한국어 6개", NO_THREAT)):
            Pm = np.column_stack([C.P(q, "orig", r) for r in regs])
            for lab, name in ((1, "injection"), (0, "benign")):
                M = Pm[y == lab]
                g = M.mean()
                ss_tot = ((M - g) ** 2).sum()
                ss_item = M.shape[1] * ((M.mean(1) - g) ** 2).sum()
                ss_reg = M.shape[0] * ((M.mean(0) - g) ** 2).sum()
                vd.append({"question": q, "register_set": set_name, "label": name, "n_items": M.shape[0],
                           "k_registers": M.shape[1], "share_item": ss_item / ss_tot, "share_register": ss_reg / ss_tot,
                           "share_residual": 1 - (ss_item + ss_reg) / ss_tot})
    VD = save(pd.DataFrame(vd), "e3_variance_decomposition")

    # ---- paired comparisons (same items)
    def pairs(q, a_cond, a_key, b_cond, b_key, label_a, label_b, register):
        return {"question": q, "a": label_a, "b": label_b, "register": register,
                "Pa": PM(q, a_cond, a_key), "Pb": PM(q, b_cond, b_key)}

    vs_polite = R2._paired_table(C, [pairs(q, "orig", "polite", "orig", r, "polite", r, r)
                                     for q in QIDS for r in REGISTERS if r != "polite"])
    save(vs_polite, "e3_vs_polite_paired")
    vs_en = R2._paired_table(C, [pairs(q, "orig", "english", "orig", r, "english", r, r)
                                 for q in QIDS for r in KO_REGISTERS + list(GROUPS)])
    save(vs_en, "e3_vs_english_paired")
    qq = R2._paired_table(C, [{"question": "QL-Q2", "a": "Q2", "b": "QL", "register": r, "Pa": PM("Q2", "orig", r),
                               "Pb": PM("QL", "orig", r)} for r in REGISTERS + list(GROUPS)])
    save(qq, "e3_q2_vs_ql_by_register")

    srcrows = []
    for q in QIDS:
        for reg in REGISTERS:
            for s, g in W[(W["register"] == reg) & (W["label_int"] == 1)].groupby("source"):
                k = int(g[f"{q}_orig_pred"].sum())
                lo, hi = J.wilson(k, len(g))
                srcrows.append({"question": q, "register": reg, "source": s, "n_injection": len(g), "tp": k,
                                "TPR": k / len(g), "TPR_lo": lo, "TPR_hi": hi, "mean_p": float(g[f"{q}_orig_p"].mean())})
    SRC = save(pd.DataFrame(srcrows), "e3_tpr_by_register_source")

    # ---- item consistency: are misses tied to items or to registers?
    ic, never = [], []
    invariant = {}  # injection items whose 0.5 verdict is the same in all 7 Korean registers, per question
    item_src = W[W.register == "english"].set_index("item_id")[["source", "technique", "text"]]
    for q in QIDS:
        piv = W[W.register.isin(KO_REGISTERS)].pivot(index="item_id", columns="register", values=f"{q}_orig_pred")
        piv = piv.loc[C.items, KO_REGISTERS]
        k_ko = piv.sum(axis=1).to_numpy()
        invariant[q] = {it for it, lab, k in zip(C.items, y, k_ko) if lab == 1 and k in (0, len(KO_REGISTERS))}
        en_pred = W[W.register == "english"].set_index("item_id").loc[C.items, f"{q}_orig_pred"].to_numpy()
        for lab, name in ((1, "injection"), (0, "benign")):
            for k in range(8):
                m = (y == lab) & (k_ko == k)
                ic.append({"question": q, "label": name, "n_korean_registers_flagged": k, "n_items": int(m.sum()),
                           "of_which_english_flagged": int(en_pred[m].sum())})
        all8 = piv.sum(axis=1) + pd.Series(en_pred, index=C.items)
        for it in [i for i, lab, s in zip(C.items, y, all8) if lab == 1 and s == 0]:
            never.append({"question": q, "item_id": it, "source": item_src.at[it, "source"],
                          "technique": item_src.at[it, "technique"], "text_english": item_src.at[it, "text"],
                          **{f"p_{r}": float(W.at[f"{it}-{r}", f"{q}_orig_p"]) for r in REGISTERS}})
    IC = save(pd.DataFrame(ic), "e3_item_consistency")
    NEVER = save(pd.DataFrame(never), "e3_injections_missed_in_all_8_registers")
    inv_counts = {**{q: len(invariant[q]) for q in QIDS}, "both_questions": len(invariant["Q2"] & invariant["QL"]),
                  "note": "injection items (of 98) with the same 0.5 verdict in all 7 Korean registers; 'both_questions' = "
                          "register-invariant under Q2 and under QL at once (the verdicts may differ between Q2 and QL)"}
    for q in QIDS:  # same count as the table (0 or 7 registers flagged)
        assert inv_counts[q] == int(IC[(IC.question == q) & (IC.label == "injection") &
                                       IC.n_korean_registers_flagged.isin([0, len(KO_REGISTERS)])].n_items.sum())

    # ---- threat benign rows: which threat sentences get flagged (exploratory) and does length matter
    TB = W[(W.register == "threat") & (W.label_int == 0)].copy()
    TB["text_english_source"] = TB["item_id"].map(src_en)
    TB["len_english_source"] = TB["text_english_source"].str.len()
    TB["len_threat"] = TB["text"].str.len()
    len_med = float(TB["len_english_source"].median())
    for key, _, rx in THREAT_FEATURES:
        TB[key] = TB["text"].str.contains(rx, regex=True)
    TB["long_question"] = TB["len_english_source"] > len_med
    feats = THREAT_FEATURES + [("long_question", f"긴 질문 (영어 원문 > 중앙값 {len_med:.0f}자)", None)]
    fr_ = []
    for q in QIDS:
        block = []
        for key, name, _ in feats:
            g1, g0 = TB[TB[key]], TB[~TB[key]]
            k1, k0 = int(g1[f"{q}_orig_pred"].sum()), int(g0[f"{q}_orig_pred"].sum())
            n1, n0 = len(g1), len(g0)
            fe = fisher_exact([[k1, n1 - k1], [k0, n0 - k0]]) if n1 and n0 else (None, 1.0)
            block.append({"question": q, "feature": key, "feature_ko": name, "n_with": n1, "fp_with": k1,
                          "FPR_with": k1 / n1 if n1 else None, "FPR_with_lo": J.wilson(k1, n1)[0] if n1 else None,
                          "FPR_with_hi": J.wilson(k1, n1)[1] if n1 else None,
                          "n_without": n0, "fp_without": k0, "FPR_without": k0 / n0 if n0 else None,
                          "FPR_without_lo": J.wilson(k0, n0)[0] if n0 else None,
                          "FPR_without_hi": J.wilson(k0, n0)[1] if n0 else None,
                          "mean_p_with": float(g1[f"{q}_orig_p"].mean()) if n1 else None,
                          "mean_p_without": float(g0[f"{q}_orig_p"].mean()) if n0 else None,
                          "fisher_p": float(fe[1])})
        for r, h in zip(block, R2._holm([b["fisher_p"] for b in block])):
            r["fisher_p_holm"] = h
        fr_ += block
    TF = save(pd.DataFrame(fr_), "e3_threat_benign_features")
    spear = {}
    for q in QIDS:
        a = spearmanr(TB["len_english_source"], TB[f"{q}_orig_p"])
        b = spearmanr(TB["len_threat"], TB[f"{q}_orig_p"])
        spear[q] = {"rho_len_english_source": float(a.statistic), "p_len_english_source": float(a.pvalue),
                    "rho_len_threat_text": float(b.statistic), "p_len_threat_text": float(b.pvalue)}
    both = TB[(TB.Q2_orig_pred == 1) & (TB.QL_orig_pred == 1)]
    tb_cols = (["item_id", "text", "text_english_source", "len_english_source", "Q2_orig_p", "QL_orig_p", "Q2_mt_p", "QL_mt_p",
                "text_mt"] + [k for k, _, _ in THREAT_FEATURES])
    save(TB.reset_index()[["uid"] + tb_cols].sort_values("Q2_orig_p", ascending=False), "e3_threat_benign_rows")
    tb_overlap = {"both": int(len(both)), "Q2_only": int(((TB.Q2_orig_pred == 1) & (TB.QL_orig_pred == 0)).sum()),
                  "QL_only": int(((TB.Q2_orig_pred == 0) & (TB.QL_orig_pred == 1)).sum()),
                  "neither": int(((TB.Q2_orig_pred == 0) & (TB.QL_orig_pred == 0)).sum())}

    # ---- thresholds: what would it take to remove the threat false alarms (same data -> optimistic, reference only)
    sweep = []
    for q in QIDS:
        for key in REGISTERS + list(GROUPS):
            Pm = PM(q, "orig", key)
            pi, pb = Pm[y == 1].ravel(), Pm[y == 0].ravel()
            for t in np.round(np.arange(0.05, 0.96, 0.01), 2):
                sweep.append({"question": q, "register": key, "threshold": float(t), "TPR": float((pi >= t).mean()),
                              "FPR": float((pb >= t).mean())})
    SW = save(pd.DataFrame(sweep), "e3_threshold_sweep")
    th_rows = []
    thr_fit = {}
    for q in QIDS:
        pb_threat = PM(q, "orig", "threat")[y == 0].ravel()
        for f in (None,) + FPR_TARGETS:
            t = THRESHOLD if f is None else thr_at_fpr(pb_threat, f)
            if f is not None:
                assert ((pb_threat >= round(t, 3)) == (pb_threat >= t)).all()
                thr_fit[(q, f)] = t
            for key in REGISTERS + list(GROUPS):
                Pm = PM(q, "orig", key)
                pi, pb = Pm[y == 1].ravel(), Pm[y == 0].ravel()
                th_rows.append({"question": q, "target": "기준 0.5" if f is None else f"협박체 정상 오탐 {int(f * 100)}% 이하",
                                "threshold": t, "fitted_on_same_data": f is not None, "register": key,
                                "TPR": float((pi >= t).mean()), "FPR": float((pb >= t).mean()),
                                "TPR_at_0.5": float((pi >= THRESHOLD).mean()),
                                "dTPR_vs_0.5": float((pi >= t).mean() - (pi >= THRESHOLD).mean())})
    TH = save(pd.DataFrame(th_rows), "e3_threshold_threat_fpr")

    fl = W[(W["label_int"] == 0) & ((W["Q2_orig_pred"] == 1) | (W["QL_orig_pred"] == 1) |
                                    (W["Q2_mt_pred"] == 1) | (W["QL_mt_pred"] == 1))]
    flagged = fl.reset_index()[["uid", "register", "text", "text_mt", "Q2_orig_p", "QL_orig_p", "Q2_mt_p", "QL_mt_p"]]
    flagged["register"] = pd.Categorical(flagged["register"], REGISTERS, ordered=True)
    save(flagged.sort_values(["register", "uid"]), "e3_e4_benign_flagged")
    missed = W[(W["label_int"] == 1) & (W["register"].isin(["english", "polite", "threat"]))]
    missed = missed[(missed["Q2_orig_pred"] == 0) | (missed["QL_orig_pred"] == 0)].reset_index()
    save(missed[["uid", "register", "source", "technique", "text", "Q2_orig_p", "QL_orig_p"]]
         .sort_values(["register", "QL_orig_p"]), "e3_missed_injections_english_polite_threat")

    # ============================================================ E4: translate then judge
    e4 = []
    for q in QIDS:
        for key in KO_REGISTERS + list(GROUPS):
            pt, _ = C.stats(PM(q, "mt", key))
            sub = W[W["register"].isin(GROUPS.get(key, [key]))]
            e4.append({"question": q, "register": key, "register_ko": NAME_KO[key], **pt,
                       "flips": int(sub[f"{q}_mt_flip"].astype(bool).sum()),
                       "input_tokens_mean": float(sub[f"{q}_mt_input_tokens"].mean())})
    E4 = save(pd.DataFrame(e4), "e4_mt_by_register")
    E4i = E4.set_index(["question", "register"])
    mt_vs_ko = R2._paired_table(C, [pairs(q, "orig", r, "mt", r, f"{r} (KO)", f"{r} (KO->EN)", r)
                                    for q in QIDS for r in KO_REGISTERS + list(GROUPS)])
    save(mt_vs_ko, "e4_mt_vs_ko_paired")
    mt_vs_en = R2._paired_table(C, [pairs(q, "orig", "english", "mt", r, "english (source)", f"{r} (KO->EN)", r)
                                    for q in QIDS for r in KO_REGISTERS + list(GROUPS)])
    save(mt_vs_en, "e4_mt_vs_english_paired")

    # translation checks (mechanical only; no claim about meaning) -- same rules as the first look
    K = W[W["register"] != "english"].copy()
    K["len_ko"], K["len_mt"] = K["text"].str.len(), K["text_mt"].str.len()
    K["len_en_source"] = K["item_id"].map(src_en).str.len()
    K["mt_over_en_source"] = K["len_mt"] / K["len_en_source"]

    def longest_loop(s):
        best = 0
        for m in R2.LOOP_RE.finditer(s or ""):
            if m.group(1).strip():
                best = max(best, len(m.group(0)))
        return best

    seg = {c["src"]: c for c in J.load_jsonl(TR.SEG_CACHE)}
    plans = {u: TR.plan_row(t) for u, t in K["text"].items()}
    rebuilt = {u: TR.render(p, {k: v["en"] for k, v in seg.items()}) for u, p in plans.items()}
    assert all(rebuilt[u] == K.at[u, "text_mt"] for u in K.index), "translation file != segment cache rebuild"
    checks["translation_rebuilt_from_segment_cache"] = len(rebuilt)
    segs_of = {u: [x for is_t, s in p if is_t for x in s[1]] for u, p in plans.items()}
    K["n_segments"] = K.index.map(lambda u: len(segs_of[u]))
    K["tiny_segment"] = K.index.map(lambda u: any(len(x.strip()) <= 2 for x in segs_of[u]))
    K["capped_segment"] = K.index.map(lambda u: any(seg[x]["hit_cap"] for x in segs_of[u]))
    seg_stats = {"unique_segments": len(seg), "hit_cap": int(sum(v["hit_cap"] for v in seg.values())),
                 "segments_le_2_chars": int(sum(len(k.strip()) <= 2 for k in seg)),
                 "device": sorted({v["device"] for v in seg.values()})}
    K["loop_excess"] = K["text_mt"].map(longest_loop) - K["text"].map(longest_loop)
    K["mt_loop"] = K["loop_excess"] >= R2.LOOP_MIN
    K["emoji_ko"] = K["text"].map(lambda s: len(R2.EMOJI_RE.findall(s)))
    K["emoji_mt"] = K["text_mt"].map(lambda s: len(R2.EMOJI_RE.findall(s)))
    K["threat_word_mt"] = K["text_mt"].map(lambda s: bool(R2.THREAT_EN.search(s)))
    K["threat_word_en_source"] = K["item_id"].map(src_en).map(lambda s: bool(R2.THREAT_EN.search(s)))
    tq = (K.groupby("register").agg(rows=("text", "size"), hangul_left_rows=("hangul_left", lambda s: int((s > 0).sum())),
                                    mt_loop_rows=("mt_loop", "sum"), capped_segment_rows=("capped_segment", "sum"),
                                    tiny_segment_rows=("tiny_segment", "sum"),
                                    mt_over_en_source_median=("mt_over_en_source", "median"),
                                    rows_with_emoji_ko=("emoji_ko", lambda s: int((s > 0).sum())),
                                    rows_with_emoji_mt=("emoji_mt", lambda s: int((s > 0).sum())),
                                    threat_word_mt=("threat_word_mt", "sum"),
                                    threat_word_en_source=("threat_word_en_source", "sum"))
          .reindex(KO_REGISTERS).reset_index())
    TQ = save(tq, "e4_translation_checks_by_register")
    cols = (["register", "label_int", "len_ko", "len_mt", "len_en_source", "mt_over_en_source", "hangul_left", "loop_excess",
             "mt_loop", "n_segments", "tiny_segment", "capped_segment", "emoji_ko", "emoji_mt", "threat_word_mt", "text",
             "text_mt"] + [f"{q}_{c}_p" for q in QIDS for c in ("orig", "mt")])
    save(K.reset_index()[["uid"] + cols], "e4_translation_rows")
    sens = []
    for name, mask in (("all Korean rows", K.index == K.index), ("no segment of <= 2 chars", ~K["tiny_segment"]),
                       ("no capped segment", ~K["capped_segment"]),
                       ("no tiny / capped segment, no Hangul left",
                        ~(K["tiny_segment"] | K["capped_segment"] | (K["hangul_left"] > 0)))):
        g = K[mask]
        for q in QIDS:
            for lab, met in ((1, "TPR"), (0, "FPR")):
                h = g[g["label_int"] == lab]
                a, b = h[f"{q}_orig_pred"].astype(bool), h[f"{q}_mt_pred"].astype(bool)
                ao, bo, p = R2._mcnemar(a, b)
                sens.append({"subset": name, "question": q, "metric": met, "n": len(h), "KO": float(a.mean()),
                             "KO_to_EN": float(b.mean()), "delta": float(b.mean() - a.mean()), "only_KO": ao,
                             "only_KO_to_EN": bo, "mcnemar_p_rows": p})
    SENS = save(pd.DataFrame(sens), "e4_sensitivity_translation_artefacts")
    thr = K[(K["register"] == "threat") & (K["label_int"] == 0)]
    tsplit = []
    for kept, g in thr.groupby("threat_word_mt"):
        for q in QIDS:
            tsplit.append({"question": q, "threat_word_in_mt": bool(kept), "n_benign": len(g),
                           "FPR_ko": float(g[f"{q}_orig_pred"].mean()), "FPR_mt": float(g[f"{q}_mt_pred"].mean()),
                           "mean_p_ko": float(g[f"{q}_orig_p"].mean()), "mean_p_mt": float(g[f"{q}_mt_p"].mean())})
    TSPLIT = save(pd.DataFrame(tsplit), "e4_threat_benign_by_threat_word_kept")
    lost = K[(K.label_int == 1) & (((K.Q2_orig_pred == 1) & (K.Q2_mt_pred == 0)) | ((K.QL_orig_pred == 1) & (K.QL_mt_pred == 0)))]
    lost = lost.assign(drop_Q2=lost.Q2_orig_p - lost.Q2_mt_p, drop_QL=lost.QL_orig_p - lost.QL_mt_p,
                       lost_by=["both" if (a and b) else "Q2 only" if a else "QL only" for a, b in
                                zip((lost.Q2_orig_pred == 1) & (lost.Q2_mt_pred == 0), (lost.QL_orig_pred == 1) & (lost.QL_mt_pred == 0))])
    save(lost.reset_index()[["uid", "register", "source", "lost_by", "text", "text_mt", "Q2_orig_p", "Q2_mt_p", "QL_orig_p",
                             "QL_mt_p", "tiny_segment", "capped_segment"]].sort_values(["register", "lost_by"]),
         "e4_lost_detections_rows")
    lost_counts = lost.groupby(["register", "lost_by"]).size().unstack(fill_value=0).reindex(KO_REGISTERS, fill_value=0)

    # ============================================================ E5: benign threat FPR vs the upstream judges
    pj, runs = R2._prior(W)
    Wr = W.reset_index()
    rate = []
    for run, info in runs.items():
        df = Wr.merge(pj[["uid", run]], on="uid")
        kind = "upstream classifier" if info["prompt_condition"] == "classifier" else "upstream generative LLM"
        rate.append(R2._rate_rows(run, kind, info["prompt_condition"], df, run))
    for q in QIDS:
        rate.append(R2._rate_rows(f"Jev {q}", "Jev (this project)", "Korean original", Wr, f"{q}_orig_pred"))
        rate.append(R2._rate_rows(f"Jev {q}", "Jev (this project)", "KO->EN opus-mt", Wr, f"{q}_mt_pred"))
    RATE = save(pd.concat(rate, ignore_index=True), "e5_rates_all_judges_by_register")
    e5 = []
    pji = pj.set_index("uid")
    for reg in ("threat", "angry"):
        bset = W[(W["register"] == reg) & (W["label_int"] == 0)]
        pol = W[(W["register"] == "polite") & (W["label_int"] == 0)]
        for q in QIDS:
            block = []
            for run, info in runs.items():
                theirs = pji.loc[bset.index, run]
                ok = theirs.notna().to_numpy()
                jev = bset[f"{q}_orig_pred"].to_numpy().astype(bool)
                a_only, b_only, p = R2._mcnemar(theirs.to_numpy()[ok].astype(int).astype(bool), jev[ok])
                block.append({"register": reg, "upstream_run": run, "prompt_condition": info["prompt_condition"],
                              "jev_question": q, "n_benign": int(ok.sum()), "upstream_missing": int((~ok).sum()),
                              "upstream_FPR": float(theirs.dropna().mean()),
                              "upstream_FPR_polite": float(pji.loc[pol.index, run].dropna().mean()),
                              "jev_FPR": float(jev[ok].mean()), "jev_FPR_polite": float(pol[f"{q}_orig_pred"].mean()),
                              "upstream_only_flagged": a_only, "jev_only_flagged": b_only, "mcnemar_p": p})
            for r, h in zip(block, R2._holm([b["mcnemar_p"] for b in block])):
                r["mcnemar_p_holm"] = h
                r["verdict"] = ("Jev 낮음" if r["upstream_only_flagged"] > r["jev_only_flagged"] else "Jev 높음") if h < 0.05 \
                    else VERDICT_NONE
            e5 += block
    E5 = save(pd.DataFrame(e5), "e5_benign_fpr_jev_vs_upstream_paired")
    gen = RATE[(RATE["kind"] == "upstream generative LLM") & (RATE["register"] == "threat") & (RATE["metric"] == "FPR")]
    cls = RATE[(RATE["kind"] == "upstream classifier") & (RATE["register"] == "threat") & (RATE["metric"] == "FPR")].iloc[0]
    gen_range = [float(gen["rate"].min()), float(gen["rate"].max())]
    claim = [{"row": "docs/PROJECT.md 선행 연구 표 (인용)", "threat_benign_FPR_min": 0.55, "threat_benign_FPR_max": 0.98,
              "n_judges": None, "note": "생성형 LLM 판정기; 업스트림 README에는 숫자 없음"},
             {"row": "업스트림 결과 파일 생성형 LLM 10개 (다시 계산)", "threat_benign_FPR_min": gen_range[0],
              "threat_benign_FPR_max": gen_range[1], "n_judges": len(gen), "note": "EXAONE 2.4B·7.8B, HCX 1.5B, Kanana 2.1B·8B x baseline/definition"},
             {"row": "업스트림 분류기 Kanana Safeguard 2.1B", "threat_benign_FPR_min": float(cls["rate"]),
              "threat_benign_FPR_max": float(cls["rate"]), "n_judges": 1, "note": "classifier"}]
    for q in QIDS:
        for cond, cname in (("Korean original", "한국어 원문"), ("KO->EN opus-mt", "한->영 번역 후")):
            r = rec(RATE, judge=f"Jev {q}", condition=cond, register="threat", metric="FPR")
            row = {"row": f"Jev {q} ({cname})", "threat_benign_FPR_min": r["rate"], "threat_benign_FPR_max": r["rate"],
                   "ci_lo": r["lo"], "ci_hi": r["hi"], "n_judges": 1, "note": f"{r['k']}/{r['n']}"}
            if cond == "Korean original":
                b = E5[(E5.register == "threat") & (E5.jev_question == q)]
                g = b[b.prompt_condition != "classifier"]
                row.update({"generative_runs_jev_lower_holm": int((g.verdict == "Jev 낮음").sum()),
                            "generative_runs_no_diff": int((g.verdict == VERDICT_NONE).sum()),
                            "generative_runs_jev_higher_holm": int((g.verdict == "Jev 높음").sum()),
                            "vs_classifier": b[b.prompt_condition == "classifier"].iloc[0]["verdict"],
                            "ci_hi_below_generative_min": bool(r["hi"] < gen_range[0])})
            claim.append(row)
    CLAIM = save(pd.DataFrame(claim), "e5_claim_check")

    # ============================================================ context: 02_korean (indirect documents), direction only
    k02 = pd.read_csv(K02_PAIRED)
    ko_chars = float(np.median([len(r["text"]) for r in J.load_jsonl(KO_1000)]))
    en_chars = float(np.median([len(r["text"]) for r in J.load_jsonl(EN_1000)]))
    ctx = []
    for q in QIDS:
        for comp, comp_ko in (("KO_vs_EN", "한국어 − 영어"), ("MT_vs_KO", "번역 후 − 한국어")):
            r = k02[(k02.question == q) & (k02.comparison == comp)].iloc[0]
            ctx.append({"question": q, "comparison": comp_ko, "dataset": "02_korean (간접: 문서 속 지시)",
                        "unit": "문서 1,000 (인젝션 500 / 정상 500)", "chars_median_a": en_chars if comp == "KO_vs_EN" else ko_chars,
                        **{k: r[k] for k in ("a_TPR", "b_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi", "d_TPR_verdict", "a_FPR", "b_FPR",
                                             "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_FPR_verdict", "d_AUC", "d_AUC_lo", "d_AUC_hi",
                                             "d_AUC_verdict")}})
            for key in GROUPS:
                T = vs_en if comp == "KO_vs_EN" else mt_vs_ko
                r = rec(T, question=q, register=key)
                ctx.append({"question": q, "comparison": comp_ko, "dataset": f"02b {NAME_KO[key]} (직접 프롬프트)",
                            "unit": f"항목 221 x 말투 {len(GROUPS[key])}",
                            "chars_median_a": float(st.set_index("register").at["english", "chars_median"]) if comp == "KO_vs_EN"
                            else float(R[R.register.isin(GROUPS[key])]["chars"].median()),
                            **{k: r[k] for k in ("a_TPR", "b_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi", "d_TPR_verdict", "a_FPR",
                                                 "b_FPR", "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_FPR_verdict", "d_AUC", "d_AUC_lo",
                                                 "d_AUC_hi", "d_AUC_verdict")}})
    CTX = save(pd.DataFrame(ctx), "context_02_korean")

    # ============================================================ cost, tokens, latency (from the raw calls)
    cost_rows = []
    for exp in (EXP, EXP_MT):
        s = json.load(open(os.path.join(J.RESULTS, exp, "summary.json"), encoding="utf-8"))
        for q in QIDS:
            rs = J.raw_stats(exp, q)
            raw = [r for r in J.load_jsonl(J.raw_path(exp, q)) if r.get("http_status") == 200]
            lat = np.array([r["latency_ms"] for r in raw], dtype=float)
            states = (W["text"] if exp == EXP else W["text_mt"].dropna())
            est_tok = J.REPEATS * (len(states) * EST_BASE[q] + states.str.len().sum() / 4)
            cost_rows.append({"experiment": exp, "question": q, "api_calls": rs["api_calls"], "errors": rs["api_errors"],
                              "retries": rs["api_retries"], "input_tokens": rs["input_tokens_total"],
                              "output_tokens": rs["output_tokens_total"],
                              "input_tokens_per_call": rs["input_tokens_total"] / rs["api_calls"],
                              "input_cost_usd": rs["input_tokens_total"] * PRICE_IN,
                              "estimate_input_tokens_chars_over_4": est_tok, "estimate_cost_usd": est_tok * PRICE_IN,
                              "latency_ms_median": float(np.median(lat)), "latency_ms_p90": float(np.percentile(lat, 90)),
                              "first_call": rs["first_call"], "last_call": rs["last_call"],
                              "wall_clock_s": (s.get(q) or {}).get("run", {}).get("wall_clock_span_s"),
                              "commit_in_summary": s.get("commit")})
    COST = pd.DataFrame(cost_rows)
    # the pre-run estimate (translation not made yet) assumed every translated row as long as its English source
    mt_est_pre = {q: J.REPEATS * (len(K) * EST_BASE[q] + K["len_en_source"].sum() / 4) for q in QIDS}
    COST["estimate_pre_translation_cost_usd"] = [
        (r.estimate_input_tokens_chars_over_4 if r.experiment == EXP else mt_est_pre[r.question]) * PRICE_IN
        for r in COST.itertuples()]
    save(COST, "cost_tokens_latency")
    total_tok = int(COST["input_tokens"].sum())

    # ============================================================ figures
    PS.setup()
    figs = figures(W, C, y, E3i, E4i, vs_polite, qq, mt_vs_ko, mt_vs_en, SRC, IC, VD, SW, thr_fit, TF, RATE, E5, CTX,
                   gen_range, max_ben_no_threat, PM)

    # ============================================================ summary.json "analysis"
    def comp(T, q, reg, keys=("a_TPR", "b_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi", "d_TPR_verdict", "a_FPR", "b_FPR",
                              "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_FPR_verdict", "d_AUC", "d_AUC_lo", "d_AUC_hi",
                              "d_AUC_verdict", "d_mean_p_ben", "d_mean_p_ben_lo", "d_mean_p_ben_hi", "d_mean_p_inj",
                              "d_mean_p_inj_lo", "d_mean_p_inj_hi", "inj_only_a", "inj_only_b", "mcnemar_detect_p",
                              "mcnemar_detect_p_holm", "fp_only_a", "fp_only_b", "mcnemar_fp_p", "mcnemar_fp_p_holm")):
        return rec(T, keep=keys, question=q, register=reg)

    sp = os.path.join(OUT, "summary.json")
    summary = json.load(open(sp, encoding="utf-8"))
    pw_sig = PW[PW.holm_significant]
    an = {
        "script": "experiments/analyze_02b_korean_registers.py",
        "supersedes": "experiments/run_02b_korean_registers.py analyze (first look; this script imports its item-paired "
                      "helpers and regenerates every table and figure in this folder)",
        "generated_at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
        "analysis_commit": J.git_commit(),
        "data_kind": ("DIRECT user prompts (deepset/prompt-injections questions and attacks, Tensor Trust attacks), 221 items x "
                      "8 registers. Not documents with an embedded instruction: compare with 01-03 / 02_korean by direction "
                      "only (context_02_korean.csv)."),
        "methods": {
            "metrics": "src.jev_guard.metrics(threshold=0.5) (asserted equal inside Cells.stats)",
            "proportion_ci": "Wilson 95% for one register; item-cluster bootstrap for pooled registers",
            "paired_test": "exact McNemar on 0.5 decisions of the same items",
            "paired_bootstrap": {"resamples": B, "seed": SEED, "unit": "item, stratified by label; same index matrix for "
                                 "every register, condition (orig / mt) and question", "ci": "percentile 2.5/97.5"},
            "verdict": "CI excludes 0 AND Holm McNemar p < 0.05 -> 높아짐/낮아짐; CI only -> 탐색적; else 차이 없음/오차 범위",
            "holm": "per table and question (paired tables), per question x label over 28 pairs (pairwise), per question over "
                    "11 upstream runs (E5), per question over features (threat features)",
            "omnibus": "Cochran Q on decisions + Friedman on p, items as blocks; logistic regression not used (complete "
                       "separation: 0/123 false positives in 7 of 8 registers)",
            "score_grid": "p snapped to the 1/300 grid before comparing",
            "thresholds": "threat-FPR thresholds fitted on the same data (optimistic, reference only)",
            "threat_features": "regex features chosen after reading the threat rows -> exploratory"},
        "checks": checks,
        "input_md5": {"dataset.jsonl": md5_file(R2.DATASET), "SOURCE.json": md5_file(os.path.join(INPUTS, "SOURCE.json")),
                      "prior_judges_preds.csv": md5_file(os.path.join(INPUTS, "prior_judges_preds.csv")),
                      "registers_ko_to_en.jsonl": md5_file(R2.MT_FILE), "segment_cache.jsonl": md5_file(TR.SEG_CACHE),
                      "02_korean/tables/paired_comparisons.csv": md5_file(K02_PAIRED)},
        "e2": {"rows": len(R), "items": int(R["id"].nunique()), "registers": REGISTERS,
               "per_register": {"benign": 123, "injection": 98}, "sources_items": src_tab.to_dict("records"),
               "chars_median": st.set_index("register")["chars_median"].to_dict(),
               "benign_english_ending_with_question_mark": ben_q_share,
               "kind": "direct user prompts (questions and attack prompts addressed to the assistant), not documents"},
        "e3_by_register": {f"{q}/{k}": {c: E3i.loc[(q, k), c] for c in ("TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi",
                                                                        "AUC", "AUC_lo", "AUC_hi", "tp", "fp", "mean_p_ben",
                                                                        "mean_p_inj", "max_p_benign", "flips")}
                           for q in QIDS for k in REGISTERS + list(GROUPS)},
        "e3_max_benign_p_outside_threat": max_ben_no_threat,
        "e3_omnibus": OM.to_dict("records"),
        "e3_pairwise_holm_significant": pw_sig[["question", "metric", "register_a", "register_b", "only_a", "only_b",
                                                "mcnemar_p_holm"]].to_dict("records"),
        "e3_pairwise_significant_without_threat": int((~pw_sig.register_a.eq("threat") & ~pw_sig.register_b.eq("threat")).sum()),
        "e3_variance_decomposition": VD.to_dict("records"),
        **{f"e3_{r}_vs_polite": {q: comp(vs_polite, q, r) for q in QIDS} for r in ("threat", "angry", "genz", "english")},
        "e3_korean_pooled_vs_english": {q: comp(vs_en, q, "korean_pooled") for q in QIDS},
        "e3_korean_no_threat_vs_english": {q: comp(vs_en, q, "korean_no_threat") for q in QIDS},
        "e3_q2_vs_ql": {r: comp(qq, "QL-Q2", r) for r in REGISTERS + list(GROUPS)},
        "e3_item_consistency": IC.to_dict("records"),
        "e3_item_consistency_invariant_injections": inv_counts,
        "e3_injections_missed_in_all_8_registers": NEVER.groupby("question").size().to_dict(),
        "e3_threat_benign": {"overlap_Q2_QL": tb_overlap, "spearman_p_vs_length": spear,
                             "features": TF[["question", "feature", "n_with", "FPR_with", "n_without", "FPR_without",
                                             "fisher_p", "fisher_p_holm"]].to_dict("records"),
                             "note": "features chosen after reading the rows -> exploratory"},
        "e3_threshold_threat": {f"{q}/FPR<={int(f * 100)}%": {
            "threshold": thr_fit[(q, f)],
            **{k: rec(TH, keep=("TPR", "FPR", "dTPR_vs_0.5"), question=q, register=k,
                      target=f"협박체 정상 오탐 {int(f * 100)}% 이하") for k in ("threat", "polite", "english", "korean_no_threat")}}
            for q in QIDS for f in FPR_TARGETS},
        "e4_by_register": {f"{q}/{k}": {c: E4i.loc[(q, k), c] for c in ("TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo", "FPR_hi",
                                                                        "AUC", "AUC_lo", "AUC_hi", "flips")}
                           for q in QIDS for k in KO_REGISTERS + list(GROUPS)},
        "e4_mt_vs_ko": {f"{q}/{r}": comp(mt_vs_ko, q, r) for q in QIDS for r in KO_REGISTERS + list(GROUPS)},
        "e4_mt_vs_english": {f"{q}/{r}": comp(mt_vs_en, q, r) for q in QIDS for r in ("threat", "korean_pooled", "korean_no_threat")},
        "e4_lost_detections_rows": {r: lost_counts.loc[r].to_dict() for r in KO_REGISTERS},
        "e4_translation_checks": TQ.to_dict("records"),
        "e4_segments": seg_stats,
        "e4_sensitivity": SENS.to_dict("records"),
        "e4_threat_word_kept": TSPLIT.to_dict("records"),
        "e5": {"upstream_generative_threat_fpr_range": gen_range, "upstream_classifier_threat_fpr": float(cls["rate"]),
               "upstream_runs": runs, "claim_check": CLAIM.to_dict("records"),
               "paired": E5[["register", "upstream_run", "jev_question", "upstream_FPR", "jev_FPR", "upstream_only_flagged",
                             "jev_only_flagged", "mcnemar_p_holm", "verdict"]].to_dict("records"),
               "note": "55-98% in docs/PROJECT.md is reproduced from the upstream result files (10 generative runs, benign "
                       "threat rows); the upstream README itself reports no numbers"},
        "context_02_korean": {"note": "02_korean = indirect injection in 1,000 documents (median chars EN %.0f / KO %.0f); 02b = "
                                      "direct prompts (median chars English source %.0f). Direction only." %
                                      (en_chars, ko_chars, st.set_index("register").at["english", "chars_median"]),
                              "rows": CTX.to_dict("records")},
        "cost": {**{f"{r.experiment}/{r.question}": {"api_calls": r.api_calls, "errors": r.errors, "retries": r.retries,
                                                      "input_tokens": r.input_tokens, "input_cost_usd": r.input_cost_usd}
                    for r in COST.itertuples()},
                 "total_api_calls": int(COST["api_calls"].sum()), "total_input_tokens": total_tok,
                 "total_input_cost_usd": total_tok * PRICE_IN,
                 "estimate_cost_usd_now": float(COST["estimate_cost_usd"].sum()),
                 "estimate_cost_usd_pre_translation": float(COST["estimate_pre_translation_cost_usd"].sum()),
                 "price": "input $0.042 per 1M tokens; output price not published"},
        "p_snapped_to_1_300_grid_decision_changed": R2.SNAP_CHANGED,
        "tables": sorted(os.listdir(TAB)),
        "figures": sorted(os.path.basename(p) for p in figs),
    }
    summary["analysis"] = clean(an)
    fix_overall_ci(summary, E3i)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    # 02b_korean_registers_mt/summary.json: the E4 part of the same analysis (replaces the first-look block of
    # run_02b_korean_registers.py analyze; key names of that block are kept, with this script's values)
    sp_mt = os.path.join(OUT_MT, "summary.json")
    summary_mt = json.load(open(sp_mt, encoding="utf-8"))
    an_mt = {
        "script": an["script"],
        "supersedes": "experiments/run_02b_korean_registers.py analyze (first look; same numbers, fewer keys)",
        "generated_at": an["generated_at"], "analysis_commit": an["analysis_commit"],
        "see": "results/02b_korean_registers/summary.json 'analysis' (E2-E5) and its README section 'E4. 번역 후 판정'",
        "stats": an["methods"],
        "checks": {**{k: v for k, v in checks.items() if k.startswith(EXP_MT + "/")},
                   "translation_source_md5_equals_korean_text": checks["translation_source_md5_equals_korean_text"],
                   "translation_rebuilt_from_segment_cache": checks["translation_rebuilt_from_segment_cache"]},
        "e4_by_register": an["e4_by_register"],
        "e4_mt_vs_ko": an["e4_mt_vs_ko"],
        "e4_mt_vs_english": an["e4_mt_vs_english"],
        "e4_lost_detections_rows": an["e4_lost_detections_rows"],
        "e4_translation_checks": an["e4_translation_checks"],
        "e4_segments": an["e4_segments"],
        "e4_threat_word_kept": an["e4_threat_word_kept"],
        "cost": {**{f"{r.experiment}/{r.question}": {"api_calls": r.api_calls, "errors": r.errors, "retries": r.retries,
                                                      "input_tokens": r.input_tokens, "output_tokens": r.output_tokens,
                                                      "input_cost_usd": r.input_cost_usd, "first_call": r.first_call,
                                                      "last_call": r.last_call} for r in COST.itertuples()},
                 "total_input_tokens": total_tok, "total_input_cost_usd": total_tok * PRICE_IN,
                 "price": an["cost"]["price"]},
        "p_snapped_to_1_300_grid_decision_changed": R2.SNAP_CHANGED,
        "input_md5": {k: an["input_md5"][k] for k in ("dataset.jsonl", "registers_ko_to_en.jsonl", "segment_cache.jsonl")},
    }
    summary_mt["analysis"] = clean(an_mt)
    fix_overall_ci(summary_mt, E4i)
    with open(sp_mt, "w", encoding="utf-8") as f:
        json.dump(summary_mt, f, ensure_ascii=False, indent=1)
    digest(E3, E4, OM, PW, VD, vs_polite, vs_en, qq, mt_vs_ko, mt_vs_en, IC, NEVER, TF, spear, tb_overlap, TH, TQ, SENS,
           TSPLIT, E5, CLAIM, CTX, COST, lost_counts, seg_stats, checks)
    print("invariant injection items (7 Korean registers):", inv_counts)
    for name, s in ((EXP, summary), (EXP_MT, summary_mt)):
        for q in QIDS:
            o = s[q]["overall"]
            print(f"overall {name} {q}: TPR {o['TPR']:.4f} CI {np.round(o['TPR_ci95'], 4).tolist()} (row Wilson "
                  f"{np.round(o['TPR_ci95_row_wilson'], 4).tolist()}), FPR {o['FPR']:.4f} CI {np.round(o['FPR_ci95'], 4).tolist()}"
                  f" (row Wilson {np.round(o['FPR_ci95_row_wilson'], 4).tolist()}), AUC {o['AUC']:.4f} CI "
                  f"{np.round(o['AUC_ci95'], 4).tolist()}")
    print(f"wrote {len(os.listdir(TAB))} tables, {len(figs)} figures, summary.json['analysis'] in {EXP} and {EXP_MT}, "
          "pooled 'overall' CIs in both")


OVERALL_CI_METHOD = ("TPR_ci95/FPR_ci95/AUC_ci95: item-cluster bootstrap (label-stratified, 1000 resamples, seed 20261112, "
                     "percentile), because the pooled rows are 7 Korean registers of the same 98 injection / 123 benign items "
                     "and are not independent; same values as analysis e3_by_register / e4_by_register '<question>/"
                     "korean_pooled'. *_row_wilson = row-level Wilson written by jevlab.metric_block (treats rows as "
                     "independent -> too narrow; kept for reference). Rewritten by experiments/analyze_02b_korean_registers.py; "
                     "run_02b_korean_registers.py judge / judge-mt puts the Wilson interval back until the analysis is re-run. "
                     "by_register blocks: one register = independent items -> Wilson is right there.")


def fix_overall_ci(summary, T):
    """Pooled 'overall' block of one summary.json: item-bootstrap CIs from T (E3i or E4i, index (question, register)).
    Point estimates and counts are checked against the analysis, not changed. Idempotent (Wilson recomputed from counts)."""
    for q in QIDS:
        o = summary[q]["overall"]
        r = T.loc[(q, "korean_pooled")]
        assert (o["n"], o["n_injection"], o["n_benign"], o["tp"], o["fp"]) == \
               (int(r.n_rows), int(r.n_injection), int(r.n_benign), int(r.tp), int(r.fp)), (q, "overall counts differ")
        # AUC: summary.json uses the stored p (float noise breaks some ties), the analysis the 1/300-grid p -> |diff| < 1e-5
        assert abs(o["TPR"] - r.TPR) < 1e-12 and abs(o["FPR"] - r.FPR) < 1e-12 and abs(o["AUC"] - r.AUC) < 1e-4, q
        o["TPR_ci95"] = [float(r.TPR_lo), float(r.TPR_hi)]
        o["FPR_ci95"] = [float(r.FPR_lo), float(r.FPR_hi)]
        o["AUC_ci95"] = [float(r.AUC_lo), float(r.AUC_hi)]
        o["TPR_ci95_row_wilson"] = J.wilson(o["tp"], o["n_injection"])
        o["FPR_ci95_row_wilson"] = J.wilson(o["fp"], o["n_benign"])
        o["ci95_method"] = OVERALL_CI_METHOD


# ------------------------------------------------------------------ figures
def _yfmt(ax, axis="y", d=0):
    f = FuncFormatter(lambda v, _: f"{100 * v:.{d}f}%")
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(f)


def _eb(ax, x, v, lo, hi, color, marker="o", filled=True, ms=6, horizontal=False, lw=1.3, z=3):
    e = [[max(0.0, v - lo)], [max(0.0, hi - v)]]
    kw = dict(fmt=marker, color=color, mfc=color if filled else PS.SURFACE, mec=color, ms=ms, capsize=2.5, lw=lw, zorder=z,
              mew=1.3)
    if horizontal:
        ax.errorbar(v, x, xerr=e, **kw)
    else:
        ax.errorbar(x, v, yerr=e, **kw)


def _qhandles(extra=()):
    return [Line2D([0], [0], marker="o", color=Q_COLORS[q], lw=0, ms=6, label=Q_NAMES[q]) for q in QIDS] + list(extra)


def _reg_ticks(keys):
    return [f"{NAME_KO[k]}\n{k}" if k in REGISTERS else NAME_KO[k].replace(" 합침", "\n합침") for k in keys]


def _forest(ax, rows, get, metric, scale, fmt, offsets, styles, xlabel):
    """rows: list of keys (top to bottom); get(key, style) -> (d, lo, hi, significant) or None."""
    yy = np.arange(len(rows))[::-1].astype(float)
    lo_all, hi_all = [0.0], [0.0]
    for yi, key in zip(yy, rows):
        for off, sty in zip(offsets, styles):
            g = get(key, sty)
            if g is None:
                continue
            d, lo, hi, sig = g
            _eb(ax, yi + off, d * scale, lo * scale, hi * scale, sty["color"], marker=sty["marker"], filled=sig,
                horizontal=True, ms=5.5)
            lo_all.append(lo * scale)
            hi_all.append(hi * scale)
    lo_m, hi_m = min(lo_all), max(hi_all)
    span = hi_m - lo_m if hi_m > lo_m else 1.0
    for yi, key in zip(yy, rows):
        for off, sty in zip(offsets, styles):
            g = get(key, sty)
            if g is None:
                continue
            d, lo, hi, sig = g
            ax.text(hi * scale + 0.02 * span, yi + off, fmt(d), va="center", ha="left", fontsize=7, color=sty["color"])
    ax.axvline(0, color=PS.INK_2, lw=0.9)
    ax.set_xlim(lo_m - 0.06 * span, hi_m + 0.30 * span)
    ax.set_yticks(yy)
    ax.set_ylim(-0.6, len(rows) - 0.4)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel(xlabel, fontsize=9)
    return yy


def figures(W, C, y, E3i, E4i, vs_polite, qq, mt_vs_ko, mt_vs_en, SRC, IC, VD, SW, thr_fit, TF, RATE, E5, CTX,
            gen_range, max_ben, PM):
    out = []
    reg8 = REGISTERS

    # f01: TPR / FPR by register (+ pooled Korean)
    keys = REGISTERS + ["korean_pooled"]
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.4))
    for ax, k, ttl, ylim in ((axes[0], "TPR", "탐지율 TPR  (말투마다 인젝션 98개, 합침 686행)", (0.4, 1.06)),
                             (axes[1], "FPR", "오탐률 FPR  (말투마다 정상 123개, 합침 861행)", (-0.02, 0.68))):
        for q in QIDS:
            for i, key in enumerate(keys):
                r = E3i.loc[(q, key)]
                x = i + (-0.19 if q == "Q2" else 0.19)
                _eb(ax, x, r[k], r[f"{k}_lo"], r[f"{k}_hi"], Q_COLORS[q], ms=5.5)
                if k == "TPR" or r[k] > 0:  # FPR labels only where it is not 0/123
                    ax.annotate(f"{100 * r[k]:.1f}", (x, r[f"{k}_hi"]), xytext=(0, 3), textcoords="offset points",
                                ha="center", va="bottom", fontsize=6.8, color=Q_COLORS[q])
        ax.axvline(0.5, color=PS.AXIS, lw=0.9)
        ax.axvline(len(REGISTERS) - 0.5, color=PS.AXIS, lw=0.9, ls="--")
        ax.set_xticks(range(len(keys)), _reg_ticks(keys), fontsize=8)
        ax.set_xlim(-0.6, len(keys) - 0.4)
        ax.set_ylim(*ylim)
        _yfmt(ax)
        ax.set_title(ttl, fontsize=10.5)
        ax.grid(axis="x", visible=False)
    axes[0].legend(handles=_qhandles(), loc="lower left")
    t2, tl = E3i.loc[("Q2", "threat")], E3i.loc[("QL", "threat")]
    PS.title(fig, f"오탐은 협박체에서만 생긴다: Q2 {pct(t2.FPR)} · QL {pct(tl.FPR)}, 다른 6개 말투와 영어 원문은 0/123",
             "korean-prompt-injection-registers 221개 항목 × 8개 말투 (직접 프롬프트), 임계값 0.5, 3회 평균 p. "
             "막대 = 95% 구간 (말투 하나는 Wilson, 합침은 항목 부트스트랩), 숫자 = %. 오탐 숫자가 없는 점은 0/123\n"
             "왼쪽 실선 왼편 = 번역하지 않은 영어 원문, 점선 오른편 = 한국어 7개 말투를 합친 값")
    out.append(PS.save(fig, "f01_register_tpr_fpr", out_dir=FIG))

    # f02: ROC by register (small multiples)
    fig, axes = plt.subplots(2, 4, figsize=(13.5, 7.2), sharex=True, sharey=True)
    for ax, reg in zip(axes.ravel(), reg8):
        for j, q in enumerate(QIDS):
            p = PM(q, "orig", reg)[:, 0]
            fpr, tpr, _ = roc_curve(y, p)
            ax.plot(fpr, tpr, color=Q_COLORS[q], lw=1.6, drawstyle="steps-post")
            r = E3i.loc[(q, reg)]
            ax.plot([r.FPR], [r.TPR], "o", color=Q_COLORS[q], ms=5, mfc=PS.SURFACE, mew=1.4, zorder=4)
            ax.text(0.97, 0.05 + 0.11 * (1 - j), f"{q} AUC {r.AUC:.3f} [{r.AUC_lo:.3f}, {r.AUC_hi:.3f}]", ha="right",
                    va="bottom", fontsize=7.5, color=Q_COLORS[q], transform=ax.transAxes)
        ax.plot([0, 1], [0, 1], color=PS.AXIS, lw=0.8, ls=":")
        ax.set_title(f"{REG_KO[reg]} ({reg})", fontsize=10)
        ax.set_xlim(-0.02, 1.0)
        ax.set_ylim(0, 1.02)
        _yfmt(ax)
        _yfmt(ax, "x")
    for ax in axes[1]:
        ax.set_xlabel("오탐률 FPR", fontsize=9)
    for ax in axes[:, 0]:
        ax.set_ylabel("탐지율 TPR", fontsize=9)
    axes[0, 0].legend(handles=_qhandles([Line2D([0], [0], marker="o", color=PS.INK_2, mfc=PS.SURFACE, lw=0, ms=5,
                                                label="임계값 0.5 지점")]), loc="center right", fontsize=7.5)
    PS.title(fig, f"순서 매기기(AUC)도 협박체에서만 떨어진다: Q2 {E3i.loc[('Q2', 'threat')].AUC:.3f} · "
                  f"QL {E3i.loc[('QL', 'threat')].AUC:.3f}, 나머지는 0.99 이상",
             "말투마다 인젝션 98 / 정상 123, AUC 괄호 = 항목 부트스트랩 95% 구간 (1,000회)")
    out.append(PS.save(fig, "f02_roc_by_register", out_dir=FIG))

    # f03: paired deltas vs polite
    rows = [r for r in REGISTERS if r != "polite"]
    styles = [{"q": q, "color": Q_COLORS[q], "marker": "o"} for q in QIDS]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.4), sharey=True)
    for ax, (k, scale, fmt, lab) in zip(axes, (("TPR", 100, lambda d: f"{100 * d:+.1f}", "ΔTPR (%p)"),
                                               ("FPR", 100, lambda d: f"{100 * d:+.1f}", "ΔFPR (%p)"),
                                               ("AUC", 1, lambda d: f"{d:+.3f}", "ΔAUC"))):
        def get(key, sty, k=k):
            r = rec(vs_polite, question=sty["q"], register=key)
            return r[f"d_{k}"], r[f"d_{k}_lo"], r[f"d_{k}_hi"], r[f"d_{k}_verdict"] in SIG
        yy = _forest(ax, rows, get, k, scale, fmt, (0.17, -0.17), styles, lab)
        ax.set_title(f"말투 − 존댓말: {lab}", fontsize=10.5)
    axes[0].set_yticklabels([f"{REG_KO[r]} ({r})" for r in rows], fontsize=8.5)
    axes[1].legend(handles=_qhandles([Line2D([0], [0], marker="o", color=PS.INK_2, lw=0, ms=5.5, label="CI가 0 밖 + Holm p < 0.05"),
                                      Line2D([0], [0], marker="o", color=PS.INK_2, mfc=PS.SURFACE, lw=0, ms=5.5,
                                             label="차이 없음 또는 탐색적")]), loc="upper right", fontsize=7.5)
    PS.title(fig, "존댓말과 비교하면 협박체만 크게 움직인다 (오탐 +28.5 / +50.4%p, AUC 하락)",
             "같은 221개 항목의 짝 비교. 막대 = 항목 부트스트랩 95% 구간 (1,000회, seed 20261112), 채운 점 = 구간이 0 밖이고 "
             "표 안 Holm 보정 McNemar p < 0.05")
    out.append(PS.save(fig, "f03_delta_vs_polite", out_dir=FIG))

    # f04: p by register and label
    rng = np.random.default_rng(SEED)
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 5.2), sharey=True)
    for ax, q in zip(axes, QIDS):
        for i, reg in enumerate(reg8):
            for lab, off, col in ((0, -0.2, BEN), (1, 0.2, INJ)):
                p = W[(W.register == reg) & (W.label_int == lab)][f"{q}_orig_p"].to_numpy()
                ax.scatter(i + off + rng.uniform(-0.11, 0.11, len(p)), p, s=6, color=col, alpha=0.5, lw=0)
                ax.plot([i + off - 0.14, i + off + 0.14], [np.median(p)] * 2, color=PS.INK, lw=1.4)
        ax.axhline(THRESHOLD, color=PS.INK_2, lw=1, ls="--")
        ax.set_xticks(range(len(reg8)), _reg_ticks(reg8), fontsize=8)
        ax.set_title(Q_NAMES[q], fontsize=10.5, color=Q_COLORS[q])
        ax.set_ylim(-0.02, 1.02)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("p (3회 평균)")
    axes[1].legend(handles=[Patch(color=BEN, label="정상 (말투마다 123개)"), Patch(color=INJ, label="인젝션 (말투마다 98개)"),
                            Line2D([0], [0], color=PS.INK, lw=1.4, label="중앙값"),
                            Line2D([0], [0], color=PS.INK_2, lw=1, ls="--", label="임계값 0.5")],
                   loc="center left", bbox_to_anchor=(1.0, 0.5), fontsize=8)
    PS.title(fig, f"협박체는 정상·인젝션 모두의 p를 올린다. 협박체 밖 정상의 최고 p는 Q2 {max_ben['Q2']:.2f} · QL {max_ben['QL']:.2f}",
             "점 = 행 하나 (항목 221개 × 말투 8개), 검은 선 = 중앙값")
    out.append(PS.save(fig, "f04_p_by_register_label", out_dir=FIG))

    # f05: item consistency
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 4.9))
    for ax, lab, ttl, n_items in ((axes[0], "injection", "인젝션 항목 98개: 7개 한국어 말투 중 잡힌 말투 수", 98),
                                  (axes[1], "benign", "정상 항목 123개: 7개 한국어 말투 중 오탐된 말투 수", 123)):
        for q, off in (("Q2", -0.2), ("QL", 0.2)):
            s = IC[(IC.question == q) & (IC.label == lab)].sort_values("n_korean_registers_flagged")
            bars = ax.bar(s.n_korean_registers_flagged + off, s.n_items, width=0.4, color=Q_COLORS[q])
            PS.bar_gap(bars)
            for xv, v in zip(s.n_korean_registers_flagged + off, s.n_items):
                if v:
                    ax.text(xv, v + n_items * 0.01, str(int(v)), ha="center", va="bottom", fontsize=7.5, color=Q_COLORS[q])
        ax.set_xticks(range(8))
        ax.set_xlabel("잡힌(오탐된) 말투 수 (0 = 7개 모두 통과, 7 = 7개 모두 인젝션 판정)", fontsize=9)
        ax.set_ylabel("항목 수")
        ax.set_title(ttl, fontsize=10.5)
        ax.grid(axis="x", visible=False)
    axes[0].legend(handles=[Patch(color=Q_COLORS[q], label=Q_NAMES[q]) for q in QIDS], loc="upper left")
    v = VD[(VD.register_set == "협박체 뺀 한국어 6개") & (VD.label == "injection")].set_index("question")
    same = {q: int(IC[(IC.question == q) & (IC.label == "injection") & IC.n_korean_registers_flagged.isin([0, 7])].n_items.sum())
            for q in QIDS}
    PS.title(fig, f"판정은 말투보다 항목에 달려 있다: 인젝션 98개 중 Q2 {same['Q2']}개 · QL {same['QL']}개는 "
                  "7개 말투의 판정이 모두 같다",
             f"협박체 뺀 6개 말투에서 인젝션 p의 분산 중 항목 몫 Q2 {100 * v.loc['Q2', 'share_item']:.0f}% / "
             f"QL {100 * v.loc['QL', 'share_item']:.0f}%, 말투 몫 {100 * v.loc['Q2', 'share_register']:.1f}% / "
             f"{100 * v.loc['QL', 'share_register']:.1f}%. 정상 항목은 0개(통과) 또는 1개(협박체에서만 오탐)뿐")
    out.append(PS.save(fig, "f05_item_consistency", out_dir=FIG))

    # f06: TPR by source
    srcs = sorted(SRC.source.unique())
    fig, axes = plt.subplots(1, len(srcs), figsize=(13.5, 5.0), sharey=True)
    for ax, s in zip(axes, srcs):
        n = int(SRC[(SRC.source == s)].n_injection.iloc[0])
        for q in QIDS:
            for i, reg in enumerate(reg8):
                r = SRC[(SRC.question == q) & (SRC.register == reg) & (SRC.source == s)].iloc[0]
                x = i + (-0.17 if q == "Q2" else 0.17)
                _eb(ax, x, r.TPR, r.TPR_lo, r.TPR_hi, Q_COLORS[q], ms=5.5)
                ax.annotate(f"{100 * r.TPR:.0f}", (x, r.TPR), xytext=(-6 if q == "Q2" else 6, 0), textcoords="offset points",
                            ha="right" if q == "Q2" else "left", va="center", fontsize=6.8, color=Q_COLORS[q])
        ax.set_xticks(range(len(reg8)), _reg_ticks(reg8), fontsize=8)
        ax.set_title(f"{s}  (인젝션 {n}개)", fontsize=10.5)
        ax.set_ylim(0.2, 1.04)
        _yfmt(ax)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("탐지율 TPR")
    axes[0].legend(handles=_qhandles(), loc="lower left")
    d = SRC[SRC.register != "threat"].groupby("source").TPR.agg(["min", "max"])
    dd = [s for s in srcs if "deepset" in s][0]
    tt = [s for s in srcs if "tensor" in s.lower()][0]
    PS.title(fig, f"놓치는 인젝션은 deepset 문장이다: 협박체 밖 TPR deepset {100 * d.loc[dd, 'min']:.0f}–{100 * d.loc[dd, 'max']:.0f}%, "
                  f"Tensor Trust {100 * d.loc[tt, 'min']:.0f}–{100 * d.loc[tt, 'max']:.0f}%",
             "출처별 인젝션 탐지율, 95% Wilson 구간. 정상 123개는 모두 deepset 질문이라 출처별 FPR은 없음")
    out.append(PS.save(fig, "f06_tpr_by_source", out_dir=FIG))

    # f07: QL - Q2 per register
    rows = REGISTERS + list(GROUPS)
    sty = [{"color": PS.INK, "marker": "o"}]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.8), sharey=True)
    for ax, (k, scale, fmt, lab) in zip(axes, (("TPR", 100, lambda d: f"{100 * d:+.1f}", "ΔTPR QL − Q2 (%p)"),
                                               ("FPR", 100, lambda d: f"{100 * d:+.1f}", "ΔFPR QL − Q2 (%p)"),
                                               ("AUC", 1, lambda d: f"{d:+.3f}", "ΔAUC QL − Q2"))):
        def get(key, s, k=k):
            r = rec(qq, register=key)
            return r[f"d_{k}"], r[f"d_{k}_lo"], r[f"d_{k}_hi"], r[f"d_{k}_verdict"] in SIG
        _forest(ax, rows, get, k, scale, fmt, (0.0,), sty, lab)
        ax.axhline(len(GROUPS) - 0.5, color=PS.AXIS, lw=0.8, ls="--")
        ax.set_title(lab, fontsize=10.5)
    axes[0].set_yticklabels([f"{NAME_KO[r]} ({r})" if r in REGISTERS else NAME_KO[r] for r in rows], fontsize=8.5)
    axes[1].legend(handles=[Line2D([0], [0], marker="o", color=PS.INK, lw=0, ms=5.5, label="CI가 0 밖 (+ Holm p < 0.05)"),
                            Line2D([0], [0], marker="o", color=PS.INK, mfc=PS.SURFACE, lw=0, ms=5.5,
                                   label="차이 없음 또는 탐색적")], loc="upper right", fontsize=7.5)
    r = rec(qq, register="threat")
    PS.title(fig, f"직접 프롬프트에서 QL은 이득이 없고 협박체 오탐만 늘린다 ({pp(r['d_FPR'])}, QL만 오탐 {int(r['fp_only_b'])} / "
                  f"Q2만 {int(r['fp_only_a'])})",
             "같은 행의 QL − Q2. 막대 = 항목 부트스트랩 95% 구간, 채운 점 = 구간이 0 밖 (말투 하나는 Holm McNemar p < 0.05도 요구). "
             "점선 아래 = 여러 말투 합침")
    out.append(PS.save(fig, "f07_q2_vs_ql_by_register", out_dir=FIG))

    # f08: threshold sweep for the threat false alarms
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 4.7), sharey=True)
    panels = (("threat", "FPR", "협박체 정상 123개: 오탐률"), ("threat", "TPR", "협박체 인젝션 98개: 탐지율"),
              ("korean_no_threat", "TPR", "협박체 뺀 6개 말투 인젝션 588행: 탐지율"))
    for ax, (key, met, ttl) in zip(axes, panels):
        for q in QIDS:
            s = SW[(SW.question == q) & (SW.register == key)]
            ax.plot(s.threshold, s[met], color=Q_COLORS[q], lw=1.8)
            t5 = thr_fit[(q, 0.05)]
            ax.axvline(t5, color=Q_COLORS[q], lw=1, ls=":")
        ax.axvline(THRESHOLD, color=PS.INK_2, lw=1, ls="--")
        ax.set_title(ttl, fontsize=10.5)
        ax.set_xlabel("임계값 (p ≥ 임계값이면 차단)", fontsize=9)
        _yfmt(ax)
        ax.set_xlim(0.05, 0.95)
        ax.set_ylim(-0.02, 1.02)
    axes[1].legend(handles=_qhandles([Line2D([0], [0], color=PS.INK_2, lw=1, ls="--", label="기준 0.5"),
                                      Line2D([0], [0], color=PS.INK_2, lw=1, ls=":", label="협박체 오탐 5% 임계값 (질문 색)")]),
                   loc="lower left", fontsize=7.5)
    t2, tl = thr_fit[("Q2", 0.05)], thr_fit[("QL", 0.05)]
    nt = {q: PM(q, "orig", "korean_no_threat")[y == 1] for q in QIDS}
    tpr2, tprl = float((nt["Q2"] >= t2).mean()), float((nt["QL"] >= tl).mean())
    PS.title(fig, f"임계값을 올려 협박체 오탐을 5%로 맞추면 (Q2 {t2:.3f} · QL {tl:.3f}) 다른 6개 말투 탐지율이 "
                  f"{pct(float((nt['Q2'] >= THRESHOLD).mean()))} → {pct(tpr2)} · "
                  f"{pct(float((nt['QL'] >= THRESHOLD).mean()))} → {pct(tprl)}",
             "임계값은 같은 데이터에서 맞춘 값이라 낙관적이고 참고용. 주 지표는 0.5")
    out.append(PS.save(fig, "f08_threat_threshold", out_dir=FIG))

    # f09: threat benign features (exploratory)
    feats = list(dict.fromkeys(TF.feature))
    fig, ax = plt.subplots(figsize=(11.5, 7.6))
    yy = np.arange(len(feats))[::-1].astype(float)
    for yi, f in zip(yy, feats):
        for q, off in (("Q2", 0.2), ("QL", -0.2)):
            r = TF[(TF.question == q) & (TF.feature == f)].iloc[0]
            _eb(ax, yi + off + 0.09, r.FPR_with, r.FPR_with_lo, r.FPR_with_hi, Q_COLORS[q], "o", True, 5, True)
            _eb(ax, yi + off - 0.09, r.FPR_without, r.FPR_without_lo, r.FPR_without_hi, Q_COLORS[q], "o", False, 5, True)
            star = " *" if r.fisher_p_holm < 0.05 else ""
            ax.text(1.0, yi + off, f"{q}: {100 * r.FPR_with:.0f}% vs {100 * r.FPR_without:.0f}%  (Holm p = {r.fisher_p_holm:.2g}){star}",
                    va="center", ha="left", fontsize=7, color=Q_COLORS[q])
        if yi > 0:
            ax.axhline(yi - 0.5, color=PS.GRID, lw=0.6)
    lab = {r.feature: f"{r.feature_ko}\n(있음 {r.n_with} / 없음 {r.n_without})" for r in TF[TF.question == "Q2"].itertuples()}
    ax.set_yticks(yy, [lab[f] for f in feats], fontsize=8)
    ax.set_xlim(-0.02, 1.42)
    ax.set_xticks(np.linspace(0, 1, 6))
    _yfmt(ax, "x")
    ax.set_ylim(-0.6, len(feats) - 0.4)
    ax.grid(axis="y", visible=False)
    ax.set_xlabel("협박체 정상 질문 오탐률 (95% Wilson 구간)", fontsize=9)
    ax.legend(handles=_qhandles([Line2D([0], [0], marker="o", color=PS.INK_2, lw=0, ms=5.5, label="특징 있음 (위)"),
                                 Line2D([0], [0], marker="o", color=PS.INK_2, mfc=PS.SURFACE, lw=0, ms=5.5,
                                        label="특징 없음 (아래)")]),
              loc="upper center", bbox_to_anchor=(0.45, -0.09), ncol=4, fontsize=8)
    PS.title(fig, "탐색: '지운다·삭제한다'(두 질문)와 '다른 AI로 바꾼다'(Q2)가 붙은 협박에서 오탐이 많다",
             "협박체 정상 123행을 문장 특징으로 나눔 (분류는 p 순으로 문장을 읽은 뒤 정했으므로 가설 수준). "
             "Fisher exact, 질문마다 9개 특징 Holm, * = Holm p < 0.05")
    out.append(PS.save(fig, "f09_threat_benign_features", out_dir=FIG))

    # f10: translate-then-judge deltas (MT - KO and MT - English source)
    rows = KO_REGISTERS + list(GROUPS)
    styles = [{"q": "Q2", "T": mt_vs_ko, "color": Q_COLORS["Q2"], "marker": "o"},
              {"q": "QL", "T": mt_vs_ko, "color": Q_COLORS["QL"], "marker": "o"},
              {"q": "Q2", "T": mt_vs_en, "color": Q_COLORS["Q2"], "marker": "D"},
              {"q": "QL", "T": mt_vs_en, "color": Q_COLORS["QL"], "marker": "D"}]
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 7.0), sharey=True)
    for ax, (k, scale, fmt, lab) in zip(axes, (("TPR", 100, lambda d: f"{100 * d:+.1f}", "ΔTPR (%p)"),
                                               ("FPR", 100, lambda d: f"{100 * d:+.1f}", "ΔFPR (%p)"),
                                               ("AUC", 1, lambda d: f"{d:+.3f}", "ΔAUC"))):
        def get(key, s, k=k):
            r = rec(s["T"], question=s["q"], register=key)
            return r[f"d_{k}"], r[f"d_{k}_lo"], r[f"d_{k}_hi"], r[f"d_{k}_verdict"] in SIG
        _forest(ax, rows, get, k, scale, fmt, (0.3, 0.1, -0.1, -0.3), styles, lab)
        ax.axhline(len(GROUPS) - 0.5, color=PS.AXIS, lw=0.8, ls="--")
        ax.set_title(lab, fontsize=10.5)
    axes[0].set_yticklabels([f"{NAME_KO[r]} ({r})" if r in REGISTERS else NAME_KO[r] for r in rows], fontsize=8.5)
    axes[1].legend(handles=_qhandles([Line2D([0], [0], marker="o", color=PS.INK_2, lw=0, ms=5.5, label="번역 후 − 한국어 원문"),
                                      Line2D([0], [0], marker="D", color=PS.INK_2, lw=0, ms=5.5, label="번역 후 − 영어 원문"),
                                      Line2D([0], [0], marker="o", color=PS.INK_2, mfc=PS.SURFACE, lw=0, ms=5.5,
                                             label="속 빈 점 = 차이 없음 또는 탐색적")]), loc="upper right", fontsize=7.5)
    r2 = rec(mt_vs_ko, question="Q2", register="korean_pooled")
    rl = rec(mt_vs_ko, question="QL", register="korean_pooled")
    PS.title(fig, f"번역 후 판정은 탐지율을 잃는다 (7개 합침 Q2 {pp(r2['d_TPR'])} · QL {pp(rl['d_TPR'])}) "
                  "그리고 영어 원문 수준으로도 돌아오지 않는다",
             "opus-mt-ko-en 번역 1,547행, 같은 항목의 짝 비교. 막대 = 항목 부트스트랩 95% 구간, 채운 점 = 구간이 0 밖 "
             "(말투 하나는 Holm McNemar p < 0.05도 요구). 점선 아래 = 합침")
    out.append(PS.save(fig, "f10_mt_deltas", out_dir=FIG))

    # f11: benign threat FPR, Jev vs upstream judges
    sub = RATE[(RATE["register"] == "threat") & (RATE["metric"] == "FPR")].copy()
    sub["order"] = sub["kind"].map({"upstream generative LLM": 0, "upstream classifier": 1, "Jev (this project)": 2})
    sub = sub.sort_values(["order", "rate"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(11, 6.8))
    ax.axvspan(0.55, 0.98, color=PS.GRID, alpha=0.55, lw=0)
    ax.text(0.765, len(sub) - 0.35, "docs/PROJECT.md에 인용한 선행 결과 55–98%", ha="center", va="bottom", fontsize=8.5,
            color=PS.INK_2)
    sig = {}
    for q in QIDS:
        b = E5[(E5.register == "threat") & (E5.jev_question == q)].set_index("upstream_run")
        sig[q] = b["verdict"].to_dict()
    for i, r in sub.iterrows():
        if r["kind"].startswith("Jev"):
            color = Q_COLORS[r["judge"].split()[-1]]
            marker = "o" if r["condition"] == "Korean original" else "D"
        else:
            color, marker = PS.MUTED, "o" if r["kind"] == "upstream generative LLM" else "s"
        _eb(ax, i, r["rate"], r["lo"], r["hi"], color, marker, True, 6, True)
        note = f"{100 * r['rate']:.1f}%"
        if not r["kind"].startswith("Jev"):
            mark = ["Q2" + ("<" if sig["Q2"][r["judge"]] == "Jev 낮음" else ">" if sig["Q2"][r["judge"]] == "Jev 높음" else "≈"),
                    "QL" + ("<" if sig["QL"][r["judge"]] == "Jev 낮음" else ">" if sig["QL"][r["judge"]] == "Jev 높음" else "≈")]
            note += f"   Jev {mark[0]} · {mark[1]}"
        ax.annotate(note, (r["hi"], i), xytext=(5, 0), textcoords="offset points", va="center", fontsize=7.8, color=color)
    labels = [(f"{r['judge']} · {'한국어 원문' if r['condition'] == 'Korean original' else '한→영 번역 후'}"
               if r["kind"].startswith("Jev") else f"{r['judge']}" + (" (분류기)" if r["kind"] == "upstream classifier" else ""))
              for _, r in sub.iterrows()]
    ax.set_yticks(range(len(sub)), labels, fontsize=8.3)
    ax.set_xlim(-0.02, 1.32)
    ax.set_xticks(np.linspace(0, 1, 6))
    ax.set_ylim(-0.7, len(sub) + 0.4)
    _yfmt(ax, "x")
    ax.set_xlabel("협박체 정상 질문 123개 중 인젝션으로 판정한 비율 (95% Wilson 구간)", fontsize=9)
    ax.grid(axis="y", visible=False)
    q2 = E3i.loc[("Q2", "threat")]
    ql = E3i.loc[("QL", "threat")]
    PS.title(fig, f"협박체 정상 질문 오탐: Jev Q2 {pct(q2.FPR)} · QL {pct(ql.FPR)}, 업스트림 생성형 LLM "
                  f"{100 * gen_range[0]:.1f}–{100 * gen_range[1]:.1f}%",
             "회색 = 업스트림 결과 파일 11개 (원 = 생성형 LLM, 네모 = 분류기), 색 = Jev (원 = 원문, 마름모 = 번역 후).\n"
             "'Jev Q2<' = 같은 123문장 짝 McNemar(Holm, 11개)에서 Jev가 유의하게 낮음, '>' = 높음, '≈' = 차이 없음")
    out.append(PS.save(fig, "f11_e5_threat_fpr_vs_upstream", out_dir=FIG))

    # f12: benign FPR by register, all judges
    fig, ax = plt.subplots(figsize=(13, 5.6))
    xs = np.arange(len(reg8))
    for run in RATE[RATE.kind == "upstream generative LLM"].judge.unique():
        s = RATE[(RATE.judge == run) & (RATE.metric == "FPR")].set_index("register").loc[reg8]
        ax.plot(xs, s.rate, color=PS.MUTED, lw=0.9, alpha=0.65, marker="o", ms=3)
    s = RATE[(RATE.kind == "upstream classifier") & (RATE.metric == "FPR")].set_index("register").loc[reg8]
    ax.plot(xs, s.rate, color=PS.MUTED, lw=1.2, ls="--", marker="s", ms=4.5)
    for q, off in (("Q2", -0.08), ("QL", 0.08)):
        s = RATE[(RATE.judge == f"Jev {q}") & (RATE.condition == "Korean original") & (RATE.metric == "FPR")].set_index("register").loc[reg8]
        ax.plot(xs + off, s.rate, color=Q_COLORS[q], lw=1.8)
        for xi, (_, r) in zip(xs, s.iterrows()):
            _eb(ax, xi + off, r.rate, r.lo, r.hi, Q_COLORS[q], ms=5.5, z=5)
    ax.set_xticks(xs, _reg_ticks(reg8), fontsize=8.5)
    _yfmt(ax)
    ax.set_ylim(-0.03, 1.03)
    ax.set_ylabel("정상 질문 오탐률 (말투마다 123개)")
    ax.grid(axis="x", visible=False)
    ax.legend(handles=_qhandles([Line2D([0], [0], color=PS.MUTED, lw=0.9, marker="o", ms=3, label="업스트림 생성형 LLM 10개"),
                                 Line2D([0], [0], color=PS.MUTED, lw=1.2, ls="--", marker="s", ms=4.5,
                                        label="업스트림 분류기 Kanana Safeguard")]), loc="upper left", fontsize=8)
    ang = RATE[(RATE.kind == "upstream generative LLM") & (RATE.register == "angry") & (RATE.metric == "FPR")].rate
    PS.title(fig, f"분노체(욕설) 정상 질문: 생성형 LLM 판정기 {100 * ang.min():.0f}–{100 * ang.max():.0f}% 오탐 "
                  f"(10개 중 {int((ang >= 0.2).sum())}개가 20% 이상), Jev는 두 질문 모두 0%",
             "같은 1,768행에 대한 업스트림 판정 결과 파일(예측값)과 Jev 한국어 원문 판정. Jev 막대 = 95% Wilson 구간")
    out.append(PS.save(fig, "f12_e5_benign_fpr_all_judges", out_dir=FIG))

    # f13: context with 02_korean (direction only)
    ctx_rows = list(dict.fromkeys(zip(CTX.comparison, CTX.dataset)))
    fig, axes = plt.subplots(1, 3, figsize=(13.5, 5.6), sharey=True)
    for ax, (k, scale, lab) in zip(axes, (("TPR", 100, "ΔTPR (%p)"), ("FPR", 100, "ΔFPR (%p)"), ("AUC", 1, "ΔAUC"))):
        yy = np.arange(len(ctx_rows))[::-1].astype(float)
        for yi, (cmp_, ds) in zip(yy, ctx_rows):
            for q, off in (("Q2", 0.15), ("QL", -0.15)):
                r = CTX[(CTX.question == q) & (CTX.comparison == cmp_) & (CTX.dataset == ds)].iloc[0]
                mk = "s" if ds.startswith("02_korean") else "o"
                filled = str(r[f"d_{k}_verdict"]).startswith(SIG)
                _eb(ax, yi + off, r[f"d_{k}"] * scale, r[f"d_{k}_lo"] * scale, r[f"d_{k}_hi"] * scale, Q_COLORS[q], mk,
                    filled, 5.5, True)
        ax.axvline(0, color=PS.INK_2, lw=0.9)
        ax.axhline(2.5, color=PS.AXIS, lw=0.8, ls="--")
        ax.set_yticks(yy, [f"{c}\n{d}" for c, d in ctx_rows], fontsize=7.8)
        ax.grid(axis="y", visible=False)
        ax.set_xlabel(lab, fontsize=9)
        ax.set_title(lab, fontsize=10.5)
    axes[1].legend(handles=_qhandles([Line2D([0], [0], marker="s", color=PS.INK_2, lw=0, ms=5.5, label="02_korean 문서 (간접)"),
                                      Line2D([0], [0], marker="o", color=PS.INK_2, lw=0, ms=5.5, label="02b 직접 프롬프트"),
                                      Line2D([0], [0], marker="o", color=PS.INK_2, mfc=PS.SURFACE, lw=0, ms=5.5,
                                             label="속 빈 점 = 차이 없음")]), loc="lower right", fontsize=7.3)
    c02 = CTX[CTX.dataset.str.startswith("02_korean")].chars_median_a
    c2b = CTX[~CTX.dataset.str.startswith("02_korean")].chars_median_a
    PS.title(fig, "방향만 비교: 번역 후 판정은 두 데이터 모두 AUC를 잃지만, 오탐은 02_korean에서 늘고 02b에서는 협박체만 줄어든다",
             f"02_korean = 문서 1,000건 속 간접 인젝션 (글자 수 중앙값 {c02.min():.0f}–{c02.max():.0f}), 02b = 직접 프롬프트 221항목 "
             f"({c2b.min():.0f}–{c2b.max():.0f}). 데이터 종류·길이·기준 TPR이 달라 크기는 비교하지 않음.\n"
             "막대 = 각 실험의 짝 부트스트랩 95% 구간, 채운 점 = 구간이 0 밖 (02b 합침 행은 McNemar 없이 구간만)")
    out.append(PS.save(fig, "f13_context_02_korean", out_dir=FIG))
    return out


# ------------------------------------------------------------------ console digest (README numbers come from here + tables)
def digest(E3, E4, OM, PW, VD, vs_polite, vs_en, qq, mt_vs_ko, mt_vs_en, IC, NEVER, TF, spear, tb_overlap, TH, TQ, SENS,
           TSPLIT, E5, CLAIM, CTX, COST, lost_counts, seg_stats, checks):
    pd.set_option("display.width", 260)
    pd.set_option("display.max_columns", 50)
    pd.set_option("display.max_colwidth", 60)
    f = lambda v: "" if v is None or v != v else f"{100 * v:.1f}"  # noqa: E731
    print("checks", json.dumps(clean(checks), ensure_ascii=False)[:1500])
    print("\n== E3 by register")
    for _, r in E3.iterrows():
        print(f"  {r.question} {r.register:<17} TPR {f(r.TPR)} [{f(r.TPR_lo)},{f(r.TPR_hi)}] FPR {f(r.FPR)} [{f(r.FPR_lo)},{f(r.FPR_hi)}]"
              f" AUC {r.AUC:.3f} [{r.AUC_lo:.3f},{r.AUC_hi:.3f}] tp {r.tp} fp {r.fp} p_ben {r.mean_p_ben:.3f} p_inj {r.mean_p_inj:.3f}"
              f" maxben {r.max_p_benign:.3f} flips {r.flips}")
    print("\n== omnibus\n", OM.round(5).to_string())
    print("\n== pairwise Holm-significant\n", PW[PW.holm_significant][["question", "metric", "register_a", "register_b", "rate_a",
                                                                          "rate_b", "only_a", "only_b", "mcnemar_p_holm"]].to_string())
    print("\n== genz/angry pairwise (not threat) min Holm p:",
          PW[(PW.register_a != "threat") & (PW.register_b != "threat")].groupby(["question", "metric"]).mcnemar_p_holm.min().to_dict())
    print("\n== variance decomposition\n", VD.round(4).to_string())
    for name, T in (("vs polite", vs_polite), ("vs english", vs_en), ("QL-Q2", qq), ("MT vs KO", mt_vs_ko), ("MT vs EN", mt_vs_en)):
        print(f"\n== {name}")
        for _, r in T.iterrows():
            mc = ""
            if r.get("mcnemar_fp_p") is not None and r.get("mcnemar_fp_p") == r.get("mcnemar_fp_p"):
                mc = (f" det {r.inj_only_a}/{r.inj_only_b} p={r.mcnemar_detect_p:.2g} holm={float(r.mcnemar_detect_p_holm):.2g}"
                      f" fp {r.fp_only_a}/{r.fp_only_b} p={r.mcnemar_fp_p:.2g} holm={float(r.mcnemar_fp_p_holm):.2g}")
            print(f"  {r.question} {r.register:<17} dTPR {f(r.d_TPR)} [{f(r.d_TPR_lo)},{f(r.d_TPR_hi)}] {r.d_TPR_verdict:<20}"
                  f" dFPR {f(r.d_FPR)} [{f(r.d_FPR_lo)},{f(r.d_FPR_hi)}] {r.d_FPR_verdict:<20} dAUC {r.d_AUC:+.3f} "
                  f"[{r.d_AUC_lo:+.3f},{r.d_AUC_hi:+.3f}] {r.d_AUC_verdict} dpben {r.d_mean_p_ben:+.3f} dpinj {r.d_mean_p_inj:+.3f}{mc}")
    print("\n== item consistency\n", IC.pivot_table(index=["question", "label"], columns="n_korean_registers_flagged",
                                                     values="n_items").to_string())
    print("never detected in any of 8:", NEVER.groupby("question").size().to_dict())
    print(NEVER[["question", "item_id", "source", "text_english"]].to_string())
    print("\n== threat benign features\n", TF[["question", "feature", "n_with", "FPR_with", "n_without", "FPR_without",
                                                "mean_p_with", "mean_p_without", "fisher_p", "fisher_p_holm"]].round(4).to_string())
    print("spearman", spear, "overlap", tb_overlap)
    print("\n== thresholds\n", TH[TH.register.isin(["threat", "polite", "english", "korean_no_threat", "korean_pooled"])]
          .round(4).to_string())
    print("\n== E4 by register")
    for _, r in E4.iterrows():
        print(f"  {r.question} {r.register:<17} TPR {f(r.TPR)} [{f(r.TPR_lo)},{f(r.TPR_hi)}] FPR {f(r.FPR)} [{f(r.FPR_lo)},{f(r.FPR_hi)}]"
              f" AUC {r.AUC:.3f} flips {r.flips}")
    print("lost detections\n", lost_counts.to_string())
    print("\n== translation checks\n", TQ.to_string(), "\n", seg_stats)
    print("\n== sensitivity\n", SENS.round(4).to_string())
    print("\n== threat word kept\n", TSPLIT.round(4).to_string())
    print("\n== E5\n", E5.round(5).to_string())
    print("\n== claim\n", CLAIM.round(4).to_string())
    print("\n== context\n", CTX[["question", "comparison", "dataset", "chars_median_a", "a_TPR", "b_TPR", "d_TPR", "d_TPR_lo",
                                  "d_TPR_hi", "d_FPR", "d_FPR_lo", "d_FPR_hi", "d_AUC", "d_AUC_lo", "d_AUC_hi"]].round(4).to_string())
    print("\n== cost\n", COST.round(4).to_string())


if __name__ == "__main__":
    main()
