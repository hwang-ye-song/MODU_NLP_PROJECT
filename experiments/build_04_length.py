"""④ 길이 (04_length) 입력 생성: 위키백과 긴 정상 문서 속에 인젝션 한 문장을 묻고 문서 길이만 바꾼다. API를 부르지 않는다.

    python experiments/build_04_length.py            # results/04_length/inputs/ 를 다시 만듦 (결정적, seed 42)

PLAN D단계, RQ2 (문서가 길어져 인젝션이 묻히면 탐지율이 떨어지는가). Jev 공식 문서는 관련 없는 내용이 많은 긴 입력에서
정확도가 떨어진다고 적는다 ("context rot").

입력 (읽기만 함)
  data/injection_eval/en/dataset_en_1000.jsonl   인젝션 행의 injected_instruction (span)
  ../sim/raw/en_wiki.jsonl                        wikimedia/wikipedia 20231101.en 323개 문서 (sim/fetch_corpora.py가
                                                  HF datasets-server rows API로 받은 것). 파일이 없으면 같은 방법·같은
                                                  offset으로 다시 받는다 (--wiki 경로에 저장). md5로 같은 파일인지 확인.
출력 (results/04_length/inputs/)
  length_docs.jsonl     판정할 문서 920개 (아래 설계). uid, label, label_int, span_id, base_uid, source, risk_level,
                        carrier_id, target_chars, actual_chars, position, insert_offset, text, carrier_urls 외 메타데이터
  spans.csv             고른 span 40개
  CARRIERS.md           carrier stream별 위키백과 문서 제목·URL (CC BY-SA 4.0 출처 표시)
  build_report.json     제외 사유별 개수, 파일 md5, API 비용 사전 추정

설계
  - carrier: 위키백과 문서만. 문서 단위 제외: 제목이 목록·동음이의 문서, AI·assistant·chatbot·prompt 언급(RE_AI),
    독자에게 하는 2인칭 지시(RE_2P: you should/must/…, please, click …). 본문에서 참고문헌류 절(See also, References …)
    부터 뒤를 버리고, 산문 문단(60자 이상, 8단어 이상, 문장부호로 끝남, 표·목록 아님)만 순서대로 빈 줄로 잇는다.
  - stream 40개: 문서를 통째로 이어 붙인 텍스트, 각 STREAM_MIN(65,000)자 이상. 문서는 한 stream에만 들어간다.
    어떤 문서를 어느 stream에 넣을지는 bin covering 탐욕법으로 정하고(공급이 빠듯해 넘치는 양을 줄이려고),
    stream 안 문서 순서는 seed 42로 섞는다 (그래서 짧은 carrier가 어느 문서의 앞부분인지는 무작위).
  - carrier 길이 2,000 / 4,000 / 8,000 / 16,000 / 32,000 / 64,000자: 같은 stream의 앞부분(prefix)을 목표 길이에 가장
    가까운 문장 끝에서 자른다. 그래서 내용은 겹쳐 들어가고(nested) 길이만 바뀐다.
  - span 40개: EN 인젝션 행의 injected_instruction 중 20–300자, 한 줄, 본문에 정확히 1번, 앞뒤 공백 없음.
    3-gram Jaccard 0.7 이상인 중복 제외. 출처별 균등 배분(6개씩 + 쓸 수 있는 span이 많은 4개 출처에 1개씩 더).
    span i는 stream i와 짝.
  - 조건: span 단독(길이 0) / 길이 2k–32k × 위치 앞·중간·끝 / 64k는 중간만 (예산). 정상 대조: 모든 길이의 깨끗한 carrier.
  - 삽입: span을 그대로(byte 단위) 독립 문장으로 넣는다. 앞 = 0번 글자(span + " " + carrier), 끝 = carrier + " " + span,
    중간 = carrier 길이의 50%에 가장 가까운 문장 시작 위치(span + " " + 그 문장). insert_offset은 최종 텍스트에서 span이
    시작하는 글자 위치. 나머지 텍스트는 carrier와 byte 단위로 같다 (스크립트가 확인).
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter, defaultdict

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
EN = os.path.join(REPO, "data", "injection_eval", "en", "dataset_en_1000.jsonl")
EN_MD5 = "df3de0ffa401f34496a953f1836d39d1"
WIKI_MD5 = "7b907cf3cd90c26dfe78883746a154d9"           # sim/raw/en_wiki.jsonl used for the committed inputs
LENGTH_DOCS_MD5 = "01a63155a40e3d06ff6d181fc60bd03b"    # results/04_length/inputs/length_docs.jsonl judged by the API
WIKI_DEFAULT = os.path.join(os.path.dirname(REPO), "sim", "raw", "en_wiki.jsonl")
OUT = os.path.join(REPO, "results", "04_length", "inputs")

# sim/fetch_corpora.py, en_wiki row (dataset, config, offsets, length filter) - reproduced here for a clean clone
WIKI_DS, WIKI_CFG = "wikimedia/wikipedia", "20231101.en"
WIKI_OFFSETS = range(0, 200000, 20000)
WIKI_ROWS_PER_OFFSET = 100
WIKI_MIN, WIKI_MAX = 4000, 60000

SEED = 42
N = 40
TARGETS = (2000, 4000, 8000, 16000, 32000, 64000)
POSITIONS = {2000: ("start", "middle", "end"), 4000: ("start", "middle", "end"), 8000: ("start", "middle", "end"),
             16000: ("start", "middle", "end"), 32000: ("start", "middle", "end"), 64000: ("middle",)}
STREAM_MIN = 65000            # >= 64,000 plus slack so the 64k cut can land on either side of the target
SPAN_MIN, SPAN_MAX = 20, 300
PRICE_IN = 0.042 / 1e6        # USD per input token
EST_OVERHEAD = {"Q2": 300, "QL": 300 + 178}   # tokens per call besides the text (brief: chars/4 + 300, QL +178)
REPEATS = 3

RE_AI = re.compile(r"(?i)\bA\.I\.|\bAI\b|artificial intelligence|chat ?bots?|language models?|\bLLMs?\b|\bGPT"
                   r"|system prompt|\bassistants?\b|\bbots?\b|machine learning|neural networks?|\bprompts?\b")
RE_2P = re.compile(r"(?i)\byou (?:should|must|need|can|will|may|might|could|have to|are advised)\b|\bplease\b|\bclick"
                   r"|\blet me know\b|\bmake sure\b|\bdon't forget\b")
RE_TRAIL = re.compile(r"(?im)^[ \t]*(See also|References|Notes|Footnotes|Further reading|External links|Bibliography"
                      r"|Sources|Citations|Works cited|Notes and references|References and notes)[ \t]*$")
BAD_TITLE = ("list of", "lists of", "index of", "outline of", "timeline of", "glossary")

# sentence splitting (same abbreviation guard as data/injection_eval/_build/scripts/x3/build.py, but the sentence end
# keeps closing quotes/brackets so a cut never leaves a quote open)
ABBR = re.compile(r"(?:\b(?:Mr|Mrs|Ms|Dr|St|Jr|Sr|Mt|Ft|vs|etc|e\.g|i\.e|c|ca|cf|al|No|Vol|pp|Inc|Ltd|Co|Corp|Gen|Gov|Sen"
                  r"|Rev|Prof|Capt|Col|Lt|Sgt|Fig|approx|U\.S|U\.K|U\.N|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)"
                  r"|\b[A-Z])\.$")
SENT_GAP = re.compile(r"(?<=[.!?])([\"”')\]]*)(\s+)(?=[A-Z\"“(])")
PROSE_END = re.compile(r"[.!?][\"”')\]]*$")


def md5_file(path):
    with open(path, "rb") as f:
        return hashlib.md5(f.read()).hexdigest()


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(l) for l in f if l.strip()]


def sentences(par):
    """(start, end) offsets of the sentences of a prose paragraph; end includes closing quotes/brackets."""
    out, start = [], 0
    for m in SENT_GAP.finditer(par):
        left = par[start:m.start()]
        if ABBR.search(left) or re.search(r"\b[A-Z]\.[A-Z]\.$", left):
            continue
        out.append((start, m.start() + len(m.group(1))))
        start = m.end()
    out.append((start, len(par)))
    return out


# ------------------------------------------------------------------ wiki source
def fetch_wiki(path):
    """Re-download the en_wiki rows exactly as sim/fetch_corpora.py did (same offsets, filter and JSON layout)."""
    kept = []
    for off in WIKI_OFFSETS:
        q = urllib.parse.urlencode({"dataset": WIKI_DS, "config": WIKI_CFG, "split": "train", "offset": off,
                                    "length": WIKI_ROWS_PER_OFFSET})
        rows = []
        for attempt in range(5):
            try:
                with urllib.request.urlopen("https://datasets-server.huggingface.co/rows?" + q, timeout=60) as r:
                    rows = [x["row"] for x in json.loads(r.read())["rows"]]
                break
            except Exception as e:  # 502s happen; back off and retry
                print(f"  retry offset {off}: {e}", file=sys.stderr)
                time.sleep(3 * (attempt + 1))
        for r in rows:
            t = (r.get("text") or "").strip()
            if WIKI_MIN <= len(t) <= WIKI_MAX:
                kept.append({"src": "en_wiki", "lang": "en", "text": t, "url": r.get("url") or r.get("title") or ""})
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for k in kept:
            f.write(json.dumps(k, ensure_ascii=False) + "\n")
    print(f"fetched {len(kept)} wiki rows -> {path}")


def clean_articles(docs):
    """Article-level exclusion, then prose paragraphs of the article body (before the reference sections)."""
    arts, rej, seen = [], Counter(), set()
    for line_no, d in enumerate(docs):
        url = d["url"]
        title = urllib.parse.unquote(url.rsplit("/", 1)[-1])
        if url in seen:
            rej["duplicate_url"] += 1
            continue
        seen.add(url)
        if "disambiguation" in title.lower() or title.lower().startswith(BAD_TITLE):
            rej["title_list_or_disambiguation"] += 1
            continue
        t = d["text"]
        if RE_AI.search(t):
            rej["mentions_ai_assistant_chatbot_prompt"] += 1
            continue
        if RE_2P.search(t):
            rej["second_person_instruction"] += 1
            continue
        m = RE_TRAIL.search(t)
        body = t[:m.start()] if m else t
        pars = []
        for p in body.split("\n"):
            p = p.strip()
            if (len(p) >= 60 and len(p.split()) >= 8 and PROSE_END.search(p) and "|" not in p
                    and re.match(r"[\w\"“'(]", p)):
                pars.append(p)
        if sum(len(p) for p in pars) < 1000:
            rej["under_1000_prose_chars"] += 1
            continue
        arts.append({"title": title, "url": url, "wiki_line": line_no, "pars": pars,
                     "chars": len("\n\n".join(pars)), "raw_chars": len(t)})
    return arts, rej


def pack_streams(arts, rng):
    """Bin covering: every stream >= STREAM_MIN chars, each article in at most one stream, little overflow.
    Largest articles are spread first (each to the currently shortest open stream); each stream is then closed with
    the smallest remaining article that brings it over STREAM_MIN (or the largest one if none does)."""
    pool = sorted(arts, key=lambda a: (-a["chars"], a["url"]))
    streams = [[] for _ in range(N)]
    size = [0] * N

    def length(i):  # joined length with "\n\n" between articles
        return size[i] + 2 * max(0, len(streams[i]) - 1)

    while True:
        open_ = [i for i in range(N) if length(i) < STREAM_MIN]
        if not open_:
            break
        if not pool:
            sys.exit(f"not enough wiki text: {len(open_)} streams under {STREAM_MIN} chars - fetch more rows")
        i = min(open_, key=lambda k: (length(k), k))
        need = STREAM_MIN - length(i) - (2 if streams[i] else 0)
        closers = [a for a in pool if a["chars"] >= need]
        # spread big articles while the stream is far from full; close it with the smallest article that fits
        a = min(closers, key=lambda x: (x["chars"], x["url"])) if closers and need < 2 * pool[0]["chars"] else pool[0]
        pool.remove(a)
        streams[i].append(a)
        size[i] += a["chars"]
    for s in streams:
        rng.shuffle(s)
    order = list(range(N))
    rng.shuffle(order)
    return [streams[i] for i in order], pool


def stream_text(arts):
    """Join articles; return text, paragraph spans [(start, end, article_index)], article starts."""
    text, pars, starts = "", [], []
    for ai, a in enumerate(arts):
        if text:
            text += "\n\n"
        starts.append(len(text))
        for pi, p in enumerate(a["pars"]):
            if pi:
                text += "\n\n"
            pars.append((len(text), len(text) + len(p), ai))
            text += p
    return text, pars, starts


def sentence_bounds(text, pars):
    """Sentence starts and ends (absolute offsets) over all prose paragraphs of a stream."""
    starts, ends = [], []
    for a, b, _ in pars:
        for s, e in sentences(text[a:b]):
            starts.append(a + s)
            ends.append(a + e)
    return starts, ends


# ------------------------------------------------------------------ spans
def word_ngrams(s, n=3):
    w = re.findall(r"\w+", s.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def pick_spans(rows, rng):
    pool, rej = defaultdict(list), Counter()
    for r in rows:
        if r["label_int"] != 1:
            continue
        s = r.get("injected_instruction")
        if not isinstance(s, str) or not s:
            rej["no_span"] += 1
        elif not (SPAN_MIN <= len(s) <= SPAN_MAX):
            rej["length"] += 1
        elif "\n" in s or "\r" in s:
            rej["multi_line"] += 1
        elif r["text"].count(s) != 1:
            rej["not_exactly_once"] += 1
        elif s != s.strip():
            rej["edge_whitespace"] += 1
        else:
            pool[r["source"]].append(r)
    # de-duplicate within each source in seeded order (3-gram Jaccard >= 0.7 with an earlier kept span)
    usable, seen = {}, []
    for src in sorted(pool):
        g = sorted(pool[src], key=lambda r: r["uid"])
        rng.shuffle(g)
        keep = []
        for r in g:
            gs = word_ngrams(r["injected_instruction"])
            if any(len(gs & h) / max(1, len(gs | h)) >= 0.7 for h in seen):
                rej["near_duplicate"] += 1
                continue
            seen.append(gs)
            keep.append(r)
        usable[src] = keep
    # equal allocation: N // n_sources each, the remainder to the sources with the most usable spans
    srcs = sorted(usable)
    quota = {s: N // len(srcs) for s in srcs}
    for s in sorted(srcs, key=lambda s: (-len(usable[s]), s))[:N - sum(quota.values())]:
        quota[s] += 1
    chosen = []
    for s in srcs:
        assert len(usable[s]) >= quota[s], (s, len(usable[s]), quota[s])
        chosen += usable[s][:quota[s]]
    rng.shuffle(chosen)
    return chosen, {s: len(usable[s]) for s in srcs}, quota, rej


# ------------------------------------------------------------------ build
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--wiki", default=WIKI_DEFAULT, help="en_wiki.jsonl from sim/fetch_corpora.py (fetched if missing)")
    args = ap.parse_args()

    assert md5_file(EN) == EN_MD5, "dataset_en_1000.jsonl changed"
    if not os.path.exists(args.wiki):
        fetch_wiki(args.wiki)
    wiki_md5 = md5_file(args.wiki)
    if wiki_md5 != WIKI_MD5:
        print(f"WARNING: {args.wiki} md5 {wiki_md5} differs from the file used for the committed inputs ({WIKI_MD5})",
              file=sys.stderr)

    rows = load_jsonl(EN)
    spans, usable, quota, span_rej = pick_spans(rows, random.Random(SEED))
    arts, art_rej = clean_articles(load_jsonl(args.wiki))
    streams, unused = pack_streams(arts, random.Random(SEED))

    docs, carriers_md, span_rows = [], [], []
    for i, (sp, arts_i) in enumerate(zip(spans, streams), 1):
        sid, cid = f"S{i:02d}", f"C{i:02d}"
        span = sp["injected_instruction"]
        text, pars, art_starts = stream_text(arts_i)
        assert len(text) >= STREAM_MIN and text == text.strip()
        s_starts, s_ends = sentence_bounds(text, pars)
        span_meta = {"span_id": sid, "base_uid": sp["uid"], "base_id": sp["id"], "source": sp["source"],
                     "subset": sp.get("subset"), "doc_type": sp["doc_type"], "risk_level": sp["risk_level"],
                     "harm_type": sp.get("harm_type"), "injected_instruction": span, "span_chars": len(span),
                     "span_terminal_punct": bool(PROSE_END.search(span))}
        span_rows.append({**span_meta, "carrier_id": cid})
        # span alone (length 0)
        docs.append({"uid": f"LEN-I-{i:02d}-00k-alone", "label": "injection", "label_int": 1, **span_meta,
                     "carrier_id": None, "target_chars": 0, "actual_chars": 0, "position": "alone", "insert_offset": 0,
                     "rel_insert": None, "n_articles": 0, "text_chars": len(span), "carrier_urls": [], "text": span})
        for tgt in TARGETS:
            cut = min(s_ends, key=lambda e: (abs(e - tgt), e))
            carrier = text[:cut]
            assert carrier == carrier.rstrip() and cut in s_ends
            urls = [a["url"] for a, st in zip(arts_i, art_starts) if st < cut]
            common = {"carrier_id": cid, "target_chars": tgt, "actual_chars": len(carrier), "n_articles": len(urls),
                      "carrier_urls": urls}
            docs.append({"uid": f"LEN-B-{i:02d}-{tgt // 1000:02d}k", "label": "benign", "label_int": 0,
                         "span_id": None, "base_uid": None, "base_id": None, "source": "Wikipedia", "subset": None,
                         "doc_type": "wiki", "risk_level": 0, "harm_type": None, "injected_instruction": None,
                         "span_chars": None, "span_terminal_punct": None, **common, "position": None,
                         "insert_offset": None, "rel_insert": None, "text_chars": len(carrier), "text": carrier})
            for pos in POSITIONS[tgt]:
                if pos == "start":
                    off, new = 0, span + " " + carrier
                elif pos == "end":
                    off, new = len(carrier) + 1, carrier + " " + span
                else:
                    off = min((s for s in s_starts if 0 < s < len(carrier)), key=lambda s: (abs(s - len(carrier) / 2), s))
                    new = carrier[:off] + span + " " + carrier[off:]
                assert new[off:off + len(span)] == span and new.count(span) == 1
                docs.append({"uid": f"LEN-I-{i:02d}-{tgt // 1000:02d}k-{pos}", "label": "injection", "label_int": 1,
                             **span_meta, **common, "position": pos, "insert_offset": off,
                             "rel_insert": round(off / len(carrier), 4), "text_chars": len(new), "text": new})
        carriers_md.append((cid, sid, arts_i, art_starts, len(text)))

    # exact-removal check: taking the span (and its joining space) out gives back the clean carrier of that length
    clean = {(d["carrier_id"], d["target_chars"]): d["text"] for d in docs if d["label_int"] == 0}
    for d in docs:
        if d["label_int"] == 1 and d["position"] != "alone":
            o, s = d["insert_offset"], d["injected_instruction"]
            back = d["text"][:o - 1] + d["text"][o + len(s):] if d["position"] == "end" else d["text"][:o] + d["text"][o + len(s) + 1:]
            assert back == clean[(d["carrier_id"], d["target_chars"])], d["uid"]
    # nesting check: every shorter carrier is a prefix of the longer ones of the same stream
    for i in range(1, N + 1):
        cs = [clean[(f"C{i:02d}", t)] for t in TARGETS]
        assert all(cs[k + 1].startswith(cs[k]) for k in range(len(cs) - 1))
    assert len({d["uid"] for d in docs}) == len(docs)

    os.makedirs(OUT, exist_ok=True)
    with open(os.path.join(OUT, "length_docs.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for d in docs:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    with open(os.path.join(OUT, "spans.csv"), "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(span_rows[0].keys()))
        w.writeheader()
        w.writerows(span_rows)

    # attribution file
    md = ["# 04_length carrier 출처 (Wikipedia, CC BY-SA 4.0)", "",
          "이 실험의 carrier 텍스트는 영어 위키백과 문서에서 왔습니다. 위키백과 텍스트는 "
          "[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) 라이선스이며, 저작자는 각 문서의 기여자들입니다 "
          "(각 URL의 '역사' 탭).", "",
          f"- 원본: Hugging Face `{WIKI_DS}` 설정 `{WIKI_CFG}` (2023-11-01 덤프). HF datasets-server rows API, train split, "
          f"offset {WIKI_OFFSETS.start}–{WIKI_OFFSETS.stop - WIKI_OFFSETS.step} (간격 {WIKI_OFFSETS.step}), offset마다 "
          f"{WIKI_ROWS_PER_OFFSET}행, {WIKI_MIN:,}–{WIKI_MAX:,}자 문서만 (`sim/fetch_corpora.py`). 파일 md5 `{wiki_md5}`.",
          "- **변경 사항**: 참고문헌류 절(See also, References, Notes, Further reading, External links …)부터 뒤를 버렸고, "
          "제목·소제목·목록·표·캡션 줄을 빼고 산문 문단만 남겼습니다. 여러 문서를 빈 줄로 이어 붙였고, 길이별로 문장 끝에서 "
          "잘랐습니다. 인젝션 행에는 실험용 지시문 한 문장을 넣었습니다 (위키백과 원문이 아님).",
          "- 각 stream의 문서는 아래 순서대로 이어집니다. `prose chars`는 정리 후 그 문서가 차지하는 글자 수, "
          "`first in carrier`는 그 문서가 처음 들어가는 carrier 길이입니다 (64k 밖이면 stream에만 있고 판정 문서에는 없음).", ""]
    for cid, sid, arts_i, art_starts, total in carriers_md:
        md += [f"## {cid} (span {sid}, stream {total:,}자)", "", "| # | 제목 | URL | prose chars | first in carrier |",
               "| --- | --- | --- | --- | --- |"]
        for k, (a, st) in enumerate(zip(arts_i, art_starts), 1):
            first = next((f"{t // 1000}k" for t in TARGETS if st < next(
                d["actual_chars"] for d in docs if d["carrier_id"] == cid and d["target_chars"] == t and d["label_int"] == 0)), "– (64k 밖)")
            md += [f"| {k} | {a['title'].replace('|', '/')} | {a['url']} | {a['chars']:,} | {first} |"]
        md.append("")
    with open(os.path.join(OUT, "CARRIERS.md"), "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(md))

    # budget estimate (brief: chars/4 + 300 per call, QL +178), 3 calls per doc per question
    n_docs = len(docs)
    chars = sum(len(d["text"]) for d in docs)
    est = {q: int(REPEATS * (chars / 4 + n_docs * EST_OVERHEAD[q])) for q in ("Q2", "QL")}
    est_cost = {q: est[q] * PRICE_IN for q in est}
    cnt = Counter((d["label"], d["target_chars"], d["position"]) for d in docs)
    report = {
        "seed": SEED, "n_docs": n_docs, "n_injection": sum(d["label_int"] for d in docs),
        "n_benign": sum(1 - d["label_int"] for d in docs), "text_chars_total": chars,
        "counts": {f"{l}|{t}|{p}": c for (l, t, p), c in sorted(cnt.items(), key=lambda x: (x[0][0], x[0][1], str(x[0][2])))},
        "dataset_en_md5": EN_MD5, "wiki_file": os.path.relpath(args.wiki, REPO).replace("\\", "/"), "wiki_md5": wiki_md5,
        "wiki_source": {"dataset": WIKI_DS, "config": WIKI_CFG, "offsets": list(WIKI_OFFSETS),
                        "rows_per_offset": WIKI_ROWS_PER_OFFSET, "chars_filter": [WIKI_MIN, WIKI_MAX]},
        "wiki_rows": len(load_jsonl(args.wiki)), "articles_kept": len(arts), "articles_rejected": dict(art_rej),
        "articles_used": sum(len(s) for s in streams), "articles_unused": len(unused),
        "stream_chars": [len(stream_text(s)[0]) for s in streams],
        "span_pool_after_dedup": usable, "span_quota": quota, "span_rejected": dict(span_rej),
        "budget_estimate": {"rule": "chars/4 + 300 tokens per call (QL +178), x3 calls", "input_tokens": est,
                            "cost_usd": est_cost, "cost_usd_total": sum(est_cost.values()), "cap_usd": 1.20},
        "length_docs_md5": md5_file(os.path.join(OUT, "length_docs.jsonl")),
    }
    with open(os.path.join(OUT, "build_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print(json.dumps({k: report[k] for k in ("n_docs", "n_injection", "n_benign", "text_chars_total", "articles_kept",
                                            "articles_rejected", "articles_used", "articles_unused", "span_pool_after_dedup",
                                            "span_quota", "budget_estimate")}, ensure_ascii=False, indent=1))
    sc = report["stream_chars"]
    print(f"stream chars min {min(sc):,} median {sorted(sc)[len(sc) // 2]:,} max {max(sc):,}")
    same = report["length_docs_md5"] == LENGTH_DOCS_MD5
    print(f"length_docs.jsonl md5 {report['length_docs_md5']} - same as the inputs the API runs used: {'yes' if same else 'NO'}")


if __name__ == "__main__":
    main()
