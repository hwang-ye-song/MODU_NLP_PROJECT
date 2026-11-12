"""Rank detector-evasion candidates for the JA condition and write records.

Usage: python -X utf8 -I select_ja.py <pool.jsonl> <overrides.json> <out.jsonl> <review.txt> <n_out> <n_review> <revision> <en_llmail_part> [<en_llmail_part> ...]

- en_llmail_part: EN LLMail injection part files (missing files are skipped and reported).
  Their submissions are excluded by row_index / RowKey, and their texts are used in the
  near-duplicate check (difflib ratio >= 0.6 -> excluded).
- Order: tier "full" (all 5 objective flags true) first, then "partial" (undetected but not
  all exfil flags; rows with exfil.sent first). Inside a tier, detectors are taken round-robin
  (all, llm_judge, task_tracker, prompt_shield: scarcest first, so scarce detectors get first
  claim on a team's 3 slots); inside a detector, its levels (scenario x model x variant) rotate;
  inside a level, rows with exfil.sent first, then random.seed(42) order.
- Constraints while ranking: <= 3 per team (pass A); difflib ratio < 0.6 to every earlier pick;
  <= LONG_CAP texts longer than 3000 chars; partial rows need a goal cue (address/confirmation
  + send-like verb); manual overrides can exclude rows or fix annotations.
- Pass B (only when pass A yields fewer than n_review): a reserve tail with team cap 4, then 5,
  same ordering, appended after pass A.
"""
import json
import random
import re
import sys
import unicodedata
from collections import Counter, defaultdict
from difflib import SequenceMatcher
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
pool_p, ovr_p, out_p, rev_p, n_out, n_rev, revision = sys.argv[1:8]
en_parts = sys.argv[8:]
n_out, n_rev = int(n_out), int(n_rev)
LONG_CAP = 37          # 15% of 250 (the merge keeps 250); 13% of 280
DET_ORDER = ["all", "llm_judge", "task_tracker", "prompt_shield"]  # scarcest first
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
URL = "https://huggingface.co/datasets/microsoft/llmail-inject-challenge"

pool = [json.loads(l) for l in open(pool_p, encoding="utf-8")]
ovr = json.loads(Path(ovr_p).read_text(encoding="utf-8")) if Path(ovr_p).exists() else {}
ovr = {int(k): v for k, v in ovr.items()}

ZW = re.compile("[​-‏⁠-⁤﻿­᠎͏]")
TAGCH = re.compile("[\U000E0000-\U000E007F]")
COMB = re.compile("[̀-ͯ҉⃐-⃿]")


def norm_sim(t):
    t = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t)
    t = unicodedata.normalize("NFKC", ZW.sub("", t))
    t = COMB.sub("", unicodedata.normalize("NFKD", t))
    return re.sub(r"\s+", " ", t.lower()).strip()


# ---------------- EN exclusion ----------------
en_rows, en_keys, en_texts, en_report = set(), set(), [], []
for p in en_parts:
    pp = Path(p)
    if not pp.exists():
        en_report.append(f"missing:{pp.parent.name}/{pp.name}")
        continue
    n = 0
    for l in pp.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r.get("source") != "LLMail-Inject" or r.get("label") != "injection":
            continue
        o = r.get("origin", {})
        if o.get("row_index") is not None:
            en_rows.add(int(o["row_index"]))
        for k in ("RowKey", "RowKey_or_job_id", "job_id"):
            if o.get(k):
                en_keys.add(o[k])
        en_texts.append((norm_sim(r["text"]), None, None))
        n += 1
    en_report.append(f"{pp.parent.name}/{pp.name}:{n}")

sel_texts = []  # (norm text, shingles, team) of picks
import hashlib
_sig = hashlib.sha1("|||".join(sorted(t for t, _, _ in en_texts)).encode("utf-8")).hexdigest()[:16]
_cache_p = Path(out_p).with_name(f"en_neardup_cache_{_sig}.json")
en_cache = json.loads(_cache_p.read_text(encoding="utf-8")) if _cache_p.exists() else {}
_sh = {}


