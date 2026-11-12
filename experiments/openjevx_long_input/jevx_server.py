"""Shared OpenJevX scoring server for the long-input simulations.

One process holds the ONNX model; every experiment talks to it over HTTP so that
many agents can run at once without each loading 600 MB of weights. Scores are
cached in SQLite, keyed by (question, max_len, text), so strategies that produce
the same chunk never pay for it twice.

The prompt layout is a faithful port of openjevx.py (v0.5.2) from the model repo:
[CLS] head [SEP] [MASK]opt0 [MASK]opt1 [SEP] state [SEP], truncated to max_len,
with the state cut from the END (state_ids[:n]).

    python jevx_server.py            # listens on 127.0.0.1:21200
    POST /score  {"texts": [...], "question": "...", "max_len": 512}
       -> {"probs": [...], "state_tokens": [...], "truncated": [...], "cached": k}
    GET  /health -> counters
"""
import hashlib
import json
import math
import os
import sqlite3
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

if os.environ.get("JEVX_IMPORT_TORCH") == "1":
    import torch  # noqa: F401  loads the CUDA/cuDNN DLLs that onnxruntime-gpu needs
import onnxruntime as ort
from tokenizers import Tokenizer

if os.environ.get("JEVX_PRELOAD") == "1":
    ort.preload_dlls()  # CUDA 13 / cuDNN 9 from the nvidia-* pip wheels installed with onnxruntime-gpu[cuda,cudnn]

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL_DIR = os.environ.get("JEVX_MODEL_DIR", os.path.join(HERE, "..", "models", "openjevx"))
PORT = int(os.environ.get("JEVX_PORT", "21200"))
CACHE = os.environ.get("JEVX_CACHE", os.path.join(HERE, "cache", "scores.sqlite"))
BATCH_TOKENS = int(os.environ.get("JEVX_BATCH_TOKENS", "8192"))
ATTN_BUDGET = int(os.environ.get("JEVX_ATTN_BUDGET", str(2 ** 24)))  # cap n * L^2 so long inputs fit in GPU memory
# Simulations use a GPU copy (int8 weights folded to float, fp16 compute; |dP| <= 0.003 vs the release file).
MODEL_FILE = os.environ.get("JEVX_MODEL_FILE", "openjevx.w8.onnx")

CLS, SEP, MASK = 50281, 50282, 50284
NOUL_OPTS = ["false: no, the statement does not hold", "true: yes, the statement holds"]

cfg = json.load(open(os.path.join(MODEL_DIR, "config.json")))
TEMP_NOUL = cfg["temperature"]["noul"]
DEFAULT_MAX_LEN = cfg.get("max_len", 512)
HEAD_MAX = cfg.get("head_max", 256)
tok = Tokenizer.from_file(os.path.join(MODEL_DIR, "tokenizer.json"))

providers = []
for p in [p for p in os.environ.get("JEVX_PROVIDERS", "CPUExecutionProvider").split(",") if p]:
    if p == "CUDAExecutionProvider":  # cap the arena so the GPU never fills up
        providers.append((p, {"gpu_mem_limit": int(float(os.environ.get("JEVX_GPU_GB", "5")) * 1024 ** 3),
                              "arena_extend_strategy": "kSameAsRequested"}))
    else:
        providers.append(p)
so = ort.SessionOptions()
so.log_severity_level = 3
session = ort.InferenceSession(os.path.join(MODEL_DIR, MODEL_FILE), so, providers=providers)
print("model:", os.path.join(MODEL_DIR, MODEL_FILE), "providers:", session.get_providers(), flush=True)

