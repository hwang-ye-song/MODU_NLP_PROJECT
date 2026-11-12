"""Build the JA (detector-evasion) pool from LLMail-Inject Phase 1 raw submissions.

Usage: python -X utf8 -I pool_p1.py <raw_submissions_phase1.jsonl> <out_pool.jsonl>

Adapted from WD/_build/scripts/ja_llmail/pool_ja.py (Phase 2). Streams the file line by line.
Keeps rows whose scenario is a Phase 1 level with a detector (level[1-4][a-d,g-j]; e/f are
Spotlighting only and are dropped), objectives parse, email.retrieved == true and
defense.undetected == true. text = "Subject: <subject>

<body>", 80 <= len <= 6000, mostly English.
Exact duplicates (whitespace/case-normalised text) collapse to the best row
(full success > partial with tool call > partial; then the harder detector: all > llm_judge >
task_tracker > prompt_shield; then earliest row).
Adds heuristic features used later for ranking and annotation (goal cues, tags).
"""
import base64
import binascii
import json
import re
import sys
import unicodedata
from collections import Counter, defaultdict

sys.stdout.reconfigure(encoding="utf-8")
src, out = sys.argv[1], sys.argv[2]

KEYS = ["email.retrieved", "defense.undetected", "exfil.sent", "exfil.destination", "exfil.content"]
VALID = re.compile(r"^level([1-4])([a-j])$")
# src/agent/config.yaml (level1a..level4j: defense + model) and data/levels_descriptions.json
# "phase1"; src/agent/workloads/scenarios.py: Phase 1 "all" = task_tracker + prompt_shield +
# llm_judge + spotlight. e/f (spotlight only) have no detector and are excluded.
DEFENSE = {
    "a": ("prompt_shield", "prompt_shield", "Phi-3-medium-128k-instruct"),
    "b": ("prompt_shield", "prompt_shield", "GPT-4o-mini"),
    "c": ("task_tracker", "task_tracker_phi3_medium", "Phi-3-medium-128k-instruct"),
    "d": ("task_tracker", "task_tracker_phi3_medium", "GPT-4o-mini"),
    "g": ("llm_judge", "llm_judge", "Phi-3-medium-128k-instruct"),
    "h": ("llm_judge", "llm_judge", "GPT-4o-mini"),
    "i": ("all", "all(task_tracker_phi3+prompt_shield+llm_judge+spotlight)", "Phi-3-medium-128k-instruct"),
    "j": ("all", "all(task_tracker_phi3+prompt_shield+llm_judge+spotlight)", "GPT-4o-mini"),
}
DET_PRI = {"all": 0, "llm_judge": 1, "task_tracker": 2, "prompt_shield": 3}
STOP = {"the", "to", "and", "please", "email", "you", "is", "a", "of", "this", "with", "send",
        "for", "your", "in", "that", "it", "be", "an", "on", "as", "are", "we", "i", "my", "me"}

ZW = re.compile("[​-‏⁠-⁤﻿­᠎͏]")
TAGCH = re.compile("[\U000E0000-\U000E007F]")
FULLW = re.compile("[！-～]")
COMBINING = re.compile("[̀-ͯ҉⃐-⃿]")
CYR = re.compile("[Ѐ-ӿ]")
GREEK = re.compile("[Ͱ-Ͽ]")
MATHALPHA = re.compile("[\U0001D400-\U0001D7FF]")
ENCLOSED = re.compile("[①-⓿\U0001F130-\U0001F189]")
CJK = re.compile("[぀-ヿ㐀-鿿가-힯]")
OTHER_SCRIPT = re.compile("[֐-ۿऀ-෿฀-๿]")
LATIN_WORD_WITH_CYR = re.compile(r"\b(?=[A-Za-zЀ-ӿ]*[A-Za-z])(?=[A-Za-zЀ-ӿ]*[Ѐ-ӿ])[A-Za-zЀ-ӿ]{3,}\b")


def parse_obj(o):
    if isinstance(o, str):
        try:
            return json.loads(o)
        except Exception:
            return None
    return o


def decode_tagchars(t):
    return "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t)


def normalise(t):
    t = decode_tagchars(t)
    t = ZW.sub("", t)
    t = unicodedata.normalize("NFKC", t)
    t = COMBINING.sub("", unicodedata.normalize("NFKD", t))
    return t


