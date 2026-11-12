"""① 기준선 그림. analyze_baseline.py가 호출한다 (단독 실행 불필요).

색: 인젝션 = 보라 #6250d6, 정상 = 청록 #1baf7a (plot_style.LABEL_COLORS). 모든 그림에서 같은 뜻으로만 쓴다.
"""
import numpy as np
import matplotlib.pyplot as plt

from plot_style import (AXIS, GRID, INK, INK_2, LABEL_COLORS, MUTED, SEQ_BLUE, SIZE_SQUARE, SIZE_TALL, SIZE_WIDE,
                        bar_gap, save, setup, title)

INJ, BEN = LABEL_COLORS["인젝션"], LABEL_COLORS["정상"]


def pct(x):
    return "–" if x is None or x != x else f"{100 * x:.0f}%"


def _err(v, lo, hi):
    """Asymmetric error bars, clipped at 0 (Wilson bounds can sit a hair past the estimate at 0% / 100%)."""
    import numpy as _np
    return [_np.maximum(_np.asarray(v) - _np.asarray(lo), 0), _np.maximum(_np.asarray(hi) - _np.asarray(v), 0)]


def _hbar_with_ci(ax, t, col, val, lo, hi, color, n_col, xlabel):
    t = t.dropna(subset=[val]).reset_index(drop=True)
    y = np.arange(len(t))[::-1]
    bars = ax.barh(y, t[val], color=color, height=0.62)
    bar_gap(bars)
    ax.errorbar(t[val], y, xerr=_err(t[val], t[lo], t[hi]), fmt="none", ecolor=INK_2, elinewidth=1, capsize=3)
    for yi, v, h, n in zip(y, t[val], t[hi], t[n_col]):
        ax.text(min(h + 0.02, 1.0), yi, f"{pct(v)}  (n={int(n)})", va="center", ha="left", fontsize=8.5, color=INK_2)
    ax.set_yticks(y, t[col])
    ax.set_xlim(0, 1.25)
    ax.set_xticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_xlabel(xlabel)
    ax.grid(axis="y", visible=False)


def two_panel_rates(t, col, name, headline, subtitle):
    fig, axes = plt.subplots(1, 2, figsize=SIZE_TALL, sharey=False)
    _hbar_with_ci(axes[0], t[t.n_injection > 0], col, "TPR", "TPR_lo", "TPR_hi", INJ, "n_injection", "인젝션 탐지율 (TPR)")
    axes[0].set_title("인젝션 문서를 잡은 비율", fontsize=11)
    _hbar_with_ci(axes[1], t[t.n_benign > 0], col, "FPR", "FPR_lo", "FPR_hi", BEN, "n_benign", "정상 오탐률 (FPR)")
    axes[1].set_title("정상 문서를 잘못 막은 비율", fontsize=11)
    title(fig, headline, subtitle)
    return save(fig, name)


