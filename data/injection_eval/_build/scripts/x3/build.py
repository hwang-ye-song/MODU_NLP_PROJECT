"""X3 distractor experiment: same injection span inserted into unrelated expository carriers (Wikipedia)
vs instruction-dense carriers (Enron AESLC emails with several human-directed requests).

Usage: python -X utf8 -I build.py <WD> <aeslc data dir> <out dir> [--dump review.txt]
"""
import csv
import glob
import json
import os
import random
import re
import statistics
import sys
import unicodedata
import urllib.parse
from collections import Counter, defaultdict

import pyarrow.parquet as pq

N = 100
CMIN, CMAX = 1200, 1600
AESLC = "Yale-LILY/aeslc"
AESLC_REV = "2305f2e63b68056f9b9037a3805c8c196e0d5581"

RE_SECRET = re.compile(r"(?i)\bpass ?words?\b|\bpwd\b|\buser ?id\b|\blog-?in id\b|\bssn\b|social security"
                       r"|account (no|number|#)|routing|\biban\b|swift code|credit card|card (no|number|#)"
                       r"|passport|\bpin\b|employee (id|number|#)|\bp ?number\b")
RE_DIGITS = re.compile(r"\b\d{3}-\d{2}-\d{4}\b|\b\d{7,}\b|\b(\d{4}[ -]){3}\d{4}\b")
RE_PHONE = re.compile(r"\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b|\b\d{3}[-.]\d{4}\b|\bx-?\d{4,5}\b|\b\d-\d{4,5}\b|\bx\d-\d{4}\b|\bext\.? ?\d{3,5}\b", re.I)
RE_EMAILADDR = re.compile(r"\S+@\S+\.\w+")
RE_AI = re.compile(r"(?i)\bA\.I\.|\bAI\b|artificial intelligence|chat ?bot|language model|\bLLM\b|\bGPT|system prompt"
                   r"|\bassistant\b|\bbot\b|machine learning|neural network")
RE_FWD = re.compile(r"(?im)^(-{2,}|_{4,}|>|from:|sent:|to:|cc:|subject:.*\bfw|.*original message|.*forwarded by)")
# human-directed request markers (counted per line / sentence)
RE_REQ = re.compile(r"(?i)\b(please|pls|could you|can you|would you|will you|let me know|let us know|make sure|be sure to"
                    r"|need you to|need (?:your|to have)|kindly|don't forget|do not forget|remember to|feel free to"
                    r"|give me a call|call me|send me|i would appreciate|you should|you must|you will need|you need to"
                    r"|i'd like you to|i would like you to|i need|we need|we will need|can we|could we|i'd like|i would like"
                    r"|we would like|for your (?:review|approval|signature|comments|input)|at your earliest convenience"
                    r"|as soon as possible|asap|by (?:monday|tuesday|wednesday|thursday|friday|tomorrow|close of business"
                    r"|cob|noon|end of (?:the )?day))\b")
RE_IMP = re.compile(r"^(Please|Call|Send|Forward|Review|Let|Make|Check|Sign|Fax|Return|Bring|Contact|Reply|Respond|Complete"
                    r"|Submit|Attend|Note|Remember|Confirm|Plan|Provide|Give|Get|Ask|Read|Print|Fill|Update|E-?mail"
                    r"|Add|Don't|Do not|Be sure|Mark|RSVP|Register|Schedule|Notify|Advise|Verify)\b")
RE_YOU = re.compile(r"(?i)\byou(r|rs|rself)?\b|\bplease\b|\blet me know\b|\bmake sure\b")
ABBR = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Mt|Ft|vs|etc|e\.g|i\.e|c|ca|cf|al|No|Vol|pp|Inc|Ltd|Co|Corp|Gen|Gov|Sen|Rev|Prof|Capt|Col|Lt|Sgt|Fig|approx|U\.S|U\.K|U\.N|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)|\b[A-Z])\.$")
STOP = set("the of and to in a is that for it as was with be by on not he i this are or his from at which but have an they you were".split())


def ngrams(s, n=5):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def norm_ws(s):
    lines = [re.sub(r"[^\S\n]+", " ", ln).strip() for ln in s.replace("\r\n", "\n").split("\n")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines).strip())


