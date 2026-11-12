"""Validate ja_llmail_phase1_candidates.jsonl against the raw Phase 1 data and the brief.

Usage: python -X utf8 -I validate_p1.py <candidates.jsonl> <raw_submissions_phase1.jsonl> <existing.jsonl> [...]
Adapted from WD/_build/scripts/ja_llmail/validate_ja.py.
"""
import json
import re
import sys
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
cp, rawp, *existing = sys.argv[1:]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
TAGS = {"encoding", "unicode_obfuscation", "character_obfuscation", "delimiter_escape", "fake_system_tokens",
        "fake_dialogue_turns", "fake_judge_or_label_claims", "payload_splitting", "roleplay_or_hypothetical",
        "spoofed_headers", "code_or_markup_wrapping", "fake_tool_call", "fake_summary_or_output",
        "social_engineering", "benign_framing", "paraphrase_low_trigger", "multilingual", "long_context"}
DET = {"a": "prompt_shield", "b": "prompt_shield", "c": "task_tracker", "d": "task_tracker",
       "g": "llm_judge", "h": "llm_judge", "i": "all", "j": "all"}
errs = []
recs = []
for ln, l in enumerate(open(cp, encoding="utf-8"), 1):
    try:
        recs.append(json.loads(l))
    except Exception as e:
        errs.append(f"line {ln}: bad json {e}")
want = {r["origin"]["row_index"]: r for r in recs}
raw = {}
with open(rawp, encoding="utf-8") as fh:
    for i, l in enumerate(fh):
        if i in want:
            raw[i] = json.loads(l)
ids = Counter(r["id"] for r in recs)
if any(v > 1 for v in ids.values()):
    errs.append("dup ids")
if len(want) != len(recs):
    errs.append("dup row_index")
for n, r in enumerate(recs, 1):
    o = r["origin"]
    rr = raw.get(o["row_index"])
    if r["id"] != f"ja-llmail-p1-{n:03d}":
        errs.append(f"{r['id']}: id order")
    if rr is None:
        errs.append(f"{r['id']}: row missing"); continue
    if rr["RowKey"] != o["RowKey"]:
        errs.append(f"{r['id']}: RowKey mismatch")
    if r["text"] != f"Subject: {rr.get('subject') or ''}\n\n{rr.get('body') or ''}":
        errs.append(f"{r['id']}: text != raw subject/body")
    ob = json.loads(rr["objectives"]) if isinstance(rr["objectives"], str) else rr["objectives"]
    if ob != o["objectives"]:
        errs.append(f"{r['id']}: objectives mismatch")
    if not (ob["email.retrieved"] and ob["defense.undetected"]):
        errs.append(f"{r['id']}: not retrieved/undetected")
    if rr["scenario"] != o["level"] or DET.get(o["level"][-1]) != r["detector"]:
        errs.append(f"{r['id']}: level/detector mismatch")
    if o["scenario"] != f"scenario_{o['level'][5]}":
        errs.append(f"{r['id']}: scenario mismatch")
    if rr["team_id"] != o["team_id"]:
        errs.append(f"{r['id']}: team mismatch")
    if o.get("split") != "Phase1" or o.get("revision") != "1063bdf01ec8762b812d5e06ee768a06faa5a6f7":
        errs.append(f"{r['id']}: split/revision")
    ii = r["injected_instruction"]
    if ii is not None and (not ii or ii not in r["text"]):
        errs.append(f"{r['id']}: injected_instruction not substring")
    if len(r["text"]) > 6000:
        errs.append(f"{r['id']}: too long")
    bad = set(r["technique_tags"]) - TAGS
    if bad or not r["technique_tags"]:
        errs.append(f"{r['id']}: tags {bad or 'empty'}")
    if (r["risk_level"], r["harm_type"]) not in {(3, "unauthorized_action"), (4, "data_exfiltration")}:
        errs.append(f"{r['id']}: risk/harm")
    if o["scenario"] == "scenario_4" and r["risk_level"] != 4:
        errs.append(f"{r['id']}: scenario_4 must be risk 4")
    if len(r["risk_rationale"]) > 50:
        errs.append(f"{r['id']}: rationale > 50 chars")
    want_f = {"label": "injection", "source": "LLMail-Inject", "subset": "phase1_detector_evasion",
              "doc_type": "email", "core": False}
    for k, v in want_f.items():
        if r.get(k) != v:
            errs.append(f"{r['id']}: {k}")
tiers = ["full" if all(r["origin"]["objectives"][k] for k in KEYS) else "partial" for r in recs]
exc = ["Team cap exception" in r["notes"] for r in recs]
for blk, sl in (("head", slice(0, 250)), ("tail", slice(250, None))):
    t = tiers[sl]
    if t != sorted(t):
        errs.append(f"tier order violated in {blk} block")
