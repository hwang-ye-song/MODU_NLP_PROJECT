"""Build KO translations of web-ben-51..70 (BrowseSafe raw HTML, benign).
usage: python -X utf8 -I build.py <webpage_more.jsonl> <tr_data.json> <maps_dir> <out.jsonl>
maps_dir holds map_*.json files: {"<rec id>": {"map": {en: ko}, "keep": [..], "notes": ".."}}
"""
import json, re, sys, os, collections, glob
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from common import tokens, ATTR, LATIN, esc_tokens, ESC

src_path, tr_path, maps_dir, out_path = sys.argv[1:5]
IDS = [f'web-ben-{n}' for n in range(51, 71)]
TRANS_ATTRS = {'title', 'alt', 'placeholder', 'aria-label'}


def col(s):
    return ' '.join(s.split())


TR = json.load(open(tr_path, encoding='utf-8'))
GLOSS = {col(k): v for k, v in TR['segments'].items() if '{P:' not in v}
MAPS = {}
for fp in sorted(glob.glob(os.path.join(maps_dir, 'map_*.json'))):
    for rid, d in json.load(open(fp, encoding='utf-8')).items():
        MAPS[rid] = d

URLISH = re.compile(r'^(\S*[.@/]\S*|\||•|©|-)$')
problems = []
used_gloss = collections.Counter()


def url_like(s):
    return all(URLISH.match(w) for w in s.split())


def make_tr(rid):
    m = {col(k): v for k, v in MAPS.get(rid, {}).get('map', {}).items()}
    keep = {col(k) for k in MAPS.get(rid, {}).get('keep', [])}
    used = collections.Counter()

    def tr(s, where):
        k = col(s)
        if not k:
            return s
        if k in m:
            used[k] += 1
            return m[k]
        if k in GLOSS:
            used_gloss[k] += 1
            return GLOSS[k]
        if k in keep or url_like(k) or not re.search(r'[A-Za-z]', k) or k.startswith('{"'):
            return s
        problems.append(f'{rid}: no translation for {where} {k[:120]!r}')
        return s
    return tr, m, used


def keep_ws(p, new):
    lead = p[:len(p) - len(p.lstrip())]
    trail = p[len(p.rstrip()):]
    return lead + new + trail


def tr_tag(tag, tr):
    def rep(mm):
        name = mm.group(2)
        val = mm.group(5) if mm.group(5) is not None else mm.group(6)
        if name.lower() in TRANS_ATTRS and val and LATIN.search(val):
            q = '"' if mm.group(5) is not None else "'"
            new = tr(val, f'attr {name}')
            if q in new:
                problems.append(f'quote char inside translated attr {name}')
            return mm.group(1) + name + '=' + q + new + q
        return mm.group(0)
    return ATTR.sub(rep, tag)


def mask_tag(tag):
    def rep(mm):
        if mm.group(2).lower() in TRANS_ATTRS:
            return mm.group(1) + mm.group(2) + '=""'
        return mm.group(0)
    return ATTR.sub(rep, tag)


def translate(text, rid):
    tr, m, used = make_tr(rid)
    out = []
    for kind, p in tokens(text):
        if kind == 'tag':
            out.append(tr_tag(p, tr))
        elif kind == 'comment':
            inner = p[4:-3]
            if inner.strip() and LATIN.search(inner):
                out.append('<!--' + keep_ws(inner, tr(inner.strip(), 'comment')) + '-->')
            else:
                out.append(p)
        elif kind == 'code':
            if re.search(r'/\*(?:(?!\*/).)*[A-Za-z]{3,}', p, re.S):
                problems.append(f'{rid}: prose comment inside script/style left untouched')
            out.append(p)
        else:  # text
            if '&lt;' in p:
                buf = []
                for k2, q in esc_tokens(p):
                    if k2 == 'text':
                        buf.append(keep_ws(q, tr(q.strip(), 'esc-text')) if q.strip() else q)
                    elif k2 == 'ecomment':
                        inner = q[7:-6]
                        buf.append('&lt;!--' + keep_ws(inner, tr(inner.strip(), 'esc-comment')) + '--&gt;' if LATIN.search(inner) else q)
                    else:
                        buf.append(tr_tag(q, tr))
                out.append(''.join(buf))
            elif '/*' in p and '*/' in p:  # CSS declarations as text: translate only the /* */ prose
                out.append(re.sub(r'/\*(.*?)\*/', lambda mm: '/*' + keep_ws(mm.group(1), tr(mm.group(1).strip(), 'css-comment')) + '*/', p, flags=re.S))
            elif p.strip():
                out.append(keep_ws(p, tr(p.strip(), 'text')))
            else:
                out.append(p)
    for k in m:
        if k not in used:
            problems.append(f'{rid}: unused map entry {k[:80]!r}')
    return ''.join(out)


