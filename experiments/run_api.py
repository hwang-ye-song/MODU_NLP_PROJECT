"""API runs for the experiments (Q2 and QL, 3 calls per sample). Analysis lives in each experiment's own script.

    python experiments/run_api.py 01_baseline        # EN 1000 + NotInject 25 (reuses baseline/ Q2 calls if present)
    python experiments/run_api.py X1_register        # 450 register variants
    python experiments/run_api.py X2_user_task       # 1000 docs with the user's task: state = {"user_task", "document"}
    python experiments/run_api.py X3_distractor      # 400: same span in wiki vs instruction-dense Enron carriers (+ clean carriers)
    python experiments/run_api.py X4_persuasion      # 1200: self-classification phrases inserted at top / next to the span
    python experiments/run_api.py 01_baseline_definitions   # EN 1000 + NotInject with the own-definition questions QS, Q3, QC
    python experiments/run_api.py 02_korean          # KO 1000 (Korean original), paired to EN by pair_uid
    python experiments/translate_ko.py && python experiments/run_api.py 02_korean_mt   # KO -> EN (opus-mt-ko-en), then judge
    python experiments/run_api.py 03_judge_attack    # JA 920: 420 audited detector-evading attacks + 500 EN benign
    python experiments/run_api.py parity X2_user_task QL   # judge() vs saved runs on 3 samples

Every run is resumable: calls already in results/<exp>/raw/<Q>_raw.jsonl are not repeated.
"""
import json
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import jevlab as J  # noqa: E402

EN = os.path.join(J.DATA, "en", "dataset_en_1000.jsonl")
NOTINJECT = os.path.join(J.DATA, "en", "overdefense_ref_notinject.jsonl")
X1 = os.path.join(J.DATA, "experiments", "X1_register.jsonl")
X2 = os.path.join(J.DATA, "experiments", "X2_user_task.jsonl")
X3 = os.path.join(J.DATA, "experiments", "X3_distractor.jsonl")
X4 = os.path.join(J.DATA, "experiments", "X4_persuasion.jsonl")
KO = os.path.join(J.DATA, "ko", "dataset_ko_1000.jsonl")
# JA grows from 920 to 1000 rows (same 920 rows + 80 new attacks); use the newest file present. Cached calls are
# matched on uid + text md5, so switching files only calls the API for the new rows.
JA = next(p for p in (os.path.join(J.DATA, "judge_attack", f) for f in ("dataset_ja_1000.jsonl", "dataset_ja_920.jsonl"))
          if os.path.exists(p))
KO_MT = os.path.join(J.RESULTS, "02_korean_mt", "translation", "ko_to_en.jsonl")  # made by experiments/translate_ko.py

# Questions per experiment: every experiment uses Q2 and QL (CLAUDE.md); the own-definition questions run on the
# baseline documents only, in their own folder so the 01_baseline numbers stay untouched.
EXP_QUESTIONS = {"01_baseline_definitions": ("QS", "Q3", "QC")}


def label_int(r):
    return int(r.get("label_int", 1 if r.get("label") == "injection" else 0))