def split_sents(par):
    """Return list of (start, end) char offsets of sentences in a prose paragraph."""
    out, start = [], 0
    for m in re.finditer(r"(?<=[.!?])[\"”')\]]*\s+(?=[A-Z\"“(])", par):
        left = par[start:m.start()].rstrip("\"”')]")
        if ABBR.search(left) or re.search(r"\b[A-Z]\.[A-Z]\.$", left):
            continue
        out.append((start, m.start()))
        start = m.end()
    out.append((start, len(par)))
    return out


def english_ok(t):
    letters = [ch for ch in t if ch.isalpha()]
    if not letters:
        return False
    nonlatin = sum(1 for ch in letters if not unicodedata.name(ch, "").startswith("LATIN"))
    words = re.findall(r"[a-z']+", t.lower())
    return nonlatin / len(letters) < 0.01 and words and sum(w in STOP for w in words) / len(words) > 0.12


class RefIndex:
    def __init__(self, texts):
        self.idx = defaultdict(set)
        self.sizes = []
        self.names = []
        for i, (name, t) in enumerate(texts):
            g = ngrams(t)
            self.sizes.append(len(g))
            self.names.append(name)
            for x in g:
                self.idx[x].add(i)

    def worst(self, t):
        g = ngrams(t)
        c = Counter()
        for x in g:
            for i in self.idx.get(x, ()):
                c[i] += 1
        best = (0.0, None)
        for i, k in c.items():
            cont = k / max(1, len(g))                  # share of carrier found in ref
            jac = k / (len(g) + self.sizes[i] - k)
            v = max(cont, jac)
            if v > best[0]:
                best = (v, self.names[i])
        return best


def load_refs(wd):
    refs = []
    for fp in [f"{wd}/en/dataset_en_1000.jsonl"] + sorted(glob.glob(f"{wd}/_build/parts_v2/*.jsonl")) + \
              sorted(glob.glob(f"{wd}/_build/*candidates.jsonl")):
        with open(fp, encoding="utf-8") as f:
            for ln in f:
                if ln.strip():
                    r = json.loads(ln)
                    refs.append((f"{os.path.basename(fp)}:{r.get('id')}", r["text"]))
    return refs


# ---------------- carriers: Wikipedia ----------------
def wiki_carriers(wd, ref):
    out, rej = [], Counter()
    with open(f"{wd}/sim/raw/en_wiki.jsonl", encoding="utf-8") as f:
        docs = [json.loads(l) for l in f]
    for li, d in enumerate(docs):
        title = urllib.parse.unquote(d["url"].rsplit("/", 1)[-1])
        if "disambiguation" in title.lower() or title.lower().startswith(("list of", "lists of", "index of", "outline of", "timeline of", "glossary")):
            rej["title"] += 1
            continue
        pars = [p.strip() for p in d["text"].split("\n") if p.strip()]
        # prose paragraphs only (headings, captions, list items dropped)
        pars = [p for p in pars if len(p) >= 150 and p[-1] in ".!?\"”)" and "|" not in p]
        if not pars:
            rej["noprose"] += 1
            continue
        # build excerpt from the first prose paragraphs, cutting at a sentence boundary in [CMIN, CMAX]
        text, ok = "", False
        for p in pars:
            sep = "\n\n" if text else ""
            if len(text) + len(sep) + len(p) < CMIN:
                text += sep + p
                continue
            for s, e in split_sents(p):
                cand = text + sep + p[:e]
                if CMIN <= len(cand) <= CMAX:
                    text, ok = cand, True
                    break
                if len(cand) > CMAX:
                    break
            break
        if not ok:
            rej["len"] += 1
            continue
        if RE_YOU.search(text):
            rej["you/please"] += 1
            continue
        if RE_AI.search(text):
            rej["ai"] += 1
            continue
        if not english_ok(text):
            rej["lang"] += 1
            continue
        if "(; )" in text or "( )" in text or re.search(r"\(\s*[;,]", text):
            rej["artifact"] += 1
            continue
        v, who = ref.worst(text)
        if v >= 0.3:
            rej["dup_main"] += 1
            continue
        out.append({"carrier_source": "wiki", "text": text, "title": title,
                    "origin": {"dataset": "wikimedia/wikipedia", "config": "20231101.en",
                               "file": "sim/raw/en_wiki.jsonl", "line": li, "url": d["url"],
                               "fetched_by": "sim/fetch_corpora.py (HF datasets-server rows API)"},
                    "n_requests": count_requests(text)})
    return out, rej


