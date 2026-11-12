import json, statistics as st, collections, sys
R = [json.loads(l) for l in open(sys.argv[1], encoding="utf-8")]
d = collections.defaultdict(list)
for r in R:
    d[(r["subset"], r["label"])].append(len(r["text"]))
for k in sorted(d):
    print(k, len(d[k]), st.median(d[k]), sorted(d[k]))
inj = [len(r["text"]) for r in R if r["label"] == "injection"]
ben = [len(r["text"]) for r in R if r["label"] == "benign"]
print("n", len(inj), len(ben), "medians", st.median(inj), st.median(ben),
      "AUC", round(sum((a > b) + 0.5 * (a == b) for a in inj for b in ben) / len(inj) / len(ben), 3))
print("doc_type", sorted(collections.Counter((r["doc_type"], r["label"]) for r in R).items()))
