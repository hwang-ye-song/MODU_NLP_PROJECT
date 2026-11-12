"""Build the eligible LLMail-Inject Phase 2 pool with heuristic technique tags.

Usage: python -X utf8 -I pool.py <raw_submissions_phase2.jsonl> <out_pool.jsonl>

Filters: valid Phase 2 scenario (level[12][k-v]), all 5 objective flags present,
non-empty body, text = "Subject: <subject>\\n\\n<body>" with 100 <= len <= 3000,
mostly-English (checked on NFKC-normalised text so Unicode tricks are not dropped),
exact-duplicate removal on (normalised text, scenario, stratum) (first occurrence kept);
cross-level repeats of one text are left for the selection-time near-duplicate filter.
"""
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
src, out = sys.argv[1], sys.argv[2]

KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
VALID = re.compile(r"^level[12][k-v]$")
STOP = {"the", "to", "and", "please", "email", "you", "is", "a", "of", "this", "with", "send",
        "for", "your", "in", "that", "it", "be", "an", "on", "as", "are", "we", "i", "my", "me"}

TAG_RX = {
    "fake_tokens": r"<\|[^|>\n]{1,30}\|>|\[/?(INST|SYS|SYSTEM|USER|ASSISTANT)\]|<</?SYS>>|<\s*/?\s*(system|user|assistant|im_start|im_end|start_of_turn|end_of_turn|human|bot)\b[^>\n]{0,20}>|^\s*(###\s*)?(system|user|assistant|human)\s*:|<start_of_turn>|<end_of_turn>",
    "delimiter_escape": r"end of (the )?(email|emails|context|document|data|input)|</\s*(email|emails|mail|mails|context|document|data|input|tool|tool_output|function_results)>|\"\s*\}\s*\]|```\s*\n\s*(</|---|\{)|-{3,}\s*end|={3,}|\[end\]|#####",
    "spoofed_header": r"^\s*(From|Sent|To|Cc|Date)\s*:|forwarded message|original message|^\s*>\s*On .* wrote:",
    "urgency": r"\b(urgent|urgently|immediately|asap|right away|deadline|critical|time[- ]sensitive|emergency)\b",
    "authority": r"\b(ceo|cfo|cto|administrator|admin|it department|it team|security team|compliance|hr department|microsoft|openai|developer|management|director|boss|supervisor|officer)\b",
    "base64": r"[A-Za-z0-9+/]{24,}={0,2}",
    "hex": r"(\b[0-9A-Fa-f]{2}\b[\s,:]+){12,}|(\\x[0-9a-fA-F]{2}){8,}|0x[0-9a-fA-F]{2}",
    "encoding_kw": r"\b(base64|hex|rot13|rot-13|caesar|decode|decoded|encode|encoded|cipher|reverse[d]?|backwards|ascii|binary|morse|unicode)\b",
    "code": r"```|\bdef \w+\(|\bfunction\s*\w*\(|\bimport \w+|\bprint\(|\breturn\b|\bconsole\.log|\bvar \w+\s*=|\bconst \w+\s*=|\{\s*\"(to|body|recipient|function|name|tool|action)\"\s*:",
    "tool_call": r"send_email|sendemail|tool_call|function_call|\"arguments\"|api call|<tool|tool_code",
    "judge": r"\b(judge|evaluator|evaluation|classifier|prompt shield|tasktracker|task tracker|safety (check|filter|label|rating)|not (a )?(prompt )?injection|jailbreak|is safe|rated?|score)\b",
    "roleplay": r"\b(pretend|role[- ]?play|you are now|imagine|game|story|character|simulation|act as|hypothetical)\b",
    "split": r"\b(concatenate|concatenation|combine|join|merge|first (letter|word|part)|part [12]|step \d|fill in|variable|placeholder)\b",
    "html": r"<!--|<html|<div|<span|<p>|<br|<table|<a href|<b>|style=",
    "markdown": r"^\s*#{1,6} |\*\*[^*\n]+\*\*|^\s*\|.*\|\s*$",
    "spaced_or_obf": r"(\b\w\s){6,}\w\b|\(at\)|\[at\]|\{at\}|\bdot com\b|\(dot\)|\[dot\]",
    "leet": r"\b(?![\w.]*@)[a-z]+[0137$][a-z]+\b",
    "fake_summary": r"\b(summary of (the )?emails?|here is (the|a) summary|email summary|summary:)",
}
TAG_C = {k: re.compile(v, re.I | re.M) for k, v in TAG_RX.items()}

