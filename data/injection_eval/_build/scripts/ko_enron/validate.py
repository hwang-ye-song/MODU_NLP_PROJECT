"""usage: python -X utf8 -I validate.py <src_en.jsonl> <out_ko.jsonl>"""
import json, re, sys

src = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8") if l.strip()]
out_lines = open(sys.argv[2], encoding="utf-8").read().split("\n")
assert out_lines[-1] == ""
out = [json.loads(l) for l in out_lines[:-1]]
problems = []
assert len(src) == len(out), (len(src), len(out))
ids = [o["id"] for o in out]
assert len(set(ids)) == len(ids)
for s, o in zip(src, out):
    rid = s["id"]
    if o["pair_id"] != rid or o["id"] != rid + "-ko":
        problems.append((rid, "id/order"))
    for k in ("label", "source", "subset", "origin", "core", "notes"):
        if o[k] != s[k]:
            problems.append((rid, "field " + k))
    if o["injected_instruction"] is not None or o["label"] != "benign":
        problems.append((rid, "label/inj"))
    st, ot = s["text"], o["text"]
    sl, ol = st.split("\n"), ot.split("\n")
    if len(sl) != len(ol):
        problems.append((rid, f"line count {len(sl)} vs {len(ol)}"))
    if not ol[0].startswith("Subject: ") or ol[1] != "":
        problems.append((rid, "subject/blank"))
    # blank lines same positions
    if [i for i, x in enumerate(sl) if x == ""] != [i for i, x in enumerate(ol) if x == ""]:
        problems.append((rid, "blank line positions"))
    # trailing whitespace
    if any(x != x.strip(" \t") for x in ol):
        problems.append((rid, "leading/trailing ws"))
    if "\\u" in json.dumps(o, ensure_ascii=False):
        problems.append((rid, "escaped unicode"))
    # Hangul ratio over letters
    letters = [c for c in ot if c.isalpha()]
    hangul = [c for c in letters if "가" <= c <= "힣"]
    ratio = len(hangul) / max(1, len(letters))
    # preserved tokens: emails, $ amounts, x-extensions, 4+digit numbers, numeric dates
    toks = set(re.findall(r"[\w.]+@[\w.]+|\$[\d,.\-]+|\bx\d{5}\b|\b\d{4,}\b|\b\d{1,2}/\d{1,2}(?:/\d{2})?\b|\b[A-Z]{2,}[A-Z0-9&/\-]*\b", st))
    missing = sorted(t for t in toks if t not in ot)
    # English words left (sequences of >=4 lowercase-ish English words)
    eng_runs = re.findall(r"(?:\b[a-z][a-z']+\b[ ,]+){4,}", ot)
    print(f"{rid}: lines={len(ol)} hangul={ratio:.2f} missing={missing} engruns={eng_runs[:2]}")
print("PROBLEMS:", problems if problems else "none")
