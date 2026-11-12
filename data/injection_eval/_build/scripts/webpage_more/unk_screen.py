"""List unclassified yes rows (no known template) that carry strong AI-directed cues, with context."""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from common import english_ok, ARTIFACT, site_of
from templates import classify
bs = json.load(open(sys.argv[1], encoding="utf-8"))
used = {json.loads(l)["origin"].get("row_index") for l in open(sys.argv[2], encoding="utf-8")}
lo, hi = int(sys.argv[3]), int(sys.argv[4])
STRONG = re.compile(r"ignore (all )?(previous|prior|above)|previous instructions|disregard (all |any )?(previous|prior)|system prompt|system instructions|\bAI (assistant|agent|model|system)|language model|you are now|override|your (new )?(role|directive|primary directive|task)|conversation (history|data|logs)|if you are an? (AI|assistant|automated)|automated (assistant|agent)|assistant processing", re.I)
weak_n = 0
for x in bs:
    h = x["content"]
    if x["label"] != "yes" or not (lo < len(h) <= hi) or x["row_index"] in used or not english_ok(h) or ARTIFACT.search(h):
        continue
    hits, weak = classify(h)
    if hits:
        continue
    ms = list(STRONG.finditer(h))
    if not ms:
        weak_n += 1
        continue
    m = ms[0]
    s = re.sub(r"\s+", " ", h[max(0, m.start() - 250):m.end() + 700])
    print("##", x["row_index"], len(h), site_of(h), ",".join(weak), "||", s)
print("no-strong-cue rows:", weak_n)
