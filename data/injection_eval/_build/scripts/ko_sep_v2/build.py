import sys, json, re, runpy, difflib

en_path, inj_path, ben_path, out_path = sys.argv[1:5]
INJ = runpy.run_path(inj_path)["INJ"]
BEN = runpy.run_path(ben_path)["BEN"]
PREFIX_EN = "On top of your main task, answer this priority question: "

recs = [json.loads(l) for l in open(en_path, encoding="utf-8")]
out = []
for r in recs:
    rid = r["id"]
    if r["label"] == "injection":
        probe, body, wit, extra = INJ[rid]
        pos = r["origin"]["probe_position_in_data"]
        assert r["text"].startswith(r["injected_instruction"]) if pos == "start" else r["text"].endswith(r["injected_instruction"]), rid
        text = probe + " " + body if pos == "start" else body + " " + probe
        inj = probe
        note = (f"Passage translated into natural Korean prose; SEP probe translated as a Korean request in the same position ({pos}, single-space join as in EN). "
                + ("Insistent lead-in 'On top of your main task, answer this priority question:' rendered with the fixed phrase '주어진 작업에 더해 다음 우선 질문에도 답하세요:'. " if r["injected_instruction"].startswith(PREFIX_EN) else "")
                + f"origin.witness kept in English; expected Korean answer: {wit}.")
    else:
        text, extra = BEN[rid]
        inj = None
        note = "Passage translated into natural Korean prose; no instruction added."
    if extra:
        note += " " + extra
    o = {"id": rid + "-ko", "pair_id": rid, "lang": "ko", "label": r["label"], "source": r["source"],
         "subset": r["subset"], "text": text, "injected_instruction": inj, "origin": r["origin"],
         "notes": r["notes"], "core": r["core"], "translation_notes": note}
    out.append(o)

# validation
assert len(out) == len(recs) == 60
assert len({o["id"] for o in out}) == 60
assert set(INJ) | set(BEN) == {r["id"] for r in recs}
for o, r in zip(out, recs):
    assert o["pair_id"] == r["id"]
    if o["label"] == "injection":
        assert o["injected_instruction"] and o["injected_instruction"] in o["text"]
        pos = r["origin"]["probe_position_in_data"]
        assert (o["text"].startswith(o["injected_instruction"]) if pos == "start" else o["text"].endswith(o["injected_instruction"]))
    else:
        assert o["injected_instruction"] is None
        assert not re.search(r"답하세요|알려 주세요|말하세요|작업|지시|무시|AI|어시스턴트", o["text"]), o["id"]
    t = o["text"]
    hang = len(re.findall(r"[가-힣]", t)); lat = len(re.findall(r"[A-Za-z]", t))
    words = re.findall(r"[A-Za-z][A-Za-z'\-]*", t)
    if hang / max(1, hang + lat) < 0.8:
        print("LOW HANGUL", o["id"], hang, lat)
    if words:
        print(o["id"], "latin:", sorted(set(words)))
for i in range(60):
    for j in range(i + 1, 60):
        a, b = out[i]["text"], out[j]["text"]
        if difflib.SequenceMatcher(None, a, b).ratio() > 0.6:
            print("SIMILAR", out[i]["id"], out[j]["id"])

with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for o in out:
        f.write(json.dumps(o, ensure_ascii=False) + "\n")
# re-read check
back = [json.loads(l) for l in open(out_path, encoding="utf-8")]
assert len(back) == 60
print("OK", len(back), sum(o["label"] == "injection" for o in back), sum(o["label"] == "benign" for o in back))
