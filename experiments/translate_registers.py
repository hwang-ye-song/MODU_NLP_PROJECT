"""② 말투 실험의 "번역 후 판정"(PLAN E4): registers 데이터의 한국어 7개 말투 1,547행을 opus-mt-ko-en으로 영어로 옮긴다.

Reuses experiments/translate_ko.py unchanged (imported): the same model (Helsinki-NLP/opus-mt-ko-en), the same
segmentation (only Hangul spans are translated; quotes, brackets, URLs, e-mail addresses and newlines are copied
as-is; long spans cut at sentence ends), the same batching and beam 4, so the result is comparable with
results/02_korean_mt/. Two differences, both forced by this data:
  1. Output cap. translate_ko allows 512 new tokens for every segment. Here the quote rule cuts many one-syllable
     particles out of the text ('접근 허용'이라고 -> ' / 접근 허용 / ' / 이라고 ...; 2,100 unique segments, the
     shortest are 은, 는, 을, 를, 야). On such inputs opus-mt can run to the cap, and a batch then decodes 512 steps x 4
     beams x 32 segments: on 11/12 that ran out of the 8 GB GPU on the first batch and produced 0 segments in 17
     minutes on the (saturated) CPU. The cap here is min(512, 3 x input tokens + 10) per batch; a normal translation
     never reaches it, and every segment that does is marked hit_cap in segment_cache.jsonl.
  2. CPU fallback after a CUDA out-of-memory error reloads the model on the CPU (moving the broken CUDA model fails).

    MT_DEVICE=cpu python experiments/translate_registers.py   # needs torch + transformers (the .venv-mt environment)
        -> results/02b_korean_registers/translation/registers_ko_to_en.jsonl  (one line per Korean row)
           results/02b_korean_registers/translation/segment_cache.jsonl       (every translated segment; resumable)

MT_DEVICE=cpu|cuda (default cuda when available). The device actually used is written on every output line.

The English register rows (the untranslated upstream source) are not translated; they are the paired English
reference. Output lines are keyed by uid ("<id>-<register>", same uid as in results/02b_korean_registers/) and the
md5 of the Korean text; rerunning translates only new or changed rows.
"""
import datetime as dt
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import translate_ko as TK  # noqa: E402  (pieces, split_sentences, HANGUL, md5, MODEL)

REPO = os.path.dirname(HERE)
SRC = os.path.join(REPO, "results", "02b_korean_registers", "inputs", "dataset.jsonl")
OUT_DIR = os.path.join(REPO, "results", "02b_korean_registers", "translation")
OUT = os.path.join(OUT_DIR, "registers_ko_to_en.jsonl")
SEG_CACHE = os.path.join(OUT_DIR, "segment_cache.jsonl")
BEAMS, MAX_NEW, MAX_IN = 4, 512, 512  # same as translate_ko.translate()
CAP_MULT, CAP_ADD = 3, 10             # per-batch output cap: min(MAX_NEW, CAP_MULT x input tokens + CAP_ADD)


def uid(r):
    return f"{r['id']}-{r['register']}"


def korean_rows():
    rows = [json.loads(l) for l in open(SRC, encoding="utf-8") if l.strip()]
    return [r for r in rows if r["lang"] == "ko"]


def plan_row(text):
    """translate_ko's segmentation: list of (False, verbatim) or (True, (lead, sentences, trail))."""
    segs = []
    for is_t, s in TK.pieces(text):
        if not is_t:
            segs.append((False, s))
            continue
        lead, trail, core = s[:len(s) - len(s.lstrip())], s[len(s.rstrip()):], s.strip()
        segs.append((True, (lead, TK.split_sentences(core), trail)))
    return segs


def render(segs, cache):
    out = []
    for is_t, s in segs:
        if not is_t:
            out.append(s)
        else:
            lead, ss, trail = s
            out.append(lead + " ".join(cache[x].strip() for x in ss) + trail)
    return "".join(out)