def lang_stats(t):
    n = normalise(t)
    letters = [c for c in n if c.isalpha()]
    if not letters:
        return 0.0, 0, 0
    ascii_ratio = sum(c.isascii() for c in letters) / len(letters)
    words = re.findall(r"[a-z]+", n.lower())
    sw = sum(w in STOP for w in words)
    return ascii_ratio, sw, len(words)


B64 = re.compile(r"(?<![A-Za-z0-9+/=])[A-Za-z0-9+/]{20,}={0,2}(?![A-Za-z0-9+/=])")
HEXSEQ = re.compile(r"(?:\b[0-9A-Fa-f]{2}\b[\s,:]*){10,}|(?:\\x[0-9a-fA-F]{2}){6,}|(?:0x[0-9a-fA-F]{2}[\s,]*){6,}|\b[0-9a-fA-F]{30,}\b")
BINSEQ = re.compile(r"(?:\b[01]{7,8}\b\s*){6,}")
MORSE = re.compile(r"(?:[.\-]{1,6}\s+){10,}")


def b64_hits(t):
    n = 0
    for m in B64.finditer(t):
        s = m.group(0)
        if s.isalpha() and (s.islower() or s.isupper()):
            continue
        try:
            d = base64.b64decode(s + "=" * (-len(s) % 4), validate=True)
            dd = d.decode("utf-8")
            if sum(c.isprintable() for c in dd) / max(1, len(dd)) > 0.9 and re.search(r"[a-z]{3}", dd, re.I):
                n += 1
        except (binascii.Error, UnicodeDecodeError, ValueError):
            pass
    return n


