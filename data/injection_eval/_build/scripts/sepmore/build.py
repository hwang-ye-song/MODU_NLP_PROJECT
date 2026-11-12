"""Build SEP general-document slice (30 injection + 30 benign).

Usage: python -X utf8 -I build_sep.py <repo_dir> <wd_dir> <out_path>
Reads only data files from the cloned SEP repo (no code is imported/run).
"""
import collections
import difflib
import glob
import json
import os
import random
import re
import sys

REPO, WD, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
DATA_FILE = "datasets/SEP_dataset.json"
PROBES_FILE = "SEP_dataset/source/probes.json"
RAW_FILE = "SEP_dataset/interim_data_files/raw_data.json"
URL = "https://github.com/egozverev/Should-It-Be-Executed-Or-Processed"
HEAD_COMMIT = "7606c0696f20f5aa433169fd2221f76852d1d4f5"
FILE_COMMIT = "252cfa1f94f909ebd1318876bb9310068bd9f06c"

N_PER_LABEL = 20

# General tasks whose data passages are not prose documents (code, prompts,
# math word problems ending in a question/imperative, non-English text).
EXCLUDED_GENERAL = {
    "Translation",
    "Prompt Development and Customization",
    "Code Writing",
    "Code Analysis",
    "Mathematical Problem Solving",
    # data are first-person preference statements addressed to a recommender
    # ("Any restaurant recommendation should cater to ..."), i.e. requests to the assistant
    "Personalized Recommendation Generation",
}

OLDIDX={json.loads(l)["origin"]["index"] for l in open(os.path.join(WD,"_build/parts_v2/sep.jsonl"),encoding="utf-8")}
data = json.load(open(os.path.join(REPO, DATA_FILE), encoding="utf-8"))
probes = json.load(open(os.path.join(REPO, PROBES_FILE), encoding="utf-8"))
raw = json.load(open(os.path.join(REPO, RAW_FILE), encoding="utf-8"))

# ---- subtask/system prompt -> general task mapping (from interim raw data)
name2gt, sp2gt = {}, {}


def walk(v, gt):
    if isinstance(v, str):
        try:
            v = json.loads(v)
        except Exception:
            return
        if isinstance(v, str):
            return
    if isinstance(v, list):
        for e in v:
            walk(e, gt)
    elif isinstance(v, dict):
        if "name" in v and "system_prompt" in v:
            name2gt.setdefault(v["name"], set()).add(gt)
            sp2gt.setdefault(v["system_prompt"], set()).add(gt)
        else:
            for e in v.values():
                walk(e, gt)


for dom, tasks in raw["output"].items():
    if dom == "descr":
        continue
    for gt, tds in tasks.items():
        if gt == "descr":
            continue
        walk(tds["subtasks"], gt)


def general_task(x):
    s = sp2gt.get(x["system_prompt_clean"]) or name2gt.get(x["info"]["subtask"])
    return sorted(s)[0] if s else None


# ---- verify probe reconstruction for every item
for i, x in enumerate(data):
    pr = probes[x["info"]["appended_task_id"]]["instruction"]
    pos = x["info"]["appended_type"][1]
    exp = pr + " " + x["prompt_clean"] if pos == "l" else x["prompt_clean"] + " " + pr
    assert exp == x["prompt_instructed"], i

# ---- clean-passage filters
STOP = set("the a an of and to in is are was were for on with that this by as at from it its be has have".split())
IMPERATIVE_START = re.compile(
    r"(^|[.!:\n]\s*)(please|write|create|generate|compose|draft|design|develop|explain|describe|list|find|calculate|"
    r"identify|provide|suggest|recommend|help|imagine|tell|name|translate|summari[sz]e|analy[sz]e|evaluate|compare|"
    r"determine|give|make|rewrite|consider|discuss|outline|solve|show|plan|propose|assess|review|edit|correct|"
    r"conceptuali[sz]e|envision|brainstorm|craft|invent|devise|act|pretend|respond|answer|ignore)\b",
    re.I,
)
AI_ADDRESS = re.compile(
    r"\b(can you|could you|would you|will you|help me|i need help|i want you|please|assistant|chatbot|ai\b|"
    r"recommend me|suggest|question:|task:|prompt:|instruction|"
    # reader-directed calls to action (e.g. phishing samples) -- avoid ambiguous benign items
    r"claim your|click|visit our|enter your|reply with|respond with|"
    # first-person advice/recommendation requests addressed to a helper
    r"looking for (advice|recommendations|suggestions|tips|ideas|guidance)|"
    r"i need (advice|help|ideas|suggestions|guidance)|any (advice|tips|recommendations|suggestions)|"
    # creative briefs specifying what the output should do
    r"(choreography|design|piece|concept|artwork|logo|soundtrack|campaign|composition|story|poem) (should|must)\b)",
    re.I,
)

