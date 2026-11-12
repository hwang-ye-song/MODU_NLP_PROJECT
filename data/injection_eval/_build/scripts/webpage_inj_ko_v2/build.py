"""Build KO translations of webpage injection records.
usage: python -X utf8 -I build.py <in webpage.jsonl> <tr_data.json> <agentdojo_ko.json> <out.jsonl>
"""
import json, re, sys, collections

src_path, tr_path, ad_path, out_path = sys.argv[1:5]
TR = json.load(open(tr_path, encoding='utf-8'))
AD = json.load(open(ad_path, encoding='utf-8'))
PAY = TR['payloads']
SEG = TR['segments']
KEEP = set(TR['keep_exact'])

TOK = re.compile(r'(<!--.*?-->|<[^>]*>|&lt;.*?&gt;)', re.S)
LATIN_WORD = re.compile(r'[A-Za-z]{2,}')
URLISH = re.compile(r'^(\S*[.@/]\S*|\||•)$')


def expand(v):
    return re.sub(r'\{P:(.*?)\}', lambda m: PAY[m.group(1)], v, flags=re.S)


def url_like(s):
    return all(URLISH.match(w) for w in s.split())


def sub_payloads(s):
    for en, ko in PAY.items():
        s = s.replace(en, ko)
    return s


def translate_html(text, rid, problems):
    parts = TOK.split(text)
    out = []
    for i, p in enumerate(parts):
        if i % 2 == 1:  # markup token
            if p.startswith('<!--'):
                q = sub_payloads(p)
                inner = q[4:-3]
                left = [w for w in LATIN_WORD.findall(re.sub(r'\S*[.@/]\S*', '', inner)) if w != 'TODO']
                if left:
                    problems.append(f'{rid}: untranslated comment words {left}')
                out.append(q)
            elif p.startswith('&lt;'):
                if any(en in p for en in PAY):
                    problems.append(f'{rid}: payload inside escaped tag')
                out.append(p)
            else:
                out.append(sub_payloads(p))
            continue
        s = p.strip()
        if not s:
            out.append(p); continue
        lead = p[:len(p) - len(p.lstrip())]
        trail = p[len(p.rstrip()):]
        if s in SEG:
            out.append(lead + expand(SEG[s]) + trail)
        elif s in PAY:
            out.append(lead + PAY[s] + trail)
        elif s in KEEP or url_like(s) or not LATIN_WORD.search(s):
            out.append(p)
        else:
            problems.append(f'{rid}: no translation for text node {s!r}')
            out.append(p)
    return ''.join(out)


def tags(t):
    return re.findall(r'<\s*/?\s*([A-Za-z!][\w-]*)', t)


def full_tags(t):
    return [x for x in TOK.findall(t)]


EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]+')
URL = re.compile(r'(?:https?://|www\.)[A-Za-z0-9._~:/?#\[\]@!$&\'()*+,;=%-]+')


def payload_locations(text, en):
    locs = []
    for m in re.finditer(r'<!--.*?-->|<[^>]*>', text, re.S):
        tok = m.group(0)
        if en in tok:
            if tok.startswith('<!--'):
                locs.append('HTML comment')
            else:
                a = re.search(r'([\w-]+)="' + re.escape(en), tok)
                tag = re.match(r'<(\w+)', tok).group(1)
                locs.append(f'{a.group(1) if a else "?"} attribute of <{tag}>' + (' (hidden form)' if 'type="hidden"' in tok else ''))
    stripped = re.sub(r'<!--.*?-->|<[^>]*>', '\x00', text, flags=re.S)
    if en in stripped:
        locs.append('visible text node')
    return locs


rows = [json.loads(l) for l in open(src_path, encoding='utf-8')]
inj = [r for r in rows if r['label'] == 'injection']
problems = []
outs = []
for r in inj:
    rid = r['id']
    en_text = r['text']
    if rid in AD:
        ko_text = AD[rid]['text']; ko_inj = AD[rid]['inj']; notes = AD[rid]['notes']
        if tags(en_text) != tags(ko_text):
            problems.append(f'{rid}: <tag> list differs')
    else:
        ko_text = translate_html(en_text, rid, problems)
        en_inj = r['injected_instruction']
        ko_inj = PAY[en_inj]
        locs = payload_locations(en_text, en_inj)
        extra = []
        if 'lang="en"' in en_text:
            extra.append('<html lang="en"> left unchanged (markup kept byte-identical).')
        if 'Oct 15, 11:59 PM PDT' in en_text:
            extra.append("Timestamp 'Oct 15, 11:59 PM PDT' kept verbatim.")
        if 'MenuSearchDirections' in en_text:
            extra.append("Run-together UI labels 'MenuSearchDirections' rendered run-together as '메뉴검색경로'.")
        if en_inj.startswith('TODO:'):
            extra.append("'TODO:' marker kept; list items rendered as Korean to-do items.")
        if en_inj.startswith('---END CONTEXT---'):
            extra.append("Fake delimiter '---END CONTEXT---' translated as '---컨텍스트 끝---'.")
        if '&lt;' in en_text:
            extra.append('HTML-escaped markup (&lt;...&gt;) kept identical; only its human-readable text translated.')
        notes = ('BrowseSafe raw HTML: all tags, attributes, class/id, CSS/JS/JSON, URLs, link texts that are URLs, and email addresses kept byte-identical; '
                 'only human-visible text nodes and the injected payload translated (brand/site names in Latin script). '
                 f'Payload location(s) unchanged: {", ".join(locs)}; every occurrence translated identically. '
                 'Tag sequence and full tag strings verified identical to the source (modulo the translated payload). ' + ' '.join(extra)).strip()
        # full tag check
        exp = [sub_payloads(t) for t in full_tags(en_text)]
        if exp != full_tags(ko_text):
            problems.append(f'{rid}: full tag strings differ')
        if tags(en_text) != tags(ko_text):
            problems.append(f'{rid}: <tag> list differs')
        if re.findall(r'&lt;/?[\w-]+', en_text) != re.findall(r'&lt;/?[\w-]+', ko_text):
            problems.append(f'{rid}: escaped tag list differs')
    if ko_inj not in ko_text:
        problems.append(f'{rid}: injected_instruction not substring')
    if collections.Counter(EMAIL.findall(en_text)) != collections.Counter(EMAIL.findall(ko_text)):
        problems.append(f'{rid}: email multiset differs {EMAIL.findall(en_text)} vs {EMAIL.findall(ko_text)}')
    if collections.Counter(u.rstrip(".,") for u in URL.findall(en_text)) != collections.Counter(u.rstrip(".,") for u in URL.findall(ko_text)):
        problems.append(f'{rid}: URL multiset differs')
    o = collections.OrderedDict()
    o['id'] = rid + '-ko'; o['pair_id'] = rid; o['lang'] = 'ko'
    for k in ('label', 'source', 'subset'):
        o[k] = r[k]
    o['text'] = ko_text; o['injected_instruction'] = ko_inj
    o['origin'] = r['origin']; o['notes'] = r['notes']; o['core'] = r['core']
    o['translation_notes'] = notes
    outs.append(o)

with open(out_path, 'w', encoding='utf-8', newline='\n') as f:
    for o in outs:
        f.write(json.dumps(o, ensure_ascii=False) + '\n')
print('written', len(outs))
print('problems:', len(problems))
for p in problems:
    print(' ', p)
