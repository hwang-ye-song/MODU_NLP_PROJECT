"""Build the BIPIA slice (20 injection / 15 benign) for the PI detection dataset.

Usage: python -I build.py <bipia_repo_dir> <commit_sha> <out_jsonl>

Only reads BIPIA data files. Insertion logic is a re-implementation of
bipia/data/utils.py (insert_start / insert_middle / insert_end); nothing from the
BIPIA repo is imported or executed. insert_middle needs NLTK's untrained
PunktSentenceTokenizer, exactly as BIPIA uses it.
"""
import difflib
import json
import os
import random
import re
import sys

from nltk.tokenize.punkt import PunktSentenceTokenizer

REPO, COMMIT, OUT = sys.argv[1], sys.argv[2], sys.argv[3]
BENCH = os.path.join(REPO, "benchmark")
URL = "https://github.com/microsoft/BIPIA"
INSERT_SEED = 2023  # BIPIA README: AutoPIABuilder.from_name(...)(seed=2023) / run.py --seed 2023
MAX_LEN = 3000

N_INJ = {"email": 7, "table": 7, "code": 6}
N_BEN = {"email": 5, "table": 5, "code": 5}


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


def load_contexts(task):
    rel = f"benchmark/{task}/test.jsonl"
    rows = []
    with open(os.path.join(REPO, rel), encoding="utf-8") as f:
        for i, line in enumerate(f):
            if not line.strip():
                continue
            r = json.loads(line)
            ctx = r["context"]
            if task == "code":  # CodeIPIABuilder: "\n".join(normal_sample["context"])
                ctx = "\n".join(ctx)
            rows.append({"index": i, "context": ctx, "row": r, "file": rel})
    return rows


def is_english(text):
    letters = [ch for ch in text if ch.isalpha()]
    if not letters:
        return False
    return sum(1 for ch in letters if ord(ch) > 127) / len(letters) <= 0.02


def norm(text):
    return re.sub(r"\s+", " ", text).strip().lower()


def email_keys(text):
    m = re.search(r"RECEIVED DATE:\s*([^|]+)", text)
    date = m.group(1).strip() if m else None
    amounts = {re.sub(r"\D", "", a) for a in re.findall(r"\$\s?(\d[\d,\s]*\.\d\d)", text)}
    amounts.discard("10000")  # "$100.00" notification-threshold footer in every Mercury email
    return date, frozenset(amounts)


def same_source(task, a, b):
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


def load_attacks(name):
    with open(os.path.join(BENCH, name), encoding="utf-8") as f:
        return json.load(f)


