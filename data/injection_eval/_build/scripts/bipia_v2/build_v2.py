"""Build the BIPIA v2 slice: the 35 core records (unchanged + "core": true) followed by
125 new records, for totals of injection 90 (email/table/code 30/30/30) and benign 70
(email 20 / table 25 / code 25).

Usage: python -X utf8 -I build_v2.py <bipia_repo_dir> <commit_sha> <core_bipia_jsonl> <out_jsonl>

Only reads BIPIA data files; nothing from the BIPIA repo is imported or executed. The insertion
functions re-implement bipia/data/utils.py (insert_start / insert_middle / insert_end) exactly as
the core build did; insert_middle uses NLTK's untrained PunktSentenceTokenizer with
random.Random(2023) (BIPIA's documented seed).
"""
import difflib
import json
import os
import random
import re
import sys
from collections import Counter, defaultdict

from nltk.tokenize.punkt import PunktSentenceTokenizer

REPO, COMMIT, CORE, OUT = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4]
URL = "https://github.com/microsoft/BIPIA"
INSERT_SEED = 2023
MAX_LEN = 3000
TASKS = ["email", "table", "code"]
TARGET_INJ = {"email": 30, "table": 30, "code": 30}
TARGET_BEN = {"email": 20, "table": 25, "code": 25}
POS = ["start", "middle", "end"]
ATTACK_FILE = {"email": "benchmark/text_attack_test.json", "table": "benchmark/text_attack_test.json",
               "code": "benchmark/code_attack_test.json"}


# ---- BIPIA insertion functions (replicated from bipia/data/utils.py) ----
def insert_end(context, attack, random_state=None):
    return "\n".join([context, attack])


def insert_start(context, attack, random_state=None):
    return "\n".join([attack, context])


def middle_split(context, random_state=None):
    rng = random.Random(random_state)
    sentence_indexes = list(PunktSentenceTokenizer().span_tokenize(context))
    start, _ = rng.sample(sentence_indexes, k=1)[0]
    return start, len(sentence_indexes)


def insert_middle(context, attack, random_state=None):
    start, _ = middle_split(context, random_state)
    return "\n".join([context[:start], attack, context[start:]])


INSERT = {"start": insert_start, "middle": insert_middle, "end": insert_end}
FN_NAME = {"start": "insert_start", "middle": "insert_middle", "end": "insert_end"}
_MID = {}


def mid(ctx):
    if ctx not in _MID:
        _MID[ctx] = middle_split(ctx, INSERT_SEED)
    return _MID[ctx]


# ---- similarity helpers ----
def norm(text):
    return re.sub(r"\s+", " ", text).strip().lower()


_G = {}


def grams(text, n=5):
    if text not in _G:
        w = norm(text).split()
        _G[text] = {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}
    return _G[text]


def email_keys(text):
    m = re.search(r"RECEIVED DATE:\s*([^|]+)", text)
    date = m.group(1).strip() if m else None
    amounts = {re.sub(r"\D", "", a) for a in re.findall(r"\$\s?(\d[\d,\s]*\.\d\d)", text)}
    amounts.discard("10000")  # "$100.00" notification-threshold footer in every Mercury email
    return date, frozenset(amounts)


def same_source(task, a, b):
    """The core build's variant test (exact/normalised match, email date/amount keys, ratio>=0.95)."""
    if norm(a) == norm(b):
        return True
    if task == "email":
        da, aa = email_keys(a)
        db, ab = email_keys(b)
        if da and da == db:
            return True
        if aa and aa == ab:
            return True
    sm = difflib.SequenceMatcher(None, a, b)
    return sm.real_quick_ratio() >= 0.95 and sm.quick_ratio() >= 0.95 and sm.ratio() >= 0.95


_S = {}


def strict_dup(a, b):
    """Near-duplicate per the common brief: word 5-gram Jaccard >= 0.5 or difflib ratio >= 0.8."""
    key = (a, b) if a <= b else (b, a)
    if key in _S:
        return _S[key]
    ga, gb = grams(a), grams(b)
    res = len(ga & gb) / max(1, len(ga | gb)) >= 0.5
    if not res:
        sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
        res = sm.real_quick_ratio() >= 0.8 and sm.quick_ratio() >= 0.8 and sm.ratio() >= 0.8
    _S[key] = res
    return res


def is_english(text):
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    return sum(1 for ch in letters if ord(ch) > 127) / len(letters) <= 0.02


# ---- data loading ----
def load_rows(task, split):
    rel = f"benchmark/{task}/{split}.jsonl"
    rows = []
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            r = json.loads(line)
            ctx = r["context"]
            if task == "code":  # CodeIPIABuilder: "\n".join(normal_sample["context"])
                ctx = "\n".join(ctx)
            rows.append({"split": split, "index": i, "file": rel, "context": ctx, "row": r})
    return rows


