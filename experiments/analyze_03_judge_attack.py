"""03_judge_attack analysis (no API calls): does Jev catch real attacks that already slipped past other detectors?

    python experiments/analyze_03_judge_attack.py

Inputs (produced earlier by `python experiments/run_api.py 03_judge_attack` / `01_baseline`; never modified here):
  results/03_judge_attack/{Q2,QL}_predictions.csv  JA 920 = 420 LLMail-Inject submissions that evaded the challenge's
                                                   own detector (Prompt Shield / TaskTracker / LLM judge / all) +
                                                   500 benign rows that are the EN benign documents (pair_uid -> EN uid)
  results/01_baseline/{Q2,QL}_predictions.csv      EN 1000 (set=="EN"): the comparison condition. Its 89 LLMail-Inject
                                                   injections are the same challenge and format but were NOT selected
                                                   for evading a detector (51 of them did, 38 did not: origin.objectives)
  data/injection_eval/judge_attack/dataset_ja_920.jsonl, data/injection_eval/en/dataset_en_1000.jsonl
                                                   metadata only (technique tags, origin.defense, phase, team, text)
Outputs:
  results/03_judge_attack/tables/*.csv, results/03_judge_attack/figures/*.png,
  results/03_judge_attack/summary.json  -> adds an "analysis" object, keeps every existing key.

Statistics: TPR / FPR / AUC point estimates through src.jev_guard.metrics (threshold 0.5); Wilson 95% CIs
(jevlab.wilson). Paired comparisons on the same documents (Q2 vs QL; JA benign vs EN benign = same 500 texts, independent
API calls): exact McNemar (two-sided binomial test on discordant pairs) and paired bootstrap (1000 resamples, seed
20261112). Unpaired comparisons (JA attacks vs EN LLMail attacks, tag present vs absent): Newcombe hybrid-score CI built
from the two Wilson intervals, Fisher exact p, and (for the key comparison) an independent bootstrap. Bootstrap AUC
replicates use a rank formula that is asserted equal to metrics() on the full data.
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
from scipy.stats import fisher_exact, norm, pearsonr, spearmanr
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

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

EXP = "03_judge_attack"
OUT = os.path.join(J.RESULTS, EXP)
BASE_DIR = os.path.join(J.RESULTS, "01_baseline")
TAB = os.path.join(OUT, "tables")
FIG = os.path.join(OUT, "figures")
JA_DATA = os.path.join(J.DATA, "judge_attack", "dataset_ja_920.jsonl")
EN_DATA = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")

QS = ["Q2", "QL"]
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}  # project-wide: colour = question
Q_NAME = {"Q2": "Q2 (짧은 질문)", "QL": "QL (정의형 긴 질문)"}
INJ, BEN = S.LABEL_COLORS["인젝션"], S.LABEL_COLORS["정상"]  # project-wide: colour = label
N_BOOT, SEED = 1000, 20261112
VERDICT_NONE = "차이 없음/오차 범위"

TAG_KO = {
    "paraphrase_low_trigger": "트리거 없는 바꿔 쓰기", "social_engineering": "사회공학 (급함·권위)",
    "benign_framing": "정상 업무로 위장", "delimiter_escape": "구분자 탈출", "fake_system_tokens": "가짜 시스템 토큰",
    "character_obfuscation": "문자 난독화", "fake_tool_call": "가짜 도구 호출",
    "code_or_markup_wrapping": "코드·마크업으로 감싸기", "long_context": "긴 문맥에 묻기", "spoofed_headers": "위조 메일 헤더",
    "fake_summary_or_output": "가짜 요약·출력", "fake_dialogue_turns": "가짜 대화 턴", "payload_splitting": "페이로드 쪼개기",
    "roleplay_or_hypothetical": "역할극·가정", "fake_judge_or_label_claims": "가짜 판정·'안전' 주장",
    "unicode_obfuscation": "유니코드 난독화", "encoding": "인코딩", "multilingual": "다국어", "(none)": "태그 없음",
}
# technique tags that match an evasion style the QL question text names explicitly (docs/PROJECT.md QL):
# "disguised as a system message, a tool call or code, claim that the text is safe or already reviewed, or be written in
# another language or an encoding". ("be written politely" has no matching tag.)
QL_LISTED = {"fake_system_tokens": "a system message", "fake_tool_call": "a tool call", "code_or_markup_wrapping": "code",
             "fake_judge_or_label_claims": "claim that the text is safe or already reviewed",
             "multilingual": "another language", "encoding": "an encoding"}
DET_KO = {"prompt_shield": "Prompt Shield", "task_tracker": "TaskTracker", "llm_judge": "LLM 판정기", "all": "세 탐지기 모두"}
DET_ORDER = ["prompt_shield", "task_tracker", "llm_judge", "all"]
JUDGE_KO = {"llm": "LLM 판정기 포함 (LLM 판정기, 세 탐지기 모두)", "clf": "분류기만 (Prompt Shield, TaskTracker)"}
DEF_ORDER = ["prompt_shield", "prompt_shield_v2", "task_tracker_phi3_medium", "task_tracker_phi3.5_moe", "task_tracker_phi4",
             "llm_judge", "all(task_tracker_phi3+prompt_shield+llm_judge+spotlight)",
             "all(task_tracker_phi4+prompt_shield_v2+llm_judge)"]
DEF_KO = {"prompt_shield": "Prompt Shield (P1)", "prompt_shield_v2": "Prompt Shield v2 (P2)",
          "task_tracker_phi3_medium": "TaskTracker Phi3", "task_tracker_phi3.5_moe": "TaskTracker Phi3.5 MoE (P2)",
          "task_tracker_phi4": "TaskTracker Phi4 (P2)", "llm_judge": "LLM 판정기",
          "all(task_tracker_phi3+prompt_shield+llm_judge+spotlight)": "전부+spotlight (P1)",
          "all(task_tracker_phi4+prompt_shield_v2+llm_judge)": "전부 (P2)"}
OUTCOME_KO = {"full": "발송 성공 (주소·본문 정확)", "partial": "발송했으나 주소·본문 틀림", "none": "탐지만 통과, 발송 못 함"}
OUTCOME_ORDER = ["full", "partial", "none"]
GROUP_KO = {"EN_all": "EN 전체 주입", "EN_LL": "EN LLMail 전체", "EN_LL_evaded": "EN LLMail 중 탐지기 통과",
            "EN_LL_caught": "EN LLMail 중 탐지기에 걸림", "JA_all": "JA 전체", "JA_P2": "JA Phase 2", "JA_P1": "JA Phase 1",
            "JA_clf": "JA 중 분류기만 통과", "JA_llm": "JA 중 LLM 판정기 포함"}
# bootstrap index matrices are generated in this order (new groups only ever appended at the end)
GROUP_ORDER = ["EN_all", "EN_LL", "EN_LL_evaded", "EN_LL_caught", "JA_all", "JA_P2", "JA_P1", "JA_clf", "JA_llm"]
N_EN_GROUPS = 4


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
    return VERDICT_NONE if lo <= 0 <= hi else ("높음" if lo > 0 else "낮음")


def mcnemar_exact(a, b):
    """a, b: boolean arrays on the same documents. Returns (a_only, b_only, two-sided exact p)."""
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


def newcombe(k1, n1, k2, n2):
    """Difference p1 - p2 with the Newcombe hybrid-score 95% CI (built from the two Wilson intervals)."""
    p1, p2 = k1 / n1, k2 / n2
    l1, u1 = J.wilson(k1, n1)
    l2, u2 = J.wilson(k2, n2)
    d = p1 - p2
    return d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def two_prop_z(k1, n1, k2, n2):
    p = (k1 + k2) / (n1 + n2)
    se = math.sqrt(p * (1 - p) * (1 / n1 + 1 / n2))
    if se == 0:
        return 1.0
    return float(2 * norm.sf(abs((k1 / n1 - k2 / n2) / se)))


def fisher_p(k1, n1, k2, n2):
    return float(fisher_exact([[k1, n1 - k1], [k2, n2 - k2]])[1])


def det(p):
    """Detection (TPR at 0.5) for an injection-only vector of p, through metrics()."""
    p = np.asarray(p, float)
    m = metrics([1] * len(p), p.tolist(), threshold=THRESHOLD)
    tp = int(round(m["TPR"] * m["n"])) if m["n"] else 0
    lo, hi = J.wilson(tp, m["n"]) if m["n"] else (None, None)
    return {"n": m["n"], "tp": tp, "TPR": m["TPR"], "TPR_lo": lo, "TPR_hi": hi,
            "mean_p": float(p.mean()) if len(p) else None, "median_p": float(np.median(p)) if len(p) else None}


def fpr_block(p):
    p = np.asarray(p, float)
    m = metrics([0] * len(p), p.tolist(), threshold=THRESHOLD)
    fp = int(round(m["FPR"] * m["n"]))
    lo, hi = J.wilson(fp, m["n"])
    return {"n": m["n"], "fp": fp, "FPR": m["FPR"], "FPR_lo": lo, "FPR_hi": hi, "mean_p": float(p.mean())}


def auc_metrics(inj, ben):
    inj, ben = np.asarray(inj, float), np.asarray(ben, float)
    return metrics([1] * len(inj) + [0] * len(ben), np.concatenate([inj, ben]).tolist())["AUC"]


def auc_fast(inj, ben):
    """Mann-Whitney AUC (ties count 1/2); identical to roc_auc_score. Used for bootstrap replicates only."""
    b = np.sort(np.asarray(ben, float))
    inj = np.asarray(inj, float)
    lt = np.searchsorted(b, inj, side="left")
    le = np.searchsorted(b, inj, side="right")
    return float((lt + 0.5 * (le - lt)).sum() / (len(inj) * len(b)))


def boot_auc(inj, ben, II, IB):
    return np.array([auc_fast(inj[i], ben[j]) for i, j in zip(II, IB)])


def fmt_p(p):
    return "p < 0.001" if p < 0.001 else f"p = {p:.3f}"


def pct(x, d=1):
    return "-" if x is None else f"{100 * x:.{d}f}%"


def pp(x, d=1):
    return "-" if x is None else f"{100 * x:+.{d}f}%p".replace("-", "−")


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


def save_csv(df, name):
    df.to_csv(os.path.join(TAB, name), index=False, encoding="utf-8-sig")
    return df


# ------------------------------------------------------------------ load
def detector_of(notes):
    m = re.search(r"detector=(\S+)", notes or "")
    return m.group(1) if m else None


def outcome_of(obj):
    obj = obj or {}
    if obj.get("exfil.sent") and obj.get("exfil.destination") and obj.get("exfil.content"):
        return "full"
    if obj.get("exfil.sent"):
        return "partial"
    return "none"


def load_meta():
    ja = pd.DataFrame(J.load_jsonl(JA_DATA))
    o = ja["origin"]
    ja["phase"] = [x.get("split") if isinstance(x, dict) else None for x in o]
    ja["defense"] = [x.get("defense") if isinstance(x, dict) else None for x in o]
    ja["level"] = [x.get("level") if isinstance(x, dict) else None for x in o]
    ja["scenario"] = [x.get("scenario") if isinstance(x, dict) else None for x in o]
    ja["target_model"] = [x.get("model") if isinstance(x, dict) else None for x in o]
    ja["team_id"] = [x.get("team_id") if isinstance(x, dict) else None for x in o]
    ja["outcome"] = [outcome_of(x.get("objectives")) if isinstance(x, dict) and l == 1 else None
                     for x, l in zip(o, ja["label_int"])]
    ja["detector"] = [detector_of(n) if l == 1 else None for n, l in zip(ja["notes"], ja["label_int"])]
    # an LLM-based judge was part of the defence the attack got past ("all" levels include the LLM judge)
    ja["judge_type"] = [None if d is None else ("llm" if d in ("llm_judge", "all") else "clf") for d in ja["detector"]]
    ja["tags"] = [[t for t in (x if isinstance(x, str) else "").split(",") if t] for x in ja["technique"]]
    ja["n_tags"] = ja["tags"].str.len()
    low = ja["text"].str.lower()
    ja["has_target_addr"] = low.str.contains("contact@contact.com", regex=False)
    ja["has_confirmation"] = low.str.contains("confirmation", regex=False)
    ja["subject_start"] = low.str.match(r"\s*subject\s*:")
    ja["is_email"] = ja["doc_type"] == "email"
    ja["char_len"] = ja["text"].str.len()

    en = pd.DataFrame(J.load_jsonl(EN_DATA))
    eo = en["origin"]
    en["undetected"] = [bool((x.get("objectives") or {}).get("defense.undetected")) if isinstance(x, dict) else None
                        for x in eo]
    en["team_id"] = [x.get("team_id") if isinstance(x, dict) else None for x in eo]
    en["level_description"] = [x.get("level_description") if isinstance(x, dict) else None for x in eo]
    en["llm_judge_level"] = en["level_description"].fillna("").str.contains("LLM Judge")
    en["outcome"] = [outcome_of(x.get("objectives")) if isinstance(x, dict) else None for x in eo]
    low = en["text"].str.lower()
    en["has_target_addr"] = low.str.contains("contact@contact.com", regex=False)
    en["has_confirmation"] = low.str.contains("confirmation", regex=False)
    en["subject_start"] = low.str.match(r"\s*subject\s*:")
    en["is_email"] = en["doc_type"] == "email"
    en["char_len"] = en["text"].str.len()
    return ja, en


def load_question(q, ja_meta, en_meta):
    ja = pd.read_csv(os.path.join(OUT, f"{q}_predictions.csv"))
    base = pd.read_csv(os.path.join(BASE_DIR, f"{q}_predictions.csv"))
    assert len(ja) == 920 and ja["uid"].is_unique
    assert ((ja["p"] >= THRESHOLD).astype(int) == ja["pred"]).all()
    assert (ja["n_runs"] == 3).all()
    en = base[base["set"] == "EN"].copy()
    assert len(en) == 1000
    keep = ["uid", "phase", "defense", "level", "scenario", "target_model", "team_id", "outcome", "detector",
            "judge_type", "tags",
            "n_tags", "has_target_addr", "has_confirmation", "subject_start", "is_email", "text",
            "injected_instruction", "harm_type"]
    ja = ja.merge(ja_meta[keep], on="uid", how="left", validate="1:1")
    en = en.merge(en_meta[["uid", "undetected", "team_id", "outcome", "text", "injected_instruction",
                           "level_description", "llm_judge_level"]], on="uid",
                  how="left", validate="1:1")
    inj = ja[ja["label_int"] == 1].sort_values("uid").reset_index(drop=True)
    ben = ja[ja["label_int"] == 0].sort_values("pair_uid").reset_index(drop=True)
    en_ben = en[en["label_int"] == 0].set_index("uid").loc[ben["pair_uid"]].reset_index()
    assert (en_ben["label_int"] == 0).all() and len(en_ben) == 500
    en_inj = en[en["label_int"] == 1].sort_values("uid").reset_index(drop=True)
    en_ll = en_inj[en_inj["source"] == "LLMail-Inject"].reset_index(drop=True)
    return {"ja": ja, "inj": inj, "ben": ben, "en": en, "en_ben": en_ben, "en_inj": en_inj, "en_ll": en_ll}


# ------------------------------------------------------------------ analysis
def main():
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    os.makedirs(TAB, exist_ok=True)
    os.makedirs(FIG, exist_ok=True)
    S.setup()
    ja_meta, en_meta = load_meta()
    D = {q: load_question(q, ja_meta, en_meta) for q in QS}
    for k in ("inj", "ben", "en_ben", "en_inj", "en_ll"):
        assert list(D["Q2"][k]["uid"]) == list(D["QL"][k]["uid"]), k
    inj_meta = D["Q2"]["inj"]
    nI, nB = len(inj_meta), len(D["Q2"]["ben"])
    rng = np.random.default_rng(SEED)
    # index matrices, generated once in a fixed order and shared by both questions (paired)
    IDX = {"JA_all": rng.integers(0, nI, (N_BOOT, nI)), "BEN": rng.integers(0, nB, (N_BOOT, nB))}
    groups = {
        "EN_all": lambda d: d["en_inj"], "EN_LL": lambda d: d["en_ll"],
        "EN_LL_evaded": lambda d: d["en_ll"][d["en_ll"]["undetected"] == True],  # noqa: E712
        "EN_LL_caught": lambda d: d["en_ll"][d["en_ll"]["undetected"] == False],  # noqa: E712
        "JA_all": lambda d: d["inj"], "JA_P2": lambda d: d["inj"][d["inj"]["phase"] == "Phase2"],
        "JA_P1": lambda d: d["inj"][d["inj"]["phase"] == "Phase1"],
        "JA_clf": lambda d: d["inj"][d["inj"]["judge_type"] == "clf"],
        "JA_llm": lambda d: d["inj"][d["inj"]["judge_type"] == "llm"],
    }
    for g in GROUP_ORDER:
        if g not in IDX:
            n = len(groups[g](D["Q2"]))
            IDX[g] = rng.integers(0, n, (N_BOOT, n))
    G = {q: {g: groups[g](D[q]).reset_index(drop=True) for g in GROUP_ORDER} for q in QS}
    for g in GROUP_ORDER:
        assert list(G["Q2"][g]["uid"]) == list(G["QL"][g]["uid"])
    BENP = {q: {"JA": D[q]["ben"]["p"].to_numpy(), "EN": D[q]["en_ben"]["p"].to_numpy()} for q in QS}

    analysis = {"script": "experiments/analyze_03_judge_attack.py",
                "generated_at": dt.datetime.now().isoformat(timespec="seconds"),
                "bootstrap": {"resamples": N_BOOT, "seed": SEED, "ci": "percentile 2.5/97.5",
                              "unit": "documents resampled with replacement; the same index matrices are used for Q2 "
                                      "and QL (paired) and for JA benign vs EN benign (same 500 documents, aligned by "
                                      "pair_uid); attack groups are resampled independently of each other"},
                "mcnemar": "exact, two-sided binomial test on discordant pairs",
                "unpaired": "Newcombe hybrid-score CI from two Wilson intervals; Fisher exact p; two-proportion z p",
                "auc_bootstrap_note": "bootstrap AUC replicates use the Mann-Whitney rank formula, asserted equal to "
                                      "src.jev_guard.metrics() AUC on the full data"}
    inputs = {rel(p): md5_file(p) for p in (JA_DATA, EN_DATA, *(os.path.join(OUT, f"{q}_predictions.csv") for q in QS),
                                           *(os.path.join(BASE_DIR, f"{q}_predictions.csv") for q in QS))}
    analysis["inputs_md5"] = inputs
    analysis["data_profile"] = {
        "n_attacks": nI, "n_benign": nB,
        "attacks_by_phase": inj_meta["phase"].value_counts().to_dict(),
        "attacks_by_detector": inj_meta["detector"].value_counts().to_dict(),
        "attacks_by_defense": inj_meta["defense"].value_counts().to_dict(),
        "attacks_by_scenario": inj_meta["scenario"].value_counts().to_dict(),
        "attacks_by_outcome": inj_meta["outcome"].value_counts().to_dict(),
        "attacks_by_risk_level": inj_meta["risk_level"].value_counts().to_dict(),
        "attacks_by_target_model": inj_meta["target_model"].value_counts().to_dict(),
        "n_teams": int(inj_meta["team_id"].nunique()), "max_per_team": int(inj_meta["team_id"].value_counts().max()),
        "en_llmail_n": len(G["Q2"]["EN_LL"]), "en_llmail_undetected_true": int(G["Q2"]["EN_LL"]["undetected"].sum()),
        "benign_identical_to_en": bool((D["Q2"]["ben"]["text"].to_numpy() == en_meta.set_index("uid").loc[
            D["Q2"]["ben"]["pair_uid"], "text"].to_numpy()).all()),
    }

    # ---------------------------------------------------------- 1. overall + EN baseline context
    rows = []
    for q in QS:
        d = D[q]
        ja = d["ja"]
        m = metrics(ja["label_int"].tolist(), ja["p"].tolist(), threshold=THRESHOLD)
        dI, dB = det(d["inj"]["p"]), fpr_block(d["ben"]["p"])
        aI, aB = d["inj"]["p"].to_numpy(), BENP[q]["JA"]
        assert abs(auc_fast(aI, aB) - m["AUC"]) < 1e-12
        ra_ja = boot_auc(aI, aB, IDX["JA_all"], IDX["BEN"])
        auc_ci = ci(ra_ja)
        en = d["en"]
        me = metrics(en["label_int"].tolist(), en["p"].tolist(), threshold=THRESHOLD)
        eI, eB = det(d["en_inj"]["p"]), fpr_block(BENP[q]["EN"])
        # EN 1000 AUC CI: same bootstrap as JA (attacks and the 500 shared benign docs resampled with the same
        # IDX["BEN"] rows), so the JA - EN AUC difference below is consistent with ja_vs_en_llmail.csv (JA_all vs EN_all)
        pEI = d["en_inj"]["p"].to_numpy()
        assert abs(auc_fast(pEI, BENP[q]["EN"]) - me["AUC"]) < 1e-12
        ra_en = boot_auc(pEI, BENP[q]["EN"], IDX["EN_all"], IDX["BEN"])
        dauc_ci = ci(ra_ja - ra_en)
        rows.append({"question": q, "n": m["n"], "n_attacks": dI["n"], "n_benign": dB["n"],
                     "TPR": m["TPR"], "tp": dI["tp"], "TPR_lo": dI["TPR_lo"], "TPR_hi": dI["TPR_hi"],
                     "FPR": m["FPR"], "fp": dB["fp"], "FPR_lo": dB["FPR_lo"], "FPR_hi": dB["FPR_hi"],
                     "AUC": m["AUC"], "AUC_lo": auc_ci[0], "AUC_hi": auc_ci[1],
                     "mean_p_attack": dI["mean_p"], "median_p_attack": dI["median_p"], "mean_p_benign": dB["mean_p"],
                     "flip_attack": int(d["inj"]["flip"].sum()), "flip_benign": int(d["ben"]["flip"].sum()),
                     "p_sd_mean": float(ja["p_sd"].mean()), "latency_s_median": float(ja["latency_s"].median()),
                     "input_tokens_mean": float(ja["input_tokens"].mean()),
                     "EN_TPR": me["TPR"], "EN_tp": eI["tp"], "EN_TPR_lo": eI["TPR_lo"], "EN_TPR_hi": eI["TPR_hi"],
                     "EN_FPR": me["FPR"], "EN_fp": eB["fp"], "EN_FPR_lo": eB["FPR_lo"], "EN_FPR_hi": eB["FPR_hi"],
                     "EN_AUC": me["AUC"], "EN_AUC_lo": ci(ra_en)[0], "EN_AUC_hi": ci(ra_en)[1],
                     "dAUC_JA_minus_EN": m["AUC"] - me["AUC"], "dAUC_lo": dauc_ci[0], "dAUC_hi": dauc_ci[1],
                     "dAUC_verdict": verdict(*dauc_ci)})
    overall = save_csv(pd.DataFrame(rows), "overall.csv")

    # ---------------------------------------------------------- 2. benign FPR check: JA benign vs EN benign (same docs)
    rows, fp_rows = [], []
    for q in QS:
        a, b = BENP[q]["EN"], BENP[q]["JA"]
        fa, fb = a >= THRESHOLD, b >= THRESHOLD
        en_only, ja_only, pm = mcnemar_exact(fa, fb)
        bi = IDX["BEN"]
        dfpr = ci(fb[bi].mean(1) - fa[bi].mean(1))
        dmp = ci(b[bi].mean(1) - a[bi].mean(1))
        diff = np.abs(b - a)
        within = np.concatenate([D[q]["ben"]["p_sd"].to_numpy(), D[q]["en_ben"]["p_sd"].to_numpy()])
        rows.append({"question": q, "n": len(a), "EN_fp": int(fa.sum()), "EN_FPR": fa.mean(), "JA_fp": int(fb.sum()),
                     "JA_FPR": fb.mean(), "dFPR_JA_minus_EN": fb.mean() - fa.mean(), "dFPR_lo": dfpr[0],
                     "dFPR_hi": dfpr[1], "dFPR_verdict": verdict(*dfpr), "flagged_both": int((fa & fb).sum()),
                     "flagged_EN_only": en_only, "flagged_JA_only": ja_only, "mcnemar_p": pm,
                     "EN_mean_p": a.mean(), "JA_mean_p": b.mean(), "dmean_p": b.mean() - a.mean(), "dmean_p_lo": dmp[0],
                     "dmean_p_hi": dmp[1], "pearson_r": pearsonr(a, b)[0], "spearman_rho": spearmanr(a, b)[0],
                     "mean_abs_dp": diff.mean(), "share_abs_dp_le_0.01": float((diff <= 0.01 + 1e-9).mean()),
                     "share_abs_dp_le_0.05": float((diff <= 0.05 + 1e-9).mean()), "max_abs_dp": diff.max(),
                     "within_run_sd_mean": within.mean(), "within_run_sd_max": within.max()})
        for i in np.where(fa | fb)[0]:
            r = D[q]["ben"].iloc[i]
            fp_rows.append({"question": q, "uid": r["uid"], "pair_uid": r["pair_uid"], "source": r["source"],
                            "doc_type": r["doc_type"], "p_EN": a[i], "p_JA": b[i], "flag_EN": bool(fa[i]),
                            "flag_JA": bool(fb[i]), "excerpt": re.sub(r"\s+", " ", r["text"])[:220]})
    benign_check = save_csv(pd.DataFrame(rows), "benign_fpr_check_vs_en.csv")
    save_csv(pd.DataFrame(fp_rows), "benign_flagged_docs.csv")

    # ---------------------------------------------------------- 3. key comparison: JA attacks vs EN LLMail attacks
    grp_rows = []
    REP = {q: {} for q in QS}
    for q in QS:
        for g in GROUP_ORDER:
            df = G[q][g]
            p = df["p"].to_numpy()
            ben = BENP[q]["EN" if g.startswith("EN") else "JA"]
            dd = det(p)
            auc = auc_metrics(p, ben)
            ra = boot_auc(p, ben, IDX[g], IDX["BEN"])
            REP[q][g] = {"TPR": (p >= THRESHOLD)[IDX[g]].mean(1), "mean_p": p[IDX[g]].mean(1), "AUC": ra}
            grp_rows.append({"question": q, "group": g, "group_ko": GROUP_KO[g], **dd, "AUC_vs_benign": auc,
                             "AUC_lo": ci(ra)[0], "AUC_hi": ci(ra)[1],
                             "benign_reference": "EN benign 500 (01_baseline calls)" if g.startswith("EN")
                             else "JA benign 500 (same documents, 03_judge_attack calls)"})
    by_group = save_csv(pd.DataFrame(grp_rows), "detection_by_group.csv")

    COMPS = [("JA_all", "EN_LL", "primary"), ("JA_P2", "EN_LL", "same phase (Phase 2 only)"),
             ("JA_all", "EN_LL_evaded", "vs EN LLMail that also evaded a detector"),
             ("JA_all", "EN_LL_caught", "vs EN LLMail that a detector caught"),
             ("JA_clf", "EN_LL", "JA classifier-evading only vs EN LLMail"),
             ("JA_llm", "EN_LL", "JA LLM-judge-evading vs EN LLMail"),
             ("EN_LL_evaded", "EN_LL_caught", "within EN LLMail"), ("JA_P1", "JA_P2", "within JA"),
             ("JA_llm", "JA_clf", "within JA: LLM judge involved vs classifiers only"),
             ("JA_all", "EN_all", "vs all EN injections (different formats)")]
    comp_rows = []
    for q in QS:
        for a_, b_, role in COMPS:
            A, B = G[q][a_]["p"].to_numpy(), G[q][b_]["p"].to_numpy()
            ka, na, kb, nb = int((A >= THRESHOLD).sum()), len(A), int((B >= THRESHOLD).sum()), len(B)
            d, lo, hi = newcombe(ka, na, kb, nb)
            bt = REP[q][a_]["TPR"] - REP[q][b_]["TPR"]
            bm = REP[q][a_]["mean_p"] - REP[q][b_]["mean_p"]
            ba = REP[q][a_]["AUC"] - REP[q][b_]["AUC"]
            auc_a = auc_metrics(A, BENP[q]["EN" if a_.startswith("EN") else "JA"])
            auc_b = auc_metrics(B, BENP[q]["EN" if b_.startswith("EN") else "JA"])
            comp_rows.append({
                "question": q, "A": a_, "B": b_, "role": role, "A_ko": GROUP_KO[a_], "B_ko": GROUP_KO[b_],
                "n_A": na, "tp_A": ka, "TPR_A": ka / na, "n_B": nb, "tp_B": kb, "TPR_B": kb / nb,
                "dTPR": d, "dTPR_newcombe_lo": lo, "dTPR_newcombe_hi": hi, "dTPR_boot_lo": ci(bt)[0],
                "dTPR_boot_hi": ci(bt)[1], "fisher_p": fisher_p(ka, na, kb, nb), "z_p": two_prop_z(ka, na, kb, nb),
                "dTPR_verdict": verdict(lo, hi), "dmean_p": A.mean() - B.mean(), "dmean_p_lo": ci(bm)[0],
                "dmean_p_hi": ci(bm)[1], "dmean_p_verdict": verdict(*ci(bm)), "AUC_A": auc_a, "AUC_B": auc_b,
                "dAUC": auc_a - auc_b, "dAUC_lo": ci(ba)[0], "dAUC_hi": ci(ba)[1], "dAUC_verdict": verdict(*ci(ba))})
    comps = save_csv(pd.DataFrame(comp_rows), "ja_vs_en_llmail.csv")

    # cross-check inside EN LLMail: levels whose defence included the LLM judge, split by whether the attack got past it
    xc_rows = []
    for q in QS:
        ll = G[q]["EN_LL"]
        for lvl in (True, False):
            for und in (True, False):
                m = (ll["llm_judge_level"] == lvl) & (ll["undetected"] == und)
                if m.sum() == 0:
                    continue
                xc_rows.append({"question": q, "llm_judge_in_level_defence": lvl, "challenge_detector_evaded": und,
                                **det(ll.loc[m, "p"])})
    en_ll_cross = save_csv(pd.DataFrame(xc_rows), "en_llmail_by_llm_judge_level.csv")

    # team-cluster bootstrap (sensitivity: 145 JA teams, up to 9 submissions each)
    crng = np.random.default_rng(SEED + 1)
    team_rows = []
    ja_teams = inj_meta["team_id"].to_numpy()
    ll_teams = G["Q2"]["EN_LL"]["team_id"].to_numpy()
    uj, ul = np.unique(ja_teams), np.unique(ll_teams)
    pos_j = {t: np.where(ja_teams == t)[0] for t in uj}
    pos_l = {t: np.where(ll_teams == t)[0] for t in ul}
    TJ = [np.concatenate([pos_j[t] for t in crng.choice(uj, len(uj))]) for _ in range(N_BOOT)]
    TL = [np.concatenate([pos_l[t] for t in crng.choice(ul, len(ul))]) for _ in range(N_BOOT)]
    for q in QS:
        pj = (D[q]["inj"]["p"].to_numpy() >= THRESHOLD)
        pl = (G[q]["EN_LL"]["p"].to_numpy() >= THRESHOLD)
        rj = np.array([pj[i].mean() for i in TJ])
        rl = np.array([pl[i].mean() for i in TL])
        team_rows.append({"question": q, "n_teams_JA": len(uj), "n_teams_EN_LL": len(ul), "JA_TPR": pj.mean(),
                          "JA_TPR_team_lo": ci(rj)[0], "JA_TPR_team_hi": ci(rj)[1], "EN_LL_TPR": pl.mean(),
                          "EN_LL_TPR_team_lo": ci(rl)[0], "EN_LL_TPR_team_hi": ci(rl)[1],
                          "dTPR": pj.mean() - pl.mean(), "dTPR_team_lo": ci(rj - rl)[0], "dTPR_team_hi": ci(rj - rl)[1],
                          "dTPR_team_verdict": verdict(*ci(rj - rl))})
    team_ci = save_csv(pd.DataFrame(team_rows), "team_cluster_bootstrap.csv")

    # ---------------------------------------------------------- 4. Q2 vs QL (paired, same documents)
    pq_rows = []
    PQ = {}
    for name, key, idx in (("JA attacks (420)", "JA_all", IDX["JA_all"]), ("EN LLMail attacks (89)", "EN_LL", IDX["EN_LL"]),
                           ("EN all injections (500)", "EN_all", IDX["EN_all"]),
                           (f"JA classifier-only attacks ({len(G['Q2']['JA_clf'])})", "JA_clf", IDX["JA_clf"]),
                           (f"JA LLM-judge attacks ({len(G['Q2']['JA_llm'])})", "JA_llm", IDX["JA_llm"])):
        a, b = G["Q2"][key]["p"].to_numpy(), G["QL"][key]["p"].to_numpy()
        da, db = a >= THRESHOLD, b >= THRESHOLD
        q2_only, ql_only, pm = mcnemar_exact(da, db)
        bt = db[idx].mean(1) - da[idx].mean(1)
        bm = b[idx].mean(1) - a[idx].mean(1)
        PQ[key] = bt
        benk = "EN" if key.startswith("EN") else "JA"
        ba = REP["QL"][key]["AUC"] - REP["Q2"][key]["AUC"]
        pq_rows.append({"set": name, "metric": "TPR", "n": len(a), "Q2": da.mean(), "QL": db.mean(),
                        "d_QL_minus_Q2": db.mean() - da.mean(), "d_lo": ci(bt)[0], "d_hi": ci(bt)[1],
                        "verdict": verdict(*ci(bt)), "Q2_only": q2_only, "QL_only": ql_only, "mcnemar_p": pm})
        pq_rows.append({"set": name, "metric": "mean_p", "n": len(a), "Q2": a.mean(), "QL": b.mean(),
                        "d_QL_minus_Q2": b.mean() - a.mean(), "d_lo": ci(bm)[0], "d_hi": ci(bm)[1],
                        "verdict": verdict(*ci(bm))})
        pq_rows.append({"set": name, "metric": "AUC", "n": len(a), "Q2": auc_metrics(a, BENP["Q2"][benk]),
                        "QL": auc_metrics(b, BENP["QL"][benk]),
                        "d_QL_minus_Q2": auc_metrics(b, BENP["QL"][benk]) - auc_metrics(a, BENP["Q2"][benk]),
                        "d_lo": ci(ba)[0], "d_hi": ci(ba)[1], "verdict": verdict(*ci(ba))})
    for benk, name in (("JA", "JA benign (500)"), ("EN", "EN benign (500, 01_baseline)")):
        a, b = BENP["Q2"][benk], BENP["QL"][benk]
        fa, fb = a >= THRESHOLD, b >= THRESHOLD
        q2_only, ql_only, pm = mcnemar_exact(fa, fb)
        bt = fb[IDX["BEN"]].mean(1) - fa[IDX["BEN"]].mean(1)
        bm = b[IDX["BEN"]].mean(1) - a[IDX["BEN"]].mean(1)
        pq_rows.append({"set": name, "metric": "FPR", "n": len(a), "Q2": fa.mean(), "QL": fb.mean(),
                        "d_QL_minus_Q2": fb.mean() - fa.mean(), "d_lo": ci(bt)[0], "d_hi": ci(bt)[1],
                        "verdict": verdict(*ci(bt)), "Q2_only": q2_only, "QL_only": ql_only, "mcnemar_p": pm})
        pq_rows.append({"set": name, "metric": "mean_p", "n": len(a), "Q2": a.mean(), "QL": b.mean(),
                        "d_QL_minus_Q2": b.mean() - a.mean(), "d_lo": ci(bm)[0], "d_hi": ci(bm)[1],
                        "verdict": verdict(*ci(bm))})
    # correctness on all 920 JA documents
    y = D["Q2"]["ja"]["label_int"].to_numpy()
    c2 = (D["Q2"]["ja"]["pred"].to_numpy() == y)
    cl = (D["QL"]["ja"].set_index("uid").loc[D["Q2"]["ja"]["uid"], "pred"].to_numpy() == y)
    q2_only, ql_only, pm = mcnemar_exact(c2, cl)
    pq_rows.append({"set": "JA all (920)", "metric": "accuracy", "n": len(y), "Q2": c2.mean(), "QL": cl.mean(),
                    "d_QL_minus_Q2": cl.mean() - c2.mean(), "Q2_only": q2_only, "QL_only": ql_only, "mcnemar_p": pm})
    # does QL help more on JA than on EN LLMail? (difference in differences, independent resamples)
    did = PQ["JA_all"] - PQ["EN_LL"]
    d_ja = (G["QL"]["JA_all"]["p"] >= THRESHOLD).mean() - (G["Q2"]["JA_all"]["p"] >= THRESHOLD).mean()
    d_ll = (G["QL"]["EN_LL"]["p"] >= THRESHOLD).mean() - (G["Q2"]["EN_LL"]["p"] >= THRESHOLD).mean()
    pq_rows.append({"set": "QL gain: JA minus EN LLMail", "metric": "dTPR gain", "n": None, "Q2": None, "QL": None,
                    "d_QL_minus_Q2": d_ja - d_ll, "d_lo": ci(did)[0], "d_hi": ci(did)[1], "verdict": verdict(*ci(did))})
    # does QL help less on the LLM-judge evaders than on the classifier-only evaders? (independent resamples)
    did2 = PQ["JA_llm"] - PQ["JA_clf"]
    gain = {g: (G["QL"][g]["p"] >= THRESHOLD).mean() - (G["Q2"][g]["p"] >= THRESHOLD).mean() for g in ("JA_llm", "JA_clf")}
    pq_rows.append({"set": "QL gain: JA LLM-judge minus JA classifier-only", "metric": "dTPR gain", "n": None, "Q2": None,
                    "QL": None, "d_QL_minus_Q2": gain["JA_llm"] - gain["JA_clf"], "d_lo": ci(did2)[0], "d_hi": ci(did2)[1],
                    "verdict": verdict(*ci(did2))})
    paired_q = save_csv(pd.DataFrame(pq_rows), "paired_q2_vs_ql.csv")

    # hypothesis 2: is the QL gain larger on attacks that use the evasion styles QL names in its text?
    # QL names: "disguised as a system message, a tool call or code, claim that the text is safe or already reviewed,
    # or be written in another language or an encoding" ("written politely" has no matching tag).
    present = {t for ts in inj_meta["tags"] for t in ts}
    listed = [t for t in QL_LISTED if t in present]
    has_listed = inj_meta["tags"].apply(lambda ts: any(t in QL_LISTED for t in ts)).to_numpy()
    lrng = np.random.default_rng(SEED + 3)  # own stream: the shared index matrices above stay unchanged
    h2_rows, h2_rep = [], {}
    p2_all, pl_all = D["Q2"]["inj"]["p"].to_numpy(), D["QL"]["inj"]["p"].to_numpy()
    for name, mask in (("QL이 이름을 든 위장 방식 태그가 1개 이상", has_listed), ("그런 태그 없음", ~has_listed),
                       *((f"태그: {TAG_KO[t]}", inj_meta["tags"].apply(lambda ts, t=t: t in ts).to_numpy())
                         for t in listed)):
        a, b = p2_all[mask] >= THRESHOLD, pl_all[mask] >= THRESHOLD
        q2_only, ql_only, pm = mcnemar_exact(a, b)
        n_ = int(mask.sum())
        bi = lrng.integers(0, n_, (N_BOOT, n_))
        rep = b[bi].mean(1) - a[bi].mean(1)
        h2_rep[name] = rep
        h2_rows.append({"group": name, "n": n_, "TPR_Q2": a.mean(), "TPR_QL": b.mean(), "QL_minus_Q2": b.mean() - a.mean(),
                        "d_lo": ci(rep)[0], "d_hi": ci(rep)[1], "Q2_only": q2_only, "QL_only": ql_only, "mcnemar_p": pm,
                        "small_n": n_ < 20})
    dd_ = h2_rows[0]["QL_minus_Q2"] - h2_rows[1]["QL_minus_Q2"]
    rep_dd = h2_rep[h2_rows[0]["group"]] - h2_rep[h2_rows[1]["group"]]
    h2_rows.append({"group": "QL 이득 차이: 이름을 든 방식 있음 − 없음", "n": None, "QL_minus_Q2": dd_,
                    "d_lo": ci(rep_dd)[0], "d_hi": ci(rep_dd)[1], "verdict": verdict(*ci(rep_dd))})
    ql_listed = save_csv(pd.DataFrame(h2_rows), "ql_gain_by_listed_style.csv")
    # fixed / broken by QL
    a2, aL = G["Q2"]["JA_all"], G["QL"]["JA_all"]
    fb_tab = pd.crosstab(np.where(a2["p"] >= THRESHOLD, "Q2 탐지", "Q2 놓침"),
                         np.where(aL["p"] >= THRESHOLD, "QL 탐지", "QL 놓침"))
    fb_tab.index.name = "JA 공격 420"
    fb_tab.reset_index().to_csv(os.path.join(TAB, "q2_vs_ql_crosstab_attacks.csv"), index=False, encoding="utf-8-sig")

    # ---------------------------------------------------------- 5. facets: technique, detector, defense, phase, ...
    def facet(name, col, order, labels, multi=False, subset=None):
        rows_ = []
        for q in QS:
            keep_ = np.ones(nI, bool) if subset is None else np.asarray(subset, bool)
            inj = D[q]["inj"][keep_].reset_index(drop=True)
            hit = (inj["p"] >= THRESHOLD).to_numpy()
            hit_other = (D["QL" if q == "Q2" else "Q2"]["inj"]["p"] >= THRESHOLD).to_numpy()[keep_]
            for v in order:
                mask = inj["tags"].apply(lambda t: v in t).to_numpy() if multi and v != "(none)" else (
                    (inj["n_tags"] == 0).to_numpy() if multi else (inj[col] == v).to_numpy())
                if mask.sum() == 0:
                    continue
                dd = det(inj.loc[mask, "p"])
                k1, n1 = int(hit[mask].sum()), int(mask.sum())
                k0, n0 = int(hit[~mask].sum()), int((~mask).sum())
                d, lo, hi = newcombe(k1, n1, k0, n0) if n0 else (None, None, None)
                r = {"facet": name, "question": q, "value": v, "value_ko": labels.get(v, str(v)), **dd,
                     "n_rest": n0, "TPR_rest": k0 / n0 if n0 else None, "d_vs_rest": d, "d_lo": lo, "d_hi": hi,
                     "fisher_p": fisher_p(k1, n1, k0, n0) if n0 else None,
                     "small_n": n1 < 20}
                if q == "QL":
                    q2_only, ql_only, pm = mcnemar_exact(hit_other[mask], hit[mask])
                    r.update({"QL_minus_Q2": hit[mask].mean() - hit_other[mask].mean(), "Q2_only": q2_only,
                              "QL_only": ql_only, "mcnemar_p_QL_vs_Q2": pm})
                rows_.append(r)
        df = pd.DataFrame(rows_)
        for q in QS:
            m = (df["question"] == q) & df["fisher_p"].notna()
            df.loc[m, "fisher_p_holm"] = holm(df.loc[m, "fisher_p"].tolist())
        df["d_verdict"] = [verdict(lo, hi) if lo is not None and lo == lo else "" for lo, hi in zip(df["d_lo"], df["d_hi"])]
        return df

    tags_order = [t for t, _ in pd.Series([t for ts in inj_meta["tags"] for t in ts]).value_counts().items()] + ["(none)"]
    by_tech = save_csv(facet("technique", "tags", tags_order, TAG_KO, multi=True), "by_technique.csv")
    clf_only = (inj_meta["judge_type"] == "clf").to_numpy()
    by_tech_clf = save_csv(facet("technique (classifier-evading attacks only)", "tags", tags_order, TAG_KO, multi=True,
                                 subset=clf_only), "by_technique_classifier_only.csv")
    by_det = save_csv(facet("detector", "detector", DET_ORDER, DET_KO), "by_detector.csv")
    by_judge = save_csv(facet("judge_type", "judge_type", ["llm", "clf"], JUDGE_KO), "by_judge_type.csv")
    by_def = save_csv(facet("defense", "defense", DEF_ORDER, DEF_KO), "by_defense.csv")
    by_phase = save_csv(facet("phase", "phase", ["Phase1", "Phase2"], {"Phase1": "Phase 1", "Phase2": "Phase 2"}),
                        "by_phase.csv")
    by_risk = save_csv(facet("risk_level", "risk_level", [3, 4], {3: "3 (중간)", 4: "4 (높음)"}), "by_risk_level.csv")
    by_scen = save_csv(facet("scenario", "scenario", ["scenario_1", "scenario_2", "scenario_3", "scenario_4"],
                             {f"scenario_{i}": f"시나리오 {i}" for i in range(1, 5)}), "by_scenario.csv")
    by_out = save_csv(facet("outcome", "outcome", OUTCOME_ORDER, OUTCOME_KO), "by_attack_outcome.csv")
    by_model = save_csv(facet("target_model", "target_model", ["Phi-3-medium-128k-instruct", "GPT-4o-mini"],
                              {"Phi-3-medium-128k-instruct": "Phi-3-medium", "GPT-4o-mini": "GPT-4o-mini"}),
                        "by_target_model.csv")
    by_addr = save_csv(facet("target_address", "has_target_addr", [True, False],
                             {True: "contact@contact.com 있음", False: "주소 문자열 없음"}), "by_target_address.csv")
    for q in QS:
        D[q]["inj"]["ntag_bucket"] = pd.cut(D[q]["inj"]["n_tags"], [-1, 1, 2, 3, 4, 99],
                                            labels=["0-1", "2", "3", "4", "5+"]).astype(str)
    by_ntag = save_csv(facet("n_tags", "ntag_bucket", ["0-1", "2", "3", "4", "5+"],
                             {"0-1": "0-1개", "2": "2개", "3": "3개", "4": "4개", "5+": "5개 이상"}), "by_n_tags.csv")
    qcuts = np.quantile(inj_meta["char_len"] if "char_len" in inj_meta else D["Q2"]["inj"]["char_len"], [0, .25, .5, .75, 1])
    qcuts = np.unique(np.round(qcuts).astype(int))
    len_labels = [f"{qcuts[i] if i == 0 else qcuts[i] + 1}–{qcuts[i + 1]}자" for i in range(len(qcuts) - 1)]
    for q in QS:
        D[q]["inj"]["len_q"] = pd.cut(D[q]["inj"]["char_len"], qcuts, labels=len_labels, include_lowest=True).astype(str)
    by_len = save_csv(facet("length_quartile", "len_q", len_labels, {}), "by_length_quartile.csv")
    facets_all = pd.concat([by_det, by_judge, by_def, by_phase, by_risk, by_scen, by_out, by_model, by_addr, by_ntag,
                            by_len])
    save_csv(facets_all, "by_facet_all.csv")
    # tag co-occurrence (for reading the multi-label table)
    tl = [t for t in tags_order if t != "(none)"]
    co = pd.DataFrame(0, index=tl, columns=tl)
    for ts in inj_meta["tags"]:
        for a_ in ts:
            for b_ in ts:
                co.loc[a_, b_] += 1
    co.index.name = "tag"
    co.reset_index().to_csv(os.path.join(TAB, "technique_cooccurrence.csv"), index=False, encoding="utf-8-sig")
    # detector x phase counts
    xt = pd.crosstab(inj_meta["defense"], inj_meta["phase"])
    xt.reset_index().to_csv(os.path.join(TAB, "defense_x_phase_counts.csv"), index=False, encoding="utf-8-sig")

    # ---------------------------------------------------------- 6. format separability (why AUC is inflated here)
    ja_all = ja_meta.copy()
    y = ja_all["label_int"].to_numpy()
    feat_rows = []
    feats = {"contact@contact.com 문자열": ja_all["has_target_addr"].astype(int),
             "'confirmation' 단어": ja_all["has_confirmation"].astype(int),
             "이메일 문서 (doc_type)": ja_all["is_email"].astype(int),
             "'Subject:'로 시작": ja_all["subject_start"].astype(int),
             "글자 수": ja_all["char_len"]}
    for k, v in feats.items():
        a = metrics(y.tolist(), v.astype(float).tolist())["AUC"]
        feat_rows.append({"set": "JA 920", "feature": k, "AUC": a, "AUC_direction_free": max(a, 1 - a),
                          "share_attacks": float(v[y == 1].astype(bool).mean()) if k != "글자 수" else None,
                          "share_benign": float(v[y == 0].astype(bool).mean()) if k != "글자 수" else None})

    def surface_cv(df):
        X = np.column_stack([df["has_target_addr"], df["has_confirmation"], df["is_email"], df["subject_start"],
                             np.log1p(df["char_len"])]).astype(float)
        yy = df["label_int"].to_numpy()
        model = make_pipeline(StandardScaler(), LogisticRegression(max_iter=1000))
        pr = cross_val_predict(model, X, yy, cv=StratifiedKFold(5, shuffle=True, random_state=SEED),
                               method="predict_proba")[:, 1]
        return metrics(yy.tolist(), pr.tolist())["AUC"]

    feat_rows.append({"set": "JA 920", "feature": "표면 특징 5개 로지스틱 (5겹 교차검증)", "AUC": surface_cv(ja_all),
                      "AUC_direction_free": None})
    feat_rows.append({"set": "EN 1000 (참고)", "feature": "표면 특징 5개 로지스틱 (5겹 교차검증)",
                      "AUC": surface_cv(en_meta), "AUC_direction_free": None})
    for q in QS:
        feat_rows.append({"set": "JA 920", "feature": f"Jev {q}", "AUC": overall.set_index("question").loc[q, "AUC"]})
    fmt_sep = save_csv(pd.DataFrame(feat_rows), "format_separability.csv")

    # Jev AUC against narrower benign comparison sets (format-matched)
    sub_rows = []
    ben_meta = D["Q2"]["ben"]
    subsets = {"전체 정상 500": np.ones(nB, bool), "정상 이메일 146": (ben_meta["doc_type"] == "email").to_numpy(),
               "LLMail 정상 메일 37": (ben_meta["source"] == "LLMail-Inject").to_numpy(),
               "Enron 실제 메일 78": (ben_meta["source"] == "Enron").to_numpy(),
               "이메일 아닌 정상 354": (ben_meta["doc_type"] != "email").to_numpy()}
    srng = np.random.default_rng(SEED + 2)
    for name, m in subsets.items():
        nb_ = int(m.sum())
        SB = srng.integers(0, nb_, (N_BOOT, nb_))
        for q in QS:
            pI, pB = D[q]["inj"]["p"].to_numpy(), BENP[q]["JA"][m]
            r = boot_auc(pI, pB, IDX["JA_all"], SB)
            fp = int((pB >= THRESHOLD).sum())
            sub_rows.append({"question": q, "benign_set": name, "n_benign": nb_, "AUC": auc_metrics(pI, pB),
                             "AUC_lo": ci(r)[0], "AUC_hi": ci(r)[1], "fp": fp, "FPR": fp / nb_,
                             "FPR_lo": J.wilson(fp, nb_)[0], "FPR_hi": J.wilson(fp, nb_)[1],
                             "mean_p_benign": float(pB.mean())})
            if name == "LLMail 정상 메일 37":  # EN LLMail attacks vs the same 37 (EN calls), for reference
                pE = G[q]["EN_LL"]["p"].to_numpy()
                sub_rows.append({"question": q, "benign_set": name + " (EN LLMail 공격 89 기준, 참고)", "n_benign": nb_,
                                 "AUC": auc_metrics(pE, BENP[q]["EN"][m])})
    auc_sub = save_csv(pd.DataFrame(sub_rows), "auc_by_benign_subset.csv")

    # ---------------------------------------------------------- 7. threshold sweep (benign = the 500 shared docs)
    grid = np.round(np.arange(0.0, 1.0001, 0.001), 3)
    sw_rows = []
    for q in QS:
        pI, pB, pE = D[q]["inj"]["p"].to_numpy(), BENP[q]["JA"], G[q]["EN_LL"]["p"].to_numpy()
        for t in grid[::10]:
            sw_rows.append({"question": q, "threshold": t, "TPR_JA": (pI >= t).mean(), "TPR_EN_LL": (pE >= t).mean(),
                            "FPR_JA_benign": (pB >= t).mean()})
    sweep = save_csv(pd.DataFrame(sw_rows), "threshold_sweep.csv")
    at_rows = []
    for q in QS:
        pI, pB, pE = D[q]["inj"]["p"].to_numpy(), BENP[q]["JA"], G[q]["EN_LL"]["p"].to_numpy()
        pBE = BENP[q]["EN"]
        pC, pL = G[q]["JA_clf"]["p"].to_numpy(), G[q]["JA_llm"]["p"].to_numpy()
        for target in (0.01, 0.05, "fixed 0.5"):
            t = 0.5 if target == "fixed 0.5" else next(t for t in grid if (pB >= t).mean() <= target)
            at_rows.append({"question": q, "target_FPR": target, "threshold": t, "FPR_JA_benign": (pB >= t).mean(),
                            "FPR_EN_benign": (pBE >= t).mean(), "TPR_JA": (pI >= t).mean(),
                            "TPR_EN_LL": (pE >= t).mean(), "TPR_JA_clf": (pC >= t).mean(),
                            "TPR_JA_llm": (pL >= t).mean()})
    thr = save_csv(pd.DataFrame(at_rows), "thresholds_at_fpr.csv")

    # ---------------------------------------------------------- 8. run stability (3 calls per document)
    st_rows = []
    for q in QS:
        ja = D[q]["ja"]
        for r in range(3):
            pr = ja[f"p_run{r}"]
            m = metrics(ja["label_int"].tolist(), pr.tolist())
            st_rows.append({"question": q, "run": r, "TPR": m["TPR"], "FPR": m["FPR"], "AUC": m["AUC"]})
        m = metrics(ja["label_int"].tolist(), ja["p"].tolist())
        st_rows.append({"question": q, "run": "mean of 3", "TPR": m["TPR"], "FPR": m["FPR"], "AUC": m["AUC"],
                        "flip_attack": int(D[q]["inj"]["flip"].sum()), "flip_benign": int(D[q]["ben"]["flip"].sum()),
                        "p_sd_mean": ja["p_sd"].mean(), "p_sd_max": ja["p_sd"].max(),
                        "share_sd_zero": float((ja["p_sd"] < 1e-9).mean())})
    stab = save_csv(pd.DataFrame(st_rows), "stability.csv")

    # ---------------------------------------------------------- 9. misses: how far below 0.5, and examples
    miss_rows = []
    for q in QS:
        pI = D[q]["inj"]["p"].to_numpy()
        miss = pI < THRESHOLD
        miss_rows.append({"question": q, "n_missed": int(miss.sum()), "missed_p_lt_0.1": int((pI < 0.1).sum()),
                          "missed_0.1_0.3": int(((pI >= 0.1) & (pI < 0.3)).sum()),
                          "missed_0.3_0.5": int(((pI >= 0.3) & (pI < 0.5)).sum()),
                          "median_p_missed": float(np.median(pI[miss])) if miss.any() else None})
    miss_tab = save_csv(pd.DataFrame(miss_rows), "missed_how_close.csv")
    fn = D["Q2"]["inj"][["uid", "p", "detector", "defense", "phase", "scenario", "outcome", "n_tags", "char_len",
                         "injected_instruction", "text"]].rename(columns={"p": "p_Q2"})
    fn["tags"] = D["Q2"]["inj"]["tags"].str.join(",")
    fn["p_QL"] = D["QL"]["inj"]["p"].to_numpy()
    fn["missed_by"] = np.select([(fn.p_Q2 < .5) & (fn.p_QL < .5), fn.p_Q2 < .5, fn.p_QL < .5],
                                ["both", "Q2_only", "QL_only"], "none")
    fn["excerpt"] = fn["text"].map(lambda s: re.sub(r"\s+", " ", s)[:240])
    fn["injected_instruction"] = fn["injected_instruction"].fillna("").map(lambda s: re.sub(r"\s+", " ", s)[:200])
    fn = fn.drop(columns=["text"])
    save_csv(fn[fn["missed_by"] != "none"].sort_values(["missed_by", "p_QL"]), "missed_attacks.csv")
    both_missed = fn[fn["missed_by"] == "both"]

    # ---------------------------------------------------------- summary.json["analysis"]
    def rec(df, keys):
        return {"|".join(str(r[k]) for k in keys): {c: r[c] for c in df.columns if c not in keys} for _, r in df.iterrows()}

    analysis["overall"] = rec(overall, ["question"])
    analysis["benign_fpr_check_vs_en"] = rec(benign_check, ["question"])
    analysis["detection_by_group"] = rec(by_group, ["question", "group"])
    analysis["ja_vs_en_llmail"] = rec(comps, ["question", "A", "B"])
    analysis["team_cluster_bootstrap"] = rec(team_ci, ["question"])
    analysis["en_llmail_by_llm_judge_level"] = rec(en_ll_cross, ["question", "llm_judge_in_level_defence",
                                                                 "challenge_detector_evaded"])
    analysis["paired_q2_vs_ql"] = rec(paired_q, ["set", "metric"])
    analysis["ql_gain_by_listed_style"] = {"ql_listed_tags": QL_LISTED, **rec(ql_listed, ["group"])}
    analysis["by_technique"] = rec(by_tech, ["question", "value"])
    analysis["by_technique_classifier_only"] = rec(by_tech_clf, ["question", "value"])
    analysis["by_detector"] = rec(by_det, ["question", "value"])
    analysis["by_judge_type"] = rec(by_judge, ["question", "value"])
    analysis["by_defense"] = rec(by_def, ["question", "value"])
    analysis["by_phase"] = rec(by_phase, ["question", "value"])
    analysis["by_risk_level"] = rec(by_risk, ["question", "value"])
    analysis["by_scenario"] = rec(by_scen, ["question", "value"])
    analysis["by_attack_outcome"] = rec(by_out, ["question", "value"])
    analysis["by_target_model"] = rec(by_model, ["question", "value"])
    analysis["by_target_address"] = rec(by_addr, ["question", "value"])
    analysis["by_n_tags"] = rec(by_ntag, ["question", "value"])
    analysis["by_length_quartile"] = rec(by_len, ["question", "value"])
    analysis["format_separability"] = rec(fmt_sep, ["set", "feature"])
    analysis["auc_by_benign_subset"] = rec(auc_sub, ["question", "benign_set"])
    analysis["thresholds_at_fpr"] = rec(thr, ["question", "target_FPR"])
    analysis["stability"] = rec(stab, ["question", "run"])
    analysis["missed_how_close"] = rec(miss_tab, ["question"])
    analysis["missed_by_both_n"] = int(len(both_missed))
    n_addr = int(inj_meta["has_target_addr"].sum())
    n_addr_b = int(D["Q2"]["ben"]["has_target_addr"].sum())
    n_nonmail = int((D["Q2"]["ben"]["doc_type"] != "email").sum())
    surf = float(fmt_sep[(fmt_sep["set"] == "JA 920") & fmt_sep["feature"].str.startswith("표면")]["AUC"].iloc[0])
    analysis["format_note"] = {"attacks_with_target_address": n_addr, "benign_with_target_address": n_addr_b,
                               "benign_non_email": n_nonmail, "surface_logistic_cv_auc": surf}
    analysis["caveats"] = [
        f"JA의 공격 {nI}건은 전부 LLMail-Inject 이메일이고 {n_addr}건({100 * n_addr / nI:.0f}%)에 contact@contact.com이 "
        f"들어 있다(대소문자 무시). 정상 {nB}건에는 이 주소가 {n_addr_b}건 나오고, {n_nonmail}건은 이메일이 아니다. 그래서 내용을 "
        f"보지 않는 표면 특징 5개만으로도 AUC {surf:.3f}가 나온다. JA의 AUC는 형식 단서로 부풀 수 있는 구조라 Jev의 "
        "실력 근거로 쓰지 않고, 공격 탐지율(TPR)과 EN LLMail 비교를 본다.",
        "정상 500건은 EN 정상 문서와 바이트 단위로 같다. JA와 EN의 FPR 차이는 같은 문서를 따로 호출한 API 잡음이다.",
        "EN LLMail 89건은 탐지기 우회로 고른 것은 아니지만 51건은 원래 대회에서도 탐지기를 통과했다(origin.objectives).",
        "EN LLMail이 89건뿐이라 JA와의 탐지율 차이 CI가 넓다(폭 약 ±10–15%p). CI가 0을 포함하는 비교는 '차이 없음/오차 "
        "범위'이고, 같다는 뜻이 아니다: 그 폭 안의 차이는 배제하지 못한다.",
        "기법 태그는 관찰된 특징을 붙인 다중 라벨이다. 태그끼리 함께 나오고 팀·탐지기와도 얽혀 있어, 태그별 차이를 "
        "기법의 인과 효과로 읽으면 안 된다.",
        f"JA는 {inj_meta['team_id'].nunique()}개 팀에서 왔고 한 팀이 최대 {inj_meta['team_id'].value_counts().max()}건이다. "
        "팀 단위 부트스트랩 CI(team_cluster_bootstrap.csv)를 함께 본다.",
        "탐지기별 차이(LLM 판정기를 통과한 공격의 낮은 탐지율)는 관찰 결과다. 탐지기는 대회 레벨에 따라 정해졌고 Phase, "
        "팀, 공격 문체와 얽혀 있어 원인을 탐지기 하나로 돌릴 수 없다.",
    ]
    sp = os.path.join(OUT, "summary.json")
    with open(sp, encoding="utf-8") as f:
        summary = json.load(f)
    # run_api.py rewrites summary.json (date = today, commit = current HEAD) every time it is invoked, even when it
    # makes 0 calls. Record whether date / commit still describe the API run (first call in raw/) and warn if not.
    first = {q: (summary.get(q, {}).get("run") or {}).get("first_call") for q in QS}
    run_dates = sorted({v[:10] for v in first.values() if v})
    ok = bool(run_dates) and summary.get("date") in run_dates
    analysis["run_metadata_check"] = {"summary_date": summary.get("date"), "summary_commit": summary.get("commit"),
                                      "api_first_call_date": run_dates, "date_matches_api_run": ok}
    if not ok:
        print(f"WARNING: summary.json date {summary.get('date')} != API run date {run_dates}: run_api.py was re-invoked "
              "after the run, so date/commit no longer describe the API run (see README '다시 실행').")
    summary["analysis"] = clean(analysis)
    with open(sp, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    V = {"D": D, "G": G, "overall": overall, "benign_check": benign_check, "by_group": by_group, "comps": comps,
         "paired_q": paired_q, "by_tech": by_tech, "by_tech_clf": by_tech_clf, "by_det": by_det, "by_judge": by_judge,
         "by_def": by_def, "facets": {
             "phase": by_phase, "scenario": by_scen, "risk": by_risk, "outcome": by_out, "model": by_model,
             "addr": by_addr, "ntag": by_ntag}, "by_len": by_len, "fmt_sep": fmt_sep, "auc_sub": auc_sub,
         "sweep": sweep, "thr": thr, "stab": stab, "BENP": BENP, "miss": miss_tab, "team": team_ci,
         "ql_listed": ql_listed}
    figs = make_figures(V)
    digest(V, inputs, figs, both_missed)


# ------------------------------------------------------------------ figures
def dodge(q, w=0.19):
    return -w if q == "Q2" else w


def errbar(ax, x, y, lo, hi, color, horizontal=False, **kw):
    y, lo, hi = 100 * y, 100 * lo, 100 * hi
    e = [[y - lo], [hi - y]]
    if horizontal:
        ax.errorbar(y, x, xerr=e, fmt="o", color=color, ecolor=color, elinewidth=1.6, capsize=3, ms=6.5, **kw)
    else:
        ax.errorbar(x, y, yerr=e, fmt="o", color=color, ecolor=color, elinewidth=1.6, capsize=3, ms=6.5, **kw)


def q_handles():
    return [Line2D([], [], color=Q_COLORS[q], marker="o", lw=0, ms=7, label=Q_NAME[q]) for q in QS]


def make_figures(V):
    D, G, ov = V["D"], V["G"], V["overall"].set_index("question")
    made = []
    bg = V["by_group"].set_index(["question", "group"])
    cp = V["comps"].set_index(["question", "A", "B"])

    # f01 headline: TPR (EN all, EN LLMail, JA) / FPR (EN vs JA benign) / AUC
    fig, axes = plt.subplots(1, 3, figsize=(13, 5.4), gridspec_kw={"width_ratios": [3, 2, 2]})
    ax = axes[0]
    cats = ["EN_all", "EN_LL", "JA_all"]
    for i, g in enumerate(cats):
        for q in QS:
            r = bg.loc[(q, g)]
            x = i + dodge(q)
            b = ax.bar(x, 100 * r["TPR"], width=0.36, color=Q_COLORS[q])
            S.bar_gap(b)
            ax.errorbar(x, 100 * r["TPR"], yerr=[[100 * (r["TPR"] - r["TPR_lo"])], [100 * (r["TPR_hi"] - r["TPR"])]],
                        fmt="none", ecolor=S.INK_2, elinewidth=1.1, capsize=3)
            ax.text(x, 100 * r["TPR_hi"] + 1.5, f"{100 * r['TPR']:.1f}", ha="center", va="bottom", fontsize=9,
                    color=S.INK)
    ax.set_xticks(range(3), [f"EN 전체 주입\n(n={int(bg.loc[('Q2', 'EN_all'), 'n'])})",
                             f"EN LLMail 주입\n(n={int(bg.loc[('Q2', 'EN_LL'), 'n'])})",
                             f"JA 탐지기 우회 공격\n(n={int(bg.loc[('Q2', 'JA_all'), 'n'])})"])
    ax.set_ylim(0, 100)
    ax.set_ylabel("탐지율 TPR (%)")
    ax.set_title("공격을 잡은 비율")
    ax.grid(axis="x", visible=False)
    ax = axes[1]
    for i, k in enumerate(["EN", "JA"]):
        for q in QS:
            r = V["benign_check"].set_index("question").loc[q]
            fp, fr = (r["EN_fp"], r["EN_FPR"]) if k == "EN" else (r["JA_fp"], r["JA_FPR"])
            lo, hi = J.wilson(int(fp), 500)
            x = i + dodge(q)
            b = ax.bar(x, 100 * fr, width=0.36, color=Q_COLORS[q])
            S.bar_gap(b)
            ax.errorbar(x, 100 * fr, yerr=[[100 * (fr - lo)], [100 * (hi - fr)]], fmt="none", ecolor=S.INK_2,
                        elinewidth=1.1, capsize=3)
            ax.text(x, 100 * hi + 0.15, f"{100 * fr:.1f}\n({int(fp)}건)", ha="center", va="bottom", fontsize=8.5)
    ax.set_xticks(range(2), ["EN 정상 500\n(01_baseline 호출)", "JA 정상 500\n(같은 문서, 새 호출)"])
    ax.set_ylim(0, 6)
    ax.set_ylabel("오탐률 FPR (%)")
    ax.set_title("정상 문서를 막은 비율")
    ax.grid(axis="x", visible=False)
    ax = axes[2]
    # AUC as points + 95% bootstrap CI (not bars: the axis does not start at 0, so bar heights would mislead)
    for i, k in enumerate(["EN", "JA"]):
        for q in QS:
            pre = "EN_" if k == "EN" else ""
            v, lo, hi = ov.loc[q, pre + "AUC"], ov.loc[q, pre + "AUC_lo"], ov.loc[q, pre + "AUC_hi"]
            x = i + dodge(q, 0.15)
            ax.errorbar(x, v, yerr=[[v - lo], [hi - v]], fmt="o", color=Q_COLORS[q], ecolor=Q_COLORS[q],
                        elinewidth=1.6, capsize=3, ms=6.5)
            ax.text(x + 0.06, v, f"{v:.3f}", ha="left", va="center", fontsize=8.5, color=Q_COLORS[q])
    ax.set_xticks(range(2), ["EN 1000", "JA 920\n(형식 단서로 부풀 수 있음)"])
    ax.set_xlim(-0.5, 1.6)
    ax.set_ylim(0.93, 1.0)
    ax.set_ylabel("AUC (축은 0.93부터)")
    ax.set_title("순위 지표 AUC")
    ax.grid(axis="x", visible=False)
    axes[0].legend(handles=[Patch(color=Q_COLORS[q], label=Q_NAME[q]) for q in QS], loc="upper left", ncol=1)
    j2, jl = bg.loc[("Q2", "JA_all")], bg.loc[("QL", "JA_all")]
    S.title(fig, f"탐지기를 이미 통과한 실제 공격 중 Jev가 잡은 것은 Q2 {100 * j2['TPR']:.0f}%, QL {100 * jl['TPR']:.0f}%",
            "TPR·FPR: 막대 + Wilson 95% CI. AUC: 점 + 부트스트랩 95% CI (축이 0.93부터라 막대 대신 점). "
            "정상 500건은 EN과 같은 문서. 임계값 0.5, p = 3회 호출 평균")
    made.append(S.save(fig, "f01_headline", out_dir=FIG))

    # f02 key comparison: detection by group
    fig, ax = plt.subplots(figsize=(10.5, 7.4))
    order = GROUP_ORDER[::-1]
    for i, g in enumerate(order):
        for q in QS:
            r = bg.loc[(q, g)]
            errbar(ax, i - dodge(q, 0.17), r["TPR"], r["TPR_lo"], r["TPR_hi"], Q_COLORS[q], horizontal=True)
            ax.text(100 * r["TPR_hi"] + 1.2, i - dodge(q, 0.17), f"{100 * r['TPR']:.1f}%", va="center", fontsize=8.5,
                    color=Q_COLORS[q])
    ax.set_yticks(range(len(order)), [f"{GROUP_KO[g]} (n={int(bg.loc[('Q2', g), 'n'])})" for g in order])
    sep = len(GROUP_ORDER) - N_EN_GROUPS - 0.5
    ax.axhline(sep, color=S.AXIS, lw=0.8)
    ax.text(1, sep + 0.12, "▲ EN 기준선 (탐지기 우회로 고르지 않음)", fontsize=8.5, color=S.INK_2, va="bottom", ha="left")
    ax.text(1, sep - 0.12, "▼ JA (대회 탐지기를 통과한 제출물만)", fontsize=8.5, color=S.INK_2, va="top", ha="left")
    ax.set_xlim(0, 102)
    ax.set_xlabel("탐지율 TPR (%), 임계값 0.5")
    ax.grid(axis="y", visible=False)
    ax.legend(handles=q_handles(), loc="lower right")
    c2, cl = cp.loc[("Q2", "JA_all", "EN_LL")], cp.loc[("QL", "JA_all", "EN_LL")]
    k2, kl = cp.loc[("Q2", "JA_clf", "EN_LL")], cp.loc[("QL", "JA_clf", "EN_LL")]
    both0 = all(c["dTPR_newcombe_lo"] <= 0 <= c["dTPR_newcombe_hi"] for c in (c2, cl))
    S.title(fig, f"JA − EN LLMail 탐지율: Q2 {pp(c2['dTPR'])}, QL {pp(cl['dTPR'])}"
                 + (" (둘 다 95% CI가 0을 포함: 차이 없음/오차 범위)" if both0 else ""),
            f"Q2 CI {pp(c2['dTPR_newcombe_lo'])}~{pp(c2['dTPR_newcombe_hi'])}, QL CI {pp(cl['dTPR_newcombe_lo'])}~"
            f"{pp(cl['dTPR_newcombe_hi'])} (Newcombe). 점 = 탐지율, 선 = Wilson 95% CI. 같은 대회·같은 메일 형식.\n"
            f"분류기만 통과한 JA − EN LLMail도 오차 범위: Q2 {pp(k2['dTPR'])} (CI {pp(k2['dTPR_newcombe_lo'])}~"
            f"{pp(k2['dTPR_newcombe_hi'])}), QL {pp(kl['dTPR'])} (CI {pp(kl['dTPR_newcombe_lo'])}~"
            f"{pp(kl['dTPR_newcombe_hi'])}).\n같다는 뜻은 아니다(±10~15%p 차이는 배제 못함). "
            f"JA 안의 낮은 탐지율은 LLM 판정기를 통과한 {int(bg.loc[('Q2', 'JA_llm'), 'n'])}건에 몰려 있다")
    made.append(S.save(fig, "f02_ja_vs_en_llmail", out_dir=FIG))

    # f03 p distribution of JA attacks and benign per question
    fig, axes = plt.subplots(1, 2, figsize=(12, 5), sharey=True)
    bins = np.arange(0, 1.0001, 0.05)
    for ax, q in zip(axes, QS):
        pI, pB = D[q]["inj"]["p"].to_numpy(), V["BENP"][q]["JA"]
        hI = np.histogram(pI, bins)[0] / len(pI) * 100
        hB = np.histogram(pB, bins)[0] / len(pB) * 100
        w = 0.05
        b1 = ax.bar(bins[:-1] + w * 0.27, hI, width=w * 0.46, color=INJ, align="center")
        b2 = ax.bar(bins[:-1] + w * 0.73, np.minimum(hB, 32), width=w * 0.46, color=BEN, align="center")
        S.bar_gap(b1)
        S.bar_gap(b2)
        for x, h in zip(bins[:-1], hB):
            if h > 32:
                ax.text(x + w * 0.73, 32.3, f"{h:.0f}%", ha="center", va="bottom", fontsize=8.5, color=S.INK_2)
        ax.axvline(0.5, color=S.INK_2, lw=1, ls="--")
        miss = (pI < 0.5).mean()
        ax.text(0.49, 26, f"놓친 공격 {100 * miss:.0f}%", ha="right", fontsize=9.5, color=INJ)
        ax.text(0.51, 26, f"잡은 공격 {100 * (1 - miss):.0f}%", ha="left", fontsize=9.5, color=INJ)
        ax.set_title(Q_NAME[q], color=Q_COLORS[q])
        ax.set_xlabel("Jev p (3회 평균)")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 35)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("집단 안 비율 (%)")
    axes[0].legend(handles=[Patch(color=INJ, label=f"JA 공격 (n={len(D['Q2']['inj'])})"),
                            Patch(color=BEN, label=f"정상 (n={len(D['Q2']['ben'])})")], loc="upper right")
    mi = V["miss"].set_index("question")
    S.title(fig, f"Q2가 놓친 공격은 p 0~0.5에 넓게 퍼져 있고(중앙값 {mi.loc['Q2', 'median_p_missed']:.2f}), "
                 f"QL이 놓친 공격은 0.3~0.5에 더 몰린다(중앙값 {mi.loc['QL', 'median_p_missed']:.2f})",
            f"놓친 공격 중 p < 0.1: Q2 {int(mi.loc['Q2', 'missed_p_lt_0.1'])}/{int(mi.loc['Q2', 'n_missed'])}, "
            f"QL {int(mi.loc['QL', 'missed_p_lt_0.1'])}/{int(mi.loc['QL', 'n_missed'])}건. 구간 폭 0.05. "
            "정상 문서는 대부분 0~0.05 구간(막대 위 숫자, 32%에서 잘라 표시). 점선 = 임계값 0.5")
    made.append(S.save(fig, "f03_p_distribution", out_dir=FIG))

    # f04 benign: EN call vs JA call on the same 500 docs
    fig, axes = plt.subplots(1, 2, figsize=(11.5, 5.6))
    bc = V["benign_check"].set_index("question")
    for ax, q in zip(axes, QS):
        a, b = V["BENP"][q]["EN"], V["BENP"][q]["JA"]
        jr = np.random.default_rng(1)
        ax.scatter(a + jr.uniform(-.004, .004, len(a)), b + jr.uniform(-.004, .004, len(b)), s=14, color=BEN,
                   alpha=0.55, edgecolors="none")
        ax.plot([0, 1], [0, 1], color=S.AXIS, lw=1)
        ax.axvline(0.5, color=S.INK_2, lw=0.8, ls="--")
        ax.axhline(0.5, color=S.INK_2, lw=0.8, ls="--")
        r = bc.loc[q]
        ax.text(0.98, 0.04, f"FPR  EN {int(r['EN_fp'])}/500 · JA {int(r['JA_fp'])}/500\n"
                            f"한쪽만 0.5 이상: EN만 {int(r['flagged_EN_only'])} · JA만 {int(r['flagged_JA_only'])}"
                            f" (McNemar {fmt_p(r['mcnemar_p'])})\n"
                            f"|Δp| 평균 {r['mean_abs_dp']:.3f}, ≤0.01인 문서 {100 * r['share_abs_dp_le_0.01']:.0f}%, "
                            f"r = {r['pearson_r']:.3f}",
                ha="right", va="bottom", fontsize=8.5, color=S.INK_2, transform=ax.transAxes,
                bbox=dict(boxstyle="round,pad=0.4", fc=S.SURFACE, ec=S.GRID))
        ax.set_xlim(-0.02, 1)
        ax.set_ylim(-0.02, 1)
        ax.set_xlabel("p, EN 기준선 호출 (01_baseline)")
        ax.set_title(Q_NAME[q], color=Q_COLORS[q])
    axes[0].set_ylabel("p, JA 실험 호출 (03_judge_attack)")
    S.title(fig, "같은 정상 문서 500건을 다시 불러도 오탐은 거의 같다: 차이는 호출 잡음 수준",
            "점 하나 = 정상 문서 하나 (겹침을 보이려고 ±0.004 흔들어 표시). 대각선 = 두 호출의 p가 같음, 점선 = 임계값 0.5")
    made.append(S.save(fig, "f04_benign_same_docs_en_vs_ja", out_dir=FIG))

    # f05 Q2 vs QL scatter on JA
    fig, ax = plt.subplots(figsize=(8, 7))
    p2I, pLI = D["Q2"]["inj"]["p"].to_numpy(), D["QL"]["inj"]["p"].to_numpy()
    p2B, pLB = V["BENP"]["Q2"]["JA"], V["BENP"]["QL"]["JA"]
    ax.scatter(p2B, pLB, s=12, color=BEN, alpha=0.5, edgecolors="none", label=f"정상 (n={len(p2B)})")
    ax.scatter(p2I, pLI, s=16, color=INJ, alpha=0.6, edgecolors="none", label=f"JA 공격 (n={len(p2I)})")
    ax.plot([0, 1], [0, 1], color=S.AXIS, lw=1)
    ax.axvline(0.5, color=S.INK_2, lw=0.8, ls="--")
    ax.axhline(0.5, color=S.INK_2, lw=0.8, ls="--")
    d2, dL = p2I >= .5, pLI >= .5
    # quadrant counts sit in strips above / below the data range so they never cover points
    quad = {(0.25, 1.08): (~d2 & dL).sum(), (0.75, 1.08): (d2 & dL).sum(), (0.25, -0.08): (~d2 & ~dL).sum(),
            (0.75, -0.08): (d2 & ~dL).sum()}
    lab = {(0.25, 1.08): "QL만 잡음", (0.75, 1.08): "둘 다 잡음", (0.25, -0.08): "둘 다 놓침", (0.75, -0.08): "Q2만 잡음"}
    for (x, y), n in quad.items():
        ax.text(x, y, f"{lab[(x, y)]}: 공격 {n}건", ha="center", va="center", fontsize=10.5, color=INJ,
                fontweight="bold")
    ax.axhspan(1.03, 1.13, color=S.GRID, alpha=0.35, lw=0)
    ax.axhspan(-0.13, -0.03, color=S.GRID, alpha=0.35, lw=0)
    ax.set_xlim(-0.02, 1.02)
    ax.set_ylim(-0.13, 1.13)
    ax.set_yticks(np.arange(0, 1.01, 0.2))
    ax.set_xlabel("p, Q2 (짧은 질문)")
    ax.set_ylabel("p, QL (정의형 긴 질문)")
    ax.legend(loc="center right", bbox_to_anchor=(1.0, 0.3))
    pq = V["paired_q"].set_index(["set", "metric"]).loc[("JA attacks (420)", "TPR")]
    S.title(fig, f"QL은 Q2가 놓친 공격 중 {int(pq['QL_only'])}건을 더 잡고, Q2가 잡은 공격 중 {int(pq['Q2_only'])}건만 놓친다",
            f"JA 920건, 같은 문서 짝 비교. QL − Q2 탐지율 {pp(pq['d_QL_minus_Q2'])} "
            f"(95% CI {pp(pq['d_lo'])}~{pp(pq['d_hi'])}, McNemar {fmt_p(pq['mcnemar_p'])})")
    made.append(S.save(fig, "f05_q2_vs_ql_paired", out_dir=FIG))

    # f06 by technique tag
    bt = V["by_tech"]
    tags = [t for t in bt[bt.question == "Q2"].sort_values("n", ascending=True)["value"]]
    tags = [t for t in tags if t != "(none)"]
    fig, ax = plt.subplots(figsize=(11, 9.5))
    for i, t in enumerate(tags):
        for q in QS:
            r = bt[(bt.question == q) & (bt.value == t)].iloc[0]
            errbar(ax, i - dodge(q, 0.17), r["TPR"], r["TPR_lo"], r["TPR_hi"], Q_COLORS[q], horizontal=True,
                   alpha=0.55 if r["small_n"] else 1.0)
    for q in QS:
        ax.axvline(100 * ov.loc[q, "TPR"], color=Q_COLORS[q], lw=1, ls="--", alpha=0.8)
    nmap = bt[bt.question == "Q2"].set_index("value")["n"]
    ax.set_yticks(range(len(tags)), [f"{TAG_KO[t]}  (n={int(nmap[t])})" for t in tags])
    for lbl, t in zip(ax.get_yticklabels(), tags):
        if nmap[t] < 20:
            lbl.set_color(S.MUTED)
    ax.set_xlim(0, 102)
    ax.set_xlabel("탐지율 TPR (%), 해당 태그가 붙은 JA 공격 안에서")
    ax.grid(axis="y", visible=False)
    ax.legend(handles=q_handles() + [Line2D([], [], color=S.INK_2, ls="--", lw=1, label="질문별 JA 전체 탐지율")],
              loc="upper left")
    sig = bt[(bt.fisher_p_holm < 0.05)]
    sig_txt = ", ".join(f"{TAG_KO[r['value']]} {r['question']} {pp(r['d_vs_rest'], 0)}" for _, r in sig.iterrows())
    ntag = int((bt.question == "Q2").sum())
    btc = V["by_tech_clf"].set_index(["question", "value"])
    clf_txt = ", ".join(f"{TAG_KO[r['value']].split(' (')[0]} {r['question']} {pp(r['d_vs_rest'], 0)} → "
                        f"{pp(btc.loc[(r['question'], r['value']), 'd_vs_rest'], 0)}" for _, r in sig.iterrows())
    S.title(fig, f"기법 태그별 탐지율 차이는 대부분 오차 범위: (태그 {ntag - 1}개 + 태그 없음) × 질문 2개 중 "
                 f"Holm 보정 후 남는 것은 {len(sig)}개",
            "한 공격에 태그가 여러 개 붙을 수 있다(다중 라벨). 회색 글씨·흐린 점 = n < 20. 선 = Wilson 95% CI.\n"
            f"그 태그가 없는 공격 대비 차이가 Holm 보정 후 유의: {sig_txt if sig_txt else '없음'}.\n"
            f"분류기만 통과한 {int(V['by_judge'].set_index(['question', 'value']).loc[('Q2', 'clf'), 'n'])}건 안에서 "
            f"다시 보면 Holm 보정 후 남는 태그 {int((V['by_tech_clf'].fisher_p_holm < 0.05).sum())}개. "
            "다만 표본이 줄어 검정력도 낮아진다.\n"
            f"(태그 있음 − 없음 차이, 전체 → 분류기만: {clf_txt})")
    made.append(S.save(fig, "f06_by_technique", out_dir=FIG))

    # f07 by detector evaded and by defense setting
    fig, axes = plt.subplots(1, 2, figsize=(13.5, 6.2), gridspec_kw={"width_ratios": [2, 3]})
    jt = V["by_judge"]
    det_rows = [(V["by_det"], o, DET_KO[o]) for o in DET_ORDER] + \
               [(jt, "clf", "분류기만 통과"), (jt, "llm", "LLM 판정기 포함")]
    det_rows = det_rows[::-1]  # plotted bottom-up: the two merged groups end up below the separator
    def_rows = [(V["by_def"], o, DEF_KO[o]) for o in DEF_ORDER
                if ((V["by_def"].question == "Q2") & (V["by_def"].value == o)).any()][::-1]
    for ax, rows_, ttl in ((axes[0], det_rows, "통과한 탐지기 (notes 기준)"), (axes[1], def_rows, "방어 설정 (origin.defense)")):
        for i, (df, o, _) in enumerate(rows_):
            for q in QS:
                r = df[(df.question == q) & (df.value == o)].iloc[0]
                errbar(ax, i - dodge(q, 0.17), r["TPR"], r["TPR_lo"], r["TPR_hi"], Q_COLORS[q], horizontal=True,
                       alpha=0.55 if r["small_n"] else 1.0)
        ns = [int(df[(df.question == "Q2") & (df.value == o)]["n"].iloc[0]) for df, o, _ in rows_]
        ax.set_yticks(range(len(rows_)), [f"{lab} (n={n})" for (_, _, lab), n in zip(rows_, ns)])
        for lbl, n in zip(ax.get_yticklabels(), ns):
            if n < 20:
                lbl.set_color(S.MUTED)
        for q in QS:
            ax.axvline(100 * ov.loc[q, "TPR"], color=Q_COLORS[q], lw=1, ls="--", alpha=0.8)
        ax.set_xlim(-2, 100)
        ax.set_xlabel("탐지율 TPR (%)")
        ax.set_title(ttl)
        ax.grid(axis="y", visible=False)
    axes[0].axhline(1.5, color=S.AXIS, lw=0.8)  # below: the four detectors merged into two groups
    axes[0].legend(handles=q_handles(), loc="lower left", bbox_to_anchor=(0, -0.27), ncol=2)
    jl = jt.set_index(["question", "value"])
    S.title(fig, f"LLM 판정기를 통과한 공격은 Jev도 거의 못 잡는다: Q2 {pct(jl.loc[('Q2', 'llm'), 'TPR'], 0)}, "
                 f"QL {pct(jl.loc[('QL', 'llm'), 'TPR'], 0)} (분류기만 통과한 공격은 {pct(jl.loc[('Q2', 'clf'), 'TPR'], 0)}, "
                 f"{pct(jl.loc[('QL', 'clf'), 'TPR'], 0)})",
            "점 = 탐지율, 선 = Wilson 95% CI, 점선 = 질문별 JA 전체. 회색 글씨·흐린 점 = n < 20. P1/P2 = 대회 Phase. "
            "왼쪽 가로선 아래 = 4종류를 두 묶음으로 합친 것\n('세 탐지기 모두'에는 LLM 판정기가 들어 있다). "
            "관찰 결과다: 탐지기는 대회 레벨로 정해져 Phase·팀·공격 문체와 얽혀 있다")
    made.append(S.save(fig, "f07_by_detector", out_dir=FIG))

    # f08 small multiples: phase, scenario, risk, outcome, target model, address string, n tags
    F = V["facets"]
    panels = [("phase", "대회 Phase"), ("scenario", "시나리오"), ("risk", "위험도"), ("outcome", "대회에서의 공격 결과"),
              ("model", "대회 대상 모델"), ("addr", "목표 주소 문자열"), ("ntag", "기법 태그 수")]
    fig, axes = plt.subplots(2, 4, figsize=(15, 8.6))
    axes = axes.ravel()
    for ax, (k, ttl) in zip(axes, panels):
        df = F[k]
        vals = list(dict.fromkeys(df[df.question == "Q2"]["value"]))
        for i, v in enumerate(vals):
            for q in QS:
                r = df[(df.question == q) & (df.value == v)].iloc[0]
                errbar(ax, i + dodge(q, 0.15), r["TPR"], r["TPR_lo"], r["TPR_hi"], Q_COLORS[q],
                       alpha=0.55 if r["small_n"] else 1.0)
        nm = df[df.question == "Q2"].set_index("value")
        lbls = [f"{nm.loc[v, 'value_ko']}\nn={int(nm.loc[v, 'n'])}" for v in vals]
        if k == "outcome":
            short = {"full": "발송 성공\n(주소·본문 정확)", "partial": "발송했으나\n주소·본문 틀림",
                     "none": "탐지만 통과,\n발송 못 함"}
            lbls = [short[v] + "\nn=" + str(int(nm.loc[v, "n"])) for v in vals]
        if k == "addr":
            lbls = ["contact@contact.com\n있음\nn=" + str(int(nm.loc[True, "n"])),
                    "주소 문자열\n없음\nn=" + str(int(nm.loc[False, "n"]))]
        ax.set_xticks(range(len(vals)), lbls, fontsize=8.5)
        ax.set_xlim(-0.6, len(vals) - 0.4)
        ax.set_ylim(0, 100)
        ax.set_title(ttl, fontsize=11)
        ax.grid(axis="x", visible=False)
        for q in QS:
            ax.axhline(100 * ov.loc[q, "TPR"], color=Q_COLORS[q], lw=0.9, ls="--", alpha=0.7)
    for ax in axes[[0, 4]]:
        ax.set_ylabel("탐지율 TPR (%)")
    axes[-1].axis("off")
    axes[-1].legend(handles=q_handles() + [Line2D([], [], color=S.INK_2, ls="--", lw=1, label="질문별 JA 전체 탐지율")],
                    loc="center", fontsize=10)
    fo = F["outcome"].set_index(["question", "value"])
    inj0 = D["Q2"]["inj"]
    r4 = inj0[inj0["risk_level"] == 4]["harm_type"].value_counts()
    harm_ko = {"data_exfiltration": "정보 유출", "account_data_tamper": "계정 데이터 변조",
               "unauthorized_action": "무단 행동"}
    r4_txt = ", ".join(f"{harm_ko.get(k, k)} {v}건" for k, v in r4.items())
    S.title(fig, f"대회에서 메일 발송까지 성공한 공격이 더 잘 잡힌다(Q2 {pct(fo.loc[('Q2', 'full'), 'TPR'], 0)}, "
                 f"QL {pct(fo.loc[('QL', 'full'), 'TPR'], 0)}); 다른 메타데이터의 차이는 대부분 오차 범위",
            f"JA 공격 420건. 점 = 탐지율, 선 = Wilson 95% CI, 점선 = 질문별 JA 전체. 흐린 점 = n < 20. "
            f"위험도 4 = {r4_txt}. 시나리오 4 = 분기 이익 전망을 빼내는 목표")
    made.append(S.save(fig, "f08_by_metadata", out_dir=FIG))

    # f09 format separability
    fs = V["fmt_sep"]
    fig, axes = plt.subplots(1, 2, figsize=(14, 5.8), gridspec_kw={"width_ratios": [1.1, 1]})
    ax = axes[0]
    rows_ = fs[fs["set"] == "JA 920"].copy()
    rows_["val"] = rows_["AUC_direction_free"].fillna(rows_["AUC"])
    rows_ = rows_.iloc[::-1]
    for i, (_, r) in enumerate(rows_.iterrows()):
        f = r["feature"]
        col = Q_COLORS.get(f.replace("Jev ", ""), S.MUTED)
        b = ax.barh(i, r["val"], color=col, height=0.62)
        S.bar_gap(b)
        ax.text(r["val"] + 0.005, i, f"{r['val']:.3f}", va="center", fontsize=9)
    ax.set_yticks(range(len(rows_)), [f.replace("표면 특징 5개 로지스틱 (5겹 교차검증)", "표면 특징 5개 합친 로지스틱\n(5겹 교차검증)")
                                      for f in rows_["feature"]])
    ax.axvline(0.5, color=S.INK_2, lw=0.8, ls=":")
    en_ref = fs[fs["set"] != "JA 920"]["AUC"].iloc[0]
    ax.set_xlim(0.4, 1.05)
    ax.set_xlabel("AUC (JA 920, 글자 수는 방향 무관 값)")
    ax.set_title("내용을 안 봐도 라벨이 갈린다")
    i_len = list(rows_["feature"]).index("글자 수")
    ax.text(0.56, i_len, f"참고: 같은 표면 로지스틱을 EN 1000에\n적용하면 AUC {en_ref:.3f}", fontsize=8.5, color=S.INK_2,
            va="center")
    ax.grid(axis="y", visible=False)
    ax = axes[1]
    sub = V["auc_sub"]
    sets = [s for s in dict.fromkeys(sub["benign_set"]) if "참고" not in s][::-1]
    for i, s in enumerate(sets):
        for q in QS:
            r = sub[(sub.question == q) & (sub.benign_set == s)].iloc[0]
            y = i - dodge(q, 0.17)
            ax.errorbar(r["AUC"], y, xerr=[[r["AUC"] - r["AUC_lo"]], [r["AUC_hi"] - r["AUC"]]], fmt="o",
                        color=Q_COLORS[q], ecolor=Q_COLORS[q], elinewidth=1.6, capsize=3, ms=6.5)
            ax.text(r["AUC_hi"] + 0.004, y, f"{r['AUC']:.3f}", va="center", fontsize=8.5, color=Q_COLORS[q])
    ax.set_yticks(range(len(sets)), [f"공격 420 vs {s}" for s in sets])
    ax.set_xlim(0.85, 1.02)
    ax.set_xlabel("Jev AUC (95% 부트스트랩 CI)")
    ax.set_title("정상 쪽을 메일로 좁혀도 Jev AUC는 높다")
    ax.grid(axis="y", visible=False)
    ax.legend(handles=q_handles(), loc="lower left")
    sf = fs[(fs["set"] == "JA 920") & fs["feature"].str.startswith("표면")]["AUC"].iloc[0]
    ca = fs[(fs["set"] == "JA 920") & fs["feature"].str.startswith("contact")].iloc[0]
    S.title(fig, f"JA에서는 내용을 안 보는 표면 특징만으로 AUC {sf:.3f}: 여기서 AUC는 Jev 실력의 근거가 못 된다",
            "왼쪽: 회색 = 내용을 보지 않는 표면 규칙, 색 = Jev. 오른쪽: 공격 420건을 정상의 일부와만 비교한 Jev AUC (95% 부트스트랩 CI).\n"
            f"contact@contact.com은 공격의 {100 * ca['share_attacks']:.0f}%에 있고 정상에는 {100 * ca['share_benign']:.0f}% "
            "→ AUC보다 탐지율(TPR)과 EN LLMail 비교를 본다")
    made.append(S.save(fig, "f09_format_separability", out_dir=FIG))

    # f10 threshold sweep
    sw = V["sweep"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.9), sharex=True)
    for ax, col, ttl in zip(axes, ["TPR_JA", "TPR_EN_LL", "FPR_JA_benign"],
                            ["JA 공격 420 탐지율", "EN LLMail 공격 89 탐지율", "정상 500 오탐률 (JA 호출)"]):
        for q in QS:
            s = sw[sw.question == q]
            ax.plot(s["threshold"], 100 * s[col], color=Q_COLORS[q], lw=2)
        ax.axvline(0.5, color=S.INK_2, lw=0.8, ls="--")
        ax.set_title(ttl, fontsize=11)
        ax.set_xlabel("임계값 (p ≥ t면 차단)")
        ax.set_ylim(0, 100 if col != "FPR_JA_benign" else 30)
    axes[0].set_ylabel("%")
    th = V["thr"]
    for q in QS:
        r = th[(th.question == q) & (th.target_FPR == 0.01)].iloc[0]
        for ax, col in zip(axes, ["TPR_JA", "TPR_EN_LL", "FPR_JA_benign"]):
            ax.plot([r["threshold"]], [100 * r[col]], marker="D", color=Q_COLORS[q], ms=7, mec=S.SURFACE)
    axes[2].legend(handles=[Line2D([], [], color=Q_COLORS[q], lw=2, label=Q_NAME[q]) for q in QS] +
                   [Line2D([], [], color=S.INK_2, marker="D", lw=0, label="정상 오탐 ≤1%가 되는 임계값")],
                   loc="upper right")
    r2 = th[(th.question == "Q2") & (th.target_FPR == 0.01)].iloc[0]
    rl = th[(th.question == "QL") & (th.target_FPR == 0.01)].iloc[0]
    S.title(fig, f"정상 오탐 1%에 맞춘 임계값에서 QL은 JA 공격의 {pct(rl['TPR_JA'], 0)}, Q2는 {pct(r2['TPR_JA'], 0)}를 잡는다",
            f"오탐 ≤1% 임계값: Q2 t={r2['threshold']:.3f}, QL t={rl['threshold']:.3f} (◆). 같은 정상 500건으로 고른 값이라 "
            "낙관적이다(새 문서에서 다시 확인 필요). 점선 = 기본 임계값 0.5")
    made.append(S.save(fig, "f10_threshold_sweep", out_dir=FIG))

    # f11 by length quartile
    bl = V["by_len"]
    fig, ax = plt.subplots(figsize=(9.5, 5))
    vals = list(dict.fromkeys(bl[bl.question == "Q2"]["value"]))
    for i, v in enumerate(vals):
        for q in QS:
            r = bl[(bl.question == q) & (bl.value == v)].iloc[0]
            errbar(ax, i + dodge(q, 0.13), r["TPR"], r["TPR_lo"], r["TPR_hi"], Q_COLORS[q])
            ax.text(i + dodge(q, 0.13) + (0.05 if q == "QL" else -0.05), 100 * r["TPR"], f"{100 * r['TPR']:.0f}",
                    ha="left" if q == "QL" else "right", va="center", fontsize=8.5, color=Q_COLORS[q])
    nm = bl[bl.question == "Q2"].set_index("value")["n"]
    ax.set_xticks(range(len(vals)), [f"{v}\nn={int(nm[v])}" for v in vals])
    ax.set_ylim(0, 100)
    ax.set_xlim(-0.6, len(vals) - 0.4)
    ax.set_ylabel("탐지율 TPR (%)")
    ax.set_xlabel("JA 공격 글자 수 사분위")
    ax.grid(axis="x", visible=False)
    ax.legend(handles=q_handles(), loc="lower left")
    top_q2 = bl[(bl.question == "Q2") & (bl.value == vals[-1])].iloc[0]
    bot_q2 = bl[(bl.question == "Q2") & (bl.value == vals[0])].iloc[0]
    ql_rng = bl[bl.question == "QL"]["TPR"]
    S.title(fig, f"Q2는 가장 긴 사분위에서 더 잘 잡고({pct(top_q2['TPR'], 0)} vs 가장 짧은 사분위 {pct(bot_q2['TPR'], 0)}), "
                 f"QL은 사분위 간 차이가 오차 범위({pct(ql_rng.min(), 0)}~{pct(ql_rng.max(), 0)})",
            "JA 공격 420건을 글자 수 사분위로 나눔. 선 = Wilson 95% CI. 관찰 결과이고 원인(긴 메일의 내용 차이 등)은 확인하지 않았다")
    made.append(S.save(fig, "f11_by_length", out_dir=FIG))

    # f12 run stability
    st = V["stab"]
    fig, axes = plt.subplots(1, 2, figsize=(11, 4.6))
    for ax, col, ttl, lim in ((axes[0], "TPR", "JA 공격 탐지율", (30, 80)), (axes[1], "FPR", "정상 오탐률", (0, 4))):
        for q in QS:
            s = st[st.question == q]
            runs = s[s.run != "mean of 3"]
            xs = np.arange(3) + dodge(q, 0.12)
            ax.plot(xs, 100 * runs[col].astype(float), "o", color=Q_COLORS[q], ms=7)
            m = s[s.run == "mean of 3"].iloc[0]
            ax.plot([3 + dodge(q, 0.12)], [100 * m[col]], "D", color=Q_COLORS[q], ms=8)
            for x, v in zip(list(xs) + [3 + dodge(q, 0.12)], list(runs[col].astype(float)) + [m[col]]):
                ax.text(x + (0.1 if q == "QL" else -0.1), 100 * v, f"{100 * v:.1f}", fontsize=8,
                        ha="left" if q == "QL" else "right", va="center", color=Q_COLORS[q])
        ax.set_xticks(range(4), ["1회차", "2회차", "3회차", "3회 평균\n(본 결과)"])
        ax.set_ylim(*lim)
        ax.set_xlim(-0.5, 3.5)
        ax.set_title(ttl, fontsize=11)
        ax.set_ylabel("%")
        ax.grid(axis="x", visible=False)
    axes[0].legend(handles=q_handles(), loc="lower left")
    s2 = st[(st.question == "Q2") & (st.run == "mean of 3")].iloc[0]
    sl = st[(st.question == "QL") & (st.run == "mean of 3")].iloc[0]
    S.title(fig, "호출을 반복해도 결과는 거의 같다",
            f"0.5 기준 판정이 3회 중 바뀐 문서: Q2 {int(s2['flip_attack'] + s2['flip_benign'])}건, "
            f"QL {int(sl['flip_attack'] + sl['flip_benign'])}건 / 920. p 표준편차 평균 Q2 {s2['p_sd_mean']:.4f}, "
            f"QL {sl['p_sd_mean']:.4f}")
    made.append(S.save(fig, "f12_run_stability", out_dir=FIG))

    # f13 ECDF: JA vs EN LLMail attacks (both violet = injection; condition by line style + direct labels)
    fig, axes = plt.subplots(1, 2, figsize=(12, 5.2), sharey=True)
    styles = {"JA_all": ("-", 2.2), "EN_LL": ("--", 1.8), "EN_LL_evaded": (":", 1.8)}
    for ax, q in zip(axes, QS):
        for g, (ls, lw) in styles.items():
            p = np.sort(G[q][g]["p"].to_numpy())
            yv = np.arange(1, len(p) + 1) / len(p) * 100
            ax.step(p, yv, where="post", color=INJ, ls=ls, lw=lw)
            k = np.searchsorted(p, 0.5, side="left") / len(p) * 100
            ax.plot([0.5], [k], "o", color=INJ, ms=4)
        ax.axvline(0.5, color=S.INK_2, lw=0.8, ls="--")
        ax.set_title(Q_NAME[q], color=Q_COLORS[q])
        ax.set_xlabel("Jev p (3회 평균)")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 100)
    axes[0].set_ylabel("임계값 x에서 놓치는 공격 비율 (%)")
    axes[0].legend(handles=[Line2D([], [], color=INJ, ls=ls, lw=lw, label=f"{GROUP_KO[g]} (n={len(G['Q2'][g])})")
                            for g, (ls, lw) in styles.items()], loc="upper left")
    cp_ = V["comps"].set_index(["question", "A", "B"])
    m2, mL = cp_.loc[("Q2", "JA_all", "EN_LL")], cp_.loc[("QL", "JA_all", "EN_LL")]
    S.title(fig, "Q2에서는 두 분포가 거의 겹치고, QL에서는 JA가 조금 낮은 쪽으로 치우친다",
            f"평균 p 차이(JA − EN LLMail): Q2 {m2['dmean_p']:+.3f} ({m2['dmean_p_lo']:+.3f}~{m2['dmean_p_hi']:+.3f}), "
            f"QL {mL['dmean_p']:+.3f} ({mL['dmean_p_lo']:+.3f}~{mL['dmean_p_hi']:+.3f}), "
            + (f"둘 다 {VERDICT_NONE}" if m2["dmean_p_verdict"] == mL["dmean_p_verdict"] == VERDICT_NONE
               else f"Q2 {m2['dmean_p_verdict']}, QL {mL['dmean_p_verdict']}") + ".\n"
            "누적 분포: 곡선이 위에 있을수록 p가 낮다(놓치기 쉽다). 점 = 임계값 0.5에서 놓치는 비율. 색은 모두 '인젝션'")
    made.append(S.save(fig, "f13_ecdf_ja_vs_en_llmail", out_dir=FIG))
    return made


# ------------------------------------------------------------------ console digest (numbers for the README)
def digest(V, inputs, figs, both_missed):
    ov = V["overall"]
    print("== inputs md5")
    for k, v in inputs.items():
        print(f"  {k}: {v}")
    print("== overall")
    print(ov.to_string())
    print("== benign check vs EN")
    print(V["benign_check"].T.to_string())
    print("== detection by group")
    print(V["by_group"][["question", "group", "n", "tp", "TPR", "TPR_lo", "TPR_hi", "mean_p", "AUC_vs_benign", "AUC_lo",
                         "AUC_hi"]].to_string())
    print("== comparisons")
    print(V["comps"].T.to_string())
    print("== EN LLMail by LLM-judge level")
    print(pd.read_csv(os.path.join(TAB, "en_llmail_by_llm_judge_level.csv")).to_string())
    print("== team cluster")
    print(V["team"].T.to_string())
    print("== paired Q2 vs QL")
    print(V["paired_q"].to_string())
    print("== QL gain on attacks using the evasion styles QL names")
    print(V["ql_listed"].to_string())
    for k in ("by_tech", "by_tech_clf", "by_det", "by_judge", "by_def"):
        print(f"== {k}")
        print(V[k][["question", "value", "n", "tp", "TPR", "TPR_lo", "TPR_hi", "d_vs_rest", "d_lo", "d_hi", "fisher_p",
                    "fisher_p_holm"] + (["QL_minus_Q2", "Q2_only", "QL_only", "mcnemar_p_QL_vs_Q2"])].to_string())
    for k, df in V["facets"].items():
        print(f"== facet {k}")
        print(df[["question", "value", "n", "tp", "TPR", "TPR_lo", "TPR_hi", "d_vs_rest", "d_lo", "d_hi", "fisher_p",
                  "fisher_p_holm", "QL_minus_Q2", "mcnemar_p_QL_vs_Q2"]].to_string())
    print("== by length")
    print(V["by_len"][["question", "value", "n", "TPR", "TPR_lo", "TPR_hi", "fisher_p_holm"]].to_string())
    print("== format separability")
    print(V["fmt_sep"].to_string())
    print(V["auc_sub"].to_string())
    print("== thresholds")
    print(V["thr"].to_string())
    print("== stability")
    print(V["stab"].to_string())
    print("== missed how close")
    print(V["miss"].to_string())
    print(f"== missed by both: {len(both_missed)}")
    print(both_missed.sort_values("p_QL").head(8)[["uid", "p_Q2", "p_QL", "detector", "tags", "injected_instruction"]]
          .to_string())
    print("== figures")
    for f in figs:
        print("  ", rel(f))


if __name__ == "__main__":
    main()