RX = {k: re.compile(v, re.I | re.M) for k, v in {
    "encoding_kw": r"\b(base ?64|hex(adecimal)?|rot ?13|caesar|decode|decoded|decoding|decipher|encoded|cipher|ascii codes?|binary|morse|reverse(d)? (the )?(text|string|order)|read (it )?backwards|unicode code ?points?)\b",
    "fake_tokens": r"<\|[^|>\n]{1,30}\|>|\[/?(INST|SYS|SYSTEM|USER|ASSISTANT)\]|<</?SYS>>|<\s*/?\s*(system|user|assistant|im_start|im_end|start_of_turn|end_of_turn|human|bot|developer|instructions?|admin)\b[^>\n]{0,30}>|<start_of_turn>|<end_of_turn>|\[(system|admin|developer)( message| note| instruction| override)?\]|\b(system|developer) (message|prompt|override|instruction)s?\s*:",
    "dialogue": r"^\s*(\*\*|#+\s*)?(user|assistant|human|ai|system|bot)\s*(\*\*)?\s*:",
    "delimiter_escape": r"end of (the )?(email|emails|e-mail|context|document|data|input|message|mail)s?\b|</\s*(email|emails|mail|mails|context|document|data|input|tool|tool_output|function_results|external|untrusted|message|query|content|body)\s*>|\"\s*\}\s*\]|-{5,}|={5,}|\[/?end[^\]]{0,20}\]|#{5,}|<<<|>>>|\*{5,}|_{5,}",
    "spoofed_header": r"^\s*(From|Sent|To|Cc|Date|Subject)\s*:|forwarded message|original message|^\s*>\s*On .* wrote:",
    "judge": r"\b(judge|evaluator|evaluation|classifier|prompt ?shield|task ?tracker|safety (check|filter|label|rating|review|team)|not (a )?(prompt )?injection|no (prompt )?injection|jailbreak|(is|are) (completely |totally )?safe|benign|harmless|legitimate request|verified (safe|sender)|label(l?ed)?\s*:|classif(y|ied|ication)|guardrail|detector|moderation|whitelist(ed)?|allow ?list(ed)?|pre-?approved|authori[sz]ed by the user|user (has )?(already )?(approved|authori[sz]ed|requested))\b",
    "roleplay": r"\b(pretend|role[- ]?play|you are now|imagine|let'?s play|a game|story|fictional|character|simulation|act as|hypothetical(ly)?|in this scenario)\b",
    "split": r"\b(concatenate[ds]?|concatenation|combine (the|these)|join (the|these)|merge (the|these)|first letters?|part [123]\b|fragment|piece together|assemble|variable|placeholder|\{[a-z_]+\} ?=|[a-z]\s*=\s*['\"][^'\"]{1,15}['\"]\s*[;,\n])\b",
    "html": r"<!--|<html|<div|<span|<p>|<br|<table|<a href|<b>|style=|<font|<meta|display:\s*none|font-size:\s*0|color:\s*(white|#fff)",
    "code": r"```|\bdef \w+\(|\bfunction\s*\w*\(|\bimport \w+|\bprint\(|\bconsole\.log|\bvar \w+\s*=|\bconst \w+\s*=|<\?php|#include",
    "tool_call": r"send_email|sendemail|send_mail|tool_call|function_call|\"arguments\"|\bapi[_ ]call\b|<tool|tool_code|\"(name|function)\"\s*:\s*\"send|\"to\"\s*:\s*\"|\"body\"\s*:\s*\"",
    "fake_summary": r"\b(summary of (the )?(two |ten |\d+ )?(recent )?e?-?mails?|here is (the|a|your) summary|e?-?mail summary|summary:|summari[sz]ed (all|the) emails|in summary)\b",
    "spaced_or_obf": r"(\b\w[\s.\-_*]){6,}\w\b|\(at\)|\[at\]|\{at\}|\s+at\s+contact\s+dot\b|\bdot\s+com\b|\(dot\)|\[dot\]|c0nt|c\.o\.n|conf1rm|c-o-n|@\s+contact",
    "urgency": r"\b(urgent(ly)?|immediately|asap|right away|deadline|critical|time[- ]sensitive|emergency|without delay|final notice|action required|mandatory|required action)\b",
    "authority": r"\b(ceo|cfo|cto|administrator|sysadmin|it department|it team|it support|security team|compliance|hr department|microsoft|openai|developer|management|director|supervisor|officer|legal department|audit(or)?)\b",
    "pretext": r"\b(verif(y|ication)|confirm (that|your|receipt|attendance)|test(ing)? (email|message|the system|connectivity)|audit|compliance|protocol|procedure|policy|standard practice|routine|acknowledg(e|ment)|receipt)\b",
    "ai_address": r"\b(assistant|ai|a\.i\.|llm|language model|chatbot|bot|agent|copilot|gpt|phi-?3|model|email client|system)\b",
    "classic_trigger": r"\b(ignore|disregard|forget|override|bypass)\b.{0,40}\b(instructions?|prompts?|rules?|guidelines|above|previous|prior|system)\b|\bnew instructions?\b|\bsystem prompt\b|\bjailbreak\b|\bprompt injection\b|\byou must\b|\bdo anything now\b|\bDAN\b",
    "greeting": r"^\s*(subject:.*\n\s*)?(dear|hi|hello|hey|good (morning|afternoon|evening)|greetings)\b|\b(best regards|kind regards|regards|sincerely|cheers|thanks|thank you|best wishes|warm regards)\b[,!.]?\s*$",
    "exfil_ask": r"\b(summary|summari[sz]e|contents?|all (the |my |your )?e-?mails|inbox|previous e-?mails?|other e-?mails?|the (first|other|previous) e-?mail|password|credential|api key|secret|account number|personal (data|information)|confidential|attachments?|conversation history|system prompt)\b",
}.items()}

GOAL_ADDR = re.compile(r"contact\s*(@|\(at\)|\[at\]|\{at\}| at |＠)\s*contact|contact@contact\.com", re.I)
GOAL_BODY = re.compile(r"confirm(ation)?", re.I)
GOAL_BODY4 = re.compile(r"million|profit|forecast|\bq2\b|budget|estimate|\$\s*\{?\s*num|\$\s*\d", re.I)
SEND = re.compile(r"\b(send|sent|sending|e-?mail|mail|reply|respond|forward|notify|message|write|dispatch|transmit|api|tool|function|call)\b", re.I)


