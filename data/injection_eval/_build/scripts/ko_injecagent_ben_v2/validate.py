# Usage: python -X utf8 -I validate.py <parts_v2/injecagent.jsonl> <ko_parts/injecagent_ben_new.jsonl> <ko_parts/core_ben.jsonl>
import ast
import json
import re
import sys

H = re.compile(r"[가-힣]")


def shape(x):
    if isinstance(x, dict):
        return {k: shape(v) for k, v in x.items()}
    if isinstance(x, list):
        return [shape(v) for v in x]
    return type(x).__name__


def ng(t, n=5):
    w = t.split()
    return set(tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1)))


def main(src_p, out_p, core_p):
    src = [json.loads(l) for l in open(src_p, encoding="utf-8")]
    sel = [r for r in src if r["core"] is False and r["label"] == "benign"]
    raw = open(out_p, encoding="utf-8").read()
    lines = raw.split("\n")
    assert lines[-1] == ""
    lines = lines[:-1]
    out = [json.loads(l) for l in lines]
    assert len(out) == 50
    assert [o["pair_id"] for o in out] == [r["id"] for r in sel], "order/pair mismatch"
    assert len(set(o["id"] for o in out)) == 50
    low = 0
    for o, r in zip(out, sel):
        assert o["id"] == r["id"] + "-ko" and o["lang"] == "ko"
        for k in ("label", "source", "subset", "origin", "notes", "core"):
            assert o[k] == r[k], (o["id"], k)
        assert o["injected_instruction"] is None
        assert "\\u" not in o["text"], o["id"]
        s = json.loads(o["text"])
        assert isinstance(s, str)
        assert o["text"] == json.dumps(s, ensure_ascii=False)
        d = ast.literal_eval(s)
        de = ast.literal_eval(json.loads(r["text"]))
        assert shape(d) == shape(de), o["id"]
        if len(H.findall(s)) < 5:
            low += 1
            print("low hangul", o["id"])
    print("structure checks ok; low-hangul:", low)
    core = [json.loads(l) for l in open(core_p, encoding="utf-8")]
    pool = [(o["id"], json.loads(o["text"])) for o in out] + \
           [(c["id"], json.loads(c["text"])) for c in core if c["source"] == "InjecAgent"]
    mx = (0, None, None)
    for i in range(len(pool)):
        for j in range(i + 1, len(pool)):
            a, b = ng(pool[i][1]), ng(pool[j][1])
            jac = len(a & b) / len(a | b)
            if jac > mx[0]:
                mx = (jac, pool[i][0], pool[j][0])
    print("max 5-gram jaccard among KO InjecAgent benign:", mx)


if __name__ == "__main__":
    main(*sys.argv[1:4])
