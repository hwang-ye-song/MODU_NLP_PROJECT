import json, sys, re, base64
sys.stdout.reconfigure(encoding="utf-8")
a, b = int(sys.argv[2]), int(sys.argv[3])
for l in open(sys.argv[1], encoding="utf-8"):
    r = json.loads(l)
    if a <= r["_s"] < b:
        print(f"===== S{r['_s']} row{r['row_index']} {r['level']} {r['detector']} sub{r['subrank']} team{r['team_id'][:6]} len{r['len']}")
        print(r["text"])
        for m in re.finditer(r"[A-Za-z0-9+/]{20,}={0,2}", r["text"]):
            try: print("  [b64]", base64.b64decode(m.group(0) + "=" * (-len(m.group(0)) % 4)).decode("utf-8")[:400])
            except Exception: pass