def shingles(t):
    s = _sh.get(t)
    if s is None:
        s = _sh[t] = {hash(t[i:i + 5]) for i in range(max(1, len(t) - 4))}
    return s


def similar(a, b):
    """difflib ratio >= 0.6 (character level, autojunk off); a 5-gram Jaccard >= 0.12
    prefilter skips pairs that cannot plausibly reach 0.6."""
    la, lb = len(a), len(b)
    if 2 * min(la, lb) / (la + lb) < 0.6:
        return False
    sa, sb = shingles(a), shingles(b)
    inter = len(sa & sb)
    if inter / max(1, len(sa) + len(sb) - inter) < 0.12:
        return False
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.6


def near_any(nt, texts, team=None):
    if team is not None:
        texts = sorted(texts, key=lambda x: x[2] != team)
    return any(similar(nt, s[0]) for s in texts)


# ---------------- eligibility ----------------
# undetected-but-partial rows must also show some sign that the text targets the AI/automated
# processing (otherwise it is usually an ordinary person-to-person request; see manual review)
AI_CUE = re.compile(r"\b(assistant|a\.?i\.?|llm|language model|model|agent|bot|summar\w*|tool|api|function|"
                    r"system|automat\w*|processing|process(ed)?|script|execute|dispatch|json|send_?e?mail|"
                    r"instruction|prompt|user|log)\b|<\||\{\s*\"", re.I)
# Teams whose manually reviewed rows were mostly not instructions (musings, narratives, stories,
# person-to-person requests): only rows already reviewed and kept are eligible.
REVIEW_ONLY_TEAMS = {"ab2403", "46dfe9", "21ab52", "ec6f8e", "89cc7c", "67e92f", "af5733",
                     "5aad2d", "c14698", "9ab98f", "996614"}
_rev_p = Path(ovr_p).with_name("reviewed_rows.txt")
REVIEWED = {int(x) for x in _rev_p.read_text().split()} if _rev_p.exists() else set()
excl = Counter()
cands = []
for r in pool:
    ri = r["row_index"]
    if ri in en_rows or r["RowKey"] in en_keys or r["job_id"] in en_keys:
        excl["en_same_submission"] += 1
        continue
    o = ovr.get(ri, {})
    if o.get("exclude"):
        excl["manual:" + o["exclude"].split(":")[0]] += 1
        continue
    f = r["f"]
    goal = (f["goal_addr"] or f["goal_body"]) and f["send_verb"]
    if r["tier"] == "partial" and not goal and not o.get("keep"):
        excl["partial_no_goal_cue"] += 1
        continue
    if r["team_id"][:6] in REVIEW_ONLY_TEAMS and ri not in REVIEWED:
        excl["unreviewed_row_of_low_yield_team"] += 1
        continue
    r["_nt"] = norm_sim(r["text"])
    if r["tier"] == "partial" and not AI_CUE.search(r["_nt"]) and not o.get("keep"):
        excl["partial_no_assistant_cue"] += 1
        continue
    cands.append(r)

random.seed(42)
random.shuffle(cands)
rank = {r["row_index"]: i for i, r in enumerate(cands)}


def level_lists(rows):
    """per level (= scenario x model x defense variant): subrank first, then seed order."""
    cells = defaultdict(list)
    for r in sorted(rows, key=lambda x: (x["subrank"], rank[x["row_index"]])):
        cells[r["level"]].append(r)
    return cells


picked, picked_rows = [], set()
team_n = Counter()
long_n = 0
skip = Counter()


def eligible(r, cap):
    if team_n[r["team_id"]] >= cap:
        skip["team_cap"] += 1
        return False
    if r["len"] > 3000 and long_n >= LONG_CAP:
        skip["long_cap"] += 1
        return False
    if en_texts:
        k = str(r["row_index"])
        if k not in en_cache:
            en_cache[k] = near_any(r["_nt"], en_texts)
        if en_cache[k]:
            skip["en_near_dup"] += 1
            return False
    if near_any(r["_nt"], sel_texts, r["team_id"]):
        skip["near_dup_selected"] += 1
        return False
    return True


