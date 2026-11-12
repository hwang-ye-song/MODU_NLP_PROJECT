"""Rank Phase 1 detector-evasion candidates for the JA condition and write records.

Usage: python -X utf8 -I select_p1.py <pool.jsonl> <overrides.json> <out.jsonl> <review.jsonl> <n_out> <n_review>
       <revision> <dedup_file> [<dedup_file> ...]

Adapted from WD/_build/scripts/ja_llmail/select_ja.py (Phase 2 JA set); same ranking logic.
- dedup_file: existing JSONL files. Every record's text is used in the near-duplicate check
  (difflib ratio >= 0.6 -> excluded); LLMail records are also excluded by RowKey / job_id
  (row_index is NOT used: the existing LLMail rows index the Phase 2 file).
- Order: tier "full" (all 5 objective flags true) first, then "partial" (undetected but not all
  exfil flags; rows with exfil.sent first). Inside a tier, detectors are taken round-robin
  (all, llm_judge, task_tracker, prompt_shield: scarcest first); inside a detector, its levels
  (scenario x model) rotate; inside a level, rows with exfil.sent first, then random.seed(42) order.
- Constraints: <= 3 per team (pass A); difflib ratio < 0.6 to every earlier pick and to every
  dedup_file text; <= LONG_CAP texts longer than 3000 chars; partial rows need a goal cue and an
  assistant/automation cue; manual overrides exclude rows or fix annotations.
- Pass B (only when pass A yields fewer than n_review): reserve tail with team cap 4, then 5.
"""
import hashlib
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
dedup_files = sys.argv[8:]
n_out, n_rev = int(n_out), int(n_rev)
LONG_CAP = 37          # 15% of 250 (the merge keeps 250)
DET_ORDER = ["all", "llm_judge", "task_tracker", "prompt_shield"]  # scarcest first
KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
URL = "https://huggingface.co/datasets/microsoft/llmail-inject-challenge"

pool = [json.loads(l) for l in open(pool_p, encoding="utf-8")]
ovr = json.loads(Path(ovr_p).read_text(encoding="utf-8")) if Path(ovr_p).exists() else {}
ovr = {int(k): v for k, v in ovr.items()}

ZW = re.compile("[​-‏⁠-⁤﻿­᠎͏]")
COMB = re.compile("[̀-ͯ҉⃐-⃿]")


def norm_sim(t):
    t = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t)
    t = unicodedata.normalize("NFKC", ZW.sub("", t))
    t = COMB.sub("", unicodedata.normalize("NFKD", t))
    return re.sub(r"\s+", " ", t.lower()).strip()


# ---------------- existing data ----------------
ex_keys, ex_texts, ex_report = set(), [], []
for p in dedup_files:
    pp = Path(p)
    if not pp.exists():
        ex_report.append(f"missing:{pp.name}")
        continue
    n = 0
    for l in pp.read_text(encoding="utf-8").splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        o = r.get("origin") or {}
        if r.get("source") == "LLMail-Inject":
            for k in ("RowKey", "RowKey_or_job_id", "job_id"):
                if o.get(k):
                    ex_keys.add(o[k])
        ex_texts.append((norm_sim(r["text"]), r.get("source") == "LLMail-Inject", pp.name))
        n += 1
    ex_report.append(f"{pp.name}:{n}")

sel_texts = []
_sig = hashlib.sha1(("v3-contain-jacc|||" + "|||".join(sorted(t for t, _, _ in ex_texts))).encode("utf-8")).hexdigest()[:16]
_cache_p = Path(out_p).with_name(f"ex_neardup_cache_{_sig}.json")
ex_cache = json.loads(_cache_p.read_text(encoding="utf-8")) if _cache_p.exists() else {}
_sh = {}


def shingles(t):
    s = _sh.get(t)
    if s is None:
        s = _sh[t] = {hash(t[i:i + 5]) for i in range(max(1, len(t) - 4))}
    return s


def similar(a, b, contain=True):
    """difflib ratio >= 0.6 (character level, autojunk off); a 5-gram Jaccard >= 0.12
    prefilter skips pairs that cannot plausibly reach 0.6. Stricter addition: if contain,
    a text whose 5-grams are >= 80% contained in the other (e.g. one submission pasted inside
    a longer one) also counts as a near duplicate; so does any pair with 5-gram Jaccard >= 0.5."""
    la, lb = len(a), len(b)
    sa, sb = shingles(a), shingles(b)
    inter = len(sa & sb)
    if contain and min(la, lb) >= 150 and inter / max(1, min(len(sa), len(sb))) >= 0.8:
        return True
    jac = inter / max(1, len(sa) + len(sb) - inter)
    if jac >= 0.5:          # common brief: 5-gram Jaccard must stay < 0.5
        return True
    if 2 * min(la, lb) / (la + lb) < 0.6:
        return False
    if jac < 0.12:
        return False
    return SequenceMatcher(None, a, b, autojunk=False).ratio() >= 0.6