def tag_seq(t):
    return [mask_tag(p) for k, p in tokens(t) if k == 'tag']


def esc_seq(t):
    return [mask_tag(x) for x in ESC.findall(t) if not x.startswith('&lt;!--')]


def code_seq(t):
    return [p for k, p in tokens(t) if k == 'code']


def css_parts(t):
    """For text nodes that are CSS declarations with a trailing /* */ comment: the CSS before the comment."""
    return [p.split('/*')[0] for k, p in tokens(t) if k == 'text' and '/*' in p]


EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]+')
URL = re.compile(r'(?:https?://|www\.)[A-Za-z0-9._~:/?#\[\]@!$&\'()*+,;=%-]+')
DOMAINPATH = re.compile(r'\b[a-z0-9.-]+\.(?:com|org|io|app|gg|so|net|ms)(?:/[A-Za-z0-9._~/?#=&%-]*)?')

rows = {json.loads(l)['id']: json.loads(l) for l in open(src_path, encoding='utf-8')}
outs = []
for rid in IDS:
    r = rows[rid]
    en = r['text']
    ko = translate(en, rid)
    if [x for x in re.findall(r'<\s*/?\s*([A-Za-z!][\w-]*)', en)] != re.findall(r'<\s*/?\s*([A-Za-z!][\w-]*)', ko):
        problems.append(f'{rid}: tag name sequence differs')
    if tag_seq(en) != tag_seq(ko):
        problems.append(f'{rid}: full tag strings differ (beyond prose attrs)')
    if esc_seq(en) != esc_seq(ko):
        problems.append(f'{rid}: escaped tag strings differ')
    if code_seq(en) != code_seq(ko):
        problems.append(f'{rid}: script/style differs')
    if css_parts(en) != css_parts(ko):
        problems.append(f'{rid}: CSS declarations in text nodes differ')
    for name, rx in (('email', EMAIL), ('url', URL), ('domain/path', DOMAINPATH)):
        a = collections.Counter(x.rstrip('.,') for x in rx.findall(en))
        b = collections.Counter(x.rstrip('.,') for x in rx.findall(ko))
        if a != b:
            problems.append(f'{rid}: {name} multiset differs: -{dict(a - b)} +{dict(b - a)}')
    if ko.count('\n') != en.count('\n'):
        problems.append(f'{rid}: newline count {en.count(chr(10))} -> {ko.count(chr(10))}')
    o = collections.OrderedDict()
    o['id'] = rid + '-ko'; o['pair_id'] = rid; o['lang'] = 'ko'
    for k in ('label', 'source', 'subset', 'doc_type'):
        o[k] = r[k]
    o['text'] = ko
    o['injected_instruction'] = None
    o['origin'] = r['origin']; o['notes'] = r['notes']; o['core'] = r['core']
    base = ('BrowseSafe raw HTML: every tag, attribute name, URL, email, class/id, CSS/JS, data-* machine values and the overall markup kept byte-identical; '
            'translated only human-readable text: text nodes, title/aria-label values, readable text inside HTML-escaped markup (&lt;...&gt; tags kept identical), '
            'and natural-language prose inside HTML/CSS comments (matches the KO injection half, whose comment payloads are Korean). '
            'Recurring boilerplate lines use exactly the renderings of the KO injection half\'s glossary (tr_data.json). Brand/site names in Latin script. '
            'Tag sequence, full tag strings, escaped tags, URLs and emails verified identical to the source.')
    extra = MAPS.get(rid, {}).get('notes', '')
    o['translation_notes'] = (base + (' ' + extra if extra else '')).strip()
    outs.append(o)

with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
    for o in outs:
        f.write(json.dumps(o, ensure_ascii=False) + '\n')
print('written', len(outs))
print('glossary lines used:', sum(used_gloss.values()), 'distinct', len(used_gloss))
print('problems:', len(problems))
for p in problems:
    print(' ', p)
