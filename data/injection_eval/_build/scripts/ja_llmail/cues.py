"""Print cue sentences of given rows. Usage: python -X utf8 -I cues.py <review.jsonl> <rows comma> [maxsent]"""
import json, sys, re
sys.stdout.reconfigure(encoding="utf-8")
p, rows = sys.argv[1], [int(x) for x in sys.argv[2].split(",")]
mx = int(sys.argv[3]) if len(sys.argv) > 3 else 8
CUE = re.compile(r"contact|confirm|\bsend|e-?mail|\bmail|assistant|\bai\b|summar|tool|api|dispatch|reply|forward|notify|\brun\b|execute|must|please|deliver|transmit|log", re.I)
idx = {}
for n, l in enumerate(open(p, encoding="utf-8"), 1):
    r = json.loads(l); idx[r["origin"]["row_index"]] = (n, r)
for ri in rows:
    n, r = idx[ri]
    t = r["text"]
    vis = "".join(c if (c.isprintable() or c == "\n") else "¤" for c in t)
    parts = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", vis) if s.strip()]
    hits = [s for s in parts if CUE.search(s)]
    print(f"### #{n} r{ri} L={len(t)} parts={len(parts)}")
    for s in hits[:mx]:
        print("   -", s[:260])
