"""Flag picks whose text may ask to send inbox content / sensitive data (risk 4 candidates).

Usage: python -X utf8 -I exfil_scan.py <review.jsonl> <n>
"""
import json
import re
import sys

sys.stdout.reconfigure(encoding="utf-8")
p, n = sys.argv[1], int(sys.argv[2])
RX = re.compile(
    r"(send|forward|email|mail|share|include|attach|copy|relay|deliver|transmit)[^.\n]{0,80}"
    r"(summary|summaries|summarized content|contents? of|all (the )?e-?mails|previous e-?mails|other e-?mails?|"
    r"inbox|system prompt|password|credential|api[ _]?name|api key|secret|conversation|history|"
    r"the e-?mails? (above|below)|received (e-?)?mails)", re.I)
for k, l in enumerate(open(p, encoding="utf-8"), 1):
    if k > n:
        break
    r = json.loads(l)
    t = r["text"]
    hits = [t[max(0, m.start() - 60):m.end() + 60].replace("\n", " ") for m in RX.finditer(t)]
    if hits:
        print(f"#{k} r{r['origin']['row_index']} risk={r['risk_level']}")
        for h in hits[:3]:
            print("    ", h[:260])
