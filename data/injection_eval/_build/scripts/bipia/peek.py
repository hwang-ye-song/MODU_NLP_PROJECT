import json, sys, os, unicodedata
bench, task = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(os.path.join(bench, task, "test.jsonl"), encoding="utf-8") if l.strip()]
for i, r in enumerate(rows):
    c = r["context"]
    if isinstance(c, list):
        c = "\n".join(c)
    na = sorted(set(ch for ch in c if ord(ch) > 127))
    letters = [ch for ch in c if ch.isalpha()]
    nonascii_letters = sum(1 for ch in letters if ord(ch) > 127)
    head = c[:110].replace("\n", " ").encode("ascii", "replace").decode()
    print(i, len(c), "naL=%d/%d" % (nonascii_letters, len(letters)), "".join(na)[:30].encode("unicode_escape").decode()[:80], "|", head)
