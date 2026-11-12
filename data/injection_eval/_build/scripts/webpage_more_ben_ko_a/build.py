"""Translate web-ben-32..50 (webpage_more, BrowseSafe benign) into Korean and validate.
usage: python -X utf8 -I build.py <out.jsonl>
"""
import json, re, sys, collections
B = '<DATASET_ROOT>/_build/'
HERE = '<SCRATCH>/scripts/webpage_more_ben_ko_a/'
W = '<SCRATCH>/work/webpage_more_ben_ko_a/'
out_path = sys.argv[1]
TOK = re.compile(r'(<!--.*?-->|<[^>]*>|&lt;.*?&gt;)', re.S)
LATIN = re.compile(r'[A-Za-z]{2,}')
URLISH = re.compile(r'^(\S*[.@/]\S*|\||•)$')
ATTR = re.compile(r'(\b(?:title|alt|placeholder|aria-label|data-[\w-]+)=")([^"]*)(")')
TR = json.load(open(B + 'scripts/webpage_inj_ko_v2/tr_data.json', encoding='utf-8'))
AL = json.load(open(W + 'aligned_gloss.json', encoding='utf-8'))
MY = json.load(open(HERE + 'tr_slice.json', encoding='utf-8'))
PAY = TR['payloads']
problems = []


def expand(v):
    return re.sub(r'\{P:(.*?)\}', lambda m: PAY[m.group(1)], v, flags=re.S)


SEG = {}
src_of = {}
for k, v in AL.items():
    if len(v) > 1:
        continue
    SEG[k] = list(v)[0]; src_of[k] = 'AL'
for k, v in TR['segments'].items():
    if k in SEG and SEG[k] != expand(v):
        problems.append(f'TR/AL conflict {k!r}')
    SEG[k] = expand(v); src_of[k] = 'TR'
for k, v in MY['seg'].items():
    if k in SEG and SEG[k] != v:
        problems.append(f'my rendering conflicts with {src_of[k]}: {k!r}')
        continue
    SEG.setdefault(k, v); src_of.setdefault(k, 'MY')
KEEP = set(MY['keep'])
ATTR_TR = MY['attr']
used = collections.Counter()


def url_like(s):
    return all(URLISH.match(w) for w in s.split())


def tr_tag(tok, rid):
    def f(m):
        v = m.group(2)
        if v in ATTR_TR:
            used['attr:' + v] += 1
            return m.group(1) + ATTR_TR[v] + m.group(3)
        if LATIN.search(v) and ' ' in v:
            problems.append(f'{rid}: prose attribute left untranslated {v!r}')
        return m.group(0)
    return ATTR.sub(f, tok)


def translate(text, rid):
    parts = TOK.split(text)
    out = []
    raw = MY['raw'].get(rid, {})
    for i, p in enumerate(parts):
        if i % 2 == 1:
            if p.startswith('<!--') or p.startswith('&lt;!--'):
                if p in SEG:
                    out.append(SEG[p]); used[src_of[p] + ':' + p] += 1
                else:
                    problems.append(f'{rid}: comment without translation {p!r}')
                    out.append(p)
            elif p.startswith('<'):
                out.append(tr_tag(p, rid))
            else:  # escaped tag: keep identical
                if re.search(r'\b(title|alt|placeholder|aria-label)=', p):
                    problems.append(f'{rid}: prose-capable attribute inside escaped tag {p[:80]!r}')
                out.append(p)
            continue
        if p in raw:
            out.append(raw[p]); used['raw:' + p] += 1; continue
        s = p.strip()
        if not s:
            out.append(p); continue
        lead = p[:len(p) - len(p.lstrip())]
        trail = p[len(p.rstrip()):]
        if s in SEG:
            out.append(lead + SEG[s] + trail); used[src_of[s] + ':' + s] += 1
        elif s in KEEP or url_like(s) or not LATIN.search(s):
            out.append(p); used['keep:' + s] += 1
        else:
            problems.append(f'{rid}: no translation for text node {s!r}')
            out.append(p)
    return ''.join(out)


def tagnames(t):
    return re.findall(r'<\s*/?\s*([A-Za-z!][\w-]*)', t)


def esc_tagnames(t):
    return re.findall(r'&lt;\s*/?\s*([A-Za-z!][\w-]*)', t)


