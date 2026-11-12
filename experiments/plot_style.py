"""Shared chart style for every figure in this project (PNG for slides and notebooks).

Colours follow the dataviz reference palette (validated with validate_palette.js, light mode):
  instruction-length bucket : 짧은 지시문 = blue #2a78d6, 긴 지시문 = orange #eb6834, 추출 불가 = muted gray #898781
                              (gray deliberately reads as "none"; always direct-label it)
  label                      : 인젝션 = violet #6250d6, 정상 = aqua #1baf7a (aqua is < 3:1 on the surface -> direct-label it)
Never re-map these colours in a single figure; the same entity keeps the same colour in every chart.

    from viz_style import setup, BUCKET_COLORS, LABEL_COLORS, save, title
    setup()
    fig, ax = plt.subplots(figsize=SIZE_WIDE)
    ...
    title(fig, "짧은 지시문이 60%", "EN 1,000건 중 주입 500건 기준")
    save(fig, "f1_instruction_length")
"""
import os

import matplotlib
import matplotlib.pyplot as plt

matplotlib.use("Agg")

HERE = os.path.dirname(os.path.abspath(__file__))
FIG_DIR = os.path.join(HERE, "figures")  # default; pass out_dir to save() for results/<exp>/figures

SURFACE = "#fcfcfb"
INK = "#0b0b0b"
INK_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
AXIS = "#c3c2b7"

BUCKETS = ["짧은 지시문", "긴 지시문", "추출 불가"]
BUCKET_COLORS = {"짧은 지시문": "#2a78d6", "긴 지시문": "#eb6834", "추출 불가": MUTED}
LABELS = ["인젝션", "정상"]
LABEL_COLORS = {"인젝션": "#6250d6", "정상": "#1baf7a"}
SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]  # light -> dark

SIZE_WIDE = (10, 5.2)
SIZE_SQUARE = (7.5, 6.5)
SIZE_TALL = (10, 7)


def _korean_fonts():
    """Use whichever Korean font is installed (Windows: Malgun Gothic, Colab: NanumGothic after apt install)."""
    from matplotlib import font_manager
    have = {f.name for f in font_manager.fontManager.ttflist}
    picks = [f for f in ("Malgun Gothic", "NanumGothic", "AppleGothic", "Noto Sans CJK KR") if f in have]
    return picks + ["sans-serif"]


def setup():
    plt.rcParams.update({
        "font.family": _korean_fonts(),
        "axes.unicode_minus": False,
        "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
        "text.color": INK, "axes.labelcolor": INK_2, "xtick.color": MUTED, "ytick.color": MUTED,
        "axes.edgecolor": AXIS, "axes.linewidth": 0.8,
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6, "axes.axisbelow": True,
        "axes.titlesize": 12, "axes.titleweight": "bold", "axes.titlecolor": INK, "axes.titlelocation": "left",
        "axes.labelsize": 10, "xtick.labelsize": 9, "ytick.labelsize": 9,
        "legend.frameon": False, "legend.fontsize": 9,
        "lines.linewidth": 2, "lines.markersize": 7,
        "patch.linewidth": 0, "figure.dpi": 100, "savefig.dpi": 200,
    })


def title(fig, headline, subtitle=None):
    """Figure-level headline (the takeaway) and an optional muted subtitle (what/where/n).
    Positions scale with figure height so the gap above the axes stays about the same in every chart."""
    h = fig.get_size_inches()[1]
    fig.suptitle(headline, x=0.01, y=1 - 0.06 / h, ha="left", va="top", fontsize=14, fontweight="bold", color=INK)
    lines = 0
    if subtitle:
        fig.text(0.01, 1 - 0.40 / h, subtitle, ha="left", va="top", fontsize=10, color=INK_2)
        lines = subtitle.count(chr(10)) + 1
    fig._viz_top = 1 - (0.50 + 0.22 * lines) / h


def bar_gap(bars, surface=SURFACE):
    """2px surface gap between adjacent / stacked fills."""
    for b in bars:
        b.set_edgecolor(surface)
        b.set_linewidth(1.5)


def save(fig, name, top=None, out_dir=None):
    out_dir = out_dir or FIG_DIR
    os.makedirs(out_dir, exist_ok=True)
    top = top or getattr(fig, "_viz_top", 0.88)
    fig.tight_layout(rect=(0, 0, 1, top))
    path = os.path.join(out_dir, f"{name}.png")
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path
