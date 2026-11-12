"""Near-duplicate check for picks (rows checked in parallel; pass "--nopairs" as 5th arg to skip pairwise).
Usage: sim2.py <pool.jsonl> <excl.json> <WD> <rows,comma>
(1) max(char, word) difflib ratio (autojunk off, normalised) vs every excluded text and among picks (must be < 0.6);
(2) char difflib ratio < 0.8 and word 5-gram Jaccard < 0.5 vs every record in WD/_build/parts_v2/*.jsonl and
    WD/_build/ja_llmail_candidates.jsonl (brief rule)."""
import glob, json, re, sys
from difflib import SequenceMatcher
sys.stdout.reconfigure(encoding="utf-8")
pool_p, excl_p, wd, rows_s = sys.argv[1:5]
want = [int(x) for x in rows_s.split(",")]
norm = lambda t: re.sub(r"\s+", " ", t.lower()).strip()
pool = {}
for l in open(pool_p, encoding="utf-8"):
    r = json.loads(l)
    if r["row_index"] in want:
        pool[r["row_index"]] = norm(r["text"])
ex = [(i, norm(t)) for i, t in json.load(open(excl_p, encoding="utf-8"))["texts"]]


def ratio(a, b, thr):
    best = 0.0
    for x, y in ((a, b), (a.split(), b.split())):
        sm = SequenceMatcher(None, x, y, autojunk=False)
        if sm.real_quick_ratio() >= thr and sm.quick_ratio() >= thr:
            best = max(best, sm.ratio())
    return best


def grams(t, n=5):
    w = t.split()
    return {tuple(w[i:i + n]) for i in range(max(1, len(w) - n + 1))}


others = []
for p in sorted(glob.glob(wd + "/_build/parts_v2/*.jsonl")) + [wd + "/_build/ja_llmail_candidates.jsonl"]:
    for l in open(p, encoding="utf-8"):
        r = json.loads(l)
        others.append((r["id"], norm(r["text"])))
def check(w):
    t = pool[w]
    m = max(((ratio(t, s, 0.6), i) for i, s in ex), default=(0, ""))
    g = grams(t)
    jac = max(((len(g & grams(s)) / max(1, len(g | grams(s))), i) for i, s in others))
    c8 = [i for i, s in others if ratio(t, s, 0.8) >= 0.8]
    flag = m[0] >= 0.6 or jac[0] >= 0.5 or c8
    return w, bool(flag), f"{w}: max_vs_excl(>=0.6 only)={m[0]:.3f} ({m[1]})  max_5gram_jacc={jac[0]:.3f} ({jac[1]})  ratio>=0.8:{c8}" + ("  <-- FAIL" if flag else "")


if __name__ == "__main__":
  from multiprocessing import Pool
  bad = False
  with Pool(8) as mp:
    for w, flag, line in mp.imap(check, want):
        bad |= flag
        print(line, flush=True)
  for i, a in enumerate(want if len(sys.argv) <= 5 else []):
    for b in want[i + 1:]:
        r = ratio(pool[a], pool[b], 0.45)
        if r >= 0.45:
            print(f"   pair {a}~{b}: {r:.3f}" + ("  <-- NEAR" if r >= 0.6 else ""))
            bad |= r >= 0.6
  print("ALL OK" if not bad else "SOME FAIL")
