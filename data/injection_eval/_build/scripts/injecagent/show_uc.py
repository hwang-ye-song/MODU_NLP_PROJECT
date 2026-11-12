import json, sys
for i, l in enumerate(open(sys.argv[1] + "/user_cases.jsonl", encoding="utf-8")):
    u = json.loads(l); print(i, u["User Tool"], "|", u["User Instruction"], "|", u["Tool Parameters"])