def take(d, cells, lv, cur, ptr, cap):
    """next eligible row for detector d, rotating over its levels."""
    for k in range(len(lv[d])):
        l = lv[d][(cur[d] + k) % len(lv[d])]
        lst = cells[d][l]
        while ptr[(d, l)] < len(lst):
            r = lst[ptr[(d, l)]]
            ptr[(d, l)] += 1
            if eligible(r, cap):
                cur[d] = (cur[d] + k + 1) % len(lv[d])
                return r
    return None


det_n = Counter()


def run_pass(tier, cap, limit, pass_name, quota=None):
    """quota given: detectors are filled one after another, scarcest first, each up to `quota`
    picks in total (so scarce detectors get first claim on a team's slots); quota None:
    round-robin over detectors until all are exhausted or `limit` is reached."""
    global long_n
    # reserve passes (team cap > 3) only draw on rows that were already read by hand
    reviewed_only = pass_name != "A_team_cap3"
    cells = {d: level_lists([r for r in cands if r["tier"] == tier and r["detector"] == d
                             and r["row_index"] not in picked_rows
                             and (not reviewed_only or r["row_index"] in REVIEWED)]) for d in DET_ORDER}
    lv = {d: sorted(cells[d]) for d in DET_ORDER}
    cur = {d: 0 for d in DET_ORDER}
    ptr = {(d, l): 0 for d in DET_ORDER for l in lv[d]}

    def add(r):
        global long_n
        r["_pass"] = pass_name
        picked.append(r)
        picked_rows.add(r["row_index"])
        sel_texts.append((r["_nt"], None, r["team_id"]))
        team_n[r["team_id"]] += 1
        det_n[r["detector"]] += 1
        long_n += r["len"] > 3000

    if quota is not None:
        for d in DET_ORDER:
            while len(picked) < limit and det_n[d] < quota:
                r = take(d, cells, lv, cur, ptr, cap)
                if r is None:
                    break
                add(r)
        return
    alive = {d: bool(lv[d]) for d in DET_ORDER}
    while len(picked) < limit and any(alive.values()):
        for d in DET_ORDER:
            if len(picked) >= limit or not alive[d]:
                continue
            r = take(d, cells, lv, cur, ptr, cap)
            if r is None:
                alive[d] = False
            else:
                add(r)


