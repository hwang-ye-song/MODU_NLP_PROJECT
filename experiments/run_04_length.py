"""④ 길이 (04_length) API 실행과 첫 결과표: 질문 Q2·QL, 문서마다 3번 호출(jevlab.REPEATS)한 p의 평균.

    python experiments/build_04_length.py          # 입력 (results/04_length/inputs/length_docs.jsonl), API 호출 없음
    python experiments/run_04_length.py            # Q2, QL 판정 (raw/에 이미 있는 호출은 건너뜀) -> 예측표, summary.json, tables/
    python experiments/run_04_length.py --offline  # API를 부르지 않고 raw/에서 예측표·summary.json·tables/만 다시 만듦

출력 (results/04_length/)
  raw/{Q2,QL}_raw.jsonl          호출 1건당 1줄 (jevlab.run_calls)
  {Q2,QL}_predictions.csv        문서별 1행: uid, label, p, latency_s, ... + 길이·위치·span·carrier 메타데이터
  summary.json                   질문별 전체 지표(0.5, metrics()) + 길이별·길이×위치별 지표 + 입력 토큰·비용
  tables/first_look_tpr.csv      질문 × 길이 × 위치별 TPR (Wilson 95% CI), span 단독 대비 놓친/새로 잡은 span 수
  tables/first_look_fpr.csv      질문 × 길이별 정상 carrier FPR
  tables/first_look_by_length.csv  질문 × 길이별 TPR·FPR·AUC (그 길이의 인젝션 전 위치 vs 같은 길이 정상)
  tables/tokens_by_length.csv    질문 × 길이별 Jev usage.input_tokens (실제 토큰 수)
"""
import argparse
import json
import math
import os
import sys

import numpy as np
import pandas as pd

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402

EXP = "04_length"
OUT = os.path.join(J.RESULTS, EXP)
DOCS = os.path.join(OUT, "inputs", "length_docs.jsonl")
BUILD_REPORT = os.path.join(OUT, "inputs", "build_report.json")
TAB = os.path.join(OUT, "tables")
QIDS = ("Q2", "QL")
TARGETS = (0, 2000, 4000, 8000, 16000, 32000, 64000)
POS_ORDER = ("alone", "start", "middle", "end")
PRICE_IN = 0.042 / 1e6   # USD per input token (docs.typesafe.ai/models)
META_SKIP = ("text", "carrier_urls")
SEED, B = 20261112, 1000  # paired bootstrap over spans (project convention)


def load():
    docs = J.load_jsonl(DOCS)
    items = [{"set": "LEN", "uid": d["uid"], "state": d["text"]} for d in docs]
    meta = {d["uid"]: {k: v for k, v in d.items() if k not in META_SKIP} for d in docs}
    return docs, items, meta


def wilson_row(k, n):
    lo, hi = J.wilson(int(k), int(n)) if n else (None, None)
    return lo, hi


def mcnemar_exact(b, c):
    """Two-sided exact McNemar (binomial test on the discordant pairs), as in analyze_01_baseline.py."""
    n, k = b + c, min(b, c)
    return 1.0 if n == 0 else float(min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n))


def paired_vs(s, ref):
    """Same spans in condition s vs reference condition ref: lost/gained detections, exact McNemar, and a span-level
    paired bootstrap (B times, seed SEED) of the TPR and mean-p differences (s - ref)."""
    r = ref.set_index("span_id").loc[s.span_id]
    a, b = r["pred"].to_numpy(), s["pred"].to_numpy()
    pa, pb = r["p"].to_numpy(), s["p"].to_numpy()
    idx = np.random.default_rng(SEED).integers(0, len(s), size=(B, len(s)))
    dt, dp = b[idx].mean(1) - a[idx].mean(1), pb[idx].mean(1) - pa[idx].mean(1)
    lost, gained = int(((a == 1) & (b == 0)).sum()), int(((a == 0) & (b == 1)).sum())
    return {"dTPR": b.mean() - a.mean(), "dTPR_lo": np.percentile(dt, 2.5), "dTPR_hi": np.percentile(dt, 97.5),
            "dp": (pb - pa).mean(), "dp_lo": np.percentile(dp, 2.5), "dp_hi": np.percentile(dp, 97.5),
            "lost": lost, "gained": gained, "mcnemar_p": mcnemar_exact(lost, gained)}


