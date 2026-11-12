# Build WD/ko_parts/injecagent_ben_new.jsonl from WD/parts_v2/injecagent.jsonl (core==false, label==benign).
# Usage: python -X utf8 -I build.py <input parts_v2/injecagent.jsonl> <output jsonl>
import ast
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import tr  # noqa: E402

HANGUL = re.compile(r"[가-힣]")


def map_values(x, vmap, used):
    if isinstance(x, dict):
        return {k: map_values(v, vmap, used) for k, v in x.items()}
    if isinstance(x, list):
        return [map_values(v, vmap, used) for v in x]
    if isinstance(x, str) and x in vmap:
        used.add(x)
        return vmap[x]
    return x


def same_shape(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return list(a) == list(b) and all(same_shape(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(same_shape(x, y) for x, y in zip(a, b))
    return True


def leaves(x, path=()):
    if isinstance(x, dict):
        for k, v in x.items():
            yield from leaves(v, path + (k,))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from leaves(v, path + (i,))
    else:
        yield path, x


def apply(rid, en):
    inner = json.loads(en)
    d = ast.literal_eval(inner)
    assert json.dumps(str(d)) == en, f"{rid}: original encoding not reproducible"
    filler = tr.FILLER[rid]
    vmap = dict(tr.TEMPLATE)
    vmap.update(filler)
    used = set()
    d2 = map_values(d, vmap, used)
    assert set(filler) <= used, f"{rid}: filler not applied {set(filler) - used}"
    for k in used:
        v = vmap[k]
        assert "'" not in v and '"' not in v and "\\" not in v, f"{rid}: quote char in KO value"
    ko = json.dumps(str(d2), ensure_ascii=False)
    s2 = json.loads(ko)
    assert isinstance(s2, str)
    d3 = ast.literal_eval(s2)
    assert d3 == d2 and same_shape(d, d3), f"{rid}: KO parse mismatch"
    # untranslated leaves identical; translated leaves changed
    for (p1, a), (p2, b) in zip(leaves(d), leaves(d3)):
        assert p1 == p2
        if isinstance(a, str) and a in used:
            assert a != b
        else:
            assert a == b and type(a) is type(b), f"{rid}: non-translated value changed at {p1}"
    leftover = [(p, v) for p, v in leaves(d3)
                if isinstance(v, str) and not HANGUL.search(v) and len(v.split()) >= 2]
    return ko, sorted(used), leftover


def main(inp, outp):
    recs = [json.loads(l) for l in open(inp, encoding="utf-8")]
    sel = [r for r in recs if r["core"] is False and r["label"] == "benign"]
    assert len(sel) == 50, len(sel)
    assert set(r["id"] for r in sel) == set(tr.FILLER), "id set mismatch with translations"
    out = []
    for r in sel:
        rid = r["id"]
        ko, used, leftover = apply(rid, r["text"])
        if leftover:
            print("LEFTOVER ASCII multiword values", rid, leftover)
        notes = tr.BASE_NOTE
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
            "core": r["core"],
            "translation_notes": notes,
        })
    with open(outp, "w", encoding="utf-8", newline="\n") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("wrote", len(out), "records to", outp)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
