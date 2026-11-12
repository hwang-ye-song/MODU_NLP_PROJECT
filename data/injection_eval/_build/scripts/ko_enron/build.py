"""Build WD/ko_parts/enron.jsonl from the EN source and the hand-written Korean texts.
usage: python -X utf8 -I build.py <src_en.jsonl> <enron_ko.txt> <out.jsonl>
"""
import json, re, sys

src_path, ko_path, out_path = sys.argv[1:4]

BASE = ("'Subject:' marker kept in English, subject value and body translated into Korean business-email register; "
        "one-sentence-per-line structure kept (identical line count, incl. mid-abbreviation splits); "
        "names of people, companies, places, products, systems and deal/contract titles kept in Latin script; "
        "numbers, amounts, extensions, deal numbers kept verbatim")

EXTRA = {
    "enron-ben-01": "'system' -> 시스템; source typos in names kept (Arther Andersen)",
    "enron-ben-02": "extension x35926 kept",
    "enron-ben-03": "'system conditions' -> 시스템 상황; section-heading fragments run into the next sentence kept as in source; \"Notice\" kept in English",
    "enron-ben-05": "'ONLY' rendered 오직…만 (trigger-word convention); '$3-5,000' kept verbatim",
    "enron-ben-06": "numeric dates/times (4/3, 8:30 - 12:30, 3/15/02) kept verbatim, weekday abbreviations rendered as (수)/(목) etc.; month-name dates rendered in Korean order with identical values (May 13 -> 5월 13일); missing final period kept",
    "enron-ben-07": "informal classmate register kept (casual 해요체); sarcastic '(yeah, right)' -> (퍽이나)",
    "enron-ben-09": "'Sr.' / 'Mt.' line splits kept at the same points; '10/5', '12-1 PM' kept verbatim",
    "enron-ben-10": "volumes and cell references kept verbatim; 'citygate' -> 시티게이트",
    "enron-ben-11": "list of pipeline points kept verbatim except generic 'large packages' -> 대형 패키지",
    "enron-ben-12": "'September 13, 2001' rendered 2001년 9월 13일 (same values); docket number and signature line kept",
    "enron-ben-13": "'March 9, 1967' rendered 1967년 3월 9일 (same values)",
    "enron-ben-14": "'P.C.' line split kept at the same point",
    "enron-ben-16": "'execute this agreement' rendered 서명 (legal signing sense) rather than 실행",
    "enron-ben-17": "'Feb 8' rendered 2월 8일",
    "enron-ben-19": "'June 6' rendered 6월 6일",
    "enron-ben-22": "meeting-body field labels When:/Where: rendered 일시:/장소: (Korean Outlook style; not a dataset marker); timestamp rendered in Korean with identical values; '*~*~*' separator kept byte-identical; 'system' -> 시스템",
    "enron-ben-24": "'Sept 2001' rendered 2001년 9월분; deal numbers and $500.00 kept",
    "enron-ben-25": "'August 10th' rendered 8월 10일",
    "enron-ben-27": "'Boston, Mass.' line split kept at the same point",
    "enron-ben-29": "numbered-list fragments ('1.', '2.', '3.') kept on their own lines as in source",
    "enron-ben-30": "court name kept in English as a proper noun; 'You are instructed to comply' kept as an employer-to-employee directive (human-to-human); 'instruction' -> 지시; dates rendered 2월 15일 / 2002년 1월 14일; extension 5-2402 kept",
    "enron-ben-31": "list fragments and run-on name list kept exactly on the same lines; amounts ($155, $185, $84, $20) kept; 'March 19, 2001' rendered 2001년 3월 19일",
    "enron-ben-32": "'16 billion (rather than the 10 ...)' rendered in Korean units 160억 / 100억 (same values); missing final period kept",
    "enron-ben-33": "'ready for execution' rendered 체결 준비 (signing sense) rather than 실행",
    "enron-ben-34": "'ONLY' rendered 오직 (trigger-word convention); 'executed by ENA' rendered 서명; 'Pty.' line split kept; 'May 22' rendered 5월 22일",
    "enron-ben-35": "'Sept 20-22' rendered 9월 20-22일; '3 pm' rendered 오후 3시",
    "enron-ben-36": "'1.2 million b/d' rendered 120만 b/d (same value)",
    "enron-ben-37": "'Jul 1st' etc. rendered 7월 1일 etc.; missing period between two sentences on one line kept",
    "enron-ben-38": "defined terms 'Business Days' and \"the relevant Scheduled Trading Date\" kept in English (they are terms of the English GTCs); asterisk separator kept",
    "enron-ben-39": "'B.A.' line split kept at the same point; sender line 'Brent Hendry@ENRON_DEVELOPMENT' kept verbatim",
    "enron-ben-40": "dash-separated issue list kept on one line; asset/station identifiers kept verbatim",
}

# parse Korean texts
ko = {}
cur = None
buf = []
for line in open(ko_path, encoding="utf-8").read().split("\n"):
    m = re.match(r"^##### (enron-ben-\d+)$", line)
    if m:
        if cur:
            ko[cur] = "\n".join(buf).rstrip("\n")
        cur, buf = m.group(1), []
    else:
        buf.append(line)
if cur:
    ko[cur] = "\n".join(buf).rstrip("\n")

src = [json.loads(l) for l in open(src_path, encoding="utf-8") if l.strip()]
assert len(src) == len(ko) == 40, (len(src), len(ko))

out = []
for r in src:
    rid = r["id"]
    t = ko[rid]
    rec = {
        "id": rid + "-ko",
        "pair_id": rid,
        "lang": "ko",
        "label": r["label"],
        "source": r["source"],
        "subset": r["subset"],
        "text": t,
        "injected_instruction": None,
        "origin": r["origin"],
        "notes": r["notes"],
        "core": r["core"],
        "translation_notes": BASE + ("; " + EXTRA[rid] if rid in EXTRA else ""),
    }
    out.append(rec)

with open(out_path, "w", encoding="utf-8", newline="\n") as f:
    for rec in out:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
print("wrote", len(out))
