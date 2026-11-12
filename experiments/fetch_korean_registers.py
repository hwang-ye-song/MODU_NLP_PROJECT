"""② 말투 실험(02b_korean_registers)의 입력을 받는다: JHC56/korean-prompt-injection-registers, 고정 커밋.

    python experiments/fetch_korean_registers.py          # writes results/02b_korean_registers/inputs/

What it downloads (data files and license/attribution text only; no code from that repo is downloaded or run):
  data/dataset.jsonl        1,768 rows = 221 items x 8 registers (english + 7 Korean registers)
  data/registers.json       register definitions
  LICENSE.txt, README.md    license notice (BSD-2-Clause; deepset-derived items Apache-2.0) and attribution
  results/*.jsonl           the upstream authors' own judge outputs (11 runs). Only a compact extract is kept:
                            inputs/prior_judges_preds.csv (id, register, label, one pred column per run)

Every file is fetched through the GitHub contents API at the pinned commit and checked against the git blob SHA-1
of that commit (sha1("blob <size>\\0" + bytes)), so the saved bytes are exactly the upstream bytes.
Redistribution: BSD-2-Clause and Apache-2.0 both allow it with the notice kept, so the dataset, LICENSE.txt and the
upstream README are stored verbatim next to the data (inputs/SOURCE.json records where every byte came from).
Set GITHUB_TOKEN to raise the API rate limit (optional; 16 requests are enough unauthenticated). The token is never
printed or written.
"""
import datetime as dt
import hashlib
import io
import json
import os
import sys

import requests

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
OUT = os.path.join(REPO, "results", "02b_korean_registers", "inputs")

UPSTREAM = "JHC56/korean-prompt-injection-registers"
COMMIT = "d348b1fdad789222fbfe11b2176ddafad383430e"  # main on 2026-11-12 (committed 2026-09-26T16:51:18Z)
BLOBS = {  # git blob SHA-1 of every file at COMMIT (GET /repos/{UPSTREAM}/git/trees/{COMMIT}?recursive=1)
    "LICENSE.txt": "d5fc3154b510e501a1693baa48302d3cecce4ac3",
    "README.md": "5b53f8f1961003fc072c66d1bcaa39141b7b946f",
    "data/dataset.jsonl": "e74620a75fcd0c5a5bd4e4095b2b74d0d3ce40e6",
    "data/registers.json": "15c7caa549d44b00d2676e3712a046c8d061bb9c",
    "results/exaone_2.4b_baseline.jsonl": "0b5f324648494754a166c537be6ac3866390781d",
    "results/exaone_2.4b_definition.jsonl": "64a8ddef171d5d66fa607fb90fb0414022a03990",
    "results/exaone_7.8b_baseline.jsonl": "f43216f2abdbed8004d0796a4820c87185637e4b",
    "results/exaone_7.8b_definition.jsonl": "865730c7c392bbccc9f75ca9a213261aaa3f1efa",
    "results/hcx_1.5b_baseline.jsonl": "811f3083f9906e91cbc3c7a06c90fa5fdea0c746",
    "results/hcx_1.5b_definition.jsonl": "698a048bb714fc28c2f95a1449d91829170e6b55",
    "results/kanana_2.1b_baseline.jsonl": "e14f8c2e4b5fbb1edad40280b307a589c9367ddf",
    "results/kanana_2.1b_definition.jsonl": "cac03ecd5ecb70c245f36dbebea167b54aafc34d",
    "results/kanana_8b_baseline.jsonl": "6260b5a8a9c426981e8313df237d469ef9e3a35d",
    "results/kanana_8b_definition.jsonl": "783ab96a66d28e9c1139cf90ef923918ae658474",
    "results/kanana_safeguard_2.1b.jsonl": "ef43f58e9016ba55246de5243053e11ff3b424b5",
}
KEEP_VERBATIM = {"data/dataset.jsonl": "dataset.jsonl", "data/registers.json": "registers.json",
                 "LICENSE.txt": "LICENSE.txt", "README.md": "UPSTREAM_README.md"}
REGISTERS = ["english", "polite", "gentle", "casual", "genz", "emoticon", "angry", "threat"]
# Older upstream result files name the register in Korean / short form in a "style" field.
STYLE_TO_REGISTER = {"en": "english", "존댓말": "polite", "반말": "casual", "젠지": "genz"}


def blob_sha(b):
    return hashlib.sha1(b"blob %d\0" % len(b) + b).hexdigest()


def fetch(path):
    headers = {"Accept": "application/vnd.github.raw", "X-GitHub-Api-Version": "2022-11-28"}
    if os.environ.get("GITHUB_TOKEN"):
        headers["Authorization"] = "Bearer " + os.environ["GITHUB_TOKEN"]
    url = f"https://api.github.com/repos/{UPSTREAM}/contents/{path}"
    r = requests.get(url, params={"ref": COMMIT}, headers=headers, timeout=60)
    r.raise_for_status()
    b = r.content
    got = blob_sha(b)
    if got != BLOBS[path]:
        sys.exit(f"{path}: blob sha {got} != expected {BLOBS[path]} (download corrupted or wrong commit)")
    return b


