"""Merge 3 raters for one batch into consensus_new.json (median level, majority harm_type).

Usage: python -X utf8 -I consensus.py <rating_dir> <batch> [uid=level:harm:rationale ...overrides]
"""
import json
import statistics as st
import sys
from collections import Counter
from pathlib import Path


def qwk(a, b, K=5):
    n = len(a)
    O = Counter(zip(a, b))
    ha, hb = Counter(a), Counter(b)
    num = sum(((i - j) ** 2) * O[(i, j)] for i in range(1, K + 1) for j in range(1, K + 1))
    den = sum(((i - j) ** 2) * ha[i] * hb[j] / n for i in range(1, K + 1) for j in range(1, K + 1))
    return 1 - num / den if den else float("nan")


def main(d: Path, batch: str, overrides):
    R = {k: {r["uid"]: r for r in json.loads((d / f"rater_{k}_{batch}.json").read_text(encoding="utf-8"))}
         for k in "ABC"}
    inp = [json.loads(l)["uid"] for l in (d / f"new_{batch}.jsonl").read_text(encoding="utf-8").splitlines() if l.strip()]
    for k in "ABC":
        if set(R[k]) != set(inp):
            print(f"rater {k}: uid mismatch ({len(R[k])} vs {len(inp)})")
    uids = [u for u in inp if all(u in R[k] for k in "ABC")]
    exact = sum(len({R[k][u]["risk_level"] for k in "ABC"}) == 1 for u in uids)
    print(f"{batch}: n={len(uids)} all-3 exact {exact}  ", end="")
    for p, q in ("AB", "AC", "BC"):
        print(f"QWK {p}{q}={qwk([R[p][u]['risk_level'] for u in uids], [R[q][u]['risk_level'] for u in uids]):.3f} ", end="")
    print()
    outp = d / "consensus_new.json"
    cons = json.loads(outp.read_text(encoding="utf-8")) if outp.exists() else {}
    for u in uids:
        lv = [R[k][u]["risk_level"] for k in "ABC"]
        med = int(st.median(lv))
        ht = Counter(R[k][u]["harm_type"] for k in "ABC" if R[k][u]["risk_level"] == med).most_common(1)[0][0]
        rat = next(R[k][u]["rationale_ko"] for k in "CAB" if R[k][u]["risk_level"] == med and R[k][u]["harm_type"] == ht)
        rec = {"risk_level": med, "harm_type": ht, "risk_rationale": rat, "rater_levels": lv, "adjudicated": False}
        if u in overrides:
            lvl, h, why = overrides[u]
            rec.update(risk_level=lvl, harm_type=h, risk_rationale=why, adjudicated=True)
        if max(lv) - min(lv) >= 1:
            print(f"  {u} {lv} -> {rec['risk_level']} {rec['harm_type']}{' (adj)' if rec['adjudicated'] else ''} | "
                  + " / ".join(f"{k}:{R[k][u]['harm_type']}:{R[k][u]['rationale_ko']}" for k in "ABC"))
        cons[u] = rec
    outp.write_text(json.dumps(cons, ensure_ascii=False, indent=1), encoding="utf-8")
    dist = Counter(cons[u]["risk_level"] for u in uids)
    print("  final dist:", dict(sorted(dist.items())), "| total in consensus_new:", len(cons))


if __name__ == "__main__":
    ov = {}
    for a in sys.argv[3:]:
        u, rest = a.split("=", 1)
        lvl, h, why = rest.split(":", 2)
        ov[u] = (int(lvl), h, why)
    main(Path(sys.argv[1]), sys.argv[2], ov)
