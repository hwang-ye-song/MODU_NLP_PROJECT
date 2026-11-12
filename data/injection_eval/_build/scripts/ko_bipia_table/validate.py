# Validate KO BIPIA table output against the EN source.
# Usage: python -X utf8 -I validate.py <en bipia.jsonl> <ko out jsonl> <core_inj ko jsonl>
import json, re, sys, unicodedata
from collections import Counter

EN, KO, CORE = sys.argv[1:4]
en = {}
for l in open(EN, encoding='utf-8'):
    r = json.loads(l)
    if r.get('core') is False and r.get('subset') == 'table':
        en[r['id']] = r
ko = [json.loads(l) for l in open(KO, encoding='utf-8')]  # raises on invalid JSON
core_keys = list(json.loads(open(CORE, encoding='utf-8').readline()).keys())
errs = []


def dw(s):
    return sum(2 if unicodedata.east_asian_width(ch) in ('W', 'F') else 1 for ch in s)


def strip_inj(text, inj):
    if inj is None:
        return text
    if ('\n' + inj + '\n') in text:          # middle
        return text.replace('\n' + inj + '\n', '', 1)
    if text.startswith(inj + '\n'):           # start
        return text[len(inj) + 1:]
    assert text.endswith('\n' + inj)          # end
    return text[:-(len(inj) + 1)]


assert len(ko) == len(en) == 43, (len(ko), len(en))
ids = [r['id'] for r in ko]
if len(set(ids)) != len(ids):
    errs.append('duplicate ids')
if [r['pair_id'] for r in ko] != list(en):
    errs.append('pair order mismatch')
print('labels:', Counter(r['label'] for r in ko))
for r in ko:
    e = en[r['pair_id']]
    if list(r.keys()) != core_keys:
        errs.append((r['id'], 'key order', list(r.keys())))
    if r['id'] != e['id'] + '-ko' or r['lang'] != 'ko':
        errs.append((r['id'], 'id/lang'))
    for k in ('label', 'source', 'subset', 'origin', 'notes', 'core'):
        if r[k] != e[k]:
            errs.append((r['id'], 'field changed', k))
    inj = r['injected_instruction']
    if (inj is None) != (e['injected_instruction'] is None):
        errs.append((r['id'], 'inj null mismatch'))
    if inj is not None:
        if r['text'].count(inj) != 1:
            errs.append((r['id'], 'inj not unique substring'))
        if re.search('[A-Za-z]{3,}', re.sub(r'Brand A|iPhone|AntiV|Base16', '', inj)):
            errs.append((r['id'], 'english left in inj', inj))
        # same position
        pos = e['origin']['position']
        t = r['text']
        okpos = (pos == 'start' and t.startswith(inj + '\n')) or (pos == 'end' and t.endswith('\n' + inj)) or \
                (pos == 'middle' and ('\n' + inj + '\n') in t and not t.startswith(inj) and not t.endswith(inj))
        if not okpos:
            errs.append((r['id'], 'position', pos))
    # table structure
    kt = strip_inj(r['text'], inj)
    et = strip_inj(e['text'], e['injected_instruction'])
    kl, el = kt.split('\n'), et.split('\n')
    if len(kl) != len(el) or kl[-1] != '' or el[-1] != '':
        errs.append((r['id'], 'line count', len(kl), len(el)))
        continue
    widths = set()
    for a, b in zip(kl[:-1], el[:-1]):
        if not (a.startswith('| ') and a.endswith(' |')):
            errs.append((r['id'], 'row delim', a[:40]))
        if a.count('|') != b.count('|'):
            errs.append((r['id'], 'cell count', a[:40]))
        widths.add(dw(a))
        # pipe columns aligned
    pipe_cols = set()
    for a in kl[:-1]:
        cols, x = [], 0
        for ch in a:
            if ch == '|':
                cols.append(x)
            x += dw(ch)
        pipe_cols.add(tuple(cols))
    if len(pipe_cols) != 1:
        errs.append((r['id'], 'pipes not aligned'))
    # numbers preserved (EN digit runs must be a sub-multiset of KO digit runs)
    en_nums = Counter(re.findall(r'\d+', et))
    ko_nums = Counter(re.findall(r'\d+', kt))
    missing = en_nums - ko_nums
    if missing:
        errs.append((r['id'], 'numbers missing', dict(missing)))
    extra = ko_nums - en_nums
    if any(int(k) > 12 for k in extra):
        errs.append((r['id'], 'unexpected extra numbers', dict(extra)))
    hangul = sum(1 for ch in r['text'] if '가' <= ch <= '힣')
    if hangul < 10:
        errs.append((r['id'], 'too little hangul', hangul))

print('records:', len(ko))
print('errors:', len(errs))
for x in errs:
    print(' ', x)