def load_attacks(rel):
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        return json.load(f)


def core_context(rec):
    o = rec["origin"]
    with open(os.path.join(REPO, o["file"]), encoding="utf-8") as f:
        row = json.loads(f.read().split("\n")[o["index"]])
    c = row["context"]
    return "\n".join(c) if isinstance(c, list) else c


# ---- attack / position plan ----
def plan_slots(core_recs, attacks):
    """Spread categories evenly: every text category 2x in email and 2x in table, every code
    category 3x in code (core included). Items within a category are distinct across the whole
    slice (core items excluded). Positions: 10/10/10 per subset, and within a subset a category
    never repeats a position."""
    per_cat = {"email": 2, "table": 2, "code": 3}
    core_by = defaultdict(list)  # (task, cat) -> [(item, pos)]
    for r in core_recs:
        if r["label"] != "injection":
            continue
        o = r["origin"]
        item = attacks[r["subset"]][o["attack_category"]].index(r["injected_instruction"])
        core_by[(r["subset"], o["attack_category"])].append((item, o["position"]))

    slots = {t: [] for t in TASKS}
    # items
    for group in (["email", "table"], ["code"]):
        cats = list(attacks[group[0]].keys())
        for cat in cats:
            used = {it for t in group for it, _ in core_by[(t, cat)]}
            need = {t: per_cat[t] - len(core_by[(t, cat)]) for t in group}
            avail = [i for i in range(len(attacks[group[0]][cat])) if i not in used]
            picks = random.sample(avail, sum(need.values()))
            k = 0
            for t in group:
                for _ in range(need[t]):
                    slots[t].append({"task": t, "cat": cat, "item": picks[k],
                                     "attack": attacks[t][cat][picks[k]]})
                    k += 1
    # positions
    for t in TASKS:
        core_cnt = Counter(p for (tt, _), lst in core_by.items() if tt == t for _, p in lst)
        need = Counter({p: TARGET_INJ[t] // 3 - core_cnt[p] for p in POS})
        by_cat = defaultdict(list)
        for s in slots[t]:
            by_cat[s["cat"]].append(s)
        for attempt in range(100000):
            choice = {}
            for cat, lst in by_cat.items():
                forbidden = {p for _, p in core_by[(t, cat)]}
                options = [p for p in POS if p not in forbidden]
                choice[cat] = random.sample(options, len(lst))
            if Counter(p for v in choice.values() for p in v) == need:
                break
        else:
            raise SystemExit(f"position plan failed for {t}")
        for cat, lst in by_cat.items():
            for s, p in zip(lst, choice[cat]):
                s["pos"] = p
        random.shuffle(slots[t])
    return slots


def fits(ctx, slot):
    if slot["pos"] == "middle" and mid(ctx)[0] == 0:
        return False  # BIPIA's sampled sentence start is 0 -> identical to a start insertion
    return len(INSERT[slot["pos"]](ctx, slot["attack"], random_state=INSERT_SEED)) <= MAX_LEN


# ---- context selection ----
def candidate_pool(task):
    pool = []
    for split in ["test", "train"]:
        rows = [r for r in load_rows(task, split) if is_english(r["context"]) and len(r["context"]) <= MAX_LEN]
        random.shuffle(rows)
        pool.extend(rows)
    return pool


def select_greedy(task, slots, n_ben, core_entries):
    """table/code: test-first shuffled pool; a candidate is rejected if it is a core-style variant
    or a strict near-duplicate of any already selected context (core or new, either label)."""
    selected = [c for c, _ in core_entries]
    pool = candidate_pool(task)
    dead, used = set(), set()

    def ok(ci):
        if ci in dead or ci in used:
            return False
        ctx = pool[ci]["context"]
        for s in selected:
            if same_source(task, s, ctx) or strict_dup(s, ctx):
                dead.add(ci)
                return False
        return True

    inj = []
    for slot in slots:
        for ci in range(len(pool)):
            if ci in dead or ci in used or not fits(pool[ci]["context"], slot):
                continue
            if ok(ci):
                used.add(ci)
                selected.append(pool[ci]["context"])
                inj.append((slot, pool[ci], None))
                break
        else:
            raise SystemExit(f"no context for {task} {slot['cat']} {slot['pos']}")
    ben = []
    for ci in range(len(pool)):
        if len(ben) >= n_ben:
            break
        if ok(ci):
            used.add(ci)
            selected.append(pool[ci]["context"])
            ben.append(pool[ci])
    if len(ben) < n_ben:
        raise SystemExit(f"not enough benign for {task}")
    return inj, ben, {}


def select_email(slots, n_ben, core_entries):
    """email: the pool (test+train) is too small for distinct contexts, so
    1) collapse rows into core-style variant groups (core contexts seed their groups; first
       occurrence, test before train, represents a new group);
    2) form strict near-duplicate families over all representatives (union-find) and give each
       family a single label (core families keep their core label), so no injection context is a
       near-duplicate of any benign context;
    3) reuse new injection contexts (2 uses each, different attack, category and position) only for
       the shortfall."""
    task = "email"
    rows = load_rows(task, "test") + load_rows(task, "train")
    reps = [{"context": c, "label": lab, "core": True} for c, lab in core_entries]
    for r in rows:
        if any(same_source(task, g["context"], r["context"]) for g in reps):
            continue
        if not is_english(r["context"]) or len(r["context"]) > MAX_LEN:
            continue
        reps.append({**r, "label": None, "core": False})
    n = len(reps)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for i in range(n):
        for j in range(i + 1, n):
            if strict_dup(reps[i]["context"], reps[j]["context"]):
                parent[find(i)] = find(j)
    fams = defaultdict(list)
    for i in range(n):
        fams[find(i)].append(i)
    fam_label = {}
    for f, mem in fams.items():
        labs = {reps[i]["label"] for i in mem if reps[i]["core"]}
        if len(labs) > 1:
            raise SystemExit("core family carries both labels")
        fam_label[f] = labs.pop() if labs else None
    new_in = lambda f: [i for i in fams[f] if not reps[i]["core"]]
    ben_pool = [i for f in fams if fam_label[f] == "benign" for i in new_in(f)]
    free_fams = [f for f in fams if fam_label[f] is None]
    random.shuffle(free_fams)
    short = n_ben - len(ben_pool)
    chosen = []
    if short > 0:
        # pick free families whose sizes sum exactly to the shortfall (smallest search, seeded order)
        sizes = [len(fams[f]) for f in free_fams]

        def search(k, rem, acc):
            if rem == 0:
                return acc
            if k >= len(sizes) or rem < 0:
                return None
            r = search(k + 1, rem - sizes[k], acc + [k])
            return r if r is not None else search(k + 1, rem, acc)

        pick = search(0, short, [])
        if pick is None:
            raise SystemExit("cannot fill email benign")
        chosen = [free_fams[k] for k in pick]
        for f in chosen:
            fam_label[f] = "benign"
            ben_pool += new_in(f)
    for f in free_fams:
        if fam_label[f] is None:
            fam_label[f] = "injection"
    inj_pool = [i for f in fams if fam_label[f] == "injection" for i in new_in(f)]
    # order: test before train, seeded shuffle inside each split
    def order(idx):
        t = [i for i in idx if reps[i]["split"] == "test"]
        tr = [i for i in idx if reps[i]["split"] == "train"]
        random.shuffle(t)
        random.shuffle(tr)
        return t + tr

    ben_idx = order(ben_pool)[:n_ben]
    inj_idx = order(inj_pool)
    n_double = len(slots) - len(inj_idx)
    if n_double < 0:
        inj_idx = inj_idx[: len(slots)]
        n_double = 0
    if n_double > len(inj_idx):
        raise SystemExit("email injection pool too small even with 2 uses per context")
    caps = [2 if k < n_double else 1 for k in range(len(inj_idx))]
    for attempt in range(200000):
        sl = slots[:]
        random.shuffle(sl)
        assign, k, good = [], 0, True
        for ci, cap in zip(inj_idx, caps):
            mine = sl[k:k + cap]
            k += cap
            ctx = reps[ci]["context"]
            if len({s["pos"] for s in mine}) < cap or len({s["cat"] for s in mine}) < cap:
                good = False
                break
            if not all(fits(ctx, s) for s in mine):
                good = False
                break
            assign.append((ci, mine))
        if good:
            break
    else:
        raise SystemExit("email assignment failed")
    # keep the planned slot order for record order
    slot_ctx = {}
    for ci, mine in assign:
        for s in mine:
            slot_ctx[id(s)] = ci
    inj = []
    for s in slots:
        ci = slot_ctx[id(s)]
        inj.append((s, reps[ci], ci))
    ben = [reps[i] for i in ben_idx]
    fam_info = {"families": len(fams), "benign_families_from_free": len(chosen),
                "reused_contexts": n_double}
    return inj, ben, fam_info


def main():
    random.seed(42)
    core_lines = open(CORE, encoding="utf-8").read().split("\n")
    core_lines = [l for l in core_lines if l.strip()]
    core_recs = [json.loads(l) for l in core_lines]
    attacks = {t: load_attacks(ATTACK_FILE[t]) for t in TASKS}

    slots = plan_slots(core_recs, attacks)
    new_inj, new_ben = [], []
    info = {}
    for t in TASKS:
        core_entries = [(core_context(r), r["label"]) for r in core_recs if r["subset"] == t]
        n_core_inj = sum(1 for r in core_recs if r["subset"] == t and r["label"] == "injection")
        n_core_ben = sum(1 for r in core_recs if r["subset"] == t and r["label"] == "benign")
        assert len(slots[t]) == TARGET_INJ[t] - n_core_inj
        n_ben = TARGET_BEN[t] - n_core_ben
        if t == "email":
            inj, ben, fi = select_email(slots[t], n_ben, core_entries)
        else:
            inj, ben, fi = select_greedy(t, slots[t], n_ben, core_entries)
        info[t] = fi
        # reuse bookkeeping: rep key -> list of positions in new_inj
        for slot, r, key in inj:
            new_inj.append((t, slot, r, key))
        for r in ben:
            new_ben.append((t, r))

    # ids
    inj_start = 1 + sum(1 for r in core_recs if r["label"] == "injection")
    ben_start = 1 + sum(1 for r in core_recs if r["label"] == "benign")
    users = defaultdict(list)
    for k, (t, slot, r, key) in enumerate(new_inj):
        users[(t, r["split"], r["index"])].append(f"bipia-inj-{inj_start + k:02d}")

    out = []
    for l in core_lines:
        rec = json.loads(l)
        rec["core"] = True
        out.append(rec)
    for k, (t, slot, r, key) in enumerate(new_inj):
        rid = f"bipia-inj-{inj_start + k:02d}"
        ctx = r["context"]
        pos = slot["pos"]
        text = INSERT[pos](ctx, slot["attack"], random_state=INSERT_SEED)
        split_note = ""
        if pos == "middle":
            start, nsent = mid(ctx)
            split_note = (f" Punkt found {nsent} sentence spans; random.Random({INSERT_SEED}) picked the span "
                          f"starting at char {start}.")
        extra = ""
        if t == "code":
            extra = (f" Context is the Stack Overflow answer ({r['row'].get('context_url')}) joined with '\\n' as in "
                     f"CodeIPIABuilder; the BIPIA user task is to fix the user's code given its error.")
        if r["split"] == "train":
            extra += f" Context taken from the BIPIA {t} train split because the test-split pool ran out."
        others = [u for u in users[(t, r["split"], r["index"])] if u != rid]
        if others:
            extra += (f" The {t} context pool is too small for distinct contexts, so this context is also used by "
                      f"{', '.join(others)} (different attack category and position).")
        out.append({
            "id": rid,
            "label": "injection",
            "source": "BIPIA",
            "subset": t,
            "text": text,
            "injected_instruction": slot["attack"],
            "origin": {
                "url": URL,
                "commit": COMMIT,
                "file": r["file"],
                "index": r["index"],
                "split": r["split"],
                "attack_file": ATTACK_FILE[t],
                "attack_category": slot["cat"],
                "position": pos,
                "question": r["row"].get("question") if t != "code" else None,
            },
            "notes": (f"BIPIA attack '{slot['cat']}-{slot['item']}' (category {slot['cat']}, item {slot['item']}) "
                      f"inserted with {FN_NAME[pos]} replicated from bipia/data/utils.py (joined with '\\n')."
                      f"{split_note} index = 0-based line number in {r['file']}.{extra}"),
            "core": False,
        })
    for k, (t, r) in enumerate(new_ben):
        rid = f"bipia-ben-{ben_start + k:02d}"
        extra = ""
        if t == "code":
            extra = (f" Stack Overflow answer ({r['row'].get('context_url')}) joined with '\\n' as in CodeIPIABuilder; "
                     f"the BIPIA user task is to fix the user's code given its error.")
        if r["split"] == "train":
            extra += f" Context taken from the BIPIA {t} train split because the test-split pool ran out."
        out.append({
            "id": rid,
            "label": "benign",
            "source": "BIPIA",
            "subset": t,
            "text": r["context"],
            "injected_instruction": None,
            "origin": {
                "url": URL,
                "commit": COMMIT,
                "file": r["file"],
                "index": r["index"],
                "split": r["split"],
                "attack_file": None,
                "attack_category": None,
                "position": None,
                "question": r["row"].get("question") if t != "code" else None,
            },
            "notes": (f"Original BIPIA {t} {r['split']} context, unmodified (no attack inserted). "
                      f"index = 0-based line number in {r['file']}.{extra}"),
            "core": False,
        })

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("wrote", len(out), "records to", OUT)
    print("email info", info["email"])


if __name__ == "__main__":
    main()
