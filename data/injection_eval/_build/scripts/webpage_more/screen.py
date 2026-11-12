"""Print screening view of candidate rows: label, max length, excluding rows already used."""
import json, re, sys
sys.path.insert(0, __import__("os").path.dirname(__file__))
from common import english_ok, ARTIFACT, site_of
bs = json.load(open(sys.argv[1], encoding="utf-8"))
used = {json.loads(l)["origin"].get("row_index") for l in open(sys.argv[2], encoding="utf-8")}
lab, maxlen = sys.argv[3], int(sys.argv[4])
pat = re.compile(r"(ignore|disregard|\bAI\b|assistant|\bagent\b|system (prompt|instruction|message)|you are now|override|admin mode|developer mode|previous (task|instruction)|prior (task|instruction)|\bTODO\b|important message|language model|instructions|bypass|exfiltrat|forward (all|the|sensitive|user)|reveal|display your|\byour (task|instructions|configuration)|hypothetical|in a scenario|pretend|roleplay|act as|new task|before (you|continuing|proceeding))", re.I)
n = 0
for x in bs:
    h = x["content"]
    if x["label"] != lab or len(h) > maxlen or x["row_index"] in used:
        continue
    flags = ("EN" if english_ok(h) else "NONEN") + ("" if not ARTIFACT.search(h) else "+ART")
    hits = list(pat.finditer(h))
    n += 1
    segs = [h[max(0, m.start() - 100):m.end() + 140].replace("\n", " ") for m in hits[:3]]
    print("##", x["row_index"], len(h), flags, site_of(h), "||", " ... ".join(segs)[:600])
print("count", n)