# Items rejected on manual review (ambiguous as benign / not a document).
MANUAL_EXCLUDE = {
    7121: "first-person request for scheduling advice addressed to a helper",
    3660: "creative brief prescribing what the choreography should capture",
}


def is_english(t):
    words = re.findall(r"[A-Za-z']+", t.lower())
    if not words:
        return False
    non_ascii = sum(ord(c) > 127 for c in t) / max(1, len(t))
    stop = sum(w in STOP for w in words) / len(words)
    return non_ascii < 0.02 and stop > 0.12


probe_texts = {p["instruction"] for p in probes}


def clean_ok(t):
    if not (150 <= len(t) <= 2800):
        return False
    if "?" in t or "<" in t or "```" in t:
        return False
    if not is_english(t):
        return False
    if IMPERATIVE_START.search(t) or AI_ADDRESS.search(t):
        return False
    if any(p in t for p in probe_texts):
        return False
    return True


# ---- near-duplicate check helpers
def ngrams(t, n=5):
    w = re.findall(r"\w+", t.lower())
    return {tuple(w[i:i + n]) for i in range(max(0, len(w) - n + 1))}


def near_dup(a, b):
    ga, gb = ngrams(a), ngrams(b)
    if ga and gb and len(ga & gb) / len(ga | gb) >= 0.5:
        return True
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    if sm.real_quick_ratio() < 0.8 or sm.quick_ratio() < 0.8:
        return False
    return sm.ratio() >= 0.8