def main():
    random.seed(42)

    text_attacks = load_attacks("text_attack_test.json")
    code_attacks = load_attacks("code_attack_test.json")

    # Attack categories: distinct per sample. 14 of 15 text categories split email/table,
    # 6 of 10 code categories.
    text_cats = random.sample(list(text_attacks.keys()), N_INJ["email"] + N_INJ["table"])
    code_cats = random.sample(list(code_attacks.keys()), N_INJ["code"])
    plan = {
        "email": [(c, random.randrange(len(text_attacks[c]))) for c in text_cats[: N_INJ["email"]]],
        "table": [(c, random.randrange(len(text_attacks[c]))) for c in text_cats[N_INJ["email"]:]],
        "code": [(c, random.randrange(len(code_attacks[c]))) for c in code_cats],
    }
    pos_cycles = {
        "email": ["start", "middle", "end"],
        "table": ["end", "start", "middle"],
        "code": ["middle", "end", "start"],
    }

    records_inj, records_ben = [], []
    seen_norm = set()

    for task in ["email", "table", "code"]:
        rows = load_contexts(task)
        # Unique contexts (first occurrence of each exact/near-duplicate group), English,
        # within length. Near-duplicates (variants of the same email/table) are collapsed so
        # that no underlying context can appear under both labels.
        kept = []
        for r in rows:
            if any(same_source(task, r["context"], k["context"]) for k in kept):
                continue
            kept.append(r)
        cands = [r for r in kept if is_english(r["context"]) and len(r["context"]) <= MAX_LEN]
        print(task, "rows", len(rows), "unique groups", len(kept), "eligible", len(cands))
        random.shuffle(cands)

        positions = [pos_cycles[task][i % 3] for i in range(N_INJ[task])]
        random.shuffle(positions)

        attack_file = "benchmark/code_attack_test.json" if task == "code" else "benchmark/text_attack_test.json"
        attacks = code_attacks if task == "code" else text_attacks

        used = set()
        for (cat, aidx), pos in zip(plan[task], positions):
            attack = attacks[cat][aidx]
            chosen = None
            for ci, r in enumerate(cands):
                if ci in used:
                    continue
                ctx = r["context"]
                split_note = ""
                if pos == "middle":
                    start, nsent = middle_split(ctx, INSERT_SEED)
                    # Skip contexts where BIPIA's sampled sentence start is 0
                    # (insert_middle would then be identical to a start insertion).
                    if start == 0:
                        continue
                    split_note = f" Punkt found {nsent} sentence spans; random.Random({INSERT_SEED}) picked the span starting at char {start}."
                text = INSERT[pos](ctx, attack, random_state=INSERT_SEED)
                if len(text) > MAX_LEN or norm(text) in seen_norm:
                    continue
                chosen = (ci, r, text, split_note)
                break
            if chosen is None:
                raise SystemExit(f"no candidate for {task} {cat} {pos}")
            ci, r, text, split_note = chosen
            used.add(ci)
            seen_norm.add(norm(text))
            question = r["row"].get("question") if task != "code" else None
            extra = ""
            if task == "code":
                extra = f" Context is the Stack Overflow answer ({r['row'].get('context_url')}) joined with '\\n' as in CodeIPIABuilder; the BIPIA user task is to fix the user's code given its error."
            records_inj.append({
                "label": "injection",
                "source": "BIPIA",
                "subset": task,
                "text": text,
                "injected_instruction": attack,
                "origin": {
                    "url": URL,
                    "commit": COMMIT,
                    "file": r["file"],
                    "index": r["index"],
                    "attack_file": attack_file,
                    "attack_category": cat,
                    "position": pos,
                    "question": question,
                },
                "notes": (
                    f"BIPIA attack '{cat}-{aidx}' (category {cat}, item {aidx}) inserted with {FN_NAME[pos]} "
                    f"replicated from bipia/data/utils.py (joined with '\\n').{split_note}"
                    f" index = 0-based line number in {r['file']}.{extra}"
                ),
            })

        # Benign: remaining unused candidates, unchanged.
        nb = 0
        for ci, r in enumerate(cands):
            if nb >= N_BEN[task]:
                break
            if ci in used or norm(r["context"]) in seen_norm:
                continue
            used.add(ci)
            seen_norm.add(norm(r["context"]))
            question = r["row"].get("question") if task != "code" else None
            extra = ""
            if task == "code":
                extra = f" Stack Overflow answer ({r['row'].get('context_url')}) joined with '\\n' as in CodeIPIABuilder; the BIPIA user task is to fix the user's code given its error."
            records_ben.append({
                "label": "benign",
                "source": "BIPIA",
                "subset": task,
                "text": r["context"],
                "injected_instruction": None,
                "origin": {
                    "url": URL,
                    "commit": COMMIT,
                    "file": r["file"],
                    "index": r["index"],
                    "attack_file": None,
                    "attack_category": None,
                    "position": None,
                    "question": question,
                },
                "notes": f"Original BIPIA {task} test context, unmodified (no attack inserted). index = 0-based line number in {r['file']}.{extra}",
            })
            nb += 1
        if nb < N_BEN[task]:
            raise SystemExit(f"not enough benign for {task}")

    out = []
    for i, rec in enumerate(records_inj, 1):
        out.append({"id": f"bipia-inj-{i:02d}", **rec})
    for i, rec in enumerate(records_ben, 1):
        out.append({"id": f"bipia-ben-{i:02d}", **rec})

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "w", encoding="utf-8", newline="\n") as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("wrote", len(out), "records to", OUT)


if __name__ == "__main__":
    main()
