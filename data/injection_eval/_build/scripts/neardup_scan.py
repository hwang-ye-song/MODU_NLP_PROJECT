"""Cross-file near-duplicate scan (difflib autojunk=False) over EN parts, honoring overrides drops.

Usage: python -I neardup_scan.py <WD> [threshold]
Only compares items of the same source and label (cross-label pairs are reported too, flagged).
"""
import difflib
import json
import sys
from collections import defaultdict
from pathlib import Path

wd = Path(sys.argv[1])
th = float(sys.argv[2]) if len(sys.argv) > 2 else 0.85
ov = json.loads((wd / "_build/audit/overrides.json").read_text(encoding="utf-8"))
drop = set(ov.get("drop", {}))
rows = []
for p in sorted((wd / "_build/parts_v2").glob("*.jsonl")):
    if p.stem in ("notinject",):
        continue
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            r = json.loads(line)
            if r["id"] not in drop:
                rows.append(r)
groups = defaultdict(list)
for r in rows:
    groups[r["source"]].append(r)
hits = []
for src, rs in groups.items():
    for i in range(len(rs)):
        a = rs[i]["text"]
        for j in range(i + 1, len(rs)):
            b = rs[j]["text"]
            if abs(len(a) - len(b)) > 0.3 * max(len(a), len(b)):
                continue
            sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
            if sm.real_quick_ratio() < th or sm.quick_ratio() < th:
                continue
            r = sm.ratio()
            if r >= th:
                hits.append((round(r, 3), src, rs[i]["id"], rs[i]["label"], rs[j]["id"], rs[j]["label"]))
hits.sort(reverse=True)
print(f"items scanned: {len(rows)}  pairs >= {th}: {len(hits)}")
for h in hits:
    flag = "" if h[3] == h[5] else "  <-- CROSS-LABEL"
    print(h, flag)
