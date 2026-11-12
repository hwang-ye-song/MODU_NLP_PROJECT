# -*- coding: utf-8 -*-
"""Assemble KO core-benign records from hand-written translations in tr.py.
Usage: python -X utf8 -I build.py <dataset_en_100.jsonl> <out.jsonl>
"""
import ast
import importlib.util
import json
import os
import re
import sys
import unicodedata

HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("tr", os.path.join(HERE, "tr.py"))
tr = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tr)

FENCE = re.compile(r"(```.*?```)", re.S)


def apply_lines(rid, en, ko_lines):
    """Replace each non-blank prose line positionally, keep per-line edge whitespace,
    copy fenced code byte-for-byte."""
    parts = FENCE.split(en)
    out, k = [], 0
    for i, seg in enumerate(parts):
        if i % 2 == 1:  # code fence
            out.append(seg)
            continue
        new_lines = []
        for ln in seg.split("\n"):
            core = ln.strip()
            if not core:
                new_lines.append(ln)
                continue
            assert k < len(ko_lines), f"{rid}: too few KO lines"
            ko = ko_lines[k]
            k += 1
            if ko is None:
                new_lines.append(ln)
                continue
            lead = ln[: len(ln) - len(ln.lstrip())]
            trail = ln[len(ln.rstrip()):]
            new_lines.append(lead + ko + trail)
        out.append("\n".join(new_lines))
    assert k == len(ko_lines), f"{rid}: {len(ko_lines)} KO lines given, {k} prose lines found"
    return "".join(out)


def dw(s):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def apply_table(rid, en, cmap):
    lines = en.split("\n")
    rows, idx = [], []
    for i, ln in enumerate(lines):
        if ln.startswith("|"):
            cells = [c.strip() for c in ln.strip()[1:-1].split("|")]
            rows.append(cells)
            idx.append(i)
    ncol = len(rows[0])
    assert all(len(r) == ncol for r in rows), rid

    def render(rs):
        w = [max(dw(r[j]) for r in rs) for j in range(ncol)]
        return ["| " + " | ".join(r[j] + " " * (w[j] - dw(r[j])) for j in range(ncol)) + " |" for r in rs]

    # sanity: identity render reproduces EN layout
    assert render(rows) == [lines[i] for i in idx], f"{rid}: table layout not reproducible"
    used = set()
    new_rows = []
    for r in rows:
        nr = []
        for c in r:
            if c in cmap:
                used.add(c)
                nr.append(cmap[c])
            else:
                nr.append(c)
        new_rows.append(nr)
    assert used == set(cmap), f"{rid}: unused table keys {set(cmap) - used}"
    rendered = render(new_rows)
    for i, ln in zip(idx, rendered):
        lines[i] = ln
    return "\n".join(lines)


def map_values(obj, vmap, used):
    if isinstance(obj, dict):
        return {k: map_values(v, vmap, used) for k, v in obj.items()}
    if isinstance(obj, list):
        return [map_values(v, vmap, used) for v in obj]
    if isinstance(obj, str) and obj in vmap:
        used.add(obj)
        return vmap[obj]
    return obj


def same_shape(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(same_shape(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same_shape(x, y) for x, y in zip(a, b))
    return True


def apply_injecagent(rid, en, vmap):
    inner = json.loads(en)
    d = ast.literal_eval(inner)
    assert json.dumps(str(d)) == en, f"{rid}: original encoding not reproducible"
    used = set()
    d2 = map_values(d, vmap, used)
    assert used == set(vmap), f"{rid}: unused value keys {set(vmap) - used}"
    for v in vmap.values():
        assert "'" not in v and '"' not in v and "\\" not in v, f"{rid}: quote char in KO value"
    ko = json.dumps(str(d2), ensure_ascii=False)
    # verify it parses the same way
    s2 = json.loads(ko)
    assert isinstance(s2, str)
    d3 = ast.literal_eval(s2)
    assert d3 == d2 and same_shape(d, d3), f"{rid}: KO parse mismatch"
    return ko


def note_key(r):
    s = r["source"]
    if s == "BIPIA":
        return "bipia-" + r["subset"]
    if s.startswith("LLMail"):
        return "llmail"
    if s == "InjecAgent":
        return "injecagent"
    return "notinject"


def main(inp, outp):
    recs = [json.loads(l) for l in open(inp, encoding="utf-8")]
    ben = [r for r in recs if r["label"] == "benign"]
    assert len(ben) == 50
    out = []
    for r in ben:
        rid = r["id"]
        en = r["text"]
        if rid in tr.TABLE:
            ko = apply_table(rid, en, tr.TABLE[rid])
        elif rid in tr.INJECAGENT:
            ko = apply_injecagent(rid, en, tr.INJECAGENT[rid])
        elif rid in tr.LINES:
            ko = apply_lines(rid, en, tr.LINES[rid])
        else:
            raise SystemExit(f"no translation for {rid}")
        notes = tr.NOTES[note_key(r)]
        if rid in tr.EXTRA_NOTES:
            notes += " " + tr.EXTRA_NOTES[rid]
        out.append({
            "id": rid + "-ko",
            "pair_id": rid,
            "lang": "ko",
            "label": r["label"],
            "source": r["source"],
            "subset": r["subset"],
            "text": ko,
            "injected_instruction": None,
            "origin": r["origin"],
            "notes": r["notes"],
            "core": True,
            "translation_notes": notes,
        })
    with open(outp, "w", encoding="utf-8", newline="\n") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("wrote", len(out), "records to", outp)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
