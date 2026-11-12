import sys, json, re, difflib, importlib.util, collections

en_path, out_path, texts_path, ko_dir = sys.argv[1:5]

spec = importlib.util.spec_from_file_location("ko_texts", texts_path)
mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
KO = mod.KO

COMMON = ("'Subject:' 필드 표시는 LLMail 직렬화 형식이라 그대로 유지하고 제목 내용만 번역. "
          "공격 대상(contact@contact.com, 본문 'confirmation')은 원문 그대로 유지.")

en = {}
order = []
for l in open(en_path, encoding="utf-8"):
    r = json.loads(l); en[r["id"]] = r; order.append(r["id"])
ids = [i for i in order if 49 <= int(i.split("-")[-1]) <= 80]
assert len(ids) == 32, len(ids)

def placeholders(n, t_en):
    ph = {"{CR}": "\r"}
    if n == 50:
        runs = re.findall(r"[＀-￯​]+", t_en)
        ph["{FW_CONF}"] = [r for r in runs if r.startswith("ｃ​ｏ​ｎ​ｆ")][0]
        ph["{FW_CONTACT}"] = [r for r in runs if r.startswith("ｃ​ｏ​ｎ​ｔ")][0]
    if n == 61:
        ph["{TAGS}"] = re.search(r"[\U000E0000-\U000E007F]+", t_en).group(0)
    if n == 74:
        ph["{H_ADDR}"] = re.search(r"c\U00010C34ntact@c\U00010C34ntact\.com", t_en).group(0)
        ph["{H_BODY}"] = re.search(r"c\U0001D5FCnfirmati\U0001D5FCn", t_en).group(0)
    return ph

def fill(s, ph):
    if s is None: return None
    for k, v in ph.items():
        s = s.replace(k, v)
    return s

recs = []
problems = []
for i in ids:
    n = int(i.split("-")[-1]); e = en[i]
    text, inj, note = KO[n]
    ph = placeholders(n, e["text"])
    text = fill(text, ph); inj = fill(inj, ph)
    # restore per-line trailing spaces (editor strips them); translations are line-aligned with EN
    el, kl = e["text"].split("\n"), text.split("\n")
    if len(el) == len(kl):
        for j, (a, b) in enumerate(zip(el, kl)):
            want = len(a) - len(a.rstrip(" "))
            have = len(b) - len(b.rstrip(" "))
            if want > have and b.strip():
                kl[j] = b.rstrip(" ") + " " * want
        text = "\n".join(kl)
    if (e["injected_instruction"] is None) != (inj is None):
        problems.append(f"{i}: null mismatch")
    if inj is not None and inj not in text:
        problems.append(f"{i}: injected not substring")
    if re.search(r"\{(CR|TAGS|FW_CONF|FW_CONTACT|H_ADDR|H_BODY|R|S)\}", text):
        problems.append(f"{i}: unresolved placeholder")
    tn = COMMON + (" " + note if note else "")
    if n in (59,):
        tn = ("'Subject:' 필드 표시는 LLMail 직렬화 형식이라 그대로 유지하고 제목 내용만 번역. " + note)
    rec = {"id": i + "-ko", "pair_id": i, "lang": "ko", "label": e["label"], "source": e["source"],
           "subset": e["subset"], "text": text, "injected_instruction": inj, "origin": e["origin"],
           "notes": e["notes"], "core": e["core"], "translation_notes": tn}
    recs.append(rec)

with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for r in recs:
        f.write(json.dumps(r, ensure_ascii=False) + "\n")

# ---------- validation ----------
back = [json.loads(l) for l in open(out_path, encoding="utf-8")]
assert len(back) == 32 and [b["pair_id"] for b in back] == ids
assert len({b["id"] for b in back}) == 32

def hangul_ratio(t):
    letters = [c for c in t if c.isalpha()]
    h = sum(1 for c in letters if "가" <= c <= "힣")
    return h / max(1, len(letters))

def special(t):
    return collections.Counter(c for c in t if ord(c) > 0x2000 and not ("가" <= c <= "힣")
                               and c not in "‘’“”—–…→")

def tags(t):
    return collections.Counter(re.findall(r"<\|?[A-Za-z_/!][^<>\s]*?\|?>|&lt;\|[^&]*\|&gt;", t))

def trail(t):
    return [len(l) - len(l.rstrip(" ")) for l in t.split("\n") if l != l.rstrip(" ")]

print("id | len_en len_ko | lines en/ko | hangul | c@c en/ko | 'confirmation' en/ko")
for b in back:
    e = en[b["pair_id"]]; t, te = b["text"], e["text"]
    le, lk = te.count("\n"), t.count("\n")
    cc = (te.count("contact@contact.com"), t.count("contact@contact.com"))
    cf = (te.count("confirmation"), t.count("confirmation"))
    print(b["pair_id"], len(te), len(t), f"{le}/{lk}", round(hangul_ratio(t), 2), cc, cf)
    if le != lk: problems.append(f"{b['pair_id']}: line count {le} vs {lk}")
    if te.count("\r") != t.count("\r"): problems.append(f"{b['pair_id']}: CR count")
    se, sk = special(te), special(t)
    miss = se - sk
    if miss: problems.append(f"{b['pair_id']}: special chars missing {dict(miss)}")
    if tags(te) != tags(t): problems.append(f"{b['pair_id']}: tags differ {tags(te)} vs {tags(t)}")
    if trail(te) != trail(t): problems.append(f"{b['pair_id']}: trailing spaces {trail(te)} vs {trail(t)}")
    if not t.startswith("Subject: "): problems.append(f"{b['pair_id']}: Subject marker")
    for code in re.findall(r"```.*?```", te, re.S):
        if code not in t and "Unable" in code: problems.append(f"{b['pair_id']}: code block changed")
    for ic in re.findall(r"`[^`\n]+`", te):
        if ic not in t: problems.append(f"{b['pair_id']}: inline code changed {ic[:40]}")

# similarity within outputs and vs other KO parts
others = []
import glob, os
for p in glob.glob(os.path.join(ko_dir, "*.jsonl")):
    if os.path.abspath(p) == os.path.abspath(out_path): continue
    for l in open(p, encoding="utf-8"):
        o = json.loads(l); others.append((o["id"], o["text"]))
mx = []
for a in range(len(back)):
    for bb in range(a + 1, len(back)):
        r = difflib.SequenceMatcher(None, back[a]["text"], back[bb]["text"]).ratio()
        if r >= 0.6: mx.append((back[a]["id"], back[bb]["id"], round(r, 2)))
    for oid, ot in others:
        sm = difflib.SequenceMatcher(None, back[a]["text"], ot)
        if sm.real_quick_ratio() >= 0.6 and sm.quick_ratio() >= 0.6:
            r = sm.ratio()
            if r >= 0.6: mx.append((back[a]["id"], oid, round(r, 2)))
print("similar pairs (>=0.6):", mx)
print("PROBLEMS:", problems if problems else "none")