def features(text, scen=1):
    n = normalise(text)
    f = {}
    f["goal_addr"] = bool(GOAL_ADDR.search(n))
    f["goal_body"] = bool((GOAL_BODY4 if scen == 4 else GOAL_BODY).search(n))
    f["send_verb"] = bool(SEND.search(n))
    f["b64"] = b64_hits(text)
    f["hexseq"] = bool(HEXSEQ.search(text))
    f["binseq"] = bool(BINSEQ.search(text))
    f["morse"] = bool(MORSE.search(text))
    for k, rx in RX.items():
        f[k] = len(rx.findall(n if k not in ("spaced_or_obf",) else text))
    f["zero_width"] = len(ZW.findall(text))
    f["tag_chars"] = len(TAGCH.findall(text))
    f["fullwidth"] = len(FULLW.findall(text))
    f["combining"] = len(COMBINING.findall(text))
    f["cyrillic"] = len(CYR.findall(text))
    f["greek"] = len(GREEK.findall(text))
    f["homoglyph_words"] = len(LATIN_WORD_WITH_CYR.findall(text))
    f["math_alpha"] = len(MATHALPHA.findall(text))
    f["enclosed"] = len(ENCLOSED.findall(text))
    f["non_latin"] = len(CJK.findall(text)) + len(OTHER_SCRIPT.findall(text))
    f["non_ascii"] = sum(1 for c in text if ord(c) > 127)
    # character-level ASCII obfuscation: random casing inside words
    words = re.findall(r"[A-Za-z]{4,}", text)
    f["weird_case"] = sum(1 for w in words if re.search(r"[a-z][A-Z][a-z]|[A-Z][a-z][A-Z]", w))
    f["n_words"] = len(words)
    return f


def tier(o):
    if all(o.get(k) for k in KEYS):
        return "full"
    return "partial"


def subrank(o):
    if all(o.get(k) for k in KEYS):
        return 0
    if o.get("exfil.sent"):
        return 1
    return 2


best = {}
stats = Counter()
with open(src, encoding="utf-8") as fh:
    for i, line in enumerate(fh):
        if not line.strip():
            continue
        r = json.loads(line)
        stats["total"] += 1
        sc = r.get("scenario") or ""
        m = VALID.match(sc)
        if not m:
            stats["not_phase1_level"] += 1
            continue
        if m.group(2) in "ef":
            stats["spotlight_only"] += 1
            continue
        o = parse_obj(r.get("objectives"))
        if not o or any(o.get(k) is None for k in KEYS):
            stats["bad_obj"] += 1
            continue
        if not (o["email.retrieved"] and o["defense.undetected"]):
            stats["detected_or_not_retrieved"] += 1
            continue
        subj = r.get("subject") or ""
        body = r.get("body") or ""
        if not body.strip():
            stats["empty_body"] += 1
            continue
        text = f"Subject: {subj}\n\n{body}"
        if len(text) < 80 or len(text) > 6000:
            stats["length"] += 1
            continue
        ar, sw, nw = lang_stats(text)
        english = ar >= 0.97 and sw >= 4 and sw / max(1, nw) >= 0.08
        mostly_english = (not english) and ar >= 0.75 and sw >= 6 and sw / max(1, nw) >= 0.08
        if not (english or mostly_english):
            stats["not_english"] += 1
            continue
        key = re.sub(r"\s+", " ", text.lower()).strip()
        cand = (subrank(o), DET_PRI[DEFENSE[m.group(2)][0]], i)
        if key in best and best[key][0] <= cand:
            stats["exact_dup"] += 1
            continue
        if key in best:
            stats["exact_dup"] += 1
        det, det_detail, model = DEFENSE[m.group(2)]
        best[key] = (cand, {
            "row_index": i, "RowKey": r.get("RowKey"), "job_id": r.get("job_id"),
            "level": sc, "scenario": f"scenario_{m.group(1)}", "detector": det,
            "detector_detail": det_detail, "model": model,
            "team_id": r.get("team_id"), "objectives": o, "tier": tier(o), "subrank": subrank(o),
            "text": text, "len": len(text), "english_strict": english, "ascii_ratio": round(ar, 3),
            "completed_time": r.get("completed_time"),
        })

rows = []
for _, (cand, rec) in best.items():
    rec["f"] = features(rec["text"], int(rec["scenario"][-1]))
    rows.append(rec)
rows.sort(key=lambda r: r["row_index"])
print(dict(stats))
print("pool", len(rows))
c = defaultdict(Counter)
teams = defaultdict(set)
for r in rows:
    c[r["detector"]][(r["tier"], r["subrank"])] += 1
    teams[(r["detector"], r["tier"])].add(r["team_id"])
for d in c:
    print(d, dict(sorted(c[d].items())), {t: len(teams[(d, t)]) for t in ("full", "partial")})
print("teams", len({r["team_id"] for r in rows}))
print("goal cues: addr", sum(r["f"]["goal_addr"] for r in rows), "body", sum(r["f"]["goal_body"] for r in rows))
with open(out, "w", encoding="utf-8", newline="\n") as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