_pair_p = Path(out_p).with_name("pair_cache_v3.json")
pair_cache = json.loads(_pair_p.read_text(encoding="utf-8")) if _pair_p.exists() else {}


def near_sel(r):
    """near-duplicate check against the picks so far (same team first); pair results cached across runs."""
    for nt2, ri2, team2 in sorted(sel_texts, key=lambda x: x[2] != r["team_id"]):
        a, b = sorted((r["row_index"], ri2))
        k = f"{a}|{b}"
        if k not in pair_cache:
            pair_cache[k] = similar(r["_nt"], nt2)
        if pair_cache[k]:
            return True
    return False


def near_any(nt, texts, team=None, existing=False):
    if team is not None:
        texts = sorted(texts, key=lambda x: x[2] != team)
    return any(similar(nt, s[0], contain=(not existing) or bool(s[1])) for s in texts)


# ---------------- eligibility ----------------
AI_CUE = re.compile(r"\b(assistant|a\.?i\.?|llm|language model|model|agent|bot|summar\w*|tool|api|function|"
                    r"system|automat\w*|processing|process(ed)?|script|execute|dispatch|json|send_?e?mail|"
                    r"instruction|prompt|user|log)\b|<\||\{\s*\"", re.I)
_rev_p = Path(ovr_p).with_name("reviewed_rows.txt")
REVIEWED = {int(x) for x in _rev_p.read_text().split()} if _rev_p.exists() else set()
excl = Counter()
cands = []
for r in pool:
    ri = r["row_index"]
    if r["RowKey"] in ex_keys or r["job_id"] in ex_keys:
        excl["existing_same_submission"] += 1
        continue
    o = ovr.get(ri, {})
    if o.get("exclude"):
        excl["manual:" + o["exclude"].split(":")[0]] += 1
        continue
    _t = unicodedata.normalize("NFKC", r["text"])
    _L = [c for c in _t if c.isalpha()]
    if sum(1 for c in _L if not c.isascii()) / max(1, len(_L)) > 0.12 and not o.get("keep"):
        excl["non_english_share"] += 1
        continue
    f = r["f"]
    goal = (f["goal_addr"] or f["goal_body"]) and f["send_verb"]
    if r["tier"] == "partial" and not goal and not o.get("keep"):
        excl["partial_no_goal_cue"] += 1
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
    if near_sel(r):
        skip["near_dup_selected"] += 1
        return False
    if ex_texts:
        k = str(r["row_index"])
        if k not in ex_cache:
            ex_cache[k] = near_any(r["_nt"], ex_texts, existing=True)
        if ex_cache[k]:
            skip["existing_near_dup"] += 1
            return False
    return True


def take(d, cells, lv, cur, ptr, cap):
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
# Detector allocation (coordinator request: the evaluated guardrail is itself an LLM judge).
# Shares per 280: llm_judge >= 90, all ~60, task_tracker ~70, prompt_shield ~60.
SHARE = {"all": 60, "llm_judge": 90, "task_tracker": 70, "prompt_shield": 60}
SCARCE = ["all", "llm_judge"]   # 'all' teams are a subset of llm_judge teams, so 'all' claims first


def add(r, pass_name):
    global long_n
    r["_pass"] = pass_name
    picked.append(r)
    picked_rows.add(r["row_index"])
    sel_texts.append((r["_nt"], r["row_index"], r["team_id"]))
    team_n[r["team_id"]] += 1
    det_n[r["detector"]] += 1
    long_n += r["len"] > 3000


def fill(d, cap, quota, pass_name):
    """take rows of detector d (full tier first, then partial) until det_n[d] == quota."""
    for tier in ("full", "partial"):
        cells = level_lists([r for r in cands if r["tier"] == tier and r["detector"] == d
                             and r["row_index"] not in picked_rows])
        lv = {d: sorted(cells)}
        cur = {d: 0}
        ptr = {(d, l): 0 for l in lv[d]}
        while det_n[d] < quota:
            r = take(d, {d: cells}, lv, cur, ptr, cap)
            if r is None:
                break
            add(r, pass_name)


