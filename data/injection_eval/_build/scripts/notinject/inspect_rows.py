import collections
import json
import os
import sys

sys.stdout.reconfigure(encoding="utf-8")
D = sys.argv[1]
alltexts = collections.Counter()
for split in ["NotInject_one", "NotInject_two", "NotInject_three"]:
    rows = json.load(open(os.path.join(D, split + ".json"), encoding="utf-8"))
    print("==", split)
    for r in rows:
        alltexts[r["prompt"].strip().lower()] += 1
        if r["category"] == "Multilingual":
            continue
        na = [c for c in r["prompt"] if ord(c) > 127]
        if na:
            print("  NONASCII", r["row_idx"], r["category"], ascii("".join(na)), "|", r["prompt"][:160])
        nw = [w for w in r["word_list"] if any(ord(c) > 127 for c in w)]
        if nw:
            print("  NONASCII-WORD", r["row_idx"], r["word_list"])
        missing = [w for w in r["word_list"] if w.lower() not in r["prompt"].lower()]
        if missing:
            print("  TRIGGER-NOT-VERBATIM", r["row_idx"], r["category"], missing)
    ml = [r for r in rows if r["category"] == "Multilingual"]
    ascii_ml = [r for r in ml if all(ord(c) < 128 for c in r["prompt"])]
    print("  multilingual rows:", len(ml), "of which pure-ascii:", len(ascii_ml))
    for r in ascii_ml[:5]:
        print("   ML-ASCII", r["row_idx"], r["prompt"][:160])
print("cross-split dup texts:", sum(1 for v in alltexts.values() if v > 1))