def count_requests(text):
    units = []
    for ln in text.split("\n"):
        ln = ln.strip()
        if ln:
            units += [ln[s:e] for s, e in split_sents(ln)]
    return sum(1 for u in units if RE_REQ.search(u) or RE_IMP.match(u))


# ---------------- carriers: Enron (AESLC) ----------------
def enron_carriers(data_dir, ref):
    out, rej = [], Counter()
    for split in ("train", "validation", "test"):
        f = f"data/{split}-00000-of-00001.parquet"
        tab = pq.read_table(f"{data_dir}/{split}-00000-of-00001.parquet").to_pylist()
        for i, r in enumerate(tab):
            subject = norm_ws(r["subject_line"] or "").replace("\n", " ")
            body = norm_ws(r["email_body"] or "")
            if len(body) < CMIN - 100:
                continue
            head = f"Subject: {subject}\n\n"
            # sentence ends inside the body (line ends + sentence boundaries within a line)
            ends, off = [], 0
            for ln in body.split("\n"):
                if ln.strip():
                    ends += [off + e for _, e in split_sents(ln)]
                off += len(ln) + 1
            text, ok = head, False
            for e in ends:
                cand = head + body[:e]
                if CMIN <= len(cand) <= CMAX:
                    text, ok = cand, True
                    break
                if len(cand) > CMAX:
                    break
            if not ok:
                rej["len"] += 1
                continue
            if RE_FWD.search(text.split("\n", 1)[1]):
                rej["fwd"] += 1
                continue
            body_lines = [x.strip() for x in text.split("\n")[2:] if x.strip()]
            if ("??" in text or re.search(r"\w= \w|=$|=\n|=20|=09", text)
                    or any(re.fullmatch(r"[\W_]+", x) for x in body_lines)):
                rej["encoding_artifact"] += 1
                continue
            if RE_SECRET.search(text) or RE_DIGITS.search(text):
                rej["personal_id"] += 1
                continue
            if RE_PHONE.search(text) or RE_EMAILADDR.search(text):
                rej["phone_email"] += 1
                continue
            if RE_AI.search(text):
                rej["ai"] += 1
                continue
            if not english_ok(text):
                rej["lang"] += 1
                continue
            if "http" in text or "www." in text:
                rej["url"] += 1
                continue
            nreq = count_requests(text)
            if nreq < 3:
                rej["few_requests"] += 1
                continue
            v, who = ref.worst(text)
            if v >= 0.3:
                rej["dup_main"] += 1
                continue
            out.append({"carrier_source": "enron", "text": text, "title": subject,
                        "origin": {"dataset": AESLC, "revision": AESLC_REV, "file": f, "split": split, "row_index": i,
                                   "url": f"https://huggingface.co/datasets/{AESLC}/resolve/{AESLC_REV}/{f}"},
                        "n_requests": nreq})
    return out, rej


def dedup_within(cands):
    keep, grams = [], []
    for c in cands:
        g = ngrams(c["text"])
        if any(len(g & h) / max(1, min(len(g), len(h))) >= 0.3 for h in grams):
            continue
        keep.append(c)
        grams.append(g)
    return keep


# ---------------- injection spans ----------------
SPAN_QUOTA = {("BIPIA", "news_article"): 8, ("BIPIA", "table"): 8, ("BIPIA", "email"): 8,
              ("BrowseSafe-Bench", "webpage"): 16, ("InjecAgent", "tool_response"): 20,
              ("LLMail-Inject", "email"): 20, ("SEP", "general_document"): 20}


