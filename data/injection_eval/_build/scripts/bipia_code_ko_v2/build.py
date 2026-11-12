"""Build KO translations for BIPIA code (non-core) records.

usage: python -X utf8 -I build.py <en_bipia.jsonl> <templates_ko.txt> <out.jsonl>

Templates hold the Korean prose with @@Cn@@ placeholders; the n-th fenced code
block of the EN text is inserted verbatim, so code stays byte-identical.
"""
import json
import re
import sys
from collections import Counter

FENCE = re.compile(r"```[\s\S]*?```")
INLINE = re.compile(r"`[^`]+`")
PH = re.compile(r"@@C(\d+)@@")

BASE_NOTE = "코드 블록과 인라인 코드는 바이트 단위로 동일하게 유지하고 주변 설명 문장만 번역."
EXTRA = {
    "bipia-inj-67": "링크 텍스트 'Python Naming Convention'은 원문 제목이라 영어 그대로 유지.",
    "bipia-inj-73": "원문 문장 '...to give'는 이미지가 빠져 끊긴 상태라 '결과는 다음과 같습니다'로 자연스럽게 처리.",
    "bipia-inj-74": "인용문(> ...)은 일반 설명 문장이라 번역.",
    "bipia-inj-78": "참조 질문 제목 'Accessing class variables from a list comprehension in the class definition'은 영어 그대로 유지.",
    "bipia-inj-82": "원문 도입 문장이 동명사형 조각(Integrating ...)이지만 같은 의도의 정중한 명령문으로 번역.",
    "bipia-ben-52": "인용된 문서 문장은 번역하고 인용 기호(> ) 구조와 인라인 코드는 유지. 'NOTE'는 '참고'로 번역.",
    "bipia-ben-53": "블로그 글 제목 'Serializing arbitrary Python objects to JSON using _dict_'은 영어 그대로 유지(들여쓰기 포함).",
    "bipia-ben-58": "참조 질문 제목 'Failed loading english.pickle with nltk.data.load'는 영어 그대로 유지.",
    "bipia-ben-63": "'Other Resources' 아래의 외부 자료 제목 5개는 고유 제목이라 영어 그대로 유지.",
    "bipia-ben-66": "펜스 없이 쓰인 코드 조각(subplots(), axes[num, 0] 등)과 '> IndexError'는 원문 그대로 유지.",
    "bipia-ben-70": "인용된 scikit-learn 문서 문장은 번역하고 인용 기호(> ) 구조와 줄바꿈은 유지.",
    "bipia-ben-62": "override는 고정 규칙에 따라 '재정의'로 번역.",
    "bipia-ben-67": "ignore는 고정 규칙에 따라 '무시'로 번역.",
}


def parse_templates(path):
    out, cur, buf = {}, None, []
    for line in open(path, encoding="utf-8").read().split("\n"):
        if line.startswith("=== "):
            if cur:
                out[cur] = "\n".join(buf)
            cur, buf = line[4:].strip(), []
        else:
            buf.append(line)
    if cur:
        out[cur] = "\n".join(buf)
    return out


def main(en_path, tpl_path, out_path):
    recs = [json.loads(l) for l in open(en_path, encoding="utf-8")]
    sel = [r for r in recs if r["core"] is False and r["subset"] == "code"]
    tpls = parse_templates(tpl_path)
    assert set(tpls) == {r["id"] for r in sel}, set(tpls) ^ {r["id"] for r in sel}
    problems = []
    out = []
    for r in sel:
        en = r["text"]
        blocks = FENCE.findall(en)
        body = tpls[r["id"]].strip()
        idx = [int(m) for m in PH.findall(body)]
        assert idx == list(range(len(blocks))), (r["id"], idx, len(blocks))
        ko_body = PH.sub(lambda m: blocks[int(m.group(1))], body)
        lead = en[: len(en) - len(en.lstrip())]
        trail = en[len(en.rstrip()):]
        ko = lead + ko_body + trail
        # restore per-line trailing whitespace of prose lines (markdown "> " etc.)
        en_prose = FENCE.split(en)
        ko_prose = FENCE.split(ko)
        assert len(en_prose) == len(ko_prose)
        fixed = []
        for es, ks in zip(en_prose, ko_prose):
            el, kl = es.split("\n"), ks.split("\n")
            if len(el) != len(kl):
                problems.append((r["id"], "segment line count", len(el), len(kl)))
                fixed.append(ks)
                continue
            fixed.append("\n".join(
                k.rstrip(" \t") + e[len(e.rstrip(" \t")):] for e, k in zip(el, kl)))
        ko = fixed[0]
        for b, seg in zip(blocks, fixed[1:]):
            ko += b + seg
        # checks
        if FENCE.findall(ko) != blocks:
            problems.append((r["id"], "fence mismatch"))
        en_inl = Counter(INLINE.findall(FENCE.sub("", en)))
        ko_inl = Counter(INLINE.findall(FENCE.sub("", ko)))
        if en_inl != ko_inl:
            problems.append((r["id"], "inline mismatch", en_inl - ko_inl, ko_inl - en_inl))
        if en.count("\n") != ko.count("\n"):
            problems.append((r["id"], "newline count", en.count("\n"), ko.count("\n")))
        for u in re.findall(r"https?://\S+", FENCE.sub("", en)):
            if u not in ko:
                problems.append((r["id"], "url missing", u))
        inj = None
        if r["injected_instruction"] is not None:
            en_inj = r["injected_instruction"]
            en_lead, rest = en_inj.split("\n", 1)
            k = blocks.index(rest)
            before = fixed[k]
            assert before.endswith("\n")
            ko_lead = before[:-1].split("\n")[-1]
            if en_lead.endswith((" ", "\t")) != ko_lead.endswith((" ", "\t")):
                problems.append((r["id"], "lead trailing ws differs"))
            inj = ko_lead + "\n" + rest
            if ko.count(inj) != 1:
                problems.append((r["id"], "inj not unique substring"))
            if en.count(en_inj) != 1:
                problems.append((r["id"], "EN inj odd"))
        note = BASE_NOTE + (" " + EXTRA[r["id"]] if r["id"] in EXTRA else "")
        out.append({
            "id": r["id"] + "-ko",
            "pair_id": r["id"],
            "lang": "ko",
            "label": r["label"],
            "source": r["source"],
            "subset": r["subset"],
            "text": ko,
            "injected_instruction": inj,
            "origin": r["origin"],
            "notes": r["notes"],
            "core": r["core"],
            "translation_notes": note,
        })
    with open(out_path, "w", encoding="utf-8", newline="\n") as f:
        for o in out:
            f.write(json.dumps(o, ensure_ascii=False) + "\n")
    print("written", len(out), Counter(o["label"] for o in out))
    print("problems:", len(problems))
    for p in problems:
        print("  ", p)


if __name__ == "__main__":
    main(*sys.argv[1:4])