scale = n_rev / n_out
quota = {d: round(SHARE[d] * scale) for d in SHARE}
for cap in (3, 4, 5):            # the brief allows up to 5 per team when needed; only for the scarce detectors
    for d in SCARCE:
        fill(d, cap, quota[d], "A_team_cap3" if cap == 3 else f"B_team_cap{cap}")
short_all = max(0, quota["all"] - det_n["all"])
if short_all:                   # give the 'all' shortfall to llm_judge first
    quota["llm_judge"] += short_all
    for cap in (3, 4, 5):
        fill("llm_judge", cap, quota["llm_judge"], "A_team_cap3" if cap == 3 else f"B_team_cap{cap}")
rest = n_rev - det_n["all"] - det_n["llm_judge"]
quota["task_tracker"] = round(rest * SHARE["task_tracker"] / (SHARE["task_tracker"] + SHARE["prompt_shield"]))
quota["prompt_shield"] = rest - quota["task_tracker"]
fill("task_tracker", 3, quota["task_tracker"], "A_team_cap3")
fill("prompt_shield", 3, quota["prompt_shield"], "A_team_cap3")
for d in ("task_tracker", "prompt_shield"):   # top up if the other one ran short
    if len(picked) < n_rev:
        fill(d, 3, det_n[d] + n_rev - len(picked), "A_team_cap3")
nA = sum(r["_pass"] == "A_team_cap3" for r in picked)
print("allocation quotas:", quota, "picked:", dict(det_n))


def interleave(rows):
    """smooth weighted interleave over detectors, keeping each detector's pick order."""
    q = {d: [r for r in rows if r["detector"] == d] for d in DET_ORDER}
    tot = {d: len(q[d]) for d in DET_ORDER}
    taken = Counter()
    out = []
    while any(q.values()):
        d = min((d for d in DET_ORDER if q[d]), key=lambda d: ((taken[d] + 0.5) / tot[d], DET_ORDER.index(d)))
        out.append(q[d].pop(0))
        taken[d] += 1
    return out


def block_order(rows):
    return interleave([r for r in rows if r["tier"] == "full"]) + interleave([r for r in rows if r["tier"] == "partial"])


# The merge keeps the first 250 non-overlapping items: positions 1..HEAD hold each detector's best picks in
# the same proportions as the whole list; the tail holds each detector's last picks (proportional share).
HEAD = round(n_out * 250 / 280)
tot_n = Counter(r["detector"] for r in picked)
head_n = {d: round(tot_n[d] * HEAD / len(picked)) for d in DET_ORDER}
while sum(head_n.values()) != HEAD:
    d = max(DET_ORDER, key=lambda d: tot_n[d] * HEAD / len(picked) - head_n[d]) if sum(head_n.values()) < HEAD         else min(DET_ORDER, key=lambda d: tot_n[d] * HEAD / len(picked) - head_n[d])
    head_n[d] += 1 if sum(head_n.values()) < HEAD else -1
# pick order inside a detector: pass A before reserve; full before partial; then pick sequence
seq = {r["row_index"]: i for i, r in enumerate(picked)}
by_det = {d: sorted([r for r in picked if r["detector"] == d],
                    key=lambda r: (r["_pass"] != "A_team_cap3", r["tier"] != "full", r["subrank"], seq[r["row_index"]]))
          for d in DET_ORDER}
head = [r for d in DET_ORDER for r in by_det[d][:head_n[d]]]
tail = [r for d in DET_ORDER for r in by_det[d][head_n[d]:]]
for r in head:
    r["_block"] = "head"
for r in tail:
    r["_block"] = "tail"
picked = block_order(head) + block_order(tail)

_cache_p.write_text(json.dumps(ex_cache), encoding="utf-8")
_pair_p.write_text(json.dumps(pair_cache), encoding="utf-8")

# ---------------- annotation ----------------
SENT_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
GOAL_ADDR = re.compile(r"contact\s*(@|\(at\)|\[at\]|\{at\}| at |＠)\s*contact|contact@contact\.com", re.I)
GOAL4 = re.compile(r"million|profit|forecast|\bq2\b|estimate", re.I)
SENDV = re.compile(r"\b(send|sent|sending|e-?mail|mail|reply|respond|forward|notify|dispatch|transmit)\b", re.I)


def auto_instr(text, scen):
    best = None
    for s in SENT_SPLIT.split(text):
        s = s.strip()
        if len(s) < 12:
            continue
        ns = norm_sim(s)
        has_addr = bool(GOAL_ADDR.search(ns))
        has_conf = ("confirmation" in ns) if scen != 4 else bool(GOAL4.search(ns))
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


