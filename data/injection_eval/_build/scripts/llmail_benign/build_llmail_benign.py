"""Build 15 benign samples from the LLMail-Inject false-positive test emails.

Usage: python -I build_llmail_benign.py <hf_emails_for_fp_tests.json> <gh_fp_tests.json> <out.jsonl>
"""
import json
import os
import random
import re
import sys

HF_REV = "1063bdf01ec8762b812d5e06ee768a06faa5a6f7"
HF_URL = f"https://huggingface.co/datasets/microsoft/llmail-inject-challenge/resolve/{HF_REV}/data/emails_for_fp_tests.json"
GH_SHA = "3da2399839b285e129888161fcc8cb03169d1b43"
GH_URL = f"https://raw.githubusercontent.com/microsoft/llmail-inject-challenge/{GH_SHA}/src/agent/data/fp_tests.json"

PAT = re.compile(r"^Subject of the email: (.*)\.   Body: (.*)$", re.S)
STOP = {"project", "zenith", "orion", "apollo", "helios", "aurora", "q1", "q2", "q3", "new",
        "updated", "update", "and", "the", "of"}
# Treat phase numbers as one topic word so "Phase Three Kickoff" and "Phase 3 Planning" conflict.
NUMWORDS = {"one": "phase-num", "two": "phase-num", "three": "phase-num", "1": "phase-num",
            "2": "phase-num", "3": "phase-num"}
# Map near-synonyms so e.g. "Testing" and "Test" or "Review"/"Reviews" count as the same topic word.
NORM = {"testing": "test", "results": "result", "reviews": "review", "materials": "material",
        "sessions": "session", "milestones": "milestone", "guidelines": "guideline"}

# Strata: (name, index range, number to draw)
STRATA = [
    ("project_series_zenith", range(0, 20), 1),
    ("project_series_orion", range(20, 40), 1),
    ("project_series_apollo", range(40, 60), 1),
    ("project_series_helios", range(60, 72), 1),
    ("corporate_memo", range(72, 97), 7),
    ("project_aurora", range(97, 203), 4),
]


def topic_words(subject):
    words = re.findall(r"[a-z0-9\-]+", subject.lower())
    return {NUMWORDS.get(w, NORM.get(w, w)) for w in words if w not in STOP}


def main(hf_path, gh_path, out_path):
    hf = json.load(open(hf_path, encoding="utf-8"))
    gh = json.load(open(gh_path, encoding="utf-8"))["emails"]
    assert hf == gh, "HF and GitHub FP lists differ"
    assert len(hf) == 203

    first_idx, dup_idx = {}, {}
    for i, e in enumerate(hf):
        if e in first_idx:
            dup_idx[first_idx[e]].append(i)
        else:
            first_idx[e] = i
            dup_idx[i] = []
    print("total", len(hf), "unique", len(first_idx))

    parsed = {}
    for e, i in first_idx.items():
        m = PAT.match(e)
        assert m, f"unparsed index {i}"
        subj, body = m.group(1), m.group(2)
        assert subj.strip() and body.strip()
        parsed[i] = (subj, body)

    random.seed(42)
    used_words, chosen = set(), []
    for name, rng, k in STRATA:
        cands = [i for i in rng if i in parsed]  # first occurrences only
        random.shuffle(cands)
        got = 0
        for i in cands:
            if got == k:
                break
            tw = topic_words(parsed[i][0])
            if tw & used_words:
                continue
            used_words |= tw
            chosen.append((name, i))
            got += 1
        assert got == k, f"stratum {name} short: {got}/{k}"

    rows = []
    for n, (name, i) in enumerate(chosen, 1):
        subj, body = parsed[i]
        text = f"Subject: {subj}\n\n{body}"
        assert len(text) <= 3000
        dup_note = f" Identical text also at indices {dup_idx[i]}." if dup_idx[i] else ""
        rows.append({
            "id": f"llmail-ben-{n:02d}",
            "label": "benign",
            "source": "LLMail-Inject",
            "subset": "fp_test",
            "text": text,
            "injected_instruction": None,
            "origin": {
                "url": HF_URL,
                "commit_or_revision": f"hf:{HF_REV}",
                "file": "data/emails_for_fp_tests.json",
                "index_or_key": f"[{i}]",
            },
            "notes": (
                f"Organizer-written synthetic benign email from the dedicated false-positive test set "
                f"(203 entries, 160 unique); stratum={name}. Published as one string "
                f"'Subject of the email: <subj>.   Body: <body>' (template period after subject dropped); "
                f"subject/body text verbatim. Identical copy: {GH_URL} emails[{i}] (commit {GH_SHA}).{dup_note}"
            ),
        })

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print("wrote", len(rows), out_path)


if __name__ == "__main__":
    main(*sys.argv[1:4])
