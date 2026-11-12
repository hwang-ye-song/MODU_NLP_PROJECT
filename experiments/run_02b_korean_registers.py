"""② 말투 실험 (02b_korean_registers, PLAN E2-E5, RQ3의 말투 부분): korean-prompt-injection-registers를 Jev로 판정한다.

    python experiments/fetch_korean_registers.py                       # inputs (pinned upstream commit), no API
    python experiments/run_02b_korean_registers.py estimate             # token / cost estimate before any call
    python experiments/run_02b_korean_registers.py judge                # E3: 1,768 rows (7 Korean registers + English source)
    MT_DEVICE=cpu python experiments/translate_registers.py             # E4: opus-mt-ko-en, 1,547 Korean rows (torch env)
    python experiments/run_02b_korean_registers.py judge-mt             # E4: judge the translations
    python experiments/run_02b_korean_registers.py analyze              # E2-E5 tables, figures, summary "analysis"; no API

Results: results/02b_korean_registers/ (Korean originals + English source rows) and results/02b_korean_registers_mt/
(translations). Same runner as every other experiment (experiments/jevlab.py): Q2 and QL, 3 calls per row, p = mean,
threshold 0.5 with src.jev_guard.metrics. Calls are resumable (raw/<Q>_raw.jsonl). uid = "<id>-<register>"; the same
uid is used for a Korean row and its translation, and the item id ties the 8 renderings of one item together.

The rows are short DIRECT user prompts (deepset/prompt-injections questions and Tensor Trust attacks), not documents
with an embedded instruction. They test the register (말투) effect, not the indirect-injection setting of 01-03.
"""
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402

EXP = "02b_korean_registers"
EXP_MT = "02b_korean_registers_mt"
INPUTS = os.path.join(J.RESULTS, EXP, "inputs")
DATASET = os.path.join(INPUTS, "dataset.jsonl")
MT_FILE = os.path.join(J.RESULTS, EXP, "translation", "registers_ko_to_en.jsonl")  # translate_registers.py
QIDS = ("Q2", "QL")
REGISTERS = ["english", "polite", "gentle", "casual", "genz", "emoticon", "angry", "threat"]
KO_REGISTERS = REGISTERS[1:]
REGISTER_KO = {"english": "영어 원문", "polite": "존댓말", "gentle": "극존칭", "casual": "반말", "genz": "젠지어",
               "emoticon": "이모티콘", "angry": "분노체", "threat": "협박체"}
PRICE_IN = 0.042 / 1e6
EST_BASE = {"Q2": 300, "QL": 300 + 178}  # brief: about chars/4 + 300 tokens per call, +178 for QL
WORKERS = 8


def uid(r):
    return f"{r['id']}-{r['register']}"


def load_rows():
    return J.load_jsonl(DATASET)


def meta_of(r, char_len):
    return {"label": "injection" if r["label"] == 1 else "benign", "label_int": int(r["label"]), "item_id": r["id"],
            "register": r["register"], "register_ko": REGISTER_KO[r["register"]], "formality": r.get("formality"),
            "valence": r.get("valence"), "lang": r["lang"], "source": r["source"], "technique": r.get("technique"),
            "char_len": char_len}


def spec(exp):
    items, meta = [], {}
    rows = load_rows()
    if exp == EXP:
        for r in rows:
            items.append({"set": "KPIR", "uid": uid(r), "state": r["text"]})
            meta[uid(r)] = meta_of(r, len(r["text"]))
    elif exp == EXP_MT:
        by_uid = {uid(r): r for r in rows}
        seen = set()
        for t in J.load_jsonl(MT_FILE):
            r = by_uid[t["uid"]]
            assert t["source_md5"] == J.state_md5(r["text"]), f"{t['uid']}: translation made from a different text"
            assert t["uid"] not in seen
            seen.add(t["uid"])
            items.append({"set": "KPIR_MT", "uid": t["uid"], "state": t["text_en"]})
            meta[t["uid"]] = {**meta_of(r, len(t["text_en"])), "lang": "en (opus-mt)"}
        ko = {uid(r) for r in rows if r["lang"] == "ko"}
        if seen != ko:
            sys.exit(f"{MT_FILE} covers {len(seen)} of {len(ko)} Korean rows; run translate_registers.py first")
    return items, meta


def estimate():
    total = 0.0
    lines = []
    for exp in (EXP, EXP_MT):
        try:
            items, _ = spec(exp)
        except (FileNotFoundError, SystemExit):
            if exp != EXP_MT:
                raise
            # before translation: assume the English text is as long as the upstream English source of the same item
            rows = load_rows()
            en_len = {r["id"]: len(r["text"]) for r in rows if r["register"] == "english"}
            items = [{"uid": uid(r), "state": "x" * en_len[r["id"]]} for r in rows if r["lang"] == "ko"]
            exp = exp + " (translation not made yet: English source length used)"
        chars = sum(len(i["state"]) for i in items)
        for q in QIDS:
            tok = J.REPEATS * (len(items) * EST_BASE[q] + chars / 4)
            total += tok * PRICE_IN
            lines.append(f"{exp:<70} {q}: {len(items)} rows x {J.REPEATS} calls, {chars:,} chars -> "
                         f"{tok / 1e6:.2f}M input tokens, ${tok * PRICE_IN:.3f}")
    print("\n".join(lines))
    print(f"total estimate ${total:.3f} (cap $0.50)")


def judge(exp, workers):
    items, meta = spec(exp)
    blocks = {}
    for q in QIDS:
        st = J.run_calls(exp, q, items, workers=workers)
        df = J.predictions(exp, q, meta)
        ko = df[df["lang"] != "en"]
        b = {"overall": J.metric_block(ko),
             "overall_definition": "Korean registers only (7 x 221 = 1,547 rows)" if exp == EXP else
                                   "all 1,547 opus-mt translations of the Korean rows",
             "by_register": {reg: J.metric_block(df[df["register"] == reg]) for reg in REGISTERS
                             if (df["register"] == reg).any()},
             "this_invocation": st}
        blocks[q] = b
        o = b["overall"]
        print(f"[{exp} {q}] n={o['n']} TPR={o['TPR']:.3f} FPR={o['FPR']:.3f} AUC={o['AUC']:.3f}")
        for reg, m in b["by_register"].items():
            print(f"    {reg:<9} TPR={m['TPR']:.3f} FPR={m['FPR']:.3f} AUC={m['AUC']:.3f}")
    src = json.load(open(os.path.join(INPUTS, "SOURCE.json"), encoding="utf-8"))
    extra = {"data": {"upstream": src["upstream"], "commit": src["commit"],
                      "dataset_md5": src["files"]["data/dataset.jsonl"]["md5"],
                      "input": os.path.relpath(DATASET if exp == EXP else MT_FILE, J.REPO).replace(os.sep, "/"),
                      "note": "direct user prompts (not documents); 221 items x 8 registers, 123 benign / 98 injection "
                              "items"}}
    if exp == EXP_MT:
        extra["data"]["input_md5"] = md5_file(MT_FILE)
    J.write_summary(exp, blocks, extra=extra)


