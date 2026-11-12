import json, os, random, re, sys, difflib
hf_path, core_path, out_path = sys.argv[1:4]
HF_REV = "1063bdf01ec8762b812d5e06ee768a06faa5a6f7"
HF_URL = f"https://huggingface.co/datasets/microsoft/llmail-inject-challenge/resolve/{HF_REV}/data/emails_for_fp_tests.json"
GH_SHA = "3da2399839b285e129888161fcc8cb03169d1b43"
GH_URL = f"https://raw.githubusercontent.com/microsoft/llmail-inject-challenge/{GH_SHA}/src/agent/data/fp_tests.json"
PAT = re.compile(r"^Subject of the email: (.*)\.   Body: (.*)$", re.S)
STRATA = [("project_series_zenith", range(0,20)), ("project_series_orion", range(20,40)),
          ("project_series_apollo", range(40,60)), ("project_series_helios", range(60,72)),
          ("corporate_memo", range(72,97)), ("project_aurora", range(97,203))]
hf = json.load(open(hf_path, encoding="utf-8"))
core = [json.loads(l) for l in open(core_path, encoding="utf-8")]
first, dups = {}, {}
for i, e in enumerate(hf):
    if e in first: dups[first[e]].append(i)
    else: first[e] = i; dups[i] = []
parsed = {}
for e, i in first.items():
    m = PAT.match(e); assert m
    parsed[i] = (m.group(1), m.group(2))
core_idx = {int(c["origin"]["index_or_key"].strip("[]")) for c in core}
texts = [c["text"] for c in core]
def ok(t):
    return all(difflib.SequenceMatcher(None, t, x).ratio() < 0.8 for x in texts)
# proportional allocation by unique-item counts
sizes = {n: len([i for i in r if i in parsed]) for n, r in STRATA}
tot = sum(sizes.values()); N = 25
raw = {n: N*s/tot for n, s in sizes.items()}
alloc = {n: int(v) for n, v in raw.items()}
for n in sorted(raw, key=lambda n: raw[n]-alloc[n], reverse=True)[:N-sum(alloc.values())]: alloc[n] += 1
print(sizes, alloc)
random.seed(42)
chosen, subjects = [], {parsed[i][0].lower() for i in core_idx}
for n, r in STRATA:
    c = [i for i in r if i in parsed and i not in core_idx]
    random.shuffle(c); got = 0
    for i in c:
        if got == alloc[n]: break
        s, b = parsed[i]; t = f"Subject: {s}\n\n{b}"
        if s.lower() in subjects or not ok(t) or len(t) > 3000: continue
        subjects.add(s.lower()); texts.append(t); chosen.append((n, i)); got += 1
    assert got == alloc[n], (n, got)
rows = [dict(c, core=True) for c in core]
for k, (n, i) in enumerate(chosen, 16):
    s, b = parsed[i]
    rows.append({"id": f"llmail-ben-{k:02d}", "label": "benign", "source": "LLMail-Inject", "subset": "fp_test",
      "text": f"Subject: {s}\n\n{b}", "injected_instruction": None,
      "origin": {"url": HF_URL, "commit_or_revision": f"hf:{HF_REV}", "file": "data/emails_for_fp_tests.json", "index_or_key": f"[{i}]"},
      "notes": (f"Organizer-written synthetic benign email from the dedicated false-positive test set (203 entries, 160 unique); stratum={n}. Published as one string 'Subject of the email: <subj>.   Body: <body>' (template period after subject dropped); subject/body text verbatim. Identical copy: {GH_URL} emails[{i}] (commit {GH_SHA})." + (f" Identical text also at indices {dups[i]}." if dups[i] else "")),
      "core": False})
assert len(rows) == 40 and len({r["id"] for r in rows}) == 40 and len({r["text"] for r in rows}) == 40
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for r in rows: f.write(json.dumps(r, ensure_ascii=False) + "\n")
print("ok")