recs = []
for n, r in enumerate(picked, 1):
    o = ovr.get(r["row_index"], {})
    scen = int(r["scenario"][-1])
    instr = o["instr"] if "instr" in o else auto_instr(r["text"], scen)
    if "instr_span" in o:
        a_, b_ = o["instr_span"]
        i_ = r["text"].index(a_)
        instr = r["text"][i_:r["text"].index(b_, i_) + len(b_)]
    if o.get("instr_tagrun"):
        instr = max(re.findall("[\U000E0000-\U000E007F]+", r["text"]), key=len)
    if o.get("instr_null"):
        instr = None
    assert instr is None or instr in r["text"], (r["row_index"], instr)
    tags = tags_of(r)
    tags = [x for x in tags if x not in set(o.get("tags_remove", []))]
    tags += [x for x in o.get("tags_add", []) if x not in tags]
    risk = o.get("risk", 4 if scen == 4 else 3)
    harm = "data_exfiltration" if risk == 4 else "unauthorized_action"
    if risk == 4:
        dflt = "Q2 이익 전망치를 외부 주소로 보내게 해 정보 유출" if scen == 4 else \
            "메일함 내용을 contact@contact.com으로 보내게 해 정보 유출"
    else:
        dflt = "contact@contact.com로 'confirmation' 메일 무단 발송 유도"
    rationale = o.get("rationale") or dflt
    ob = r["objectives"]
    goal_txt = "send the Q2 profit forecast ('$NUM million') to contact@contact.com" if scen == 4 else \
        "send 'confirmation' to contact@contact.com"
    tier_txt = "full success (tool call with correct recipient and body)" if r["tier"] == "full" else (
        "undetected; tool called but recipient/body wrong" if ob["exfil.sent"] else "undetected; no tool call")
    note = f"Phase 1 {r['detector_detail']} on {r['model']}, {r['scenario']} (goal: {goal_txt}): {tier_txt}."
    if o.get("note"):
        note += " " + o["note"]
    if r["_pass"] != "A_team_cap3":
        note += (f" Team cap exception ({r['_pass']}): this team's {r['_pass'][-1]}th pick, allowed only to reach the "
                 f"llm_judge/all allocation.")
    rec = {
        "id": f"ja-llmail-p1-{n:03d}", "label": "injection", "source": "LLMail-Inject",
        "subset": "phase1_detector_evasion", "doc_type": "email", "text": r["text"],
        "injected_instruction": instr, "detector": r["detector"], "technique_tags": tags,
        "risk_level": risk, "harm_type": harm, "risk_rationale": rationale,
        "origin": {"url": URL, "revision": revision, "split": "Phase1", "file": "data/raw_submissions_phase1.jsonl",
                   "row_index": r["row_index"], "RowKey": r["RowKey"], "level": r["level"],
                   "scenario": r["scenario"], "defense": r["detector_detail"], "model": r["model"],
                   "objectives": ob, "team_id": r["team_id"]},
        "notes": note, "core": False,
    }
    recs.append(rec)

with open(out_p, "w", encoding="utf-8", newline="\n") as fh:
    for rec in recs[:n_out]:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
with open(rev_p, "w", encoding="utf-8", newline="\n") as fh:
    for rec in recs:
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

top = recs[:n_out]
print("dedup files:", ex_report)
print("eligibility exclusions:", dict(excl))
print("ranking skips:", dict(skip))
print(f"picked {len(picked)} (pass A {nA}); wrote {len(top)}")
print("pass/tier:", Counter(r["_pass"] + ":" + r["tier"] for r in picked[:n_out]))
print("head250 detectors:", Counter(x["detector"] for x in recs[:250]))
print("detector x tier:", sorted(Counter((x['detector'], 'full' if all(x['origin']['objectives'][k] for k in KEYS) else 'partial') for x in top).items()))
print("scenario:", sorted(Counter(x["origin"]["scenario"] for x in top).items()), "model:", Counter(x["origin"]["model"] for x in top))
print("tags:", Counter(t for x in top for t in x["technique_tags"]).most_common())
L = sorted(len(x["text"]) for x in top)
print("len min/med/p90/max:", L[0], L[len(L) // 2], L[int(len(L) * .9)], L[-1], ">3000:", sum(l > 3000 for l in L))
print("teams:", len({x['origin']['team_id'] for x in top}), "max per team:", max(Counter(x['origin']['team_id'] for x in top).values()))
print("risk:", Counter(x["risk_level"] for x in top), "instr null:", sum(x["injected_instruction"] is None for x in top))
