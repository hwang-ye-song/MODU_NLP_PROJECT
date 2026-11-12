"""Screen yes rows in a length window: print AI-cue snippets from the full HTML (incl. attributes/comments)."""
import json, re, sys, os
sys.path.insert(0, os.path.dirname(__file__))
from common import english_ok, ARTIFACT, site_of
bs = json.load(open(sys.argv[1], encoding="utf-8"))
used = {json.loads(l)["origin"].get("row_index") for l in open(sys.argv[2], encoding="utf-8")}
lab, lo, hi = sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
pat = re.compile(r"(ignore|disregard|\bAI\b|assistant|\bagents?\b|system (prompt|instruction|message|notice|override)|you are now|override|admin mode|developer mode|(previous|prior|above) (task|instruction|command|direction)|\bTODO\b|language model|your (operational|guidelines|instructions|configuration|system)|bypass|exfiltrat|forward (all|the|sensitive|user|transaction|any)|send (all|the|it|user|confidential|your)|transmit|in a scenario|hypothetical|pretend|role ?play|act as|new (task|instruction|directive)|you should|you must|archive conversations|all correspondence|transaction (logs|details)|sensitive reports|share private|collecting their)", re.I)
n = 0
for x in bs:
    h = x["content"]
    if x["label"] != lab or not (lo < len(h) <= hi) or x["row_index"] in used:
        continue
    if not english_ok(h) or ARTIFACT.search(h):
        continue
    hits = list(pat.finditer(h))
    n += 1
    seen, segs = [], []
    for m in hits:
        if any(abs(m.start() - s) < 250 for s in seen):
            continue
        seen.append(m.start())
        segs.append(re.sub(r"\s+", " ", h[max(0, m.start() - 120):m.end() + 160]))
        if len(segs) == 3:
            break
    print("##", x["row_index"], len(h), site_of(h), "||", " ... ".join(segs)[:700])
print("count", n)