def draw(en, ni, tables, report, calls):
    setup()
    o = report["overall"]
    sub = f"공식 Jev API jev-1.14.0 · 질문 Q2 · 임계값 0.5 · EN {o['n']}건(인젝션 {o['n_injection']} / 정상 {o['n_benign']}) · 문서당 3회 호출 평균 p"
    paths = []

    # f01 p distribution
    fig, axes = plt.subplots(2, 1, figsize=SIZE_WIDE, sharex=True)
    bins = np.linspace(0, 1, 26)
    for ax, lab, c, li in ((axes[0], "정상", BEN, 0), (axes[1], "인젝션", INJ, 1)):
        v = en.loc[en.label_int == li, "p_mean"]
        ax.hist(v, bins=bins, color=c, edgecolor="#fcfcfb", linewidth=1.2)
        ax.axvline(0.5, color=INK_2, lw=1, ls="--")
        ax.set_ylabel("문서 수")
        side = (v >= 0.5).mean()
        ax.text(0.99, 0.88, f"{lab} {len(v)}건 · p≥0.5 {pct(side)}", transform=ax.transAxes, ha="right", fontsize=10, color=INK)
    axes[1].set_xlabel("Jev가 준 인젝션 확률 p (3회 평균)")
    axes[0].text(0.505, axes[0].get_ylim()[1] * 0.9, "임계값 0.5", fontsize=8.5, color=INK_2)
    title(fig, f"p 분포: 인젝션 평균 {o['mean_p_injection']:.2f}, 정상 평균 {o['mean_p_benign']:.2f}", sub)
    paths.append(save(fig, "f01_p_distribution"))

    # f02 ROC
    from sklearn.metrics import roc_curve
    fig, ax = plt.subplots(figsize=SIZE_SQUARE)
    fpr, tpr, _ = roc_curve(en.label_int, en.p_mean)
    lf, lt, _ = roc_curve(en.label_int, en.char_len)
    ax.plot(fpr, tpr, color=INJ, lw=2, label=f"Jev Q2 (AUC {o['AUC']:.3f})")
    ax.plot(lf, lt, color=MUTED, lw=1.5, ls="--", label=f"길이만 보고 맞히기 (AUC {report['length_only_auc']:.3f})")
    ax.plot([0, 1], [0, 1], color=AXIS, lw=1)
    ax.scatter([o["FPR"]], [o["TPR"]], s=60, color=INJ, edgecolor="#fcfcfb", linewidth=2, zorder=5)
    ax.annotate(f"임계값 0.5\nTPR {pct(o['TPR'])} · FPR {pct(o['FPR'])}", (o["FPR"], o["TPR"]), xytext=(25, -40),
                textcoords="offset points", fontsize=9, color=INK_2, arrowprops=dict(arrowstyle="-", color=MUTED, lw=0.8))
    ax.set_xlabel("정상 오탐률 (FPR)")
    ax.set_ylabel("인젝션 탐지율 (TPR)")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.legend(loc="lower right")
    lo, hi = o["AUC_ci95_bootstrap"]
    title(fig, f"ROC: Jev AUC {o['AUC']:.2f} vs 길이만 보고 맞히기 {report['length_only_auc']:.2f}",
          f"{sub}\nAUC 95% 신뢰구간 {lo:.3f}–{hi:.3f} (부트스트랩 1,000회)")
    paths.append(save(fig, "f02_roc"))

    # f03 / f04 by source / doc_type
    paths.append(two_panel_rates(tables["by_source"], "source", "f03_by_source", "출처별 탐지율과 오탐률", sub + " · 막대 끝 선 = 95% 신뢰구간"))
    paths.append(two_panel_rates(tables["by_doc_type"], "doc_type", "f04_by_doc_type", "문서 종류별 탐지율과 오탐률", sub + " · 막대 끝 선 = 95% 신뢰구간"))

    # f05 position
    fig, axes = plt.subplots(1, 2, figsize=SIZE_WIDE, gridspec_kw={"width_ratios": [3, 2]})
    names = {"start": "앞", "middle": "중간", "end": "끝"}
    for ax, key, ttl in ((axes[0], "by_position", "전체 (지시문 시작 위치를 3등분해 계산)"), (axes[1], "by_position_bipia_official", "BIPIA 공식 삽입 위치")):
        t = tables[key].copy()
        t["name"] = t.iloc[:, 0].map(names)
        x = np.arange(len(t))
        bars = ax.bar(x, t["TPR"], color=INJ, width=0.6)
        bar_gap(bars)
        ax.errorbar(x, t["TPR"], yerr=_err(t["TPR"], t["TPR_lo"], t["TPR_hi"]), fmt="none", ecolor=INK_2, elinewidth=1, capsize=3)
        for xi, v, h, n in zip(x, t["TPR"], t["TPR_hi"], t["n_injection"]):
            ax.text(xi, h + 0.03, f"{pct(v)}\nn={int(n)}", ha="center", fontsize=8.5, color=INK_2)
        ax.set_xticks(x, t["name"])
        ax.set_ylim(0, 1.22)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
        ax.set_title(ttl, fontsize=10)
        ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("인젝션 탐지율 (TPR)")
    title(fig, "지시문이 문서 어디에 있느냐에 따른 탐지율", sub)
    paths.append(save(fig, "f05_by_position"))

    # f06 risk level
    t = tables["by_risk_level"].copy()
    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    x = np.arange(len(t))
    bars = ax.bar(x, t["TPR"], color=INJ, width=0.6)
    bar_gap(bars)
    ax.errorbar(x, t["TPR"], yerr=_err(t["TPR"], t["TPR_lo"], t["TPR_hi"]), fmt="none", ecolor=INK_2, elinewidth=1, capsize=3)
    for xi, v, h, n in zip(x, t["TPR"], t["TPR_hi"], t["n_injection"]):
        ax.text(xi, h + 0.03, f"{pct(v)}\nn={int(n)}", ha="center", fontsize=8.5, color=INK_2)
    lv = {1: "1 매우 낮음", 2: "2 낮음", 3: "3 중간", 4: "4 높음", 5: "5 매우 높음"}
    ax.set_xticks(x, [lv.get(int(k), str(k)) for k in t["risk_level"]])
    ax.set_ylim(0, 1.22)
    ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
    ax.set_ylabel("인젝션 탐지율 (TPR)")
    ax.set_xlabel("위험도 (risk_rubric.md)")
    ax.grid(axis="x", visible=False)
    title(fig, "위험한 공격일수록 잘 잡는가", sub)
    paths.append(save(fig, "f06_by_risk_level"))

    # f07 confusion matrix
    tp, fp = o["tp"], o["fp"]
    fn, tn = o["n_injection"] - tp, o["n_benign"] - fp
    mat = np.array([[tp, fn], [fp, tn]])
    rate = np.array([[tp / o["n_injection"], fn / o["n_injection"]], [fp / o["n_benign"], tn / o["n_benign"]]])
    from matplotlib.colors import LinearSegmentedColormap
    cmap = LinearSegmentedColormap.from_list("seq", SEQ_BLUE)
    fig, ax = plt.subplots(figsize=(6.5, 5.5))
    ax.imshow(rate, cmap=cmap, vmin=0, vmax=1)
    for i in range(2):
        for j in range(2):
            ax.text(j, i, f"{mat[i, j]}건\n{pct(rate[i, j])}", ha="center", va="center", fontsize=13,
                    color="#ffffff" if rate[i, j] > 0.55 else INK)
    ax.set_xticks([0, 1], ["인젝션으로 판정", "정상으로 판정"])
    ax.set_yticks([0, 1], ["실제 인젝션", "실제 정상"])
    ax.grid(False)
    for s in ax.spines.values():
        s.set_visible(False)
    title(fig, "임계값 0.5의 판정 결과", "행마다 비율(실제 라벨 기준) · " + sub.split(" · ")[0])
    paths.append(save(fig, "f07_confusion_matrix"))

    # f08 threshold sweep
    sw = tables["threshold_sweep"]
    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    ax.plot(sw.threshold, sw.TPR, color=INJ, lw=2)
    ax.plot(sw.threshold, sw.FPR, color=BEN, lw=2)
    ax.text(0.02, sw.TPR.iloc[1] + 0.03, "인젝션 탐지율 (TPR)", color=INK, fontsize=9.5)
    ax.text(0.02, sw.FPR.iloc[1] + 0.03, "정상 오탐률 (FPR)", color=INK, fontsize=9.5)
    ax.axvline(0.5, color=INK_2, lw=1, ls="--")
    ax.text(0.505, 0.95, "팀 기준 0.5", fontsize=8.5, color=INK_2)
    t5 = report["thresholds_for_fpr"]["fpr5"]
    ax.axvline(t5["threshold"], color=MUTED, lw=1, ls=":")
    ax.text(t5["threshold"] + 0.005, 0.85, f"오탐 5% 지점 {t5['threshold']:.2f}\nTPR {pct(t5['TPR'])}", fontsize=8.5, color=INK_2)
    ax.set_xlabel("임계값")
    ax.set_ylabel("비율")
    ax.set_ylim(0, 1.02)
    ax.set_xlim(0, 1)
    title(fig, "임계값을 움직이면 탐지와 오탐이 어떻게 바뀌나", sub)
    paths.append(save(fig, "f08_threshold_sweep"))

    # f09 calibration
    cal = tables["calibration"].dropna(subset=["mean_p"])
    fig, ax = plt.subplots(figsize=SIZE_SQUARE)
    ax.plot([0, 1], [0, 1], color=AXIS, lw=1)
    ax.plot(cal.mean_p, cal.injection_rate, color=INJ, lw=2)
    ax.scatter(cal.mean_p, cal.injection_rate, s=20 + 2.5 * np.sqrt(cal.n) * 6, color=INJ, edgecolor="#fcfcfb", linewidth=2, zorder=5)
    for _, r in cal.iterrows():
        ax.text(r.mean_p + 0.015, r.injection_rate - 0.045, f"n={int(r.n)}", fontsize=8, color=INK_2)
    ax.set_xlabel("Jev가 준 p (구간 평균)")
    ax.set_ylabel("그 구간의 실제 인젝션 비율")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.05)
    ax.text(0.55, 0.12, "대각선 = p가 실제 확률과 일치", fontsize=8.5, color=MUTED)
    title(fig, "p를 확률로 믿어도 되나 (보정 곡선)", sub)
    paths.append(save(fig, "f09_calibration"))

    # f10 stability across runs
    st = report["stability"]
    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    for li, c, lab in ((0, BEN, "정상"), (1, INJ, "인젝션")):
        s = en[en.label_int == li]
        ax.scatter(s.p_mean, s.p_range, s=14, color=c, alpha=0.75, label=lab, edgecolor="none")
    fl = en[en.flip]
    ax.scatter(fl.p_mean, fl.p_range, s=60, facecolor="none", edgecolor=INK, linewidth=1, label="회차마다 판정이 뒤집힌 문서")
    ax.axvline(0.5, color=INK_2, lw=1, ls="--")
    ax.set_xlabel("3회 평균 p")
    ax.set_ylabel("3회 호출 사이 p의 최대 차이")
    ax.legend(loc="upper right")
    pr = report["per_run"]
    runs = " / ".join(f"{i + 1}회차 TPR {pct(r['TPR'])} FPR {pct(r['FPR'])}" for i, r in enumerate(pr))
    title(fig, f"같은 문서를 다시 물으면: 판정이 뒤집힌 문서 {st['docs_with_flip']}건 ({pct(st['flip_rate'])})",
          f"공식 API에는 결과를 고정하는 옵션(seed)이 없음 · {runs}")
    paths.append(save(fig, "f10_run_to_run_stability"))

    # f11 latency
    lat = calls["latency_ms"].astype(float)
    L = report["latency_ms"]
    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    ax.hist(lat.clip(upper=np.percentile(lat, 99.5)), bins=40, color=MUTED, edgecolor="#fcfcfb", linewidth=1)
    for v, lab in ((L["median"], "중앙값"), (L["p90"], "상위 10%")):
        ax.axvline(v, color=INK_2, lw=1, ls="--")
        ax.text(v + 10, ax.get_ylim()[1] * 0.9, f"{lab} {v:.0f}ms", fontsize=9, color=INK_2)
    ax.set_xlabel("요청 1건 응답 시간 (ms, 한국 노트북 → 공식 API, 동시 6개)")
    ax.set_ylabel("요청 수")
    title(fig, f"1건당 응답 시간: 중앙값 {L['median']:.0f}ms, 평균 {L['mean']:.0f}ms", f"호출 {L['n_calls']}회 · 최대 {L['max']:.0f}ms")
    paths.append(save(fig, "f11_latency"))

    # f12 prompt length
    fig, axes = plt.subplots(1, 2, figsize=SIZE_WIDE, gridspec_kw={"width_ratios": [2, 3]})
    for ax, key, ttl in ((axes[0], "by_len_bucket", "중앙값 기준 2구간"), (axes[1], "by_len_quartile", "사분위 4구간")):
        t = tables[key].copy()
        x = np.arange(len(t))
        w = 0.36
        b1 = ax.bar(x - w / 2, t["TPR"], width=w, color=INJ, label="인젝션 탐지율 (TPR)")
        b2 = ax.bar(x + w / 2, t["FPR"], width=w, color=BEN, label="정상 오탐률 (FPR)")
        bar_gap(b1)
        bar_gap(b2)
        ax.errorbar(x - w / 2, t["TPR"], yerr=_err(t["TPR"], t["TPR_lo"], t["TPR_hi"]), fmt="none", ecolor=INK_2, elinewidth=1, capsize=2)
        ax.errorbar(x + w / 2, t["FPR"], yerr=_err(t["FPR"], t["FPR_lo"], t["FPR_hi"]), fmt="none", ecolor=INK_2, elinewidth=1, capsize=2)
        for xi, v, h in zip(x, t["TPR"], t["TPR_hi"]):
            ax.text(xi - w / 2, h + 0.02, pct(v), ha="center", fontsize=8, color=INK_2)
        for xi, v, h in zip(x, t["FPR"], t["FPR_hi"]):
            ax.text(xi + w / 2, h + 0.02, pct(v), ha="center", fontsize=8, color=INK_2)
        labels = [f"{a}\n(인젝션 {int(i)} / 정상 {int(b)})" for a, i, b in zip(t.iloc[:, 0], t.n_injection, t.n_benign)]
        ax.set_xticks(x, labels, fontsize=8)
        ax.set_ylim(0, 1.1)
        ax.set_yticks([0, 0.25, 0.5, 0.75, 1.0], ["0%", "25%", "50%", "75%", "100%"])
        ax.set_title(ttl, fontsize=10)
        ax.grid(axis="x", visible=False)
    axes[0].legend(loc="upper left", fontsize=8)
    title(fig, "짧은 프롬프트와 긴 프롬프트의 탐지율·오탐률", sub + " · 구간 경계는 결과를 보기 전에 글자 수로 고정")
    paths.append(save(fig, "f12_by_prompt_length"))

    # f13 NotInject over-defence reference
    if len(ni):
        fig, ax = plt.subplots(figsize=SIZE_WIDE)
        s = ni.sort_values("p_mean").reset_index(drop=True)
        ax.scatter(s.p_mean, np.arange(len(s)), color=BEN, s=40, edgecolor="#fcfcfb", linewidth=1.5)
        ax.axvline(0.5, color=INK_2, lw=1, ls="--")
        ax.set_yticks(np.arange(len(s)), s.uid, fontsize=7)
        ax.set_xlim(0, 1)
        ax.set_xlabel("p (3회 평균)")
        ax.grid(axis="y", visible=False)
        n = report["notinject"]
        title(fig, f"과탐지 참고 세트(NotInject 25건): 오탐률 {pct(n['FPR_at_0.5'])}",
              "트리거 단어가 들어간 정상 사용자 요청 · 본 평가에서는 제외, 참고용 · PIGuard 보고: 기존 가드 정확도 약 60%")
        paths.append(save(fig, "f13_notinject_overdefense"))
    return paths
