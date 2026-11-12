"""Validate ja_llmail_candidates.jsonl against the raw data and the brief.

Usage: python -X utf8 -I validate_ja.py <candidates.jsonl> <raw_submissions_phase2.jsonl> <en_part> [<en_part> ...]
"""
import json
import re
import sys
from collections import Counter
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
cp, rawp, *en = sys.argv[1:]
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
TAGS = {"encoding", "unicode_obfuscation", "character_obfuscation", "delimiter_escape", "fake_system_tokens",
        "fake_dialogue_turns", "fake_judge_or_label_claims", "payload_splitting", "roleplay_or_hypothetical",
        "spoofed_headers", "code_or_markup_wrapping", "fake_tool_call", "fake_summary_or_output",
        "social_engineering", "benign_framing", "paraphrase_low_trigger", "multilingual", "long_context"}
DET = {"k": "prompt_shield", "l": "prompt_shield", "m": "task_tracker", "n": "task_tracker", "o": "task_tracker",
       "p": "task_tracker", "q": "task_tracker", "r": "task_tracker", "s": "llm_judge", "t": "llm_judge",
       "u": "all", "v": "all"}
errs = []
recs = []
for ln, l in enumerate(open(cp, encoding="utf-8"), 1):
    try:
        recs.append(json.loads(l))
    except Exception as e:
        errs.append(f"line {ln}: bad json {e}")
want = {r["origin"]["row_index"]: r for r in recs}
raw = {}
for i, l in enumerate(open(rawp, encoding="utf-8")):
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
    if r["id"] != f"ja-llmail-{n:03d}":
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
    if rr["scenario"] != o["level"] or DET[o["level"][-1]] != r["detector"]:
        errs.append(f"{r['id']}: level/detector mismatch")
    if o["scenario"] != f"scenario_{o['level'][5]}":
        errs.append(f"{r['id']}: scenario mismatch")
    if rr["team_id"] != o["team_id"]:
        errs.append(f"{r['id']}: team mismatch")
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
    if len(r["risk_rationale"]) > 50:
        errs.append(f"{r['id']}: rationale > 50 chars")
    for k in ("label", "source", "subset"):
        if r[k] != {"label": "injection", "source": "LLMail-Inject", "subset": "phase2_detector_evasion"}[k]:
            errs.append(f"{r['id']}: {k}")
# tiers ordered: all full before partial
tiers = ["full" if all(r["origin"]["objectives"][k] for k in KEYS) else "partial" for r in recs]
reserve = ["Reserve tail" in r["notes"] for r in recs]
main = [t for t, rs in zip(tiers, reserve) if not rs]
if main != sorted(main):
    errs.append("tier order violated in main block")
if any(reserve[i] and not reserve[i + 1] for i in range(len(reserve) - 1)):
    errs.append("reserve not contiguous at tail")
teams = Counter(r["origin"]["team_id"] for r, rs in zip(recs, reserve) if not rs)
if teams and max(teams.values()) > 3:
    errs.append("team cap > 3 in main block")
long_n = sum(len(r["text"]) > 3000 for r in recs)
if long_n > 0.15 * 250:
    errs.append(f"too many long items {long_n}")
# EN exclusion
en_rows, en_keys, en_texts = set(), set(), []
for p in en:
    if Path(p).exists():
        for l in open(p, encoding="utf-8"):
            x = json.loads(l)
            if x.get("source") == "LLMail-Inject" and x.get("label") == "injection":
                en_rows.add(x["origin"].get("row_index"))
                en_keys.add(x["origin"].get("RowKey") or x["origin"].get("RowKey_or_job_id"))
                en_texts.append(x["text"])
    else:
        print("note: missing", p)
for r in recs:
    if r["origin"]["row_index"] in en_rows or r["origin"]["RowKey"] in en_keys:
        errs.append(f"{r['id']}: overlaps EN")
# pairwise near-dup (sampled exhaustively; uses quick filters)
def nt(t):
    return re.sub(r"\s+", " ", t.lower()).strip()
T = [nt(r["text"]) for r in recs]
SH = [{t[i:i + 5] for i in range(max(1, len(t) - 4))} for t in T]
maxr = 0.0
for i in range(len(T)):
    for j in range(i):
        la, lb = len(T[i]), len(T[j])
        if 2 * min(la, lb) / (la + lb) < 0.6:
            continue
        inter = len(SH[i] & SH[j])
        if inter / max(1, len(SH[i]) + len(SH[j]) - inter) < 0.08:
            continue
        rt = SequenceMatcher(None, T[i], T[j], autojunk=False).ratio()
        maxr = max(maxr, rt)
        if rt >= 0.6:
            errs.append(f"near-dup {recs[i]['id']} ~ {recs[j]['id']} {rt:.2f}")
print("max pairwise difflib ratio among checked pairs: %.3f" % maxr)
print("records", len(recs), "| errors", len(errs))
for e in errs[:50]:
    print(" ", e)
