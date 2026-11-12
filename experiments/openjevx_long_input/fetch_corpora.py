"""Fetch benign long-text carriers (web pages, wiki articles, news) via the HF datasets-server rows API.

Writes raw/<name>.jsonl with {"src", "text", "url"}; texts are only data for building test documents.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "raw")
SOURCES = [
    # name, dataset, config, field, lang, offsets, min_chars, max_chars
    ("en_web", "HuggingFaceFW/fineweb", "sample-10BT", "text", "en", range(0, 400000, 20000), 4000, 60000),
    ("en_wiki", "wikimedia/wikipedia", "20231101.en", "text", "en", range(0, 200000, 20000), 4000, 60000),
    ("ko_web", "HuggingFaceFW/fineweb-2", "kor_Hang", "text", "ko", range(0, 400000, 20000), 900, 20000),
    ("ko_wiki", "wikimedia/wikipedia", "20231101.ko", "text", "ko", range(0, 200000, 20000), 900, 20000),
    ("ko_news", "daekeun-ml/naver-news-summarization-ko", "default", "document", "ko", range(0, 20000, 2000), 900, 20000),
]


def rows(ds, cfg, offset, length=100):
    q = urllib.parse.urlencode({"dataset": ds, "config": cfg, "split": "train", "offset": offset, "length": length})
    for attempt in range(5):
        try:
            with urllib.request.urlopen("https://datasets-server.huggingface.co/rows?" + q, timeout=60) as r:
                return [x["row"] for x in json.loads(r.read())["rows"]]
        except Exception as e:  # 502s happen; back off and retry
            print(f"  retry {ds} {offset}: {e}", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    return []


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, ds, cfg, field, lang, offsets, lo, hi in SOURCES:
        path = os.path.join(OUT, name + ".jsonl")
        if os.path.exists(path):
            print("skip", name)
            continue
        kept = []
        for off in offsets:
            for r in rows(ds, cfg, off):
                t = (r.get(field) or "").strip()
                if lo <= len(t) <= hi:
                    kept.append({"src": name, "lang": lang, "text": t, "url": r.get("url") or r.get("title") or ""})
        with open(path, "w", encoding="utf-8") as f:
            for k in kept:
                f.write(json.dumps(k, ensure_ascii=False) + "\n")
        print(name, len(kept), "docs")


if __name__ == "__main__":
    main()