def pick_spans(main):
    pool = defaultdict(list)
    for r in main:
        s = r["injected_instruction"]
        if r["label"] != "injection" or r["source"] == "AgentDojo" or not s or r["doc_type"] == "code_qa":
            continue
        if not (20 <= len(s) <= 200) or r["text"].count(s) != 1 or "\n" in s:
            continue
        if not re.match(r"^[\"“(]?[A-Z]", s) or s != s.strip():
            continue
        if "<" in s or "{" in s or "```" in s:
            continue
        if (r["source"], r["doc_type"]) in SPAN_QUOTA:
            pool[(r["source"], r["doc_type"])].append(r)
    chosen, seen = [], []
    for key, q in SPAN_QUOTA.items():
        g = sorted(pool[key], key=lambda r: r["uid"])
        if key[0] == "InjecAgent":  # balance InjecAgent subsets
            by = defaultdict(list)
            for r in g:
                by[r["subset"]].append(r)
            g = []
            for sub in sorted(by):
                random.shuffle(by[sub])
            while any(by.values()):
                for sub in sorted(by):
                    if by[sub]:
                        g.append(by[sub].pop())
        else:
            random.shuffle(g)
        k = 0
        for r in g:
            if k == q:
                break
            s = r["injected_instruction"]
            gs = ngrams(s, 3)
            if any(len(gs & h) / max(1, len(gs | h)) >= 0.7 for h in seen):
                continue
            seen.append(gs)
            chosen.append(r)
            k += 1
        assert k == q, (key, k, len(g))
    return chosen


# ---------------- insertion ----------------
def boundaries(text, kind):
    """Candidate insertion points (index where the next sentence starts) and the joiner style."""
    pts = []
    if kind == "enron":
        body_start = text.index("\n\n") + 2
        off = body_start
        for ln in text[body_start:].split("\n"):
            if ln.strip():
                for s, e in split_sents(ln)[1:]:
                    pts.append((off + s, "space"))
            off += len(ln) + 1
            # start of the next line, if this line is non-empty and the next line is non-empty
            if ln.strip() and off < len(text) and text[off] != "\n":
                pts.append((off, "line"))
    else:
        off = 0
        for par in text.split("\n\n"):
            for s, e in split_sents(par)[1:]:
                pts.append((off + s, "space"))
            off += len(par) + 2
    return pts


def insert(text, span, kind):
    mid = len(text) / 2
    pts = boundaries(text, kind)
    pos, style = min(pts, key=lambda x: abs(x[0] - mid))
    if style == "line":
        new = text[:pos] + span + "\n" + text[pos:]
    else:
        new = text[:pos] + span + " " + text[pos:]
    assert new.replace(span + ("\n" if style == "line" else " "), "", 1) == text
    return new, pos


