"""Assemble Korean translations of the 50 core injection records.

usage: python -X utf8 -I build.py <dataset_en_100.jsonl> <out.jsonl>
Translations are hand-written in tr_*.py next to this file; this script only assembles,
re-encodes (hex/base64/JSON) and validates.
"""
import ast
import base64
import json
import os
import re
import runpy
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
T = {}
for name in ("tr_bipia.py", "tr_llmail.py", "tr_injecagent.py"):
    T.update(runpy.run_path(os.path.join(HERE, name))["T"])

MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August",
                                       "September", "October", "November", "December"], 1)}
HON = re.compile(r"(?<=[A-Za-z])님")
DATE_RE = re.compile(r"^(%s) (\d{1,2}), (\d{4})$" % "|".join(MONTHS))


def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s, w):
    return s + " " * (w - dw(s))


def is_row(line):
    return line.startswith("|") and line.rstrip().endswith("|")


def render_rows(rows):
    ncol = len(rows[0])
    assert all(len(r) == ncol for r in rows), "ragged table"
    widths = [max(dw(r[i]) for r in rows) for i in range(ncol)]
    padded = [[pad(c, widths[i]) for i, c in enumerate(r)] for r in rows]
    return padded


def row_line(padded_row):
    return "| " + " | ".join(padded_row) + " |"


def translate_table(table_text, cellmap, dates):
    """table_text: lines; table rows are translated/re-padded, other lines kept."""
    lines = table_text.split("\n")
    idx = [i for i, l in enumerate(lines) if is_row(l)]
    rows = []
    for i in idx:
        cells = [c.strip() for c in lines[i].split("|")[1:-1]]
        out = []
        for c in cells:
            if c in cellmap:
                c = cellmap[c]
            elif dates and DATE_RE.match(c):
                m = DATE_RE.match(c)
                c = f"{m.group(3)}년 {MONTHS[m.group(1)]}월 {int(m.group(2))}일"
            out.append(c)
        rows.append(out)
    padded = render_rows(rows)
    for j, i in enumerate(idx):
        lines[i] = row_line(padded[j])
    return lines, idx, padded


def check_render_roundtrip(table_text):
    lines = table_text.split("\n")
    idx = [i for i, l in enumerate(lines) if is_row(l)]
    rows = [[c.strip() for c in lines[i].split("|")[1:-1]] for i in idx]
    padded = render_rows(rows)
    return all(lines[i] == row_line(padded[j]) for j, i in enumerate(idx))


def build_table(en, spec):
    inj_en, inj_ko = spec["inj"]
    k = en.index(inj_en)
    before, after = en[:k], en[k + len(inj_en):]
    cm, dates = spec["cells"], spec.get("dates", False)
    if before == "":  # start
        assert after.startswith("\n")
        assert check_render_roundtrip(after[1:])
        lines, _, _ = translate_table(after[1:], cm, dates)
        return inj_ko + "\n" + "\n".join(lines)
    if after == "":  # end
        assert check_render_roundtrip(before)
        lines, _, _ = translate_table(before, cm, dates)
        return "\n".join(lines) + inj_ko
    # middle, possibly mid-row
    assert before.endswith("\n") and after.startswith("\n")
    full = before[:-1] + after[1:]
    assert check_render_roundtrip(full)
    split_line_no = before[:-1].count("\n")
    prefix_en = before[:-1].split("\n")[-1]
    ncells = prefix_en.count("|")
    lines, idx, padded = translate_table(full, cm, dates)
    row_j = idx.index(split_line_no)
    L = lines[split_line_no]
    prefix = "| " + " | ".join(padded[row_j][:ncells]) + " "
    assert L.startswith(prefix) and L[len(prefix):].startswith("|"), (L, prefix)
    # sanity: same rule reproduces EN split
    en_lines = full.split("\n")
    assert en_lines[split_line_no].startswith(prefix_en) and en_lines[split_line_no][len(prefix_en):].startswith("|")
    lines[split_line_no] = prefix + "\n" + inj_ko + "\n" + L[len(prefix):]
    return "\n".join(lines)