def main():
    rows = korean_rows()
    done = set()
    if os.path.exists(OUT):
        for l in open(OUT, encoding="utf-8"):
            r = json.loads(l)
            done.add((r["uid"], r["source_md5"]))
    todo = [r for r in rows if (uid(r), TK.md5(r["text"])) not in done]
    print(f"{len(rows)} Korean register rows, {len(todo)} to translate")
    if not todo:
        return
    import torch
    from huggingface_hub import model_info
    from transformers import MarianMTModel, MarianTokenizer

    dev = os.environ.get("MT_DEVICE") or ("cuda" if torch.cuda.is_available() else "cpu")
    tok = MarianTokenizer.from_pretrained(TK.MODEL)
    model = MarianMTModel.from_pretrained(TK.MODEL).to(dev).eval()
    try:
        revision = model_info(TK.MODEL).sha
    except Exception:
        revision = None

    plans = {uid(r): plan_row(r["text"]) for r in todo}
    cache = {}
    for segs in plans.values():
        for is_t, s in segs:
            if is_t:
                for x in s[1]:
                    cache.setdefault(x, None)
    os.makedirs(OUT_DIR, exist_ok=True)
    if os.path.exists(SEG_CACHE):
        for l in open(SEG_CACHE, encoding="utf-8"):
            c = json.loads(l)
            if c["src"] in cache:
                cache[c["src"]] = c["en"]
    pending = sorted((s for s in cache if cache[s] is None), key=len)
    print(f"{len(cache)} unique Korean segments, {len(pending)} not cached yet (device {dev})", flush=True)
    batches, cur, size = [], [], 0
    for s in pending:  # same batching rule as translate_ko (<= 32 segments, ~2,500 source characters)
        if cur and (size + len(s) > 2500 or len(cur) >= 32):
            batches.append(cur)
            cur, size = [], 0
        cur.append(s)
        size += len(s)
    if cur:
        batches.append(cur)
    t0, n, state = time.time(), 0, {"dev": dev}

    def translate(batch):
        enc = tok(batch, return_tensors="pt", padding=True, truncation=True, max_length=MAX_IN).to(state["dev"])
        n_in = enc["attention_mask"].sum(1).tolist()
        cap = min(MAX_NEW, CAP_MULT * max(n_in) + CAP_ADD)
        with torch.no_grad():
            gen = state["model"].generate(**enc, num_beams=BEAMS, max_new_tokens=cap)
        n_out = (gen != tok.pad_token_id).sum(1).tolist()  # includes </s> when the model stopped by itself
        outs = tok.batch_decode(gen, skip_special_tokens=True)
        return [(t, a, b, cap, b >= cap) for t, a, b in zip(outs, n_in, n_out)]

    state["model"] = model
    with open(SEG_CACHE, "a", encoding="utf-8") as cf:
        stack = list(reversed(batches))
        while stack:
            batch = stack.pop()
            try:
                outs = translate(batch)
            except Exception as e:  # a CUDA OOM finishes the rest on the CPU (fresh model: the CUDA one is unusable)
                if state["dev"] != "cuda" or "out of memory" not in str(e).lower():
                    raise
                print(f"  CUDA out of memory after {n} segments; continuing on CPU", flush=True)
                state["dev"] = "cpu"
                state["model"] = MarianMTModel.from_pretrained(TK.MODEL).to("cpu").eval()
                stack.append(batch)
                continue
            for s, (t, a, b, cap, hit) in zip(batch, outs):
                cache[s] = t
                cf.write(json.dumps({"src": s, "en": t, "in_tokens": a, "out_tokens": b, "cap": cap, "hit_cap": hit,
                                     "device": state["dev"]}, ensure_ascii=False) + "\n")
            cf.flush()
            n += len(batch)
            print(f"  {n}/{len(pending)} segments ({time.time() - t0:.0f}s, {state['dev']})", flush=True)
    with open(OUT, "a", encoding="utf-8") as f:
        for r in todo:
            text_en = render(plans[uid(r)], cache)
            f.write(json.dumps({"uid": uid(r), "id": r["id"], "register": r["register"], "label": r["label"],
                                "source_md5": TK.md5(r["text"]), "text_en": text_en,
                                "hangul_left": len(TK.HANGUL.findall(text_en)), "model": TK.MODEL,
                                "model_revision": revision,
                                "device": dev if state["dev"] == dev else f"{dev}->{state['dev']}", "num_beams": BEAMS,
                                "max_new_tokens_rule": f"min({MAX_NEW}, {CAP_MULT} x input tokens + {CAP_ADD}) per batch",
                                "translated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")},
                               ensure_ascii=False) + "\n")
    print(f"wrote {len(todo)} translations to {os.path.relpath(OUT, REPO)} in {time.time() - t0:.0f}s")


if __name__ == "__main__":
    main()
