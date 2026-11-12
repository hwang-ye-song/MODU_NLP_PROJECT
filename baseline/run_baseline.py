"""① 기준선: 공식 Jev API로 EN 1,000건(+ 과탐지 참고 NotInject 25건)을 Q2 질문 하나로 판정하고, 응답을 전부 저장한다.

요청 본문은 src/jev_guard.py의 judge()와 똑같다 (model=jev-1.14.0, noul 질문 하나, instructions=Q2).
judge()는 확률만 돌려주므로, 원본 응답·지연시간·토큰 사용량·요청 ID를 남기려고 같은 요청을 여기서 직접 보낸다.
실행 시작 시 몇 건을 judge()로도 불러 p가 같은지 확인한다.

    # 레포 루트에서. API 키는 환경변수 TYPESAFE_API_KEY 또는 상위 폴더의 .env 파일에서 읽는다 (출력하지 않음).
    python baseline/run_baseline.py                      # 이미 받은 건은 건너뛰고 이어서 실행
    python baseline/run_baseline.py --limit 20           # 시험 삼아 20건만

출력: baseline/results/raw_responses.jsonl (한 줄 = 요청 한 번. 다시 실행해도 이미 성공한 문서는 다시 부르지 않음)
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
sys.path.insert(0, REPO)
from src.jev_guard import API_URL, INJECTION_QUESTION, MODEL  # noqa: E402  (same constants as judge())

DATA = {
    "EN": os.path.join(REPO, "data", "injection_eval", "en", "dataset_en_1000.jsonl"),
    "NOTINJECT": os.path.join(REPO, "data", "injection_eval", "en", "overdefense_ref_notinject.jsonl"),
}
OUT = os.path.join(HERE, "results", "raw_responses.jsonl")
QUESTION_ID = "Q2"
_lock = threading.Lock()


def api_key():
    if os.environ.get("TYPESAFE_API_KEY"):
        return os.environ["TYPESAFE_API_KEY"]
    d = os.getcwd()
    for _ in range(5):  # look for a .env in this folder or its parents
        p = os.path.join(d, ".env")
        if os.path.exists(p):
            for line in open(p, encoding="utf-8"):
                if line.strip().startswith("TYPESAFE_API_KEY="):
                    v = line.split("=", 1)[1].strip().strip('"').strip("'")
                    if v:
                        return v
        d = os.path.dirname(d)
    sys.exit("TYPESAFE_API_KEY not found (env var or .env)")


def md5(s):
    return hashlib.md5(s.encode("utf-8")).hexdigest()


def body(text):
    return {"model": MODEL, "state": text,
            "questions": {"injection": {"type": "noul", "instructions": INJECTION_QUESTION}}}


def call(key, row, set_name, run=0):
    rec = {"set": set_name, "uid": row["uid"], "run": run, "text_md5": md5(row["text"]), "model": MODEL,
           "question_id": QUESTION_ID, "question": INJECTION_QUESTION,
           "started_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds")}
    headers = {"Authorization": f"Bearer {key}"}
    for attempt in range(1, 7):
        t0 = time.perf_counter()
        try:
            r = requests.post(API_URL, json=body(row["text"]), headers=headers, timeout=90)
        except requests.RequestException as e:  # network hiccup: back off and retry
            rec.update(http_status=None, error=f"{type(e).__name__}: {e}", attempts=attempt)
            time.sleep(min(30, 2 ** attempt))
            continue
        rec["latency_ms"] = round(1000 * (time.perf_counter() - t0), 1)
        rec["http_status"] = r.status_code
        rec["attempts"] = attempt
        rec["request_id"] = r.headers.get("x-typesafe-request-id")
        if r.status_code == 429 or r.status_code >= 500:  # rate limited / server error: retry
            rec["error"] = r.text[:300]
            time.sleep(min(30, 2 ** attempt))
            continue
        try:
            resp = r.json()
        except ValueError:
            resp = {"_non_json": r.text[:2000]}
        rec["response"] = resp
        if r.ok:
            rec.pop("error", None)
            rec["noul"] = resp["answers"]["injection"]["noul"]
            rec["usage_input_tokens"] = (resp.get("usage") or {}).get("input_tokens")
            rec["usage_output_tokens"] = (resp.get("usage") or {}).get("output_tokens")
        else:
            rec["error"] = r.text[:500]
        return rec
    return rec


def done_keys():
    keys = set()
    if os.path.exists(OUT):
        for line in open(OUT, encoding="utf-8"):
            r = json.loads(line)
            if r.get("http_status") == 200 and "noul" in r:
                keys.add((r["set"], r["uid"], r.get("run", 0), r["text_md5"], r["model"], r["question_id"]))
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--repeats", type=int, default=3,
                    help="calls per document: the API has no seed and mid-range p moves by up to ~0.1 between calls")
    ap.add_argument("--parity", type=int, default=3, help="rows also sent through src.jev_guard.judge()")
    args = ap.parse_args()
    key = api_key()
    os.environ["TYPESAFE_API_KEY"] = key  # judge() reads it from the environment
    os.makedirs(os.path.dirname(OUT), exist_ok=True)

    todo, have = [], done_keys()
    for run in range(args.repeats):
        for set_name, path in DATA.items():
            for line in open(path, encoding="utf-8"):
                row = json.loads(line)
                if (set_name, row["uid"], run, md5(row["text"]), MODEL, QUESTION_ID) not in have:
                    todo.append((set_name, row, run))
    if args.limit:
        todo = todo[:args.limit]
    print(f"{len(have)} already saved, {len(todo)} to call ({MODEL}, {QUESTION_ID}, {args.repeats} runs)", flush=True)

    ok = fail = 0
    t_start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as ex, open(OUT, "a", encoding="utf-8") as f:
        futs = [ex.submit(call, key, row, s, run) for s, row, run in todo]
        for i, fu in enumerate(as_completed(futs), 1):
            rec = fu.result()
            with _lock:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                f.flush()
            ok += rec.get("http_status") == 200
            fail += rec.get("http_status") != 200
            if i % 100 == 0 or i == len(futs):
                print(f"  {i}/{len(futs)} ok={ok} fail={fail} ({time.time() - t_start:.0f}s)", flush=True)

    if args.parity:
        # judge() sends the same request; because the API is not deterministic we check that its p falls
        # within the spread of our saved runs (+-0.05), not that it is identical.
        from src.jev_guard import judge
        saved = {}
        for line in open(OUT, encoding="utf-8"):
            r = json.loads(line)
            if r.get("set") == "EN" and "noul" in r:
                saved.setdefault(r["uid"], []).append(r["noul"])
        rows = [json.loads(l) for l in open(DATA["EN"], encoding="utf-8")]
        rows = [r for r in rows if r["uid"] in saved][:args.parity]
        for r in rows:
            p, ps = judge(r["text"]), saved[r["uid"]]
            ok_ = min(ps) - 0.05 <= p <= max(ps) + 0.05
            print(f"  parity {r['uid']}: saved runs {ps} vs judge() {p} -> {'OK' if ok_ else 'OUT OF RANGE'}")


if __name__ == "__main__":
    main()