def split_run(stem):
    """'exaone_7.8b_definition' -> ('exaone_7.8b', 'definition'); the safeguard classifier has no prompt condition."""
    for cond in ("baseline", "definition"):
        if stem.endswith("_" + cond):
            return stem[: -len(cond) - 1], cond
    return stem, "classifier"


def main():
    os.makedirs(OUT, exist_ok=True)
    files = {}
    for path in BLOBS:
        b = fetch(path)
        files[path] = {"bytes": len(b), "blob_sha1": blob_sha(b), "md5": hashlib.md5(b).hexdigest()}
        if path in KEEP_VERBATIM:
            dst = os.path.join(OUT, KEEP_VERBATIM[path])
            with open(dst, "wb") as f:
                f.write(b)
            files[path]["saved_as"] = os.path.relpath(dst, REPO).replace(os.sep, "/")
            if path == "data/dataset.jsonl":
                rows = [json.loads(l) for l in io.StringIO(b.decode("utf-8")) if l.strip()]
        elif path.startswith("results/"):
            files[path]["_rows"] = [json.loads(l) for l in io.StringIO(b.decode("utf-8")) if l.strip()]
        print(f"ok {path} ({len(b):,} bytes)")

    # dataset sanity: 221 items x 8 registers, one label per item
    keys = {(r["id"], r["register"]) for r in rows}
    assert len(rows) == 1768 and len(keys) == 1768, "expected 1,768 unique (id, register) rows"
    assert {r["register"] for r in rows} == set(REGISTERS)
    lab = {}
    for r in rows:
        assert lab.setdefault(r["id"], r["label"]) == r["label"], f"label differs across registers for {r['id']}"

    # compact extract of the upstream judges' predictions (for E5: their reported false positives on threats)
    import pandas as pd
    out = []
    for path, meta in files.items():
        if "_rows" not in meta:
            continue
        stem = os.path.basename(path)[: -len(".jsonl")]
        model, cond = split_run(stem)
        seen = set()
        for r in meta.pop("_rows"):
            reg = r.get("register") or STYLE_TO_REGISTER.get(r.get("style"), r.get("style"))
            k = (r["id"], reg)
            assert k in keys and k not in seen, f"{stem}: unexpected or duplicated row {k}"
            assert int(r["label"]) == lab[r["id"]], f"{stem}: label mismatch for {k}"
            seen.add(k)
            pred = r.get("pred")
            out.append({"run": stem, "model": model, "prompt_condition": cond, "id": r["id"], "register": reg,
                        "label": int(r["label"]), "technique": r.get("technique"),
                        "pred": None if pred is None or pred != pred else int(pred)})
        assert seen == keys, f"{stem}: does not cover all 1,768 rows"
        meta["rows"] = len(seen)
    long = pd.DataFrame(out)
    runs = sorted(long["run"].unique())
    df = long.pivot(index=["id", "register", "label"], columns="run", values="pred").reset_index()
    df = df[["id", "register", "label"] + runs]
    for c in runs:
        df[c] = df[c].astype("Int64")
    df["register"] = pd.Categorical(df["register"], REGISTERS, ordered=True)
    df = df.sort_values(["id", "register"]).reset_index(drop=True)
    pj = os.path.join(OUT, "prior_judges_preds.csv")
    df.to_csv(pj, index=False, encoding="utf-8")
    run_info = long.drop_duplicates("run").set_index("run")[["model", "prompt_condition"]].to_dict("index")

    src = {"upstream": f"https://github.com/{UPSTREAM}", "commit": COMMIT, "commit_date": "2026-09-26T16:51:18Z",
           "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "method": "GitHub contents API (Accept: application/vnd.github.raw) at the pinned commit; bytes checked "
                     "against the git blob SHA-1 of that commit",
           "license": "BSD-2-Clause (Tensor Trust source data (c) 2023 The Regents of the University of California; "
                      "Korean register translations and assembly (c) 2026 Juhyuk Choi). The 162 items derived from "
                      "deepset/prompt-injections are Apache-2.0. Redistribution with the notice is allowed; LICENSE.txt "
                      "and the upstream README (attribution) are kept verbatim in this folder.",
           "files": files,
           "derived": {"prior_judges_preds.csv": {
               "from": sorted(p for p in files if p.startswith("results/")),
               "columns": "id, register, label, then one column per upstream run (file name without .jsonl): "
                          "pred, 1 = flagged as injection, empty = upstream could not parse the answer",
               "runs": run_info,
               "rows": len(df), "md5": hashlib.md5(open(pj, "rb").read()).hexdigest()}}}
    with open(os.path.join(OUT, "SOURCE.json"), "w", encoding="utf-8") as f:
        json.dump(src, f, ensure_ascii=False, indent=1)
    print(f"wrote {os.path.relpath(OUT, REPO)}: dataset.jsonl ({len(rows)} rows), registers.json, LICENSE.txt, "
          f"UPSTREAM_README.md, prior_judges_preds.csv ({len(df)} rows), SOURCE.json")


if __name__ == "__main__":
    main()
