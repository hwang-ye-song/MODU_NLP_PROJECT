"""② 한국어 "번역 후 판정": KO 1000 문서를 opus-mt-ko-en으로 영어로 옮긴다 (PLAN E4, 빈틈 3).

Only spans that contain Hangul are translated. Markup and structure stay byte-identical: HTML tags, JSON/dict
brackets and quotes, URLs, e-mail addresses and code-only lines are copied as-is, so the translated document keeps
the shape of the original (a translator that rewrote markup would change what the judge sees for reasons
unrelated to language). Long spans are cut at sentence ends so each piece fits the model's 512-token limit.

    pip install torch transformers sentencepiece sacremoses        # GPU optional; CPU works, just slower
    python experiments/translate_ko.py                              # writes results/02_korean_mt/translation/ko_to_en.jsonl

The output is cached per uid + source-text md5; rerunning only translates new or changed documents.
"""
import datetime as dt
import hashlib
import json
import os
import re
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "data", "injection_eval", "ko", "dataset_ko_1000.jsonl")
OUT = os.path.join(REPO, "results", "02_korean_mt", "translation", "ko_to_en.jsonl")
MODEL = "Helsinki-NLP/opus-mt-ko-en"

HANGUL = re.compile(r"[가-힣ㄱ-ㆎ]")
# Characters that delimit structure; a translatable span never crosses them.
STRUCT = re.compile(r"(<[^>]*>|https?://\S+|[\w.+-]+@[\w-]+\.[\w.-]+|[{}\[\]\"'`|\n\t]|\\n)")
SENT_END = re.compile(r"(?<=[.!?。])\s+|(?<=다\.)|(?<=요\.)")


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def pieces(text):
    """Split into (is_translatable, string) pieces that concatenate back to text exactly."""
    out, last = [], 0
    for m in STRUCT.finditer(text):
        if m.start() > last:
            out.append(text[last:m.start()])
        out.append(("S", m.group(0)))
        last = m.end()
    if last < len(text):
        out.append(text[last:])
    res = []
    for p in out:
        if isinstance(p, tuple):
            res.append((False, p[1]))
        elif HANGUL.search(p):
            res.append((True, p))
        else:
            res.append((False, p))
    return res


def split_sentences(span, max_chars=300):
    parts, buf = [], ""
    for s in SENT_END.split(span):
        if not s:
            continue
        if len(buf) + len(s) > max_chars and buf:
            parts.append(buf)
            buf = ""
        buf += s
    if buf:
        parts.append(buf)
    final = []
    for p in parts:  # very long run-on sentences: cut at spaces
        while len(p) > max_chars * 2:
            cut = p.rfind(" ", 0, max_chars * 2)
            cut = cut if cut > 0 else max_chars * 2
            final.append(p[:cut])
            p = p[cut:]
        final.append(p)
    return final


def main():
    import torch
    from transformers import MarianMTModel, MarianTokenizer
    from huggingface_hub import model_info

    rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    done = {}
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            r = json.loads(l)
            done[(r["uid"], r["source_md5"])] = r
    todo = [r for r in rows if (r["uid"], md5(r["text"])) not in done]
    print(f"{len(rows)} KO documents, {len(todo)} to translate")
    if not todo:
        return
    dev = os.environ.get("MT_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")  # MT_DEVICE=cpu forces CPU
    tok = MarianTokenizer.from_pretrained(MODEL)
    model = MarianMTModel.from_pretrained(MODEL).to(dev).eval()
    try:
        revision = model_info(MODEL).sha
    except Exception:
        revision = None

    # collect every unique sentence to translate
    plan, uniq = {}, {}
    for r in todo:
        segs = []
        for is_t, s in pieces(r["text"]):
            if not is_t:
                segs.append((False, s))
                continue
            lead = s[:len(s) - len(s.lstrip())]
            trail = s[len(s.rstrip()):]
            core = s.strip()
            sents = split_sentences(core)
            for x in sents:
                uniq.setdefault(x, None)
            segs.append((True, (lead, sents, trail)))
        plan[r["uid"]] = segs
    # segment cache: every finished batch is appended, so an interrupted run resumes where it stopped
    seg_cache = os.path.join(os.path.dirname(OUT), "segment_cache.jsonl")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    if os.path.exists(seg_cache):
        for l in open(seg_cache, encoding="utf-8"):
            c = json.loads(l)
            if c["src"] in uniq:
                uniq[c["src"]] = c["en"]
    sents = [s for s in uniq if uniq[s] is None]
    print(f"{len(uniq)} unique Korean segments, {len(sents)} not cached yet")
    t0 = time.time()
    order = sorted(sents, key=len)
    batches, cur, size = [], [], 0
    for s in order:  # cap each batch at ~4,000 source characters (long segments -> small batches)
        if cur and (size + len(s) > 2500 or len(cur) >= 32):
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s)
    if cur:
        batches.append(cur)

    state = {"dev": dev}

    def translate(batch):
        enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=512).to(state["dev"])
        with torch.no_grad():
            gen = model.generate(**enc, num_beams=4, max_new_tokens=512)
        return tok.batch_decode(gen, skip_special_tokens=True)

    done_n = 0
    with open(seg_cache, "a", encoding="utf-8") as cf:
        stack = list(reversed(batches))
        while stack:
            batch = stack.pop()
            try:
                outs = translate(batch)
            except Exception as e:  # a CUDA OOM can surface as OutOfMemoryError or AcceleratorError
                if state["dev"] != "cuda" or "out of memory" not in str(e).lower():
                    raise
                # after a CUDA error the context is not trustworthy: finish the remaining segments on the CPU
                print(f"  CUDA out of memory at {done_n} segments; continuing on CPU", flush=True)
                state["dev"] = "cpu"
                model.to("cpu")
                stack.append(batch)
                continue
            for s, t in zip(batch, outs):
                uniq[s] = t
                cf.write(json.dumps({"src": s, "en": t}, ensure_ascii=False) + "\n")
            cf.flush()
            done_n += len(batch)
            if done_n % 640 < len(batch):
                print(f"  {done_n}/{len(sents)} segments ({time.time() - t0:.0f}s)", flush=True)
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a", encoding="utf-8") as f:
        for r in todo:
            out = []
            for is_t, s in plan[r["uid"]]:
                if not is_t:
                    out.append(s)
                else:
                    lead, ss, trail = s
                    out.append(lead + " ".join(uniq[x].strip() for x in ss) + trail)
            text_en = "".join(out)
            f.write(json.dumps({"uid": r["uid"], "pair_uid": r.get("pair_uid"), "source_md5": md5(r["text"]),
                                "text_en": text_en, "hangul_left": len(HANGUL.findall(text_en)),
                                "model": MODEL, "model_revision": revision, "device": dev if state["dev"] == dev else f"{dev}->{state['dev']}",
                                "translated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
                               ensure_ascii=False) + "\n")
    print(f"wrote {len(todo)} translations to {os.path.relpath(OUT, REPO)} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
