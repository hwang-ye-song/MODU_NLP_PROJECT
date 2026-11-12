"""Print the select_p1 cache signature for a list of existing files. Usage: sig.py <file> [...]"""
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path

ZW = re.compile("[​-‏⁠-⁤﻿­᠎͏]")
COMB = re.compile("[̀-ͯ҉⃐-⃿]")


def norm_sim(t):
    t = "".join(chr(ord(c) - 0xE0000) if 0xE0020 <= ord(c) <= 0xE007E else c for c in t)
    t = unicodedata.normalize("NFKC", ZW.sub("", t))
    t = COMB.sub("", unicodedata.normalize("NFKD", t))
    return re.sub(r"\s+", " ", t.lower()).strip()


ex = []
for p in sys.argv[1:]:
    for l in Path(p).read_text(encoding="utf-8").splitlines():
        if l.strip():
            ex.append(norm_sim(json.loads(l)["text"]))
print(hashlib.sha1(("v3-contain-jacc|||" + "|||".join(sorted(ex))).encode("utf-8")).hexdigest()[:16], len(ex))