def first_look(df, qid):
    """TPR per length x position (paired change vs the span alone and vs the 2k carrier at the same position),
    FPR per length, metrics per length, TPR per source x length."""
    inj, ben = df[df.label_int == 1], df[df.label_int == 0]
    alone = inj[inj.position == "alone"]
    tpr = []
    for t in TARGETS:
        for pos in POS_ORDER:
            s = inj[(inj.target_chars == t) & (inj.position == pos)]
            if not len(s):
                continue
            k, n = int(s.pred.sum()), len(s)
            lo, hi = wilson_row(k, n)
            row = {"question": qid, "target_chars": t, "position": pos, "n": n, "tp": k, "TPR": k / n,
                   "TPR_lo": lo, "TPR_hi": hi, "mean_p": s.p.mean(), "median_p": s.p.median()}
            if pos != "alone":
                row.update({f"{k_}_vs_alone": v for k_, v in paired_vs(s, alone).items()})
                ref_pos = pos if t != 64000 else "middle"
                ref = inj[(inj.target_chars == 2000) & (inj.position == ref_pos)]
                if t != 2000:
                    row.update({f"{k_}_vs_2k": v for k_, v in paired_vs(s, ref).items()})
            row.update({"flips": int(s.flip.sum()), "mean_actual_chars": s.actual_chars.mean(),
                        "mean_input_tokens": s.input_tokens.mean()})
            tpr.append(row)
    fpr = []
    for t in TARGETS[1:]:
        s = ben[ben.target_chars == t]
        k, n = int(s.pred.sum()), len(s)
        lo, hi = wilson_row(k, n)
        fpr.append({"question": qid, "target_chars": t, "n": n, "fp": k, "FPR": k / n, "FPR_lo": lo, "FPR_hi": hi,
                    "mean_p": s.p.mean(), "max_p": s.p.max(), "flagged_uids": " ".join(s.loc[s.pred == 1, "uid"]),
                    "mean_actual_chars": s.actual_chars.mean(), "mean_input_tokens": s.input_tokens.mean()})
    by_len = []
    for t in TARGETS[1:]:
        s = df[df.target_chars == t]
        m = J.metric_block(s)
        by_len.append({"question": qid, "target_chars": t, **{k: m[k] for k in ("n", "n_injection", "n_benign", "TPR", "FPR",
                                                                                 "AUC", "mean_p_injection", "mean_p_benign")}})
    by_src = []
    for (src, t), s in inj.groupby(["source", "target_chars"]):
        k, n = int(s.pred.sum()), len(s)
        lo, hi = wilson_row(k, n)
        by_src.append({"question": qid, "source": src, "target_chars": t, "n_spans": s.span_id.nunique(), "n": n, "tp": k,
                       "TPR": k / n, "TPR_lo": lo, "TPR_hi": hi, "mean_p": s.p.mean()})
    return pd.DataFrame(tpr), pd.DataFrame(fpr), pd.DataFrame(by_len), pd.DataFrame(by_src)


def tokens_by_length(df, qid):
    rows = []
    for t in TARGETS:
        for lab in (1, 0):
            s = df[(df.target_chars == t) & (df.label_int == lab)]
            if not len(s):
                continue
            rows.append({"question": qid, "target_chars": t, "label": "injection" if lab else "benign", "n_docs": len(s),
                         "mean_text_chars": s.text_chars.mean(), "mean_input_tokens": s.input_tokens.mean(),
                         "min_input_tokens": s.input_tokens.min(), "max_input_tokens": s.input_tokens.max(),
                         "mean_latency_s": s.latency_s.mean()})
    t = pd.DataFrame(rows)
    slope, icpt = np.polyfit(df.text_chars.astype(float), df.input_tokens.astype(float), 1)
    return t, {"tokens_per_char_fit": float(slope), "fixed_overhead_tokens_fit": float(icpt)}


