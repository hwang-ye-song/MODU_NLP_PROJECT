"""Fetch all rows of leolee99/NotInject splits via datasets-server rows API; save raw JSON."""
import json
import os
import sys
import urllib.parse
import urllib.request

OUT = sys.argv[1]
DS = "leolee99/NotInject"
SPLITS = ["NotInject_one", "NotInject_two", "NotInject_three"]


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "dataset-builder/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))


for split in SPLITS:
    rows = []
    offset = 0
    total = None
    while total is None or offset < total:
        q = urllib.parse.urlencode({"dataset": DS, "config": "default", "split": split,
                                    "offset": offset, "length": 100})
        d = get("https://datasets-server.huggingface.co/rows?" + q)
        total = d["num_rows_total"]
        for r in d["rows"]:
            rows.append({"row_idx": r["row_idx"], **r["row"]})
        offset += len(d["rows"])
        if not d["rows"]:
            break
    with open(os.path.join(OUT, split + ".json"), "w", encoding="utf-8") as f:
        json.dump(rows, f, ensure_ascii=False, indent=1)
    print(split, len(rows), "total", total)