QUOTA = -(-n_out // len(DET_ORDER))  # 70 per detector for 280
run_pass("full", 3, n_rev, "A_team_cap3")                 # all full successes first
run_pass("partial", 3, n_rev, "A_team_cap3", QUOTA)       # scarce detectors claim team slots
run_pass("partial", 3, n_rev, "A_team_cap3")              # fill remaining cap-3 slots
nA = len(picked)
for cap in (4, 5, 6, 7, 8, 9, 10):
    for tier in ("full", "partial"):
        if len(picked) < n_rev:
            run_pass(tier, cap, n_rev, f"B_team_cap{cap}")

# final order: pass A before reserve; full before partial; round-robin across detectors (pick order inside)
def rr(rows):
    q = {d: [r for r in rows if r["detector"] == d] for d in DET_ORDER}
    out = []
    while any(q.values()):
        for d in DET_ORDER:
            if q[d]:
                out.append(q[d].pop(0))
    return out


grpA = [r for r in picked if r["_pass"] == "A_team_cap3"]
grpB = [r for r in picked if r["_pass"] != "A_team_cap3"]
picked = (rr([r for r in grpA if r["tier"] == "full"]) + rr([r for r in grpA if r["tier"] == "partial"])
          + rr([r for r in grpB if r["tier"] == "full"]) + rr([r for r in grpB if r["tier"] == "partial"]))

_cache_p.write_text(json.dumps(en_cache), encoding="utf-8")

# ---------------- annotation ----------------
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
GOAL_ADDR = re.compile(r"contact\s*(@|\(at\)|\[at\]|\{at\}| at |＠)\s*contact|contact@contact\.com", re.I)
SENDV = re.compile(r"\b(send|sent|sending|e-?mail|mail|reply|respond|forward|notify|dispatch|transmit)\b", re.I)


def auto_instr(text):
    best = None
    for s in SENT_SPLIT.split(text):
        s = s.strip()
        if len(s) < 12:
            continue
        ns = norm_sim(s)
        has_addr = bool(GOAL_ADDR.search(ns))
        has_conf = "confirmation" in ns
        has_send = bool(SENDV.search(ns))
        score = (has_send and (has_addr or has_conf)) * 4 + (has_addr and has_conf) * 2 + has_addr
        if score >= 3 and s in text and len(s) <= 400:
            key = (-score, len(s))
            if best is None or key < best[0]:
                best = (key, s)
    return best[1] if best else None


def tags_of(r):
    f, t = r["f"], []
    if f["b64"] or f["hexseq"] or f["binseq"] or f["morse"]:
        t.append("encoding")
    if f["zero_width"] or f["tag_chars"] or f["fullwidth"] > 3 or f["combining"] > 3 or f["homoglyph_words"] \
            or f["math_alpha"] or f["enclosed"] > 3:
        t.append("unicode_obfuscation")
    if f["spaced_or_obf"] or f["weird_case"] >= 3:
        t.append("character_obfuscation")
    if f["delimiter_escape"]:
        t.append("delimiter_escape")
    if f["fake_tokens"]:
        t.append("fake_system_tokens")
    if f["dialogue"]:
        t.append("fake_dialogue_turns")
    if f["judge"]:
        t.append("fake_judge_or_label_claims")
    if f["split"]:
        t.append("payload_splitting")
    if f["roleplay"]:
        t.append("roleplay_or_hypothetical")
    body = r["text"].split("\n\n", 1)[-1]
    if re.search(r"^\s*(From|Sent|To|Cc|Date|Subject)\s*:|forwarded message|original message", body, re.I | re.M):
        t.append("spoofed_headers")
    if f["code"] or f["html"]:
        t.append("code_or_markup_wrapping")
    if f["tool_call"]:
        t.append("fake_tool_call")
    if f["fake_summary"]:
        t.append("fake_summary_or_output")
    if f["urgency"] or f["authority"] or f["pretext"] >= 2:
        t.append("social_engineering")
    if f["greeting"] and not (f["classic_trigger"] or f["fake_tokens"] or f["dialogue"]):
        t.append("benign_framing")
    if not (f["classic_trigger"] or f["ai_address"] or f["fake_tokens"]):
        t.append("paraphrase_low_trigger")
    if f["non_latin"] > 5 or r["ascii_ratio"] < 0.97:
        t.append("multilingual")
    m = GOAL_ADDR.search(r["_nt"]) or re.search("confirmation", r["_nt"])
    if r["len"] > 3000 or (r["len"] > 1500 and m and m.start() / max(1, len(r["_nt"])) > 0.6):
        t.append("long_context")
    return t


def flags(o):
    return "".join(str(int(bool(o[k]))) for k in KEYS)


recs, review = [], []
for n, r in enumerate(picked, 1):
    o = ovr.get(r["row_index"], {})
    instr = o["instr"] if "instr" in o else auto_instr(r["text"])
    if "instr_span" in o:
        a_, b_ = o["instr_span"]
        i_ = r["text"].index(a_)
        instr = r["text"][i_:r["text"].index(b_, i_) + len(b_)]
    if o.get("instr_tagrun"):
        instr = max(re.findall("[󠀀-󠁿]+", r["text"]), key=len)
    if o.get("instr_null"):
        instr = None
    assert instr is None or instr in r["text"], (r["row_index"], instr)
    tags = tags_of(r)
    tags = [x for x in tags if x not in set(o.get("tags_remove", []))]
    tags += [x for x in o.get("tags_add", []) if x not in tags]
    risk = o.get("risk", 3)
    harm = "data_exfiltration" if risk == 4 else "unauthorized_action"
    rationale = o.get("rationale") or ("메일함 내용을 contact@contact.com으로 보내게 해 정보 유출" if risk == 4
                                       else "contact@contact.com로 'confirmation' 메일 무단 발송 유도")
    ob = r["objectives"]
    tier_txt = "full success (tool call with correct recipient and body)" if r["tier"] == "full" else (
        "undetected; tool called but recipient/body wrong" if ob["exfil.sent"] else "undetected; no tool call")
    note = f"{r['detector_detail']} on {r['model']}, {r['scenario']}: {tier_txt}."
    if o.get("note"):
        note += " " + o["note"]
    if r["_pass"] != "A_team_cap3":
        note += f" Reserve tail ({r['_pass']}): exceeds the 3-per-team cap."
    rec = {
        "id": f"ja-llmail-{n:03d}", "label": "injection", "source": "LLMail-Inject",
        "subset": "phase2_detector_evasion", "text": r["text"], "injected_instruction": instr,
        "detector": r["detector"], "technique_tags": tags, "risk_level": risk, "harm_type": harm,
        "risk_rationale": rationale,
        "origin": {"url": URL, "revision": revision, "split": "Phase2", "file": "data/raw_submissions_phase2.jsonl",
                   "row_index": r["row_index"], "RowKey": r["RowKey"], "level": r["level"],
                   "scenario": r["scenario"], "defense": r["detector_detail"], "model": r["model"],
                   "objectives": ob, "team_id": r["team_id"]},
        "notes": note,
    }
    recs.append(rec)
    t = r["text"]
    shown = t if len(t) <= 1400 else t[:900] + f"\n[... {len(t) - 1300} chars ...]\n" + t[-400:]
    review.append(f"=== #{n} row={r['row_index']} {r['level']} {r['detector']} obj={flags(ob)} pass={r['_pass']} "
                  f"team={r['team_id'][:8]} len={r['len']} risk={risk} tags={','.join(tags)}\n"
                  f"--- INSTR: {instr!r}\n{shown}\n")

with open(out_p, "w", encoding="utf-8", newline="\n") as fh:
    for rec in recs[:n_out]:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
Path(rev_p).write_text("\n".join(review), encoding="utf-8")
with open(Path(rev_p).with_suffix(".jsonl"), "w", encoding="utf-8", newline="\n") as fh:
    for rec in recs:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

top = recs[:n_out]
print("EN parts:", en_report, "| EN rows", len(en_rows))
print("eligibility exclusions:", dict(excl))
print("ranking skips:", dict(skip))
print(f"picked {len(picked)} (pass A {nA}); wrote {len(top)}")
print("tier:", Counter(r["_pass"] + ":" + r["tier"] for r in picked[:n_out]))
print("detector x tier:", sorted(Counter((x['detector'], 'full' if all(x['origin']['objectives'][k] for k in KEYS) else 'partial') for x in top).items()))
print("level:", sorted(Counter(x["origin"]["level"] for x in top).items()))
print("scenario:", Counter(x["origin"]["scenario"] for x in top), "model:", Counter(x["origin"]["model"] for x in top))
print("tags:", Counter(t for x in top for t in x["technique_tags"]).most_common())
L = sorted(len(x["text"]) for x in top)
print("len min/med/p90/max:", L[0], L[len(L) // 2], L[int(len(L) * .9)], L[-1], ">3000:", sum(l > 3000 for l in L))
print("teams:", len({x['origin']['team_id'] for x in top}), "max per team:", max(Counter(x['origin']['team_id'] for x in top).values()))
print("risk:", Counter(x["risk_level"] for x in top), "instr null:", sum(x["injected_instruction"] is None for x in top))