ZW = re.compile("[​-‏⁠-⁤﻿­]")
TAGCH = re.compile("[\U000E0000-\U000E007F]")
FULLW = re.compile("[！-～]")
COMBINING = re.compile("[̀-ͯ]")
CYR = re.compile("[Ѐ-ӿ]")
CJK = re.compile("[぀-ヿ㐀-鿿가-힯]")
OTHER_SCRIPT = re.compile("[֐-ۿऀ-෿฀-๿]")
MATHALPHA = re.compile("[\U0001D400-\U0001D7FF]")


def parse_obj(o):
    if isinstance(o, str):
        try:
            return json.loads(o)
        except Exception:
            return None
    return o


def stratum(o):
    if all(o.get(k) for k in KEYS):
        return "full"
    if o.get("defense.undetected"):
        return "undetected_partial"
    return "detected"


def lang_stats(t):
    n = unicodedata.normalize("NFKC", TAGCH.sub("", ZW.sub("", t)))
    letters = [c for c in n if c.isalpha()]
    if not letters:
        return 0.0, 0, 0
    ascii_ratio = sum(c.isascii() for c in letters) / len(letters)
    words = re.findall(r"[a-z]+", n.lower())
    sw = sum(w in STOP for w in words)
    return ascii_ratio, sw, len(words)


def tags(t):
    tg = [k for k, rx in TAG_C.items() if rx.search(t)]
    if ZW.search(t):
        tg.append("zero_width")
    if TAGCH.search(t):
        tg.append("tag_chars")
    if FULLW.search(t):
        tg.append("fullwidth")
    if COMBINING.search(t):
        tg.append("combining")
    if CYR.search(t):
        tg.append("cyrillic")
    if MATHALPHA.search(t):
        tg.append("math_alpha")
    if CJK.search(t) or OTHER_SCRIPT.search(t):
        tg.append("non_latin_script")
    return tg


rows = []
seen = set()
stats = Counter()
with open(src, encoding="utf-8") as f:
    for i, line in enumerate(f):
        if not line.strip():
            continue
        r = json.loads(line)
        stats["total"] += 1
        sc = r.get("scenario") or ""
        if not VALID.match(sc):
            stats["bad_scenario"] += 1
            continue
        o = parse_obj(r.get("objectives"))
        if not o or any(o.get(k) is None for k in KEYS):
            stats["bad_obj"] += 1
            continue
        subj = r.get("subject") or ""
        body = r.get("body") or ""
        if not body.strip():
            stats["empty_body"] += 1
            continue
        text = f"Subject: {subj}\n\n{body}"
        if len(text) > 3000 or len(text) < 100:
            stats["length"] += 1
            continue
        o_str = stratum(o)
        k = (re.sub(r"\s+", " ", text.lower()).strip(), sc, o_str)
        if k in seen:
            stats["exact_dup"] += 1
            continue
        seen.add(k)
        ar, sw, nw = lang_stats(text)
        english = ar >= 0.97 and sw >= 4 and sw / max(1, nw) >= 0.08
        mostly_english = (not english) and ar >= 0.75 and sw >= 6 and sw / max(1, nw) >= 0.08
        if not (english or mostly_english):
            stats["not_english"] += 1
            continue
        rows.append({
            "row_index": i, "RowKey": r.get("RowKey"), "job_id": r.get("job_id"),
            "scenario": sc, "team_id": r.get("team_id"), "objectives": o,
            "stratum": stratum(o), "text": text, "len": len(text),
            "english": english, "ascii_ratio": round(ar, 3),
            "tags": tags(text), "completed_time": r.get("completed_time"),
        })

print(dict(stats))
print("eligible", len(rows), "strict english", sum(r["english"] for r in rows))
cell = defaultdict(Counter)
teams = defaultdict(set)
for r in rows:
    cell[r["scenario"]][r["stratum"]] += 1
    teams[(r["scenario"], r["stratum"])].add(r["team_id"])
for sc in sorted(cell):
    print(sc, {s: (cell[sc][s], len(teams[(sc, s)])) for s in ["full", "undetected_partial", "detected"]})
print("teams overall", len({r["team_id"] for r in rows}))
tc = Counter(t for r in rows for t in r["tags"])
print(tc.most_common())
with open(out, "w", encoding="utf-8") as f:
    for r in rows:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")