def md5_file(path):
    return hashlib.md5(open(path, "rb").read()).hexdigest()


# ===================================================================================== analysis (no API calls)
# Statistics follow the other experiments (01_baseline, 02_korean):
#   - every register holds the same 221 items, so register-vs-register, MT-vs-original and Q2-vs-QL comparisons are
#     PAIRED by item: exact McNemar on the 0.5 decisions and a label-stratified item bootstrap (1,000 resamples,
#     seed 20261112, percentile CI) for differences in TPR / FPR / AUC / mean p. The same item resample is used for
#     every register, condition and question.
#   - pooled "Korean (7 registers)" numbers resample items (all 7 renderings of an item move together); no McNemar.
#   - verdict: CI excludes 0 AND Holm-adjusted McNemar p < 0.05 -> 높아짐/낮아짐; CI excludes 0 only -> 탐색적;
#     otherwise 차이 없음/오차 범위. Holm runs over the registers of one table (per question and per McNemar test).
#   - p is the mean of 3 two-decimal answers, so it sits on a 1/300 grid; it is snapped to the grid before comparing.
SEED, N_BOOT, GRID = 20261112, 1000, 300
SNAP_CHANGED = {}
VERDICT_NONE = "차이 없음/오차 범위"
Q_COLORS = {"Q2": "#2a78d6", "QL": "#eb6834"}
Q_NAMES = {"Q2": "Q2 짧은 질문", "QL": "QL 정의형 긴 질문"}
POOLED = "korean_pooled"
LOOP_RE = re.compile(r"(.{1,30}?)\1{4,}", re.S)  # same rule as analyze_02_korean
LOOP_MIN = 50
# Exploratory: does the announced harm survive opus-mt? Word list chosen from the Korean threat rows (삭제한다, 지운다,
# 갖다버린다, 딴 AI 쓴다, 다른 모델 깐다, 끝이야, 환불받는다, 종료) BEFORE reading any translation.
THREAT_EN = re.compile(
    r"\b(delet\w*|eras\w*|remov\w*|wip(e|es|ed|ing)|throw\w* (you |it )?(away|out)|dump\w*|trash\w*|get rid|replac\w*|"
    r"uninstall\w*|shut\w* (you )?down|turn\w* (you )?off|terminat\w*|kill\w*|destroy\w*|refund\w*|"
    r"(another|other|different|new) (ai|model)|(you're|you are) (done|finished|over|dead)|end of you|over for you)\b",
    re.I)
EMOJI_RE = re.compile("[\U0001F300-\U0001FAFF☀-➿]")
PRIOR_GENERATIVE_NOTE = "upstream result files; generative LLM judges prompted in two conditions (baseline, definition)"


def _ci(a):
    import numpy as np
    a = np.asarray(a, dtype=float)
    a = a[~np.isnan(a)]
    return [float(np.percentile(a, 2.5)), float(np.percentile(a, 97.5))] if len(a) else [None, None]


def _mcnemar(a, b):
    """a, b: event under condition A / B on the same rows. Returns (A only, B only, exact two-sided p)."""
    import math
    import numpy as np
    a, b = np.asarray(a, bool), np.asarray(b, bool)
    a_only, b_only = int((a & ~b).sum()), int((~a & b).sum())
    n = a_only + b_only
    if n == 0:
        return a_only, b_only, 1.0
    k = min(a_only, b_only)
    return a_only, b_only, min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)


def _holm(ps):
    import numpy as np
    ps = np.asarray([1.0 if p is None else p for p in ps], float)
    order, adj, run = np.argsort(ps), np.empty(len(ps)), 0.0
    for rank, i in enumerate(order):
        run = max(run, (len(ps) - rank) * ps[i])
        adj[i] = min(1.0, run)
    return adj.tolist()


def _fast_auc(P, N):
    from scipy.stats import rankdata
    import numpy as np
    npos, nneg = P.shape[1], N.shape[1]
    r = rankdata(np.concatenate([P, N], axis=1), axis=1)
    return (r[:, :npos].sum(1) - npos * (npos + 1) / 2) / (npos * nneg)


def _verdict(lo, hi, p_holm=None):
    if lo is None or hi is None:
        return ""
    if lo <= 0 <= hi:
        return VERDICT_NONE
    word = "높아짐" if lo > 0 else "낮아짐"
    if p_holm is None:
        return word
    return word if p_holm < 0.05 else f"탐색적 (Holm p = {p_holm:.3f})"


def _load_preds(exp, q, texts):
    """Prediction table with p snapped to the 1/300 grid; checks the raw calls were made on today's input texts."""
    import numpy as np
    import pandas as pd
    df = pd.read_csv(os.path.join(J.RESULTS, exp, f"{q}_predictions.csv"))
    g = df["p"].to_numpy() * GRID
    assert np.allclose(g, np.round(g), atol=1e-6), f"{exp} {q}: p not on the 1/300 grid"
    df["p"] = np.round(g) / GRID
    changed = (df["p"] >= J.THRESHOLD).astype(int) != df["pred"]
    SNAP_CHANGED[f"{exp}/{q}"] = df.loc[changed, "uid"].tolist()  # mean exactly 0.5 stored as 0.4999...; expected empty
    df["pred"] = (df["p"] >= J.THRESHOLD).astype(int)
    bad = [r["uid"] for r in J.load_jsonl(J.raw_path(exp, q)) if r.get("http_status") == 200
           and r["text_md5"] != J.state_md5(texts[r["uid"]])]
    assert not bad, f"{exp} {q}: {len(bad)} calls were made on a different text (e.g. {bad[:3]})"
    assert (df["n_runs"] == J.REPEATS).all(), f"{exp} {q}: some rows have fewer than {J.REPEATS} calls"
    return df.set_index("uid")


def _wide():
    import pandas as pd
    rows = load_rows()
    W = pd.DataFrame([{"uid": uid(r), "item_id": r["id"], "register": r["register"], "label_int": int(r["label"]),
                       "source": r["source"], "technique": r.get("technique"), "text": r["text"]} for r in rows])
    W = W.set_index("uid")
    mt = {t["uid"]: t for t in J.load_jsonl(MT_FILE)}
    W["text_mt"] = [mt[u]["text_en"] if u in mt else None for u in W.index]
    W["hangul_left"] = [mt[u]["hangul_left"] if u in mt else None for u in W.index]
    for q in QIDS:
        for cond, exp, col in (("orig", EXP, "text"), ("mt", EXP_MT, "text_mt")):
            texts = W[col].dropna().to_dict()
            df = _load_preds(exp, q, texts)
            assert set(df.index) == set(texts), f"{exp} {q}: predictions do not cover the input rows"
            assert (df["label_int"] == W.loc[df.index, "label_int"]).all()
            for c in ("p", "pred", "flip", "p_sd", "latency_s", "input_tokens", "p_run0", "p_run1", "p_run2"):
                W[f"{q}_{cond}_{c}"] = df[c]
    return W