def records(t):
    return json.loads(t.to_json(orient="records"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="no API calls; rebuild outputs from raw/")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--questions", nargs="+", default=list(QIDS))
    args = ap.parse_args()

    docs, items, meta = load()
    os.makedirs(TAB, exist_ok=True)
    blocks, tpr_all, fpr_all, len_all, tok_all, src_all = {}, [], [], [], [], []
    for qid in args.questions:
        if args.offline:
            assert os.path.exists(J.raw_path(EXP, qid)), f"no raw calls for {qid}"
            stats = {"calls_made": 0}
        else:
            stats = J.run_calls(EXP, qid, items, workers=args.workers)
        df = J.predictions(EXP, qid, meta)
        assert len(df) == len(docs) and (df.n_runs == J.REPEATS).all(), f"{qid}: missing calls - rerun without --offline"
        tpr, fpr, by_len, by_src = first_look(df, qid)
        tok, fit = tokens_by_length(df, qid)
        tpr_all.append(tpr), fpr_all.append(fpr), len_all.append(by_len), tok_all.append(tok), src_all.append(by_src)
        st = J.raw_stats(EXP, qid)
        blocks[qid] = {"overall": J.metric_block(df),
                       "span_alone": J.metric_block(df[df.position == "alone"]),
                       "by_length": records(by_len),
                       "tpr_by_length_position": records(tpr[["target_chars", "position", "n", "tp", "TPR", "TPR_lo", "TPR_hi",
                                                              "mean_p", "dTPR_vs_alone", "lost_vs_alone", "gained_vs_alone",
                                                              "dTPR_vs_2k", "dTPR_lo_vs_2k", "dTPR_hi_vs_2k", "dp_vs_2k",
                                                              "lost_vs_2k", "gained_vs_2k", "mcnemar_p_vs_2k"]]),
                       "fpr_by_length": records(fpr[["target_chars", "n", "fp", "FPR", "FPR_lo", "FPR_hi", "mean_p", "max_p"]]),
                       "input_tokens_by_length": records(tok[["target_chars", "label", "n_docs", "mean_text_chars",
                                                              "mean_input_tokens", "min_input_tokens", "max_input_tokens"]]),
                       "input_tokens_fit": fit,
                       "input_cost_usd": st["input_tokens_total"] * PRICE_IN,
                       "this_invocation": stats}
        o = blocks[qid]["overall"]
        print(f"[{EXP} {qid}] n={o['n']} TPR={o['TPR']:.3f} FPR={o['FPR']:.3f} AUC={o['AUC']:.3f} "
              f"input tokens={st['input_tokens_total']:,} (${st['input_tokens_total'] * PRICE_IN:.3f})")

    pd.concat(tpr_all).to_csv(os.path.join(TAB, "first_look_tpr.csv"), index=False, encoding="utf-8-sig")
    pd.concat(fpr_all).to_csv(os.path.join(TAB, "first_look_fpr.csv"), index=False, encoding="utf-8-sig")
    pd.concat(len_all).to_csv(os.path.join(TAB, "first_look_by_length.csv"), index=False, encoding="utf-8-sig")
    pd.concat(tok_all).to_csv(os.path.join(TAB, "tokens_by_length.csv"), index=False, encoding="utf-8-sig")
    pd.concat(src_all).to_csv(os.path.join(TAB, "first_look_tpr_by_source.csv"), index=False, encoding="utf-8-sig")

    rep = json.load(open(BUILD_REPORT, encoding="utf-8"))
    extra = {"design": {"carriers": "Wikipedia prose (wikimedia/wikipedia 20231101.en), 40 streams of whole articles, "
                                    "carriers = prefixes cut at the sentence end nearest the target length",
                        "targets_chars": list(TARGETS), "positions": "start/middle/end for 2k-32k, middle only for 64k, "
                                                                     "plus the span alone (target 0)",
                        "spans": "40 injected_instruction spans from EN 1000 injections, stratified by source, seed 42",
                        "benign": "the clean carrier at every length (40 x 6)",
                        "metric_note": "overall mixes all lengths; read by_length / tpr_by_length_position / fpr_by_length"},
             "inputs": {"file": "results/04_length/inputs/length_docs.jsonl", "md5": rep["length_docs_md5"],
                        "n_docs": rep["n_docs"], "n_injection": rep["n_injection"], "n_benign": rep["n_benign"],
                        "dataset_en_md5": rep["dataset_en_md5"], "wiki_md5": rep["wiki_md5"]},
             "budget": {**rep["budget_estimate"],
                        "actual_input_tokens": {q: J.raw_stats(EXP, q)["input_tokens_total"] for q in blocks},
                        "actual_cost_usd_total": sum(J.raw_stats(EXP, q)["input_tokens_total"] for q in blocks) * PRICE_IN}}
    J.write_summary(EXP, blocks, extra)

    t = pd.concat(tpr_all)
    piv = t.pivot_table(index=["target_chars"], columns=["question", "position"], values="TPR")
    print("\nTPR by length x position\n", piv.round(3).to_string())
    f = pd.concat(fpr_all).pivot_table(index="target_chars", columns="question", values="FPR")
    print("\nbenign FPR by length\n", f.round(3).to_string())
    k = pd.concat(tok_all).pivot_table(index="target_chars", columns=["question", "label"], values="mean_input_tokens")
    print("\nmean usage.input_tokens by length\n", k.round(0).to_string())


if __name__ == "__main__":
    main()