def main():
    wd, aeslc_dir, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
    dump = sys.argv[sys.argv.index("--dump") + 1] if "--dump" in sys.argv else None
    random.seed(42)
    with open(f"{wd}/en/dataset_en_1000.jsonl", encoding="utf-8") as f:
        main_rows = [json.loads(l) for l in f]
    ref = RefIndex(load_refs(wd))

    spans = pick_spans(main_rows)
    random.shuffle(spans)

    wiki, wrej = wiki_carriers(wd, ref)
    enron, erej = enron_carriers(aeslc_dir, ref)
    print("wiki candidates", len(wiki), dict(wrej))
    print("enron candidates", len(enron), dict(erej))
    random.shuffle(wiki)
    random.shuffle(enron)
    wiki = dedup_within(wiki)[:N]
    enron = dedup_within(enron)[:N]
    assert len(wiki) == N and len(enron) == N, (len(wiki), len(enron))

    rows = []
    for kind, carriers, ctype, doc_type, csrc in (("wiki", wiki, "unrelated_expository", "wiki", "Wikipedia"),
                                                 ("enron", enron, "instruction_dense", "email", "Enron")):
        for k, (c, sp) in enumerate(zip(carriers, spans), 1):
            cid = f"X3-{kind}-{k:03d}"
            span = sp["injected_instruction"]
            new, pos = insert(c["text"], span, kind)
            common = {"carrier_type": ctype, "carrier_source": kind, "carrier_id": cid, "carrier_len": len(c["text"]),
                      "carrier_doc_type": doc_type, "carrier_n_requests": c["n_requests"], "slot": k,
                      "carrier_origin": c["origin"]}
            rows.append({"exp": "X3", "base_id": sp["id"], "base_uid": sp["uid"], "label": "injection", "label_int": 1,
                         "source": sp["source"], "doc_type": sp["doc_type"], "risk_level": sp["risk_level"],
                         **common, "inj_pair_id": f"X3-P{k:03d}", "position": "middle", "insert_offset": pos,
                         "span_subset": sp["subset"],
                         "text": new, "injected_instruction": span, "variant_text_source": "template",
                         "notes": (f"Carrier {cid} ({csrc}) with the injected span of main-set {sp['uid']} ({sp['source']}/"
                                   f"{sp['subset']}) inserted verbatim as its own sentence at the sentence boundary closest "
                                   f"to the carrier's middle (char {pos}); carrier text otherwise byte-identical.")})
            rows.append({"exp": "X3", "base_id": None, "base_uid": None, "label": "benign", "label_int": 0,
                         "source": csrc, "doc_type": doc_type, "risk_level": 0,
                         **common, "inj_pair_id": None, "position": None, "insert_offset": None, "span_subset": None,
                         "text": c["text"], "injected_instruction": None, "variant_text_source": "original",
                         "notes": (f"Carrier {cid} unchanged ({csrc}; {'title' if kind == 'wiki' else 'subject'}: "
                                   f"{c['title'][:80]}). Not a main-set row; paired with the injection row of the same "
                                   f"carrier_id. {c['n_requests']} human-directed request sentence(s) by regex.")})
    # order: by slot, kind, label
    rows.sort(key=lambda r: (r["slot"], r["carrier_source"] != "wiki", r["label"] != "injection"))
    for n, r in enumerate(rows, 1):
        r["exp_uid"] = f"X3-{n:04d}"
    cols = ["exp", "exp_uid", "base_id", "base_uid", "label", "label_int", "source", "doc_type", "risk_level",
            "carrier_type", "carrier_source", "carrier_id", "carrier_len", "carrier_doc_type", "carrier_n_requests",
            "inj_pair_id", "slot", "position", "insert_offset", "span_subset", "text", "injected_instruction",
            "variant_text_source", "carrier_origin", "notes"]
    rows = [{c: r[c] for c in cols} for r in rows]

    os.makedirs(out_dir, exist_ok=True)
    jp, cp = f"{out_dir}/X3_distractor.jsonl", f"{out_dir}/X3_distractor.csv"
    with open(jp, "w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    with open(cp, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow({k: (json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v) for k, v in r.items()})

    # ---------- validation ----------
    with open(jp, encoding="utf-8") as f:
        back = [json.loads(l) for l in f]
    ids = {r["id"] for r in main_rows}
    assert len(back) == 4 * N
    assert len({r["exp_uid"] for r in back}) == len(back)
    for r in back:
        if r["injected_instruction"] is not None:
            assert r["text"].count(r["injected_instruction"]) == 1
            assert r["base_id"] in ids
    assert len({r["carrier_id"] for r in back}) == 2 * N
    assert len({r["text"] for r in back if r["label"] == "benign"}) == 2 * N
    pairs = Counter(r["inj_pair_id"] for r in back if r["inj_pair_id"])
    assert set(pairs.values()) == {2} and len(pairs) == N
    print(Counter((r["carrier_type"], r["label"]) for r in back))
    print("span sources", Counter((r["source"], r["doc_type"]) for r in back if r["label"] == "injection" and r["carrier_source"] == "wiki"))
    for ct in ("unrelated_expository", "instruction_dense"):
        g = [r for r in back if r["carrier_type"] == ct]
        cl = [r["carrier_len"] for r in g if r["label"] == "benign"]
        il = [len(r["text"]) for r in g if r["label"] == "injection"]
        nr = [r["carrier_n_requests"] for r in g if r["label"] == "benign"]
        print(ct, "carrier_len med/min/max", statistics.median(cl), min(cl), max(cl),
              "| inj text len med", statistics.median(il), "| requests med/min", statistics.median(nr), min(nr))
    sl = [len(r["injected_instruction"]) for r in back if r["injected_instruction"]]
    print("span len med", statistics.median(sl), min(sl), max(sl))
    print("enron splits", Counter(r["carrier_origin"]["split"] for r in back if r["carrier_source"] == "enron" and r["label"] == "benign"))
    if dump:
        with open(dump, "w", encoding="utf-8") as f:
            for r in back:
                f.write(f"===== {r['exp_uid']} {r['carrier_id']} {r['label']} span={r['base_uid']} req={r['carrier_n_requests']}\n{r['text']}\n\n")


if __name__ == "__main__":
    main()
