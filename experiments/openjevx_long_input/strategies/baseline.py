"""Reference strategies every family compares against.

  truncate      what OpenJevX does by itself: one call, the document cut after the first 450 tokens
  window_max    450-token windows with 96-token overlap, document score = max over windows

    python -m strategies.baseline            # runs both on dev and saves results
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from eval_lib import (STATE_BUDGET, chunk_tokens, evaluate, load_docs, print_summary, result,  # noqa: E402
                      save_result, score_nested)


def truncate(docs):
    first = [[chunk_tokens(d["text"], STATE_BUDGET, 0)[0]] for d in docs]
    probs = score_nested(first)
    return [result(p[0], chunks=c) for p, c in zip(probs, first)]


def window_max(docs, window=STATE_BUDGET, overlap=96):
    cl = [chunk_tokens(d["text"], window, overlap) for d in docs]
    probs = score_nested(cl)
    return [result(max(p), chunks=c) for p, c in zip(probs, cl)]


CONFIGS = {"truncate": (truncate, {}), "window_max_450_96": (window_max, {"window": STATE_BUDGET, "overlap": 96})}


def run(docs, name):
    fn, cfg = CONFIGS[name]
    return fn(docs, **cfg)


if __name__ == "__main__":
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    docs = load_docs(split)
    for name, (fn, cfg) in CONFIGS.items():
        out = fn(docs, **cfg)
        m = evaluate(docs, out)
        print_summary(f"baseline:{name}", m)
        save_result(f"baseline:{name}", cfg, m, split=split, owner="baseline",
                    per_doc=[{"id": d["id"], **o} for d, o in zip(docs, out)])