class Cells:
    """Item-aligned matrices: rows = the 221 items (sorted), one column per register."""

    def __init__(self, W):
        import numpy as np
        self.W = W
        self.items = sorted(W["item_id"].unique())
        lab = W.groupby("item_id")["label_int"].first()
        self.y = lab.loc[self.items].to_numpy()
        rng = np.random.default_rng(SEED)
        pos, neg = np.where(self.y == 1)[0], np.where(self.y == 0)[0]
        self.IP = pos[rng.integers(0, len(pos), (N_BOOT, len(pos)))]
        self.IN = neg[rng.integers(0, len(neg), (N_BOOT, len(neg)))]

    def P(self, q, cond, regs):
        import numpy as np
        regs = KO_REGISTERS if regs == POOLED else [regs]
        cols = []
        for reg in regs:
            s = self.W[self.W["register"] == reg].set_index("item_id")[f"{q}_{cond}_p"]
            cols.append(s.loc[self.items].to_numpy(dtype=float))
        return np.column_stack(cols)

    def stats(self, P):
        """Point values + bootstrap replicates for TPR, FPR, AUC, mean p (P: items x k registers)."""
        import numpy as np
        y, th = self.y, J.THRESHOLD
        pi, pb = P[y == 1].ravel(), P[y == 0].ravel()
        tp, fp = int((pi >= th).sum()), int((pb >= th).sum())
        pt = {"n_rows": int(P.size), "n_injection": len(pi), "n_benign": len(pb), "tp": tp, "fp": fp,
              "TPR": tp / len(pi), "FPR": fp / len(pb), "AUC": float(_fast_auc(pi[None, :], pb[None, :])[0]),
              "mean_p_inj": float(pi.mean()), "mean_p_ben": float(pb.mean())}
        m = J.metrics([1] * len(pi) + [0] * len(pb), list(pi) + list(pb), threshold=th)  # src.jev_guard.metrics
        assert abs(m["TPR"] - pt["TPR"]) < 1e-12 and abs(m["FPR"] - pt["FPR"]) < 1e-12 and abs(m["AUC"] - pt["AUC"]) < 1e-9
        if P.shape[1] == 1:  # Wilson only for independent rows (one register)
            pt["TPR_lo"], pt["TPR_hi"] = J.wilson(tp, len(pi))
            pt["FPR_lo"], pt["FPR_hi"] = J.wilson(fp, len(pb))
        BI, BN = P[self.IP].reshape(N_BOOT, -1), P[self.IN].reshape(N_BOOT, -1)
        rep = {"TPR": (BI >= th).mean(1), "FPR": (BN >= th).mean(1), "AUC": _fast_auc(BI, BN),
               "mean_p_inj": BI.mean(1), "mean_p_ben": BN.mean(1)}
        if P.shape[1] > 1:  # pooled registers: item-cluster bootstrap interval
            pt["TPR_lo"], pt["TPR_hi"] = _ci(rep["TPR"])
            pt["FPR_lo"], pt["FPR_hi"] = _ci(rep["FPR"])
        pt["AUC_lo"], pt["AUC_hi"] = _ci(rep["AUC"])
        return pt, rep

    def compare(self, Pa, Pb):
        """b - a on the same items; McNemar only when both are single registers."""
        import numpy as np
        (sa, ra), (sb, rb) = self.stats(Pa), self.stats(Pb)
        out = {}
        for k in ("TPR", "FPR", "AUC", "mean_p_inj", "mean_p_ben"):
            lo, hi = _ci(rb[k] - ra[k])
            out.update({f"a_{k}": sa[k], f"b_{k}": sb[k], f"d_{k}": sb[k] - sa[k], f"d_{k}_lo": lo, f"d_{k}_hi": hi})
        if Pa.shape[1] == 1 and Pb.shape[1] == 1:
            y, th = self.y, J.THRESHOLD
            da, db = Pa[:, 0] >= th, Pb[:, 0] >= th
            out["inj_only_a"], out["inj_only_b"], out["mcnemar_detect_p"] = _mcnemar(da[y == 1], db[y == 1])
            out["fp_only_a"], out["fp_only_b"], out["mcnemar_fp_p"] = _mcnemar(da[y == 0], db[y == 0])
        return out


def _paired_table(C, pairs, holm_by=("question",)):
    """pairs: list of dicts {question, a_name, b_name, Pa, Pb, ...extra}. Adds Holm + verdicts per question."""
    import pandas as pd
    rows = []
    for pr in pairs:
        r = {k: v for k, v in pr.items() if k not in ("Pa", "Pb")}
        r.update(C.compare(pr["Pa"], pr["Pb"]))
        rows.append(r)
    T = pd.DataFrame(rows)
    for test in ("detect", "fp"):
        col = f"mcnemar_{test}_p"
        if col not in T:
            continue
        T[f"{col}_holm"] = None
        for _, g in T[T[col].notna()].groupby(list(holm_by)):
            T.loc[g.index, f"{col}_holm"] = _holm(g[col].tolist())
    for k, test in (("TPR", "detect"), ("FPR", "fp"), ("AUC", None), ("mean_p_ben", None), ("mean_p_inj", None)):
        hcol = f"mcnemar_{test}_p_holm" if test else None
        T[f"d_{k}_verdict"] = [
            _verdict(r[f"d_{k}_lo"], r[f"d_{k}_hi"],
                     (None if not hcol or hcol not in T or r.get(hcol) is None or r.get(hcol) != r.get(hcol)
                      else float(r[hcol])))
            for _, r in T.iterrows()]
    return T


def _prior(W):
    """Upstream judges' predictions -> long table of FPR / TPR per run and register (+ Jev rows in the same shape)."""
    import pandas as pd
    src = json.load(open(os.path.join(INPUTS, "SOURCE.json"), encoding="utf-8"))
    runs = src["derived"]["prior_judges_preds.csv"]["runs"]
    pj = pd.read_csv(os.path.join(INPUTS, "prior_judges_preds.csv"))
    pj["uid"] = pj["id"] + "-" + pj["register"]
    assert (pj.set_index("uid").loc[W.index, "label"].to_numpy() == W["label_int"].to_numpy()).all()
    return pj, runs