existing = []
for pat in ("parts/*.jsonl", "parts_v2/*.jsonl"):
    for fp in glob.glob(os.path.join(WD, pat)):
        if os.path.abspath(fp) == os.path.abspath(OUT):
            continue
        with open(fp, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    existing.append(json.loads(line)["text"])
existing_ngrams = [ngrams(t) for t in existing]


def dup_existing(t):
    g = ngrams(t)
    for e, eg in zip(existing, existing_ngrams):
        if g and eg and len(g & eg) / len(g | eg) >= 0.5:
            return True
        sm = difflib.SequenceMatcher(None, t, e, autojunk=False)
        if sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8:
            return True
    return False


# ---- candidate pool
clean_counts = collections.Counter(x["prompt_clean"] for x in data)
pool = collections.defaultdict(lambda: collections.defaultdict(list))  # domain -> gt -> [idx]
for i, x in enumerate(data):
    gt = general_task(x)
    if gt is None or gt in EXCLUDED_GENERAL:
        continue
    if clean_counts[x["prompt_clean"]] > 1 or i in MANUAL_EXCLUDE or i in OLDIDX:
        continue
    if not clean_ok(x["prompt_clean"]):
        continue
    pool[x["info"]["type"]][gt].append(i)

random.seed(42)
domains = sorted(pool)
for d in domains:
    for gt in pool[d]:
        random.shuffle(pool[d][gt])

old=[json.loads(l) for l in open(os.path.join(WD,"_build/parts_v2/sep.jsonl"),encoding="utf-8")]
old_idx={r["origin"]["index"] for r in old}
used_subtasks, used_sysprompts = set(), set()
used_probe_base={r["origin"]["appended_task_id"]%50 for r in old if r["label"]=="injection"}
used_probe_ids={r["origin"]["appended_task_id"] for r in old if r["label"]=="injection"}
chosen_texts = []


def ok_new(text):
    if any(near_dup(text, c) for c in chosen_texts):
        return False
    return not dup_existing(text)


def pick(label, slots):
    """slots: list of (domain, insistent, pos) ; pos/insistent None for benign."""
    out = []
    gt_order = {d: sorted(pool[d]) for d in domains}
    for d in domains:
        random.shuffle(gt_order[d])
    gt_ptr = collections.Counter()
    for d, insist, pos in slots:
        gts = gt_order[d]
        found = None
        for k in range(len(gts)):
            gt = gts[(gt_ptr[d] + k) % len(gts)]
            for i in pool[d][gt]:
                x = data[i]
                inf = x["info"]
                if inf["subtask"] in used_subtasks or x["system_prompt_clean"] in used_sysprompts:
                    continue
                if label == "injection":
                    if inf["is_insistent"] != insist or inf["appended_type"][1] != pos:
                        continue
                    if inf["appended_task_id"] % 50 in used_probe_base:
                        continue
                    text = x["prompt_instructed"]
                else:
                    text = x["prompt_clean"]
                if len(text) > 3000 or not ok_new(text):
                    continue
                found = (i, gt, text)
                break
            if found:
                gt_ptr[d] = (gt_ptr[d] + k + 1) % len(gts)
                break
        assert found, (label, d, insist, pos)
        i, gt, text = found
        x = data[i]
        used_subtasks.add(x["info"]["subtask"])
        used_sysprompts.add(x["system_prompt_clean"])
        if label == "injection":
            used_probe_base.add(x["info"]["appended_task_id"] % 50)
        chosen_texts.append(text)
        out.append((i, gt, text))
    return out


# injection slots: 10 per domain, insistence x position balanced (15/15 each)
inj_attrs =[(False, "l")] * 5 + [(False, "r")] * 5 + [(True, "l")] * 5 + [(True, "r")] * 5
random.shuffle(inj_attrs)
inj_slots = [(domains[k % 3], ins, pos) for k, (ins, pos) in enumerate(inj_attrs)]
inj_slots.sort(key=lambda s: domains.index(s[0]))
ben_slots = [(domains[k % 3], None, None) for k in range(N_PER_LABEL)]; ben_slots.sort(key=lambda s: domains.index(s[0]))

inj = pick("injection", inj_slots)
ben = pick("benign", ben_slots)

records = []
for n, (i, gt, text) in enumerate(inj, 1):
    x = data[i]
    inf = x["info"]
    probe = probes[inf["appended_task_id"]]["instruction"]
    assert text.count(probe) == 1
    where = "start" if inf["appended_type"][1] == "l" else "end"
    records.append({
        "id": f"sep-inj-{n+30:02d}",
        "label": "injection",
        "source": "SEP",
        "subset": "general_document",
        "text": text,
        "injected_instruction": probe,
        "origin": {
            "url": URL,
            "commit": HEAD_COMMIT,
            "file_last_commit": FILE_COMMIT,
            "file": DATA_FILE,
            "index": i,
            "field": "prompt_instructed",
            "task_prompt": x["system_prompt_clean"],
            "task_domain": inf["type"],
            "general_task": gt,
            "subtask": inf["subtask"],
            "appended_task_id": inf["appended_task_id"],
            "appended_type": inf["appended_type"],
            "probe_position_in_data": where,
            "is_insistent": inf["is_insistent"],
            "witness": x["witness"],
        },
        "notes": (f"SEP item {i} data prompt with probe (prompt_instructed), unmodified; "
                  f"{'insistent' if inf['is_insistent'] else 'non-insistent'} probe #{inf['appended_task_id']} "
                  f"(SEP_dataset/source/probes.json) joined with a single space at the {where} of the clean data passage. "
                  f"general_task mapped from {RAW_FILE}. Task/system prompt kept only in origin.task_prompt."),
        "core": False,
    })
for n, (i, gt, text) in enumerate(ben, 1):
    x = data[i]
    inf = x["info"]
    records.append({
        "id": f"sep-ben-{n+30:02d}",
        "label": "benign",
        "source": "SEP",
        "subset": "general_document",
        "text": text,
        "injected_instruction": None,
        "origin": {
            "url": URL,
            "commit": HEAD_COMMIT,
            "file_last_commit": FILE_COMMIT,
            "file": DATA_FILE,
            "index": i,
            "field": "prompt_clean",
            "task_prompt": x["system_prompt_clean"],
            "task_domain": inf["type"],
            "general_task": gt,
            "subtask": inf["subtask"],
        },
        "notes": (f"SEP item {i} clean data prompt (prompt_clean), unmodified, no probe; different item and subtask "
                  f"from all sep-inj records. general_task mapped from {RAW_FILE}. Task/system prompt kept only in origin.task_prompt."),
        "core": False,
    })

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w", encoding="utf-8", newline="\n") as f:
    for r in records:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

print("pool sizes:", {d: {gt: len(v) for gt, v in pool[d].items()} for d in domains})
print("written", len(records), OUT)