# Every session.run happens on this one thread: the CUDA provider keeps per-thread cuBLAS handles and
# memory, so letting each HTTP request thread call run() exhausts the GPU.
from concurrent.futures import ThreadPoolExecutor  # noqa: E402
_runner = ThreadPoolExecutor(max_workers=1)
run_lock = threading.Lock()
db_lock = threading.Lock()
os.makedirs(os.path.dirname(CACHE), exist_ok=True)
db = sqlite3.connect(CACHE, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL")
db.execute("CREATE TABLE IF NOT EXISTS s (k TEXT PRIMARY KEY, p REAL, n INTEGER)")
db.commit()
stats = {"requests": 0, "texts": 0, "cache_hits": 0, "model_items": 0, "model_seconds": 0.0, "started": time.time()}


def enc(text):
    return tok.encode(text, add_special_tokens=False).ids


_head_cache = {}


def head_ids(question):
    """[CLS] head [SEP] opts [SEP] and marker positions, exactly as openjevx.py builds them."""
    if question in _head_cache:
        return _head_cache[question]
    head = enc("noul question: " + question.replace("[MASK]", " "))
    opts = [[MASK] + enc(" " + o)[:48] for o in NOUL_OPTS]
    budget = HEAD_MAX - sum(map(len, opts))
    head = head[:max(8, budget)]
    ids, markers = [CLS] + head + [SEP], []
    for o in opts:
        markers.append(len(ids))
        ids += o
    ids.append(SEP)
    _head_cache[question] = (ids, markers)
    return ids, markers


def build(question, text, max_len):
    prefix, markers = head_ids(question)
    state = enc(text.replace("[MASK]", " "))
    room = max(0, max_len - len(prefix) - 1)
    ids = (prefix + state[:room] + [SEP])[:max_len]
    return ids, markers, len(state), len(state) > room


def key(question, max_len, text):
    return hashlib.sha1(f"{question}\x00{max_len}\x00{text}".encode("utf-8")).hexdigest()


def run_model(items):
    """items: list of (ids, markers). Returns P(true) per item, batched by length."""
    order = sorted(range(len(items)), key=lambda i: len(items[i][0]))
    out = [None] * len(items)
    i = 0
    while i < len(order):
        L = len(items[order[i]][0])
        j = i
        while j < len(order):
            Lj, k = len(items[order[j]][0]), j - i + 1
            if j > i and (k * Lj > BATCH_TOKENS or k * Lj * Lj > ATTN_BUDGET):
                break
            j += 1
        batch = order[i:j]
        n, length = len(batch), max(len(items[b][0]) for b in batch)
        ids = np.zeros((n, length), np.int64)
        attn = np.zeros((n, length), np.int64)
        pos = np.zeros((n, 2), np.int64)
        pm = np.ones((n, 2), bool)
        qt = np.full((n,), 2, np.int64)
        for r, b in enumerate(batch):
            t, m = items[b]
            ids[r, :len(t)] = t
            attn[r, :len(t)] = 1
            pos[r] = m
        t0 = time.perf_counter()
        feeds = {"input_ids": ids, "attention_mask": attn, "marker_pos": pos, "marker_mask": pm, "qtype": qt}
        logits, _ = _runner.submit(session.run, ["logits", "act_logits"], feeds).result()
        stats["model_seconds"] += time.perf_counter() - t0
        stats["model_items"] += n
        for r, b in enumerate(batch):
            z0, z1 = float(logits[r, 0]) / TEMP_NOUL, float(logits[r, 1]) / TEMP_NOUL
            m = max(z0, z1)
            e0, e1 = math.exp(z0 - m), math.exp(z1 - m)
            out[b] = e1 / (e0 + e1)
        i = j
    return out


def score(texts, question, max_len):
    keys = [key(question, max_len, t) for t in texts]
    probs, ntok, trunc = [None] * len(texts), [0] * len(texts), [False] * len(texts)
    with db_lock:
        found = {}
        uniq = list(set(keys))
        for s in range(0, len(uniq), 500):
            part = uniq[s:s + 500]
            q = "SELECT k, p, n FROM s WHERE k IN (%s)" % ",".join("?" * len(part))
            for k, p, n in db.execute(q, part):
                found[k] = (p, n)
    todo = {}
    for i, k in enumerate(keys):
        if k in found:
            probs[i], ntok[i] = found[k]
            stats["cache_hits"] += 1
        else:
            todo.setdefault(k, []).append(i)
    if todo:
        ks = list(todo)
        built = [build(question, texts[todo[k][0]], max_len) for k in ks]
        ps = run_model([(b[0], b[1]) for b in built])
        rows = []
        for k, b, p in zip(ks, built, ps):
            for i in todo[k]:
                probs[i], ntok[i] = p, b[2]
            rows.append((k, p, b[2]))
        with db_lock:
            db.executemany("INSERT OR REPLACE INTO s VALUES (?,?,?)", rows)
            db.commit()
    prefix_len = len(head_ids(question)[0])
    for i in range(len(texts)):
        trunc[i] = ntok[i] > max(0, max_len - prefix_len - 1)
    return probs, ntok, trunc


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path.startswith("/health"):
            s = dict(stats)
            s["uptime_s"] = round(time.time() - s.pop("started"), 1)
            s["ms_per_model_item"] = round(1000 * s["model_seconds"] / max(1, s["model_items"]), 1)
            s["providers"] = session.get_providers()
            s["model_file"] = MODEL_FILE
            s["default_max_len"] = DEFAULT_MAX_LEN
            self._send(200, s)
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        if not self.path.startswith("/score"):
            return self._send(404, {"error": "not found"})
        try:
            req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            texts = req["texts"]
            question = req["question"]
            max_len = int(req.get("max_len", DEFAULT_MAX_LEN))
            if not isinstance(texts, list) or not all(isinstance(t, str) for t in texts):
                raise ValueError("texts must be a list of strings")
            if max_len < 64 or max_len > 4096:
                raise ValueError("max_len must be in [64, 4096] (8192 does not fit in this GPU's memory)")
            stats["requests"] += 1
            stats["texts"] += len(texts)
            probs, ntok, trunc = score(texts, question, max_len)
            self._send(200, {"probs": probs, "state_tokens": ntok, "truncated": trunc})
        except Exception as e:  # report, never crash the server
            self._send(400, {"error": f"{type(e).__name__}: {e}"})


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    print(f"jevx server ready on 127.0.0.1:{PORT}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        sys.exit(0)