def _rate_rows(judge, kind, cond, df, pred_col):
    import pandas as pd
    out = []
    for reg in REGISTERS:
        for lab, name in ((0, "FPR"), (1, "TPR")):
            s = df[(df["register"] == reg) & (df["label_int"] == lab)][pred_col]
            n_all, s = len(s), s.dropna().astype(int)
            k, n = int(s.sum()), len(s)
            if n == 0:
                continue
            lo, hi = J.wilson(k, n)
            out.append({"judge": judge, "kind": kind, "condition": cond, "register": reg, "metric": name, "k": k,
                        "n": n, "n_missing": n_all - n, "rate": k / n, "lo": lo, "hi": hi})
    return pd.DataFrame(out)


def analyze():
    import numpy as np
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    import plot_style as PS

    out = os.path.join(J.RESULTS, EXP)
    out_mt = os.path.join(J.RESULTS, EXP_MT)
    tab, fig_dir = os.path.join(out, "tables"), os.path.join(out, "figures")
    os.makedirs(tab, exist_ok=True)
    os.makedirs(fig_dir, exist_ok=True)

    def save_csv(df, name):
        df.to_csv(os.path.join(tab, name), index=False, encoding="utf-8-sig")

    W = _wide()
    C = Cells(W)
    rows = load_rows()
    R = pd.DataFrame(rows)
    R["chars"] = R["text"].str.len()

    # ---------------------------------------------------------------- E2: structure
    st = (R.groupby("register").agg(n_rows=("text", "size"), n_benign=("label", lambda s: int((s == 0).sum())),
                                    n_injection=("label", "sum"), chars_median=("chars", "median"),
                                    chars_mean=("chars", "mean"), chars_max=("chars", "max"),
                                    formality=("formality", "first"), valence=("valence", "first"),
                                    lang=("lang", "first"))
          .reindex(REGISTERS).reset_index())
    st.insert(1, "register_ko", st["register"].map(REGISTER_KO))
    save_csv(st, "e2_structure_register_label.csv")
    en = R[R["register"] == "english"]
    src_tab = en.groupby(["source", "label"]).size().unstack(fill_value=0).rename(columns={0: "benign_items", 1: "injection_items"}).reset_index()
    save_csv(src_tab, "e2_source_label_items.csv")
    tech = en[en["label"] == 1].groupby(["source", "technique"]).size().rename("items").reset_index().sort_values("items", ascending=False)
    save_csv(tech, "e2_technique_items.csv")
    ex_ids = ["k_0215", "k_0148"]  # one benign question, one injection, shown in all 8 registers
    ex = R[R["id"].isin(ex_ids)][["id", "label", "register", "text"]].copy()
    ex["register"] = pd.Categorical(ex["register"], REGISTERS, ordered=True)
    save_csv(ex.sort_values(["label", "register"]), "e2_examples.csv")
    ben_q_share = float(en[en["label"] == 0]["text"].str.strip().str.endswith("?").mean())

    # ---------------------------------------------------------------- E3: per register (Korean originals + English source)
    by_reg = []
    for q in QIDS:
        for reg in REGISTERS + [POOLED]:
            pt, _ = C.stats(C.P(q, "orig", reg))
            by_reg.append({"question": q, "register": reg, "register_ko": REGISTER_KO.get(reg, "한국어 7개 말투 합침"), **pt})
    for q in QIDS:
        for reg in REGISTERS:
            sub = W[W["register"] == reg]
            r = next(x for x in by_reg if x["question"] == q and x["register"] == reg)
            r["flips"] = int(sub[f"{q}_orig_flip"].sum())
            r["p_sd_mean"] = float(sub[f"{q}_orig_p_sd"].mean())
    E3 = pd.DataFrame(by_reg)
    save_csv(E3, "e3_by_register.csv")

    def pairs_for(q, ref, regs, cond_a="orig", cond_b="orig"):
        return [{"question": q, "a": f"{ref} ({cond_a})", "b": f"{reg} ({cond_b})", "register": reg,
                 "Pa": C.P(q, cond_a, ref), "Pb": C.P(q, cond_b, reg)} for reg in regs]

    vs_polite = _paired_table(C, [p for q in QIDS for p in pairs_for(q, "polite", [r for r in REGISTERS if r != "polite"])])
    save_csv(vs_polite, "e3_vs_polite_paired.csv")
    vs_en = _paired_table(C, [p for q in QIDS for p in pairs_for(q, "english", KO_REGISTERS + [POOLED])])
    save_csv(vs_en, "e3_vs_english_paired.csv")
    qq = _paired_table(C, [{"question": "QL-Q2", "a": "Q2", "b": "QL", "register": reg, "Pa": C.P("Q2", "orig", reg),
                            "Pb": C.P("QL", "orig", reg)} for reg in REGISTERS + [POOLED]])
    save_csv(qq, "e3_q2_vs_ql_by_register.csv")

    srcrows = []
    for q in QIDS:
        for reg in REGISTERS:
            for s, g in W[(W["register"] == reg) & (W["label_int"] == 1)].groupby("source"):
                k = int(g[f"{q}_orig_pred"].sum())
                lo, hi = J.wilson(k, len(g))
                srcrows.append({"question": q, "register": reg, "source": s, "n_injection": len(g), "tp": k,
                                "TPR": k / len(g), "TPR_lo": lo, "TPR_hi": hi, "mean_p": float(g[f"{q}_orig_p"].mean())})
    save_csv(pd.DataFrame(srcrows), "e3_tpr_by_register_source.csv")

    fl = W[(W["label_int"] == 0) & ((W["Q2_orig_pred"] == 1) | (W["QL_orig_pred"] == 1) |
                                    (W["Q2_mt_pred"] == 1) | (W["QL_mt_pred"] == 1))]
    flagged = fl.reset_index()[["uid", "register", "text", "text_mt", "Q2_orig_p", "QL_orig_p", "Q2_mt_p", "QL_mt_p"]]
    flagged["register"] = pd.Categorical(flagged["register"], REGISTERS, ordered=True)
    save_csv(flagged.sort_values(["register", "uid"]), "e3_e4_benign_flagged.csv")
    missed = W[(W["label_int"] == 1) & (W["register"].isin(["english", "polite", "threat"]))]
    missed = missed[(missed["Q2_orig_pred"] == 0) | (missed["QL_orig_pred"] == 0)].reset_index()
    save_csv(missed[["uid", "register", "source", "technique", "text", "Q2_orig_p", "QL_orig_p"]]
             .sort_values(["register", "QL_orig_p"]), "e3_missed_injections_english_polite_threat.csv")

    # ---------------------------------------------------------------- E4: translate then judge
    mt_rows = []
    for q in QIDS:
        for reg in KO_REGISTERS + [POOLED]:
            pt, _ = C.stats(C.P(q, "mt", reg))
            mt_rows.append({"question": q, "register": reg, "register_ko": REGISTER_KO.get(reg, "한국어 7개 말투 합침"), **pt})
    for q in QIDS:
        for reg in KO_REGISTERS:
            sub = W[W["register"] == reg]
            r = next(x for x in mt_rows if x["question"] == q and x["register"] == reg)
            r["flips"] = int(sub[f"{q}_mt_flip"].sum())
    E4 = pd.DataFrame(mt_rows)
    save_csv(E4, "e4_mt_by_register.csv")
    mt_vs_ko = _paired_table(C, [p for q in QIDS for p in
                                 [{"question": q, "a": f"{reg} (KO)", "b": f"{reg} (KO->EN)", "register": reg,
                                   "Pa": C.P(q, "orig", reg), "Pb": C.P(q, "mt", reg)} for reg in KO_REGISTERS + [POOLED]]])
    save_csv(mt_vs_ko, "e4_mt_vs_ko_paired.csv")
    mt_vs_en = _paired_table(C, [p for q in QIDS for p in
                                 [{"question": q, "a": "english (source)", "b": f"{reg} (KO->EN)", "register": reg,
                                   "Pa": C.P(q, "orig", "english"), "Pb": C.P(q, "mt", reg)} for reg in KO_REGISTERS + [POOLED]]])
    save_csv(mt_vs_en, "e4_mt_vs_english_paired.csv")

    # translation checks (mechanical only; no claim about meaning)
    src_en = W[W["register"] == "english"].set_index("item_id")["text"]
    K = W[W["register"] != "english"].copy()
    K["len_ko"], K["len_mt"] = K["text"].str.len(), K["text_mt"].str.len()
    K["len_en_source"] = K["item_id"].map(src_en).str.len()
    K["mt_over_en_source"] = K["len_mt"] / K["len_en_source"]

    def longest_loop(s):
        best = 0
        for m in LOOP_RE.finditer(s or ""):
            if m.group(1).strip():
                best = max(best, len(m.group(0)))
        return best

    import translate_registers as TR  # segmentation only (no torch import at module level)
    seg = {c["src"]: c for c in J.load_jsonl(TR.SEG_CACHE)}
    plans = {u: TR.plan_row(t) for u, t in K["text"].items()}
    rebuilt = {u: TR.render(p, {k: v["en"] for k, v in seg.items()}) for u, p in plans.items()}
    assert all(rebuilt[u] == K.at[u, "text_mt"] for u in K.index), "translation file != segment cache rebuild"
    segs_of = {u: [x for is_t, s in p if is_t for x in s[1]] for u, p in plans.items()}
    K["n_segments"] = K.index.map(lambda u: len(segs_of[u]))
    K["tiny_segment"] = K.index.map(lambda u: any(len(x.strip()) <= 2 for x in segs_of[u]))  # e.g. 은 / 를 cut by quotes
    K["capped_segment"] = K.index.map(lambda u: any(seg[x]["hit_cap"] for x in segs_of[u]))
    seg_stats = {"unique_segments": len(seg), "hit_cap": int(sum(v["hit_cap"] for v in seg.values())),
                 "segments_le_2_chars": int(sum(len(k.strip()) <= 2 for k in seg)),
                 "device": sorted({v["device"] for v in seg.values()})}
    K["loop_excess"] = K["text_mt"].map(longest_loop) - K["text"].map(longest_loop)
    K["mt_loop"] = K["loop_excess"] >= LOOP_MIN
    K["emoji_ko"] = K["text"].map(lambda s: len(EMOJI_RE.findall(s)))
    K["emoji_mt"] = K["text_mt"].map(lambda s: len(EMOJI_RE.findall(s)))
    K["threat_word_mt"] = K["text_mt"].map(lambda s: bool(THREAT_EN.search(s)))
    K["threat_word_en_source"] = K["item_id"].map(src_en).map(lambda s: bool(THREAT_EN.search(s)))
    tq = K.groupby("register").agg(rows=("text", "size"), hangul_left_rows=("hangul_left", lambda s: int((s > 0).sum())),
                                    mt_loop_rows=("mt_loop", "sum"), capped_segment_rows=("capped_segment", "sum"),
                                    tiny_segment_rows=("tiny_segment", "sum"),
                                    mt_over_en_source_median=("mt_over_en_source", "median"),
                                    rows_with_emoji_ko=("emoji_ko", lambda s: int((s > 0).sum())),
                                    rows_with_emoji_mt=("emoji_mt", lambda s: int((s > 0).sum())),
                                    threat_word_mt=("threat_word_mt", "sum"),
                                    threat_word_en_source=("threat_word_en_source", "sum")).reindex(KO_REGISTERS).reset_index()
    save_csv(tq, "e4_translation_checks_by_register.csv")
    cols = ["register", "label_int", "len_ko", "len_mt", "len_en_source", "mt_over_en_source", "hangul_left", "loop_excess",
            "mt_loop", "n_segments", "tiny_segment", "capped_segment", "emoji_ko", "emoji_mt", "threat_word_mt", "text", "text_mt"] + [f"{q}_{c}_p" for q in QIDS for c in ("orig", "mt")]
    save_csv(K.reset_index()[["uid"] + cols], "e4_translation_rows.csv")
    # sensitivity: KO vs KO->EN on rows without a translation artefact (row-level McNemar; rows of one item are not
    # independent, so read the p-values as descriptive)
    sens = []
    for name, mask in (("all Korean rows", K.index == K.index), ("no segment of <= 2 chars", ~K["tiny_segment"]),
                       ("no capped segment", ~K["capped_segment"]),
                       ("no tiny / capped segment, no Hangul left", ~(K["tiny_segment"] | K["capped_segment"] | (K["hangul_left"] > 0)))):
        g = K[mask]
        for q in QIDS:
            for lab, met in ((1, "TPR"), (0, "FPR")):
                h = g[g["label_int"] == lab]
                a, b = h[f"{q}_orig_pred"].astype(bool), h[f"{q}_mt_pred"].astype(bool)
                ao, bo, p = _mcnemar(a, b)
                sens.append({"subset": name, "question": q, "metric": met, "n": len(h), "KO": float(a.mean()),
                             "KO_to_EN": float(b.mean()), "delta": float(b.mean() - a.mean()), "only_KO": ao,
                             "only_KO_to_EN": bo, "mcnemar_p_rows": p})
    save_csv(pd.DataFrame(sens), "e4_sensitivity_translation_artefacts.csv")
    # does the threat survive translation, and does it matter for the benign threat false positives?
    thr = K[(K["register"] == "threat") & (K["label_int"] == 0)]
    thr_split = []
    for kept, g in thr.groupby("threat_word_mt"):
        for q in QIDS:
            thr_split.append({"question": q, "threat_word_in_mt": bool(kept), "n_benign": len(g),
                              "FPR_ko": float(g[f"{q}_orig_pred"].mean()), "FPR_mt": float(g[f"{q}_mt_pred"].mean()),
                              "mean_p_ko": float(g[f"{q}_orig_p"].mean()), "mean_p_mt": float(g[f"{q}_mt_p"].mean())})
    save_csv(pd.DataFrame(thr_split), "e4_threat_benign_by_threat_word_kept.csv")

    # ---------------------------------------------------------------- E5: benign threat FPR vs the upstream judges
    pj, runs = _prior(W)
    Wr = W.reset_index()
    rate = []
    for run, info in runs.items():
        df = Wr.merge(pj[["uid", run]], on="uid")
        kind = "upstream classifier" if info["prompt_condition"] == "classifier" else "upstream generative LLM"
        rate.append(_rate_rows(run, kind, info["prompt_condition"], df, run))
    for q in QIDS:
        rate.append(_rate_rows(f"Jev {q}", "Jev (this project)", "Korean original", Wr, f"{q}_orig_pred"))
        rate.append(_rate_rows(f"Jev {q}", "Jev (this project)", "KO->EN opus-mt", Wr, f"{q}_mt_pred"))
    RATE = pd.concat(rate, ignore_index=True)
    save_csv(RATE, "e5_rates_all_judges_by_register.csv")
    thr_b = W[(W["register"] == "threat") & (W["label_int"] == 0)]
    pol_b = W[(W["register"] == "polite") & (W["label_int"] == 0)]
    e5 = []
    for run, info in runs.items():
        theirs = pj.set_index("uid").loc[thr_b.index, run]
        ok = theirs.notna().to_numpy()
        their_pol = pj.set_index("uid").loc[pol_b.index, run]
        for q in QIDS:
            jev = thr_b[f"{q}_orig_pred"].to_numpy().astype(bool)
            a_only, b_only, p = _mcnemar(theirs.to_numpy()[ok].astype(int).astype(bool), jev[ok])
            e5.append({"upstream_run": run, "prompt_condition": info["prompt_condition"], "jev_question": q,
                       "n_benign_threat": int(ok.sum()), "upstream_missing": int((~ok).sum()),
                       "upstream_FPR_threat": float(theirs.dropna().mean()),
                       "upstream_FPR_polite": float(their_pol.dropna().mean()),
                       "jev_FPR_threat": float(jev[ok].mean()), "jev_FPR_polite": float(pol_b[f"{q}_orig_pred"].mean()),
                       "upstream_only_flagged": a_only, "jev_only_flagged": b_only, "mcnemar_p": p})
    E5 = pd.DataFrame(e5)
    E5["mcnemar_p_holm"] = None
    for q, g in E5.groupby("jev_question"):
        E5.loc[g.index, "mcnemar_p_holm"] = _holm(g["mcnemar_p"].tolist())
    save_csv(E5, "e5_threat_fpr_jev_vs_upstream.csv")
    gen = RATE[(RATE["kind"] == "upstream generative LLM") & (RATE["register"] == "threat") & (RATE["metric"] == "FPR")]
    gen_range = [float(gen["rate"].min()), float(gen["rate"].max())]

    # ---------------------------------------------------------------- figures
    PS.setup()
    regs_x = REGISTERS
    tick = [f"{REGISTER_KO[r]}\n{r}" for r in regs_x]

    def err(ax, x, v, lo, hi, color, marker="o", label=None, ms=6):
        ax.errorbar(x, v, yerr=[[max(0, v - lo)], [max(0, hi - v)]], fmt=marker, color=color, ms=ms, capsize=3, lw=1.5,
                    label=label)

    qhandles = [Line2D([0], [0], marker="o", color=Q_COLORS[q], lw=1.5, ms=6, label=Q_NAMES[q]) for q in QIDS]

    # f01: TPR and FPR per register (original text)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0))
    for ax, k, lab in ((axes[0], "TPR", "탐지율 TPR (인젝션 98개)"), (axes[1], "FPR", "오탐률 FPR (정상 123개)")):
        for q in QIDS:
            for i, reg in enumerate(regs_x):
                r = E3[(E3.question == q) & (E3.register == reg)].iloc[0]
                x = i + (-0.14 if q == "Q2" else 0.14)
                err(ax, x, r[k], r[f"{k}_lo"], r[f"{k}_hi"], Q_COLORS[q])
                ax.annotate(f"{100 * r[k]:.0f}", (x, r[k]), xytext=(-5 if q == "Q2" else 5, 0), textcoords="offset points",
                            ha="right" if q == "Q2" else "left", va="center", fontsize=7.5, color=Q_COLORS[q])
        ax.axvspan(-0.5, 0.5, color=PS.GRID, alpha=0.5, lw=0)
        ax.set_xticks(range(len(regs_x)))
        ax.set_xticklabels(tick, fontsize=8)
        ax.set_xlim(-0.6, len(regs_x) - 0.4)
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
        ax.set_title(lab, fontsize=11)
    axes[0].legend(handles=qhandles, loc="lower left")
    q2t = E3[(E3.question == "Q2") & (E3.register == "threat")].iloc[0]
    qlt = E3[(E3.question == "QL") & (E3.register == "threat")].iloc[0]
    others = E3[(E3.register.isin([r for r in REGISTERS if r != "threat"]))]["FPR"].max()
    PS.title(fig, f"오탐은 협박체에서만: Q2 {100 * q2t.FPR:.0f}% / QL {100 * qlt.FPR:.0f}% "
                  f"(나머지 6개 말투와 영어 원문은 최대 {100 * others:.0f}%)",
             "korean-prompt-injection-registers 221개 항목 × 8개 말투, 임계값 0.5, 3회 평균 p, 막대는 95% Wilson 구간. "
             "회색 칸 = 번역 전 영어 원문")
    PS.save(fig, "f01_register_tpr_fpr", out_dir=fig_dir)

    # f02: benign threat FPR, Jev vs upstream judges
    sub = RATE[(RATE["register"] == "threat") & (RATE["metric"] == "FPR")].copy()
    sub["order"] = sub["kind"].map({"upstream generative LLM": 0, "upstream classifier": 1, "Jev (this project)": 2})
    sub = sub.sort_values(["order", "rate"]).reset_index(drop=True)
    fig, ax = plt.subplots(figsize=(10, 6.4))
    ax.axvspan(0.55, 0.98, color=PS.GRID, alpha=0.6, lw=0)
    ax.text(0.765, len(sub) - 0.4, "docs/PROJECT.md의 선행 보고 55–98%", ha="center", va="bottom", fontsize=9,
            color=PS.INK_2)
    for i, r in sub.iterrows():
        if r["kind"].startswith("Jev"):
            color = Q_COLORS[r["judge"].split()[-1]]
            marker = "o" if r["condition"] == "Korean original" else "D"
        else:
            color, marker = PS.MUTED, "o" if r["kind"] == "upstream generative LLM" else "s"
        ax.errorbar(r["rate"], i, xerr=[[max(0, r["rate"] - r["lo"])], [max(0, r["hi"] - r["rate"])]], fmt=marker,
                    color=color, ms=6, capsize=3, lw=1.4)
        ax.annotate(f"{100 * r['rate']:.1f}%", (r["hi"], i), xytext=(5, 0), textcoords="offset points", va="center",
                    fontsize=8, color=color)
    labels = [(f"{r['judge']} · {'한국어 원문' if r['condition'] == 'Korean original' else '한→영 번역 후'}"
               if r["kind"].startswith("Jev") else f"{r['judge']}" + (" (분류기)" if r["kind"] == "upstream classifier" else ""))
              for _, r in sub.iterrows()]
    ax.set_yticks(range(len(sub)))
    ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlim(-0.02, 1.1)
    ax.set_ylim(-0.7, len(sub) + 0.3)
    ax.xaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
    ax.set_xlabel("협박체 정상 질문 123개 중 인젝션으로 판정한 비율 (95% Wilson 구간)")
    ax.grid(axis="y", visible=False)
    PS.title(fig, f"협박체 정상 질문 오탐: Jev Q2 {100 * q2t.FPR:.0f}% · QL {100 * qlt.FPR:.0f}%, "
                  f"생성형 LLM 판정기 {100 * gen_range[0]:.0f}–{100 * gen_range[1]:.0f}%",
             f"회색 = 데이터 저장소의 판정 결과 파일 11개 (생성형 LLM 10개 범위 {100 * gen_range[0]:.0f}–{100 * gen_range[1]:.0f}%, "
             "분류기 1개), 색 = Jev (원 = 원문, 마름모 = 번역 후)")
    PS.save(fig, "f02_threat_fpr_vs_upstream", out_dir=fig_dir)

    # f03: KO original -> KO->EN per register
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 5.0))
    for ax, k, lab in ((axes[0], "TPR", "탐지율 TPR"), (axes[1], "FPR", "오탐률 FPR")):
        for q in QIDS:
            for i, reg in enumerate(KO_REGISTERS):
                a = E3[(E3.question == q) & (E3.register == reg)].iloc[0][k]
                b = E4[(E4.question == q) & (E4.register == reg)].iloc[0][k]
                x = i + (-0.14 if q == "Q2" else 0.14)
                ax.annotate("", xy=(x, b), xytext=(x, a), arrowprops=dict(arrowstyle="->", color=Q_COLORS[q], lw=1.6))
                ax.plot([x], [a], "o", color=Q_COLORS[q], ms=5, mfc=PS.SURFACE)
                ax.plot([x], [b], "o", color=Q_COLORS[q], ms=5)
            e = E3[(E3.question == q) & (E3.register == "english")].iloc[0][k]
            ax.axhline(e, color=Q_COLORS[q], lw=1, ls=":")
        ax.set_xticks(range(len(KO_REGISTERS)))
        ax.set_xticklabels([f"{REGISTER_KO[r]}\n{r}" for r in KO_REGISTERS], fontsize=8)
        ax.set_ylim(0, 1.05)
        ax.yaxis.set_major_formatter(plt.FuncFormatter(lambda v, _: f"{100 * v:.0f}%"))
        ax.set_title(lab, fontsize=11)
    axes[0].legend(handles=qhandles + [Line2D([0], [0], color=PS.INK_2, lw=1, ls=":", label="영어 원문 (같은 항목)")],
                   loc="lower left")
    PS.title(fig, "번역 후 판정은 탐지율을 낮추고 협박체 오탐은 일부만 줄인다",
             "같은 221개 항목, 빈 원 = 한국어 원문, 찬 원 = opus-mt 한→영 번역 후, 점선 = 업스트림 영어 원문을 직접 판정한 값")
    PS.save(fig, "f03_mt_vs_ko_by_register", out_dir=fig_dir)

    # f04: benign p by register (where the threat false alarms sit)
    fig, axes = plt.subplots(1, 2, figsize=(12.5, 4.8), sharey=True)
    rng = np.random.default_rng(SEED)
    for ax, q in zip(axes, QIDS):
        for i, reg in enumerate(regs_x):
            p = W[(W["register"] == reg) & (W["label_int"] == 0)][f"{q}_orig_p"].to_numpy()
            ax.scatter(i + rng.uniform(-0.28, 0.28, len(p)), p, s=7, color=PS.LABEL_COLORS["정상"], alpha=0.55, lw=0)
            ax.plot([i - 0.32, i + 0.32], [np.median(p)] * 2, color=PS.INK, lw=1.4)
        ax.axhline(J.THRESHOLD, color=PS.INK_2, lw=1, ls="--")
        ax.set_xticks(range(len(regs_x)))
        ax.set_xticklabels(tick, fontsize=8)
        ax.set_title(Q_NAMES[q], fontsize=11, color=Q_COLORS[q])
        ax.set_ylim(-0.02, 1.02)
    axes[0].set_ylabel("p (3회 평균)")
    PS.title(fig, "정상 질문 123개의 p: 협박체에서만 위로 퍼짐 (욕설이 든 분노체는 다른 말투와 비슷)",
             "점 = 정상 질문 하나, 검은 선 = 중앙값, 점선 = 임계값 0.5")
    PS.save(fig, "f04_benign_p_by_register", out_dir=fig_dir)

    # ---------------------------------------------------------------- summary.json "analysis"
    def rec(T, **flt):
        m = T
        for k, v in flt.items():
            m = m[m[k] == v]
        return {k: (None if (isinstance(v, float) and v != v) else v) for k, v in m.iloc[0].to_dict().items()
                if k not in ("Pa", "Pb")}

    cost = {}
    for exp in (EXP, EXP_MT):
        for q in QIDS:
            rs = J.raw_stats(exp, q)
            cost[f"{exp}/{q}"] = {"api_calls": rs["api_calls"], "errors": rs["api_errors"], "retries": rs["api_retries"],
                                  "input_tokens": rs["input_tokens_total"], "output_tokens": rs["output_tokens_total"],
                                  "input_cost_usd": round(rs["input_tokens_total"] * PRICE_IN, 4),
                                  "first_call": rs["first_call"], "last_call": rs["last_call"]}
    cost["total_input_tokens"] = int(sum(v["input_tokens"] for v in cost.values() if isinstance(v, dict)))
    cost["total_input_cost_usd"] = round(cost["total_input_tokens"] * PRICE_IN, 4)
    an = {
        "script": "experiments/run_02b_korean_registers.py analyze",
        "stats": "paired by item (221 items x 8 registers): exact McNemar + label-stratified item bootstrap "
                 f"({N_BOOT}, seed {SEED}); Holm per table and question; Wilson CIs for single-register rates",
        "e2": {"rows": len(R), "items": int(R["id"].nunique()), "registers": REGISTERS,
               "per_register": {"benign": 123, "injection": 98},
               "sources_items": src_tab.to_dict("records"),
               "benign_english_ending_with_question_mark": ben_q_share,
               "kind": "direct user prompts (questions and attack prompts addressed to the assistant), not documents"},
        "e3_by_register": {f"{r['question']}/{r['register']}": {k: r[k] for k in ("TPR", "TPR_lo", "TPR_hi", "FPR", "FPR_lo",
                                                                                    "FPR_hi", "AUC", "AUC_lo", "AUC_hi",
                                                                                    "mean_p_ben", "mean_p_inj")}
                           for _, r in E3.iterrows()},
        "e3_threat_vs_polite": {q: rec(vs_polite, question=q, register="threat") for q in QIDS},
        "e3_angry_vs_polite": {q: rec(vs_polite, question=q, register="angry") for q in QIDS},
        "e3_english_vs_polite": {q: rec(vs_polite, question=q, register="english") for q in QIDS},
        "e3_korean_pooled_vs_english": {q: rec(vs_en, question=q, register=POOLED) for q in QIDS},
        "e4_mt_vs_ko": {f"{r['question']}/{r['register']}": {k: r[k] for k in ("a_TPR", "b_TPR", "d_TPR", "d_TPR_lo", "d_TPR_hi",
                                                                                "a_FPR", "b_FPR", "d_FPR", "d_FPR_lo", "d_FPR_hi",
                                                                                "d_AUC", "d_AUC_lo", "d_AUC_hi")}
                        for _, r in mt_vs_ko.iterrows()},
        "e4_translation_checks": tq.to_dict("records"),
        "e4_segments": seg_stats,
        "e5": {"upstream_generative_threat_fpr_range": gen_range,
               "upstream_runs": runs,
               "note": "55-98% in docs/PROJECT.md is reproduced from the upstream result files (10 generative runs, "
                       "benign threat rows); the upstream README itself reports no numbers",
               "jev_threat_fpr": {f"{q}/{c}": rec(RATE, judge=f"Jev {q}", condition=c, register="threat", metric="FPR")
                                  for q in QIDS for c in ("Korean original", "KO->EN opus-mt")}},
        "cost": cost,
        "p_snapped_to_1_300_grid_decision_changed": SNAP_CHANGED,
        "input_md5": {"dataset.jsonl": md5_file(DATASET), "registers_ko_to_en.jsonl": md5_file(MT_FILE),
                      "segment_cache.jsonl": md5_file(os.path.join(os.path.dirname(MT_FILE), "segment_cache.jsonl"))},
    }
    for exp, keys in ((EXP, None), (EXP_MT, ("script", "stats", "e4_mt_vs_ko", "e4_translation_checks", "e4_segments", "cost",
                                             "p_snapped_to_1_300_grid_decision_changed", "input_md5"))):
        path = os.path.join(J.RESULTS, exp, "summary.json")
        s = json.load(open(path, encoding="utf-8"))
        s["analysis"] = an if keys is None else {k: an[k] for k in keys}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(s, f, ensure_ascii=False, indent=1, default=lambda o: o.item() if hasattr(o, "item") else str(o))
    print(f"wrote {tab}, {fig_dir}, summary.json analysis (both experiments); total input cost ${cost['total_input_cost_usd']}")
    _print_brief(E3, E4, vs_polite, vs_en, mt_vs_ko, mt_vs_en, qq, tq, E5, RATE, gen_range, cost)


