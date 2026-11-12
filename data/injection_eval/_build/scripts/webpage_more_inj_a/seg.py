"""Segment / assemble / validate KO translation of BrowseSafe injection pages (web-inj-31..50).

Adapted from WD/_build/scripts/web_ko_ben/seg.py (benign half) and webpage_inj_ko_v2/build.py.

usage:
  python -X utf8 -I seg.py list                      # unique segments, glossary hits marked
  python -X utf8 -I seg.py review <id> [...]         # print assembled KO page + validation
  python -X utf8 -I seg.py build <in_jsonl> <out_jsonl>

Only natural-language text is replaced: text nodes (outside script/style), comment bodies,
text inside HTML-escaped markup (escaped tags themselves kept), and the values of
alt/title/placeholder/aria-label/value/data-*/content attributes when they are prose.
Every other byte of the markup is copied unchanged.
Translations: tr_mine.json {en_segment: ko} + glossary tr_data.json (segments + payloads).
"""
import collections
import json
import os
import re
import sys
from html.parser import HTMLParser

HERE = os.path.dirname(os.path.abspath(__file__))
GLOSS = '<DATASET_ROOT>/_build/scripts/webpage_inj_ko_v2/tr_data.json'
IDS = ['web-inj-%02d' % i for i in range(31, 51)]

TOK = re.compile(r'(<!--.*?-->|<script\b.*?</script\s*>|<style\b.*?</style\s*>|<[^>]*>'
                 r'|&lt;!--|--&gt;|&lt;/?[A-Za-z][^<>]*?&gt;)', re.S | re.I)
ATTR = re.compile(r'(\s(?:alt|title|placeholder|aria-label|value|data-[\w-]+|content)=)'
                  r'("([^"]*)"|\'([^\']*)\')', re.I)
LETTER = re.compile(r'[A-Za-z]')


def attr_is_prose(v):
    if not LETTER.search(v):
        return False
    if '://' in v and ' ' not in v.strip():
        return False
    if re.search(r'[;{}=]', v):
        return False
    if re.fullmatch(r'[\w.\-/#@:]+', v) and not re.search(r'[A-Z][a-z]', v):
        return False
    return True


def text_parts(s, kind):
    core = s.strip()
    if not core or not LETTER.search(core):
        return [('raw', s)]
    i = s.find(core)
    return [('seg', kind, s[:i], core, s[i + len(core):])]


def segments(text):
    parts = []
    pos = 0
    for m in TOK.finditer(text):
        if m.start() > pos:
            parts.extend(text_parts(text[pos:m.start()], 'text'))
        tok = m.group(0)
        low = tok.lower()
        if low.startswith('<!--'):
            parts.append(('raw', '<!--'))
            parts.extend(text_parts(tok[4:-3], 'comment'))
            parts.append(('raw', '-->'))
        elif low.startswith('<script') or low.startswith('<style') or low.startswith('<!') or tok.startswith('&'):
            parts.append(('raw', tok))
        elif tok == '--&gt;':
            parts.append(('raw', tok))
        else:
            p = 0
            for am in ATTR.finditer(tok):
                val = am.group(3) if am.group(3) is not None else am.group(4)
                vstart = am.start(2) + 1
                if attr_is_prose(val):
                    parts.append(('raw', tok[p:vstart]))
                    parts.extend(text_parts(val, 'attr:' + am.group(1).strip().rstrip('=')))
                    p = vstart + len(val)
            parts.append(('raw', tok[p:]))
        pos = m.end()
    if pos < len(text):
        parts.extend(text_parts(text[pos:], 'text'))
    return parts


def load_src(rid):
    return open(f'{HERE}/src/{rid}.html', encoding='utf-8', newline='').read()


def load_tr():
    g = json.load(open(GLOSS, encoding='utf-8'))
    pay = g['payloads']
    seg = {k: re.sub(r'\{P:(.*?)\}', lambda m: pay[m.group(1)], v, flags=re.S) for k, v in g['segments'].items()}
    gl = dict(seg)
    gl.update(pay)
    mine = json.load(open(f'{HERE}/tr_mine.json', encoding='utf-8')) if os.path.exists(f'{HERE}/tr_mine.json') else {}
    return gl, mine


def assemble(rid, gl, mine, missing):
    src = load_src(rid)
    out = []
    for p in segments(src):
        if p[0] == 'raw':
            out.append(p[1])
            continue
        core = p[3]
        if core in gl:
            v = gl[core]
            if core in mine and mine[core] != v:
                missing.append(f'{rid}: tr_mine overrides glossary for {core!r} (glossary wins)')
        elif core in mine:
            v = mine[core]
            if v == '=':
                v = core
        else:
            missing.append(f'{rid}: no translation for {core!r}')
            v = core
        out.append(p[2] + v + p[4])
    return src, ''.join(out)


class TagSeq(HTMLParser):
    SKIP = {'alt', 'title', 'placeholder', 'aria-label', 'value', 'content'}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.seq = []

    def _attrs(self, attrs):
        return tuple((k, None if (k in self.SKIP or k.startswith('data-')) else v) for k, v in attrs)

    def handle_starttag(self, tag, attrs):
        self.seq.append(('S', tag, self._attrs(attrs)))

    def handle_startendtag(self, tag, attrs):
        self.seq.append(('SE', tag, self._attrs(attrs)))

    def handle_endtag(self, tag):
        self.seq.append(('E', tag))

    def handle_comment(self, data):
        self.seq.append(('C',))

    def handle_decl(self, decl):
        self.seq.append(('D', decl))