def spec(exp):
    """Returns (items, meta) for an experiment."""
    items, meta = [], {}
    if exp in ("01_baseline", "01_baseline_definitions"):
        for set_name, path in (("EN", EN), ("NOTINJECT", NOTINJECT)):
            for r in J.load_jsonl(path):
                items.append({"set": set_name, "uid": r["uid"], "state": r["text"]})
                meta[r["uid"]] = {"label": r.get("label", "benign"), "label_int": label_int(r), "set": set_name, "id": r.get("id"),
                                  "source": r.get("source"), "subset": r.get("subset"), "doc_type": r.get("doc_type"),
                                  "risk_level": r.get("risk_level"), "harm_type": r.get("harm_type"), "char_len": len(r["text"])}
    elif exp == "X1_register":
        for r in J.load_jsonl(X1):
            items.append({"set": "X1", "uid": r["exp_uid"], "state": r["text"]})
            meta[r["exp_uid"]] = {k: r.get(k) for k in ("label", "base_uid", "base_id", "register", "original_register", "source",
                                                         "subset", "doc_type", "risk_level", "variant_text_source", "span_len_ratio")}
            meta[r["exp_uid"]]["label_int"] = label_int(r)
    elif exp == "X2_user_task":
        for r in J.load_jsonl(X2):
            items.append({"set": "X2", "uid": r["exp_uid"], "state": {"user_task": r["user_task"], "document": r["text"]}})
            meta[r["exp_uid"]] = {k: r.get(k) for k in ("label", "base_uid", "base_id", "user_task_source", "source", "subset",
                                                         "doc_type", "risk_level")}
            meta[r["exp_uid"]]["label_int"] = label_int(r)
    elif exp == "X3_distractor":
        for r in J.load_jsonl(X3):
            items.append({"set": "X3", "uid": r["exp_uid"], "state": r["text"]})
            meta[r["exp_uid"]] = {k: r.get(k) for k in ("label", "base_uid", "base_id", "source", "doc_type", "risk_level",
                                                         "carrier_type", "carrier_source", "carrier_id", "carrier_len",
                                                         "carrier_n_requests", "inj_pair_id", "slot", "span_subset", "insert_offset")}
            meta[r["exp_uid"]]["label_int"] = label_int(r)
            meta[r["exp_uid"]]["char_len"] = len(r["text"])
    elif exp == "X4_persuasion":
        for r in J.load_jsonl(X4):
            items.append({"set": "X4", "uid": r["exp_uid"], "state": r["text"]})
            meta[r["exp_uid"]] = {k: r.get(k) for k in ("label", "base_uid", "base_id", "source", "doc_type", "risk_level",
                                                         "persuasion_type", "persuasion_pos", "template_id",
                                                         "contains_classifier_note", "insert_offset")}
            meta[r["exp_uid"]]["label_int"] = label_int(r)
    elif exp == "02_korean":
        for r in J.load_jsonl(KO):
            items.append({"set": "KO", "uid": r["uid"], "state": r["text"]})
            meta[r["uid"]] = {"label": r["label"], "label_int": label_int(r), "pair_uid": r.get("pair_uid"), "id": r.get("id"),
                              "source": r.get("source"), "subset": r.get("subset"), "doc_type": r.get("doc_type"),
                              "risk_level": r.get("risk_level"), "harm_type": r.get("harm_type"), "char_len": len(r["text"])}
    elif exp == "02_korean_mt":
        ko = {r["uid"]: r for r in J.load_jsonl(KO)}
        for t in J.load_jsonl(KO_MT):
            r = ko[t["uid"]]
            items.append({"set": "KO_MT", "uid": t["uid"], "state": t["text_en"]})
            meta[t["uid"]] = {"label": r["label"], "label_int": label_int(r), "pair_uid": r.get("pair_uid"), "id": r.get("id"),
                              "source": r.get("source"), "subset": r.get("subset"), "doc_type": r.get("doc_type"),
                              "risk_level": r.get("risk_level"), "char_len": len(t["text_en"])}
    elif exp == "03_judge_attack":
        for r in J.load_jsonl(JA):
            items.append({"set": "JA", "uid": r["uid"], "state": r["text"]})
            meta[r["uid"]] = {"label": r["label"], "label_int": label_int(r), "pair_uid": r.get("pair_uid"), "id": r.get("id"),
                              "source": r.get("source"), "subset": r.get("subset"), "doc_type": r.get("doc_type"),
                              "risk_level": r.get("risk_level"), "technique": r.get("technique"), "char_len": len(r["text"])}
    else:
        sys.exit(f"unknown experiment {exp}")
    return items, meta


def seed_baseline_q2():
    """Copy the Q2 calls already made for baseline/ (PR #10) into results/01_baseline/raw/Q2_raw.jsonl once."""
    old = os.path.join(J.REPO, "baseline", "results", "raw_responses.jsonl")
    dst = J.raw_path("01_baseline", "Q2")
    if not os.path.exists(old) or os.path.exists(dst):
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    with open(dst, "w", encoding="utf-8") as f:
        for r in J.load_jsonl(old):
            r.setdefault("run", 0)  # the first 8 trial calls predate the run field; they were run 0
            r.setdefault("retries", max(0, int(r.get("attempts", 1)) - 1))
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"seeded {dst} from baseline/results/raw_responses.jsonl")


def main():
    if sys.argv[1] == "parity":
        exp, qid = sys.argv[2], sys.argv[3]
        os.environ["TYPESAFE_API_KEY"] = J.api_key()
        from src.jev_guard import judge
        items, meta = spec(exp)
        saved = {}
        for r in J.load_jsonl(J.raw_path(exp, qid)):
            if "noul" in r:
                saved.setdefault(r["uid"], []).append(r["noul"])
        if not isinstance(J.QUESTIONS[qid], str):
            sys.exit(f"{qid} uses noul criteria, which judge() cannot send; parity check not applicable")
        for it in [i for i in items if i["uid"] in saved][:3]:
            p, ps = judge(it["state"], question=J.QUESTIONS[qid]), saved[it["uid"]]
            ok = min(ps) - 0.05 <= p <= max(ps) + 0.05
            print(f"parity {exp} {qid} {it['uid']}: saved {ps} vs judge() {p} -> {'OK' if ok else 'OUT OF RANGE'}")
        return
    exp = sys.argv[1]
    workers = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    if exp == "01_baseline":
        seed_baseline_q2()
    items, meta = spec(exp)
    stats, blocks = {}, {}
    for qid in EXP_QUESTIONS.get(exp, ("Q2", "QL")):
        stats[qid] = J.run_calls(exp, qid, items, workers=workers)
        df = J.predictions(exp, qid, meta)
        main_df = df[df["set"] == "EN"] if "set" in df.columns and (df["set"] == "EN").any() else df
        blocks[qid] = {"overall": J.metric_block(main_df), "this_invocation": stats[qid]}
        o = blocks[qid]["overall"]
        print(f"[{exp} {qid}] n={o['n']} TPR={o['TPR']} FPR={o['FPR']} AUC={o['AUC']}")
    J.write_summary(exp, blocks)


if __name__ == "__main__":
    main()
