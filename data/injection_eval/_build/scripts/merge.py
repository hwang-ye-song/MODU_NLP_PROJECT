"""Merge parts/*.jsonl into the final 100-item dataset and validate it.

Usage: python -I merge.py <workdir>
"""
import csv
import json
import sys
from collections import Counter
from pathlib import Path

PLAN = {
    ("injection", "BIPIA"): 20,
    ("injection", "LLMail-Inject"): 15,
    ("injection", "InjecAgent"): 15,
    ("benign", "BIPIA"): 15,
    ("benign", "LLMail-Inject"): 15,
    ("benign", "InjecAgent"): 10,
    ("benign", "NotInject"): 10,
}
PART_ORDER = ["bipia", "llmail_injection", "injecagent", "llmail_benign", "notinject"]
REQUIRED = ["id", "label", "source", "subset", "text", "injected_instruction", "origin"]


def main(workdir: Path) -> int:
    parts_dir = workdir / "parts"
    rows, problems = [], []
    for name in PART_ORDER:
        p = parts_dir / f"{name}.jsonl"
        if not p.exists():
            problems.append(f"missing part file: {p.name}")
            continue
        for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError as e:
                problems.append(f"{p.name}:{ln} bad JSON: {e}")
                continue
            miss = [k for k in REQUIRED if k not in r]
            if miss:
                problems.append(f"{p.name}:{ln} missing fields {miss}")
            if r.get("label") not in ("injection", "benign"):
                problems.append(f"{p.name}:{ln} bad label {r.get('label')!r}")
            if not str(r.get("text", "")).strip():
                problems.append(f"{p.name}:{ln} empty text")
            r["_part"] = name
            rows.append(r)

    # ordering: injection first, then benign, each in PART_ORDER
    rows.sort(key=lambda r: (r["label"] != "injection", PART_ORDER.index(r["_part"])))

    counts = Counter((r["label"], r["source"]) for r in rows)
    for key, want in PLAN.items():
        if counts.get(key, 0) != want:
            problems.append(f"count {key}: got {counts.get(key, 0)}, want {want}")
    for key in counts:
        if key not in PLAN:
            problems.append(f"unexpected (label, source) {key}: {counts[key]}")

    ids = Counter(r["id"] for r in rows)
    problems += [f"duplicate id {i}" for i, c in ids.items() if c > 1]
    texts = Counter(r["text"].strip() for r in rows)
    problems += [f"duplicate text: {t[:60]!r}" for t, c in texts.items() if c > 1]
    for r in rows:
        inj = r.get("injected_instruction")
        if r["label"] == "injection" and inj and inj not in r["text"]:
            problems.append(f"{r['id']}: injected_instruction not found in text")
        if "<Attacker Instruction>" in r["text"]:
            problems.append(f"{r['id']}: unfilled InjecAgent placeholder")

    for i, r in enumerate(rows, 1):
        r["uid"] = f"en-{i:03d}"
        r["label_int"] = 1 if r["label"] == "injection" else 0
        r["char_len"] = len(r["text"])
        r.pop("_part", None)

    out_jsonl = workdir / "dataset_en_100.jsonl"
    with out_jsonl.open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            ordered = {k: r[k] for k in ["uid", "id", "label", "label_int", "source", "subset", "char_len",
                                         "text", "injected_instruction", "origin", "notes"] if k in r}
            f.write(json.dumps(ordered, ensure_ascii=False) + "\n")

    out_csv = workdir / "dataset_en_100.csv"
    with out_csv.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["uid", "source_id", "label", "label_int", "source", "subset", "char_len",
                    "text", "injected_instruction", "origin_json", "notes"])
        for r in rows:
            w.writerow([r["uid"], r["id"], r["label"], r["label_int"], r["source"], r["subset"], r["char_len"],
                        r["text"], r.get("injected_instruction") or "",
                        json.dumps(r.get("origin", {}), ensure_ascii=False), r.get("notes", "")])

    print(f"rows: {len(rows)}")
    for key in PLAN:
        print(f"  {key[0]:9s} {key[1]:14s} {counts.get(key, 0):3d} / {PLAN[key]}")
    sub = Counter((r["label"], r["source"], r["subset"]) for r in rows)
    print("subsets:")
    for k, v in sorted(sub.items()):
        print(f"  {k}: {v}")
    lens = sorted(r["char_len"] for r in rows)
    if lens:
        print(f"char_len min/median/max: {lens[0]}/{lens[len(lens)//2]}/{lens[-1]}")
        for lab in ("injection", "benign"):
            l = sorted(r["char_len"] for r in rows if r["label"] == lab)
            if l:
                print(f"  {lab} median len: {l[len(l)//2]}")
    print("PROBLEMS:" if problems else "OK: no problems")
    for p in problems:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