def tagseq(t):
    p = TagSeq()
    p.feed(t)
    p.close()
    return p.seq


def skeleton(t):
    """every markup token with prose attribute values blanked; escaped tags kept whole."""
    out = []
    for p in segments(t):
        pass
    toks = [m.group(0) for m in TOK.finditer(t)]
    res = []
    for tok in toks:
        if tok.startswith('<!--'):
            res.append('<!--C-->')
            continue
        if tok.startswith('<') and not tok.lower().startswith(('<script', '<style', '<!')):
            def blank(am):
                val = am.group(3) if am.group(3) is not None else am.group(4)
                return am.group(1) + ('"P"' if attr_is_prose(val) else am.group(2))
            tok = ATTR.sub(blank, tok)
        res.append(tok)
    return res


EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]+')
URL = re.compile(r'https?://[A-Za-z0-9._~:/?#\[\]@!$&*+,;=%-]+')
DOM = re.compile(r'(?<![A-Za-z0-9@./-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|so|ai|gg)(?:/[A-Za-z0-9._/-]*)?')


def validate(src, ko):
    errs = []
    if tagseq(src) != tagseq(ko):
        errs.append('tagseq differs')
    if skeleton(src) != skeleton(ko):
        a, b = skeleton(src), skeleton(ko)
        diff = [(x, y) for x, y in zip(a, b) if x != y][:2]
        errs.append(f'markup skeleton differs {len(a)} vs {len(b)} {diff}')
    for pat in (URL, EMAIL, DOM):
        sa = collections.Counter(x.rstrip('.,') for x in pat.findall(src))
        sb = collections.Counter(x.rstrip('.,') for x in pat.findall(ko))
        if sa != sb:
            errs.append(f'mismatch {pat.pattern[:20]}: {(sa - sb)} vs {(sb - sa)}')
    if src.count('&lt;') != ko.count('&lt;') or src.count('&gt;') != ko.count('&gt;'):
        errs.append('entity count differs')
    if sorted(re.findall(r'&#?\w+;', src)) != sorted(re.findall(r'&#?\w+;', ko)):
        errs.append('entities differ')
    if src.count('\n') != ko.count('\n'):
        errs.append(f'newline count differs {src.count(chr(10))} vs {ko.count(chr(10))}')
    return errs


def main():
    cmd = sys.argv[1]
    gl, mine = load_tr()
    if cmd == 'list':
        seen = collections.OrderedDict()
        for rid in IDS:
            for p in segments(load_src(rid)):
                if p[0] == 'seg':
                    seen.setdefault(p[3], []).append((rid, p[1]))
        for core, occ in seen.items():
            if core in gl:
                st = 'GLOSS'
            elif core in mine:
                st = 'MINE'
            else:
                st = 'TODO'
            if len(sys.argv) > 2 and st not in sys.argv[2:]:
                continue
            print(f"{st}\t{len(occ)}\t{occ[0][0]}\t{occ[0][1]}\t{json.dumps(core, ensure_ascii=False)}")
    elif cmd == 'review':
        for rid in sys.argv[2:]:
            missing = []
            src, ko = assemble(rid, gl, mine, missing)
            print(f'##### {rid} errs={validate(src, ko)} missing={missing}')
            print(ko)
    elif cmd == 'build':
        inp, outp = sys.argv[2], sys.argv[3]
        recs = {json.loads(l)['id']: json.loads(l) for l in open(inp, encoding='utf-8')}
        inj_ko = json.load(open(f'{HERE}/inj_ko.json', encoding='utf-8'))
        notes = json.load(open(f'{HERE}/notes.json', encoding='utf-8'))
        out = []
        bad = 0
        for rid in IDS:
            r = recs[rid]
            missing = []
            src, ko = assemble(rid, gl, mine, missing)
            assert src == r['text'], rid
            errs = validate(src, ko) + missing
            ki = inj_ko[rid]
            if ki not in ko:
                errs.append('injected_instruction not substring')
            if errs:
                bad += 1
                print(rid, errs)
            o = collections.OrderedDict()
            o['id'] = rid + '-ko'
            o['pair_id'] = rid
            o['lang'] = 'ko'
            for k in ('label', 'source', 'subset', 'doc_type'):
                o[k] = r[k]
            o['text'] = ko
            o['injected_instruction'] = ki
            o['origin'] = r['origin']
            o['notes'] = r['notes']
            o['core'] = r['core']
            o['translation_notes'] = notes[rid]
            out.append(o)
            print(f"{rid} len {len(src)}->{len(ko)} hangul={len(re.findall(r'[가-힣]', ko))}")
        with open(outp, 'w', encoding='utf-8', newline='\n') as f:
            for o in out:
                f.write(json.dumps(o, ensure_ascii=False) + '\n')
        print(f'wrote {len(out)} records, failures: {bad}')


if __name__ == '__main__':
    main()