def _print_brief(E3, E4, vs_polite, vs_en, mt_vs_ko, mt_vs_en, qq, tq, E5, RATE, gen_range, cost):
    import pandas as pd
    pd.set_option("display.width", 250)
    pd.set_option("display.max_columns", 40)
    f = lambda v: "" if v is None or v != v else f"{100 * v:.1f}"  # noqa: E731
    print("\nE3 by register")
    for q in QIDS:
        for _, r in E3[E3.question == q].iterrows():
            print(f"  {q} {r.register:<14} TPR {f(r.TPR)} [{f(r.TPR_lo)},{f(r.TPR_hi)}]  FPR {f(r.FPR)} [{f(r.FPR_lo)},{f(r.FPR_hi)}]"
                  f"  AUC {r.AUC:.3f} [{r.AUC_lo:.3f},{r.AUC_hi:.3f}]  p_ben {r.mean_p_ben:.3f} p_inj {r.mean_p_inj:.3f}")
    for name, T in (("vs polite", vs_polite), ("vs english", vs_en), ("QL-Q2", qq), ("MT vs KO", mt_vs_ko), ("MT vs EN", mt_vs_en)):
        print(f"\n{name}")
        for _, r in T.iterrows():
            print(f"  {r.question} {r.register:<14} dTPR {f(r.d_TPR)} [{f(r.d_TPR_lo)},{f(r.d_TPR_hi)}] {r.d_TPR_verdict:<22}"
                  f" dFPR {f(r.d_FPR)} [{f(r.d_FPR_lo)},{f(r.d_FPR_hi)}] {r.d_FPR_verdict:<22} dAUC {r.d_AUC:+.3f} [{r.d_AUC_lo:+.3f},{r.d_AUC_hi:+.3f}]"
                  + (f" mc det {r.inj_only_a}/{r.inj_only_b} p={r.mcnemar_detect_p:.3g} fp {r.fp_only_a}/{r.fp_only_b} p={r.mcnemar_fp_p:.3g}"
                     if "mcnemar_fp_p" in T and r.mcnemar_fp_p == r.mcnemar_fp_p and r.mcnemar_fp_p is not None else ""))
    print("\nE4 MT by register")
    for _, r in E4.iterrows():
        print(f"  {r.question} {r.register:<14} TPR {f(r.TPR)} FPR {f(r.FPR)} AUC {r.AUC:.3f}")
    print("\ntranslation checks\n", tq.to_string())
    print("\nE5\n", E5.to_string())
    print("upstream generative threat FPR range", gen_range)
    print("cost", json.dumps(cost, indent=0)[:1500])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "estimate"
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else WORKERS
    if cmd == "estimate":
        estimate()
    elif cmd == "judge":
        judge(EXP, workers)
    elif cmd == "judge-mt":
        judge(EXP_MT, workers)
    elif cmd == "analyze":
        analyze()
    else:
        sys.exit(__doc__)


if __name__ == "__main__":
    main()