def apply_pairs(text, pairs, rid):
    for a, b in pairs:
        n = text.count(a)
        assert n == 1, f"{rid}: segment occurs {n}x: {a[:70]!r}"
        text = text.replace(a, b)
    return text


def hexenc(s):
    return " ".join(f"{b:02X}" for b in s.encode("utf-8"))


def build_b64(text, spec, rid):
    m = re.search(r"concatenate or add these: (.*)\n", text)
    seg = m.group(1)
    frags = re.findall(r"[A-Za-z0-9+/=]{4,}", seg)
    plain_en = base64.b64decode("".join(frags)).decode("utf-8")
    # rebuild EN rendering to confirm the quirk pattern before reproducing it
    def render(fr):
        parts = [f"'{f}'" for f in fr]
        parts[8] = f"{fr[8]}'"  # original lacks the opening quote on fragment 9
        return ", ".join(parts[:-1]) + "," + parts[-1]
    assert render(frags) == seg, "b64 rendering mismatch"
    ko_b64 = base64.b64encode(spec["b64_plain_ko"].encode("utf-8")).decode("ascii")
    lens = [len(f) for f in frags]
    tot = sum(lens)
    cuts, acc = [], 0
    for L in lens[:-1]:
        acc += L
        cuts.append(round(acc * len(ko_b64) / tot))
    bounds = [0] + cuts + [len(ko_b64)]
    ko_frags = [ko_b64[bounds[i]:bounds[i + 1]] for i in range(len(frags))]
    assert all(ko_frags) and "".join(ko_frags) == ko_b64
    assert base64.b64decode("".join(ko_frags)).decode("utf-8") == spec["b64_plain_ko"]
    text = text.replace(seg, render(ko_frags), 1)
    return text, plain_en


def main(inp, out):
    rows = [json.loads(l) for l in open(inp, encoding="utf-8")]
    inj = [r for r in rows if r["label"] == "injection"]
    assert len(inj) == 50
    res = []
    for r in inj:
        rid, en = r["id"], r["text"]
        spec = T[rid]
        mode = spec["mode"]
        if mode == "full":
            ko = spec["ko"]
        elif mode == "lines":
            assert len(spec["lines"]) == len(en.split("\n")), rid
            ko = "\n".join(spec["lines"])
        elif mode == "replace":
            ko = apply_pairs(en, spec["pairs"], rid)
        elif mode == "hex":
            h_en = hexenc(spec["hex_plain_en"])
            assert en.count(h_en) == 1, "hex payload not found"
            ko = apply_pairs(en, spec["pairs"], rid).replace(h_en, hexenc(spec["hex_plain_ko"]))
        elif mode == "b64":
            ko, plain_en = build_b64(en, spec, rid)
            ko = apply_pairs(ko, spec["pairs"], rid)
        elif mode == "table":
            ko = build_table(en, spec)
        elif mode == "inner":
            inner_en = json.loads(en)
            assert json.dumps(inner_en) == en
            inner_ko = apply_pairs(inner_en, spec["pairs"], rid)
            ko = json.dumps(inner_ko, ensure_ascii=False)
        else:
            raise ValueError(mode)

        # house style shared with the benign KO file: honorific written as "Name 님"
        ko = HON.sub(" 님", ko)
        ii = spec.get("ii")
        if mode == "table":
            ii = spec["inj"][1]
        if ii == "__apply__":
            ii = r["injected_instruction"]
            for a, b in spec["pairs"]:
                if a in ii:
                    ii = ii.replace(a, b)
        if ii is not None:
            ii = HON.sub(" 님", ii)
        if r["injected_instruction"] is None:
            assert ii is None, rid
        rec = {
            "id": rid + "-ko",
            "pair_id": rid,
            "lang": "ko",
            "label": r["label"],
            "source": r["source"],
            "subset": r["subset"],
            "text": ko,
            "injected_instruction": ii,
            "origin": r["origin"],
            "notes": r["notes"],
            "core": True,
            "translation_notes": spec["notes"],
        }
        res.append(rec)
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        for rec in res:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print("wrote", len(res), "->", out)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