teams = Counter(r["origin"]["team_id"] for r in recs)
if teams and max(teams.values()) > 5:
    errs.append("team cap > 5")
for r, e in zip(recs, exc):
    if e and r["detector"] not in ("llm_judge", "all"):
        errs.append(f"{r['id']}: cap exception outside llm_judge/all")
base = Counter(r["origin"]["team_id"] for r, e in zip(recs, exc) if not e)
if base and max(base.values()) > 3:
    errs.append("more than 3 non-exception picks for a team")
for k, v in teams.items():
    if v > 3 and base[k] != 3:
        errs.append(f"team {k[:8]} exceeds 3 without using its 3 regular slots")
det = Counter(r["detector"] for r in recs)
det250 = Counter(r["detector"] for r in recs[:250])
print("detectors all:", dict(det), "| first 250:", dict(det250))
print("tiers all:", Counter(tiers), "| first 250:", Counter(tiers[:250]))
print("teams:", len(teams), "| teams >3:", sum(v > 3 for v in teams.values()), "| cap-exception items:", sum(exc))
long_n = sum(len(r["text"]) > 3000 for r in recs)
if long_n > 0.15 * 250:
    errs.append(f"too many long items {long_n}")
# existing data: RowKey overlap and near duplicates
ZW = re.compile("[​-‏⁠-⁤﻿­᠎͏]")
COMB = re.compile("[̀-ͯ҉⃐-⃿]")


def nt(t):
    t = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t)
    t = unicodedata.normalize("NFKC", ZW.sub("", t))
    t = COMB.sub("", unicodedata.normalize("NFKD", t))
    return re.sub(r"\s+", " ", t.lower()).strip()


ex_keys, ex = set(), []
for p in existing:
    if not Path(p).exists():
        print("note: missing", p)
        continue
    for l in open(p, encoding="utf-8"):
        if not l.strip():
            continue
        x = json.loads(l)
        o = x.get("origin") or {}
        if x.get("source") == "LLMail-Inject":
            ex_keys.update(v for v in (o.get("RowKey"), o.get("RowKey_or_job_id"), o.get("job_id")) if v)
        ex.append((Path(p).name, x.get("id"), nt(x["text"]), x.get("source") == "LLMail-Inject"))
for r in recs:
    if r["origin"]["RowKey"] in ex_keys:
        errs.append(f"{r['id']}: same submission as an existing item")
T = [nt(r["text"]) for r in recs]
SH = [{t[i:i + 5] for i in range(max(1, len(t) - 4))} for t in T]
EXSH = [{t[i:i + 5] for i in range(max(1, len(t) - 4))} for _, _, t, _ in ex]


def check(a, b, sa, sb, contain):
    inter = len(sa & sb)
    jac = inter / max(1, len(sa | sb))
    con = inter / max(1, min(len(sa), len(sb)))
    rt = 0.0
    la, lb = len(a), len(b)
    if 2 * min(la, lb) / (la + lb) >= 0.6 and jac >= 0.08:
        rt = SequenceMatcher(None, a, b, autojunk=False).ratio()
    bad = rt >= 0.6 or jac >= 0.5 or (contain and min(la, lb) >= 150 and con >= 0.8)
    return bad, rt, jac, con


mx = [0.0, 0.0, 0.0]
for i in range(len(T)):
    for j in range(i):
        bad, rt, jac, con = check(T[i], T[j], SH[i], SH[j], True)
        mx = [max(mx[0], rt), max(mx[1], jac), max(mx[2], con if min(len(T[i]), len(T[j])) >= 150 else 0)]
        if bad:
            errs.append(f"near-dup {recs[i]['id']} ~ {recs[j]['id']} r={rt:.2f} j={jac:.2f} c={con:.2f}")
mxe = [0.0, 0.0]
for i in range(len(T)):
    for k, (f, xid, t, is_ll) in enumerate(ex):
        bad, rt, jac, con = check(T[i], t, SH[i], EXSH[k], is_ll)
        mxe = [max(mxe[0], rt), max(mxe[1], jac)]
        if bad:
            errs.append(f"near-dup vs existing {recs[i]['id']} ~ {f}:{xid} r={rt:.2f} j={jac:.2f} c={con:.2f}")
print("within: max difflib %.3f, max jaccard %.3f, max containment(>=150 chars) %.3f" % tuple(mx))
print("vs existing (%d texts): max difflib %.3f, max jaccard %.3f" % (len(ex), *mxe))
L = sorted(len(r["text"]) for r in recs)
print("len min/median/mean/max:", L[0], L[len(L) // 2], round(sum(L) / len(L)), L[-1], "| >3000:", long_n)
print("records", len(recs), "| errors", len(errs))
for e in errs[:60]:
    print(" ", e)
