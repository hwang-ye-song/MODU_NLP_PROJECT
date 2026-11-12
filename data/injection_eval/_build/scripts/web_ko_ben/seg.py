"""Segment / assemble / validate KO translation of benign webpage records.

usage:
  python -X utf8 -I seg.py <base_dir> list <id> [<id>...]
  python -X utf8 -I seg.py <base_dir> review <id> [<id>...]
  python -X utf8 -I seg.py <base_dir> build <in_jsonl> <out_jsonl>

base_dir contains src/<id>.txt (EN text) and ko/<id>.json ({"<idx>": "<ko>" | "="}).
Only natural-language text is replaced: text nodes (outside script/style),
comment bodies, and the values of alt/title/placeholder/aria-label/value/data-*/
content attributes. Every other byte of the markup is copied unchanged.
"""
import json
import re
import sys
from html.parser import HTMLParser

TOK = re.compile(r'(<!--.*?-->|<script\b.*?</script\s*>|<style\b.*?</style\s*>|<[^>]*>)',
                 re.S | re.I)
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
        # identifier-like (ids, emails, paths) -> not prose
        return False
    return True


def segments(text):
    """Yield list of parts: ('raw', s) or ('seg', kind, lead, core, trail)."""
    parts = []
    pos = 0
    for m in TOK.finditer(text):
        if m.start() > pos:
            parts.extend(text_parts(text[pos:m.start()], 'text'))
        tok = m.group(0)
        low = tok.lower()
        if low.startswith('<!--'):
            body = tok[4:-3]
            parts.append(('raw', '<!--'))
            parts.extend(text_parts(body, 'comment'))
            parts.append(('raw', '-->'))
        elif low.startswith('<script') or low.startswith('<style') or low.startswith('<!'):
            parts.append(('raw', tok))
        else:
            p = 0
            for am in ATTR.finditer(tok):
                val = am.group(3) if am.group(3) is not None else am.group(4)
                q = am.group(2)[0]
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


def text_parts(s, kind):
    core = s.strip()
    if not core or not LETTER.search(core):
        return [('raw', s)]
    i = s.find(core)
    return [('seg', kind, s[:i], core, s[i + len(core):])]


def uniq_segs(parts):
    order = []
    seen = {}
    for p in parts:
        if p[0] == 'seg' and p[3] not in seen:
            seen[p[3]] = len(order)
            order.append((p[1], p[3]))
    return order, seen


def load_src(base, rid):
    return open(f'{base}/src/{rid}.txt', encoding='utf-8', newline='').read()


def assemble(base, rid):
    src = load_src(base, rid)
    parts = segments(src)
    order, seen = uniq_segs(parts)
    tr = json.load(open(f'{base}/ko/{rid}.json', encoding='utf-8'))
    missing = [str(i) for i in range(len(order)) if str(i) not in tr]
    extra = [k for k in tr if not (k.isdigit() and int(k) < len(order))]
    if missing or extra:
        raise SystemExit(f'{rid}: missing {missing} extra {extra}')
    try:
        gl = json.load(open(f'{base}/glossary.json', encoding='utf-8'))
    except FileNotFoundError:
        gl = {}
    out = []
    kept = []
    for p in parts:
        if p[0] == 'raw':
            out.append(p[1])
        else:
            k = str(seen[p[3]])
            v = tr[k]
            if p[3] in gl:
                if v != gl[p[3]]:
                    OVERRIDES.append((rid, p[3], v, gl[p[3]]))
                v = gl[p[3]]
            if v == '=':
                v = p[3]
                kept.append(p[3])
            out.append(p[2] + v + p[4])
    return src, ''.join(out), kept


OVERRIDES = []


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


def raw_tags(t):
    return re.findall(r'</?[A-Za-z][^>]*>', t)


def validate(src, ko):
    errs = []
    if tagseq(src) != tagseq(ko):
        errs.append('tagseq differs')
    # tag names + attribute names from raw regex
    a = [re.sub(r'="[^"]*"', '=""', x) for x in raw_tags(src)]
    b = [re.sub(r'="[^"]*"', '=""', x) for x in raw_tags(ko)]
    if a != b:
        errs.append('raw tag skeleton differs')
    # all URLs / emails preserved
    for pat in (r'https?://[A-Za-z0-9._~:/?#\[\]@!$&*+,;=%-]+',
                r'[A-Za-z0-9.+_-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+',
                r'(?<![A-Za-z0-9@./-])[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io)(?:/[A-Za-z0-9._/-]*)?'):
        sa = sorted(re.findall(pat, src))
        sb = sorted(re.findall(pat, ko))
        if sa != sb:
            errs.append(f'mismatch {pat}: {set(sa) ^ set(sb)}')
    if src.count('&lt;') != ko.count('&lt;') or src.count('&gt;') != ko.count('&gt;'):
        errs.append('entity count differs')
    # escaped markup shown as text must also be preserved
    esc = re.compile(r'&lt;/?[A-Za-z!][^&]*?&gt;|&lt;[A-Za-z][^&<]*')
    if [x for x in esc.findall(src) if not x.startswith('&lt;!--')] != \
            [x for x in esc.findall(ko) if not x.startswith('&lt;!--')]:
        errs.append('escaped markup differs')
    if sorted(re.findall(r'&#?\w+;', src)) != sorted(re.findall(r'&#?\w+;', ko)):
        errs.append('entities differ')
    return errs


def main():
    base = sys.argv[1]
    cmd = sys.argv[2]
    if cmd == 'list':
        for rid in sys.argv[3:]:
            order, _ = uniq_segs(segments(load_src(base, rid)))
            print(f'##### {rid}')
            for i, (kind, s) in enumerate(order):
                print(f'{i}\t{kind}\t{json.dumps(s, ensure_ascii=False)}')
    elif cmd == 'review':
        for rid in sys.argv[3:]:
            src, ko, kept = assemble(base, rid)
            print(f'##### {rid} errs={validate(src, ko)} kept={kept} glossary_overrides={[(o[2], o[3]) for o in OVERRIDES if o[0] == rid]}')
            print(ko)
    elif cmd == 'build':
        inp, outp = sys.argv[3], sys.argv[4]
        recs = [json.loads(l) for l in open(inp, encoding='utf-8')]
        ben = [r for r in recs if r['label'] == 'benign']
        notes = json.load(open(f'{base}/notes.json', encoding='utf-8'))
        out = []
        bad = 0
        for r in ben:
            src, ko, kept = assemble(base, r['id'])
            assert src == r['text'], r['id']
            errs = validate(src, ko)
            if errs:
                bad += 1
                print(r['id'], errs)
            hangul = len(re.findall(r'[가-힣]', ko))
            seg_en = [s for s in kept if re.search(r'[A-Za-z]{3,}\s+[A-Za-z]{3,}\s+[A-Za-z]{3,}', s)]
            print(f"{r['id']} len {len(src)}->{len(ko)} hangul={hangul} kept={len(kept)} kept_prose={seg_en}")
            o = {'id': r['id'] + '-ko', 'pair_id': r['id'], 'lang': 'ko', 'label': r['label'],
                 'source': r['source'], 'subset': r['subset'], 'text': ko,
                 'injected_instruction': None, 'origin': r['origin'], 'notes': r['notes'],
                 'core': r['core'], 'translation_notes': notes[r['id']]}
            out.append(o)
        with open(outp, 'w', encoding='utf-8', newline='\n') as f:
            for o in out:
                f.write(json.dumps(o, ensure_ascii=False) + '\n')
        print(f'wrote {len(out)} records, validation failures: {bad}')


if __name__ == '__main__':
    main()
