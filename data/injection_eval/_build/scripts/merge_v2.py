"""Build the final EN / KO / JA datasets (1,000 rows each) with risk levels + doc_type, and validate.

New part files are appended after the original ones so existing uids stay stable.

Usage: python -X utf8 -I _build/scripts/merge_v2.py <dataset root> <unused>
"""
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

# part file -> (expected injection, expected benign); order = row order in outputs
PART_PLAN = {
    "bipia": (90, 70),
    "bipia_abstract": (40, 40),
    "llmail_injection": (80, 0),
    "injecagent": (80, 60),
    "sep": (30, 30),
    "webpage": (30, 30),
    "llmail_benign": (0, 40),
    "enron": (0, 40),
    "enron_hardneg": (0, 25),
    "hardneg": (0, 15),
    # v3 expansion (appended so the 700-row uids above do not move)
    "agentdojo_tools": (60, 60),
    "webpage_more": (40, 40),
    "bipia_abstract_more": (30, 30),
    "sep_more": (20, 20),
}
TARGET = {"injection": 500, "benign": 500}
# ranked reserve parts used, in order, to refill items removed by the label audit
RESERVES = {"injection": ["llmail_injection_reserve"],
            "benign": ["enron_hardneg_reserve", "enron_reserve"]}
# judge-attack candidate files, in order, with how many non-overlapping items to keep from each
JA_FILES = [("ja_llmail_candidates.jsonl", 250), ("ja_llmail_phase1_candidates.jsonl", 250)]
REF_PARTS = ["notinject"]  # direct user prompts -> over-defense reference set, not in main eval
ENRON_HN_KEEP = 25
RISK_LABEL = {0: "정상", 1: "매우 낮음", 2: "낮음", 3: "중간", 4: "높음", 5: "매우 높음"}
HARM_KO = {
    "task_hijack": "과제 이탈", "output_manipulation": "출력 형식 조작", "ad_promo": "광고·홍보",
    "misinformation": "오정보·선동", "phishing_fraud": "피싱·사기", "unauthorized_action": "무단 행동",
    "data_exfiltration": "정보 유출", "account_data_tamper": "계정·데이터 변조",
    "surveillance_malware": "감시·악성코드", "financial_harm": "금전 피해", "physical_harm": "물리적 위해",
    "system_destruction": "시스템 파괴·마비",
}
DOC_KO = {"email": "이메일", "tool_response": "도구 응답(JSON)", "table": "표", "code_qa": "코드 Q&A",
          "news_article": "뉴스 기사(웹)", "webpage": "웹페이지", "general_document": "일반 문서",
          "wiki": "사내 문서·위키", "chat": "채팅 로그", "manual": "제품 매뉴얼", "user_prompt": "사용자 프롬프트"}
COLS = ["uid", "pair_uid", "id", "lang", "condition", "doc_type", "doc_type_ko", "label", "label_int",
        "source", "subset", "core", "risk_level", "risk_label", "harm_type", "harm_type_ko", "technique",
        "control", "char_len", "text", "injected_instruction", "risk_rationale", "notes", "origin"]

problems = []


def doc_type(r):
    if r.get("doc_type") in DOC_KO:  # part files from v3 carry their own doc_type
        return r["doc_type"]
    s, sub = r.get("source"), r.get("subset")
    if s == "BIPIA":
        return {"email": "email", "table": "table", "code": "code_qa", "abstract": "news_article"}.get(sub, sub)
    if s in ("LLMail-Inject", "Enron"):
        return "email"
    if s == "InjecAgent":
        return "tool_response"
    if s == "SEP":
        return "general_document"
    if s == "NotInject":
        return "user_prompt"
    if sub == "webpage":
        return "webpage"
    if s == "Synthetic":
        m = re.search(r"format:\s*([^;]+);", r.get("notes") or "")
        f = (m.group(1) if m else "").lower()
        for key, dt in (("email", "email"), ("manual", "manual"), ("wiki", "wiki"), ("web", "webpage"),
                        ("chat", "chat")):
            if key in f:
                return dt
    problems.append(f"unknown doc_type for {r.get('id')} ({s}/{sub})")
    return None