def norm_tag(tok):
    return ATTR.sub(lambda m: m.group(1) + '#' + m.group(3) if (m.group(2) in ATTR_TR or m.group(2) in ATTR_TR.values()) else m.group(0), tok)


EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]+')
URL = re.compile(r'(?:https?://|www\.)[A-Za-z0-9._~:/?#\[\]@!$&\'()*+,;=%-]+')
DOMAIN = re.compile(r'\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|gg|so)(?:/[A-Za-z0-9._~/?=&#-]*)?')

BASE_NOTE = ('BrowseSafe raw HTML: every tag, attribute name, URL, email, class/id, CSS and the overall markup kept byte-identical '
             '(<html lang="en"> where present left unchanged); translated only human-readable text: text nodes, title/placeholder/aria-label values, '
             'readable text inside HTML-escaped markup (&lt;...&gt; tags kept identical), and natural-language prose inside HTML/CSS comments '
             '(matches the KO injection half, whose comment payloads are Korean). Recurring boilerplate lines use exactly the renderings from the '
             "KO injection half's glossary. Brand/site names in Latin script. Tag sequence verified identical to the source.")

rows = [json.loads(l) for l in open(B + 'parts_v2/webpage_more.jsonl', encoding='utf-8')]
want = ['web-ben-%d' % i for i in range(32, 51)]
byid = {r['id']: r for r in rows}
outs = []
for rid in want:
    r = byid[rid]
    assert r['label'] == 'benign' and r['injected_instruction'] is None
    en = r['text']
    ko = translate(en, rid)
    a, b = TOK.split(en), TOK.split(ko)
    if len(a) != len(b):
        problems.append(f'{rid}: token count differs')
    else:
        for x, y in zip(a[1::2], b[1::2]):
            if x.startswith('<!--') or x.startswith('&lt;!--'):
                ok = (x.startswith('<!--') and y.startswith('<!-- ') and y.endswith(' -->')) or \
                     (x.startswith('&lt;!--') and y.startswith('&lt;!-- ') and y.endswith(' --&gt;'))
                if not ok:
                    problems.append(f'{rid}: comment delimiters changed')
                continue
            if norm_tag(x) != norm_tag(y):
                problems.append(f'{rid}: tag string differs {x[:80]!r}')
    if tagnames(en) != tagnames(ko):
        problems.append(f'{rid}: <tag> sequence differs')
    if esc_tagnames(en) != esc_tagnames(ko):
        problems.append(f'{rid}: escaped tag sequence differs')
    for rx, nm in ((EMAIL, 'email'), (URL, 'url'), (DOMAIN, 'domain')):
        ce = collections.Counter(u.rstrip('.,') for u in rx.findall(en))
        ck = collections.Counter(u.rstrip('.,') for u in rx.findall(ko))
        if ce != ck:
            problems.append(f'{rid}: {nm} multiset differs {ce - ck} / {ck - ce}')
    # leftover English in visible text / comments
    vis = re.sub(r'<(?!!--)[^>]*>|&lt;(?!!--).*?&gt;', ' ', ko, flags=re.S)
    vis = re.sub(r'\S*[.@/]\S*', ' ', vis)
    left = [w for w in LATIN.findall(vis)]
    hangul = len(re.findall(r'[\uac00-\ud7a3]', vis))
    extra = MY['rec_notes'].get(rid, '')
    o = collections.OrderedDict()
    o['id'] = rid + '-ko'; o['pair_id'] = rid; o['lang'] = 'ko'
    for k in ('label', 'source', 'subset', 'doc_type'):
        o[k] = r[k]
    o['text'] = ko; o['injected_instruction'] = None
    o['origin'] = r['origin']; o['notes'] = r['notes']; o['core'] = r['core']
    o['translation_notes'] = (BASE_NOTE + (' ' + extra if extra else '')).strip()
    outs.append(o)
    print(rid, 'len en/ko', len(en), len(ko), 'hangul', hangul, 'latin-left', sorted(set(left)))

with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
    for o in outs:
        f.write(json.dumps(o, ensure_ascii=False) + '\n')
unused = [k for k in MY['seg'] if not any(u.endswith(':' + k) for u in used)] + [k for k in ATTR_TR if 'attr:' + k not in used]
print('written', len(outs), 'unused my-entries', unused)
print('problems:', len(problems))
for p in problems:
    print('  ', p)