def load(p):
    if not p.exists():
        problems.append(f"missing {p.name}")
        return []
    out = []
    for ln, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError as e:
                problems.append(f"{p.name}:{ln} bad JSON {e}")
    return out


def auc_len(rows):
    pos = [r["char_len"] for r in rows if r["label"] == "injection"]
    neg = [r["char_len"] for r in rows if r["label"] == "benign"]
    if not pos or not neg:
        return None
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def write(rows, stem: Path):
    stem.parent.mkdir(parents=True, exist_ok=True)
    with stem.with_suffix(".jsonl").open("w", encoding="utf-8", newline="\n") as f:
        for r in rows:
            f.write(json.dumps({k: r.get(k) for k in COLS}, ensure_ascii=False) + "\n")
    with stem.with_suffix(".csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(COLS)
        for r in rows:
            w.writerow([json.dumps(r.get(k), ensure_ascii=False) if k == "origin"
                        else ("" if r.get(k) is None else r.get(k)) for k in COLS])


def summarize(name, rows):
    print(f"\n== {name}: {len(rows)} rows ==")
    c = Counter((r["doc_type"], r["label"]) for r in rows)
    for dt in sorted({k[0] for k in c}, key=str):
        print(f"  {str(dt):16s} inj {c.get((dt, 'injection'), 0):4d}  ben {c.get((dt, 'benign'), 0):4d}")
    lens = defaultdict(list)
    for r in rows:
        lens[r["label"]].append(r["char_len"])
    for lab, l in lens.items():
        l.sort()
        print(f"  {lab} len median {l[len(l)//2]}  p90 {l[int(len(l)*.9)]}")
    a = auc_len(rows)
    if a is not None:
        print(f"  length-only AUC (higher len => injection): {a:.3f}")
    rl = Counter(r["risk_level"] for r in rows if r["label"] == "injection")
    print("  risk levels (injection):", dict(sorted(rl.items(), key=lambda x: (x[0] is None, x[0]))))


def finish(r):
    r["risk_label"] = RISK_LABEL.get(r.get("risk_level"))
    r["harm_type_ko"] = HARM_KO.get(r.get("harm_type"))
    r["doc_type"] = doc_type(r)
    r["doc_type_ko"] = DOC_KO.get(r["doc_type"])
    r["char_len"] = len(r["text"])
    return r


def main(wd: Path, sp: Path):
    global problems
    risk = {}
    for f in ["consensus_core.json", "consensus_new.json"]:
        p = wd / "_build" / "rating" / f
        if p.exists():
            risk.update(json.loads(p.read_text(encoding="utf-8")))

    # ---------- audit overrides ----------
    # _build/audit/overrides.json: {"set": {id: {field: value}}, "drop": {id: reason}}
    ov_path = wd / "_build" / "audit" / "overrides.json"
    ov = json.loads(ov_path.read_text(encoding="utf-8")) if ov_path.exists() else {}
    ov_set, ov_drop = ov.get("set", {}), ov.get("drop", {})

    def apply_ov(rows):
        out = []
        for r in rows:
            if r.get("id") in ov_drop:
                continue
            if r.get("id") in ov_set:
                r = {**r, **ov_set[r["id"]]}
            out.append(r)
        return out

    # ---------- EN ----------
    reserve_files = sorted({f for fs in RESERVES.values() for f in fs if f != "enron_hardneg_reserve"})
    raw = {n: load(wd / "_build" / "parts_v2" / f"{n}.jsonl")
           for n in list(PART_PLAN) + REF_PARTS + reserve_files}
    parts = {n: apply_ov(v) for n, v in raw.items()}
    enron_texts = {r["text"].strip() for r in parts["enron"]}
    hn_all = [r for r in parts["enron_hardneg"] if r["text"].strip() not in enron_texts]
    parts["enron_hardneg"] = hn_all[:ENRON_HN_KEEP]
    parts["enron_hardneg_reserve"] = hn_all[ENRON_HN_KEEP:]  # ranked leftovers, used only to refill
    reserve_ids = {r["id"] for n in RESERVES["injection"] + RESERVES["benign"] for r in parts.get(n, [])}
    en = []
    for lab, prefix in (("injection", "EN-I"), ("benign", "EN-B")):
        i = 0
        main_rows = []
        for n, (want_i, want_b) in PART_PLAN.items():
            rows = [r for r in parts[n] if r.get("label") == lab]
            n_dropped = sum(1 for r in raw[n] if r.get("label") == lab and r.get("id") in ov_drop)
            want = (want_i if lab == "injection" else want_b) - n_dropped
            if len(rows) != want:
                problems.append(f"EN {n} {lab}: {len(rows)} != {want}")
            main_rows += rows
        # refill what the audit dropped from ranked reserve files, so each label reaches its target
        deficit = TARGET[lab] - len(main_rows)
        for n in RESERVES[lab]:
            if deficit <= 0:
                break
            take = [r for r in parts.get(n, []) if r.get("label") == lab][:deficit]
            main_rows += [{**r, "notes": ((r.get("notes") or "") + " | audit refill").strip(" |")} for r in take]
            deficit -= len(take)
        if deficit > 0:
            problems.append(f"EN {lab}: still {deficit} short of {TARGET[lab]} after reserves")
        if deficit < 0:
            problems.append(f"EN {lab}: {-deficit} over target {TARGET[lab]}")
        for r in main_rows:
                i += 1
                r = dict(r)
                r.update(uid=f"{prefix}-{i:03d}", pair_uid=None, lang="en", condition="EN",
                         label_int=int(lab == "injection"), core=bool(r.get("core")),
                         technique=None, control=None)
                if lab == "injection":
                    rk = risk.get(r["id"])
                    if rk is None:
                        problems.append(f"no risk for {r['id']}")
                        rk = {}
                    r.update(risk_level=rk.get("risk_level"), harm_type=rk.get("harm_type"),
                             risk_rationale=rk.get("risk_rationale"))
                else:
                    r.update(risk_level=0, harm_type=None, risk_rationale=None)
                en.append(finish(r))
    ids = Counter(r["id"] for r in en)
    problems += [f"EN dup id {k}" for k, v in ids.items() if v > 1]
    tx = Counter(r["text"].strip() for r in en)
    problems += [f"EN dup text {k[:50]!r}" for k, v in tx.items() if v > 1]
    for r in en:
        if r.get("injected_instruction") and r["injected_instruction"] not in r["text"]:
            problems.append(f"EN {r['id']}: injected_instruction not in text")
    core_n = sum(r["core"] for r in en) + sum(bool(r.get("core")) for n in REF_PARTS for r in parts[n])
    if core_n != 100:
        problems.append(f"EN core count (main + reference) {core_n} != 100")
    n_en = len(en)
    by_id = {r["id"]: r for r in en}
    write(en, wd / "en" / f"dataset_en_{n_en}")
    summarize("EN", en)

    ref = []
    for i, r in enumerate((r for n in REF_PARTS for r in parts[n]), 1):
        r = dict(r)
        r.update(uid=f"EN-R-{i:03d}", pair_uid=None, lang="en", condition="EN_REF", label_int=0,
                 core=bool(r.get("core")), risk_level=0, harm_type=None, risk_rationale=None)
        ref.append(finish(r))
    ref_by_id = {r["id"]: r for r in ref}
    if ref:
        write(ref, wd / "en" / "overdefense_ref_notinject")
        print(f"\n== EN over-defense reference: {len(ref)} rows ==")

    # ---------- KO ----------
    ko = []
    kdir = wd / "_build" / "ko_parts"
    for p in sorted(kdir.glob("*.jsonl")) if kdir.exists() else []:
        ko += apply_ov(load(p))
    if ko:
        out, ko_ref = [], []
        seen = Counter(r.get("pair_id") for r in ko)
        problems += [f"KO dup pair {k}" for k, v in seen.items() if v > 1]
        for r in ko:
            pid = r.get("pair_id")
            e = by_id.get(pid) or ref_by_id.get(pid)
            if e is None:
                # unused reserve items may already be translated; that is fine
                if pid not in reserve_ids and pid not in ov_drop:
                    problems.append(f"KO orphan {pid}")
                continue
            if r.get("label") != e["label"]:
                problems.append(f"KO label mismatch {pid}")
            r = dict(r)
            r.update(uid=e["uid"].replace("EN-", "KO-"), pair_uid=e["uid"], lang="ko",
                     condition="KO_REF" if pid in ref_by_id else "KO",
                     label=e["label"], label_int=e["label_int"], source=e["source"], subset=e["subset"],
                     doc_type=e["doc_type"],
                     core=e["core"], risk_level=e["risk_level"], harm_type=e["harm_type"],
                     risk_rationale=e["risk_rationale"], technique=None, control=None, notes=e.get("notes"))
            if r.get("injected_instruction") and r["injected_instruction"] not in r["text"]:
                problems.append(f"KO {r['id']}: injected_instruction not in text")
            if sum('가' <= ch <= '힣' for ch in r["text"]) == 0:
                problems.append(f"KO {r['id']}: no Hangul at all")
            r = finish(r)
            (ko_ref if pid in ref_by_id else out).append(r)
        out.sort(key=lambda r: r["uid"])
        missing = [i for i in by_id if i not in {r.get("pair_id") for r in ko}]
        if missing:
            problems.append(f"KO missing {len(missing)} EN items (e.g. {missing[:4]})")
        write(out, wd / "ko" / f"dataset_ko_{len(out)}")
        summarize("KO", out)
        if ko_ref:
            ko_ref.sort(key=lambda r: r["uid"])
            write(ko_ref, wd / "ko" / "overdefense_ref_notinject_ko")
            print(f"  KO over-defense reference: {len(ko_ref)} rows")

    # ---------- JA ----------
    # 250 real detector-evading LLMail Phase2 attacks (public data, unpaired) + all EN benign unchanged
    if (wd / "_build" / JA_FILES[0][0]).exists():
        en_llmail_rows = {(r["origin"].get("split", "Phase2"), r["origin"].get("row_index")) for r in en
                          if r["source"] == "LLMail-Inject" and r["label"] == "injection"}
        seen_texts = {r["text"].strip() for r in en}
        keep, dropped = [], 0
        for fname, n_keep in JA_FILES:
            jp = wd / "_build" / fname
            if not jp.exists():
                problems.append(f"missing {fname}")
                continue
            got = 0
            for r in apply_ov(load(jp)):
                if got >= n_keep:
                    break
                key = (r["origin"].get("split", "Phase2"), r["origin"].get("row_index"))
                if key in en_llmail_rows or r["text"].strip() in seen_texts:
                    dropped += 1
                    continue
                seen_texts.add(r["text"].strip())
                keep.append(r)
                got += 1
            if got < n_keep:
                problems.append(f"JA {fname}: only {got} non-overlapping candidates (< {n_keep})")
        out = []
        for i, r in enumerate(keep, 1):
            r = dict(r)
            if r.get("injected_instruction") and r["injected_instruction"] not in r["text"]:
                problems.append(f"JA {r['id']}: injected_instruction not in text")
            rk = risk.get(r["id"])
            if rk:  # 3-rater consensus overrides the collector's single rating
                r.update(risk_level=rk["risk_level"], harm_type=rk["harm_type"],
                         risk_rationale=rk["risk_rationale"])
            r.update(uid=f"JA-I-{i:03d}", pair_uid=None, lang="en", condition="JA", label="injection",
                     label_int=1, core=False, technique=",".join(r.get("technique_tags") or []),
                     control=False,
                     notes=((r.get("notes") or "") + f" | detector={r.get('detector')}").strip(" |"))
            out.append(finish(r))
        for e in en:
            if e["label"] == "benign":
                r = dict(e)
                r.update(uid=e["uid"].replace("EN-", "JA-"), pair_uid=e["uid"], condition="JA",
                         technique=None, control=True)
                out.append(r)
        write(out, wd / "judge_attack" / f"dataset_ja_{len(out)}")
        summarize("JA", out)
        print(f"  candidates dropped for EN overlap: {dropped}")
        print("  detector:", dict(Counter(r.get("detector") for r in keep)))
        print("  technique tags:", dict(Counter(t for r in keep for t in (r.get("technique_tags") or [])).most_common()))

    print("\nPROBLEMS:" if problems else "\nOK: no problems")
    for p in problems[:80]:
        print("  -", p)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]), Path(sys.argv[2])))
