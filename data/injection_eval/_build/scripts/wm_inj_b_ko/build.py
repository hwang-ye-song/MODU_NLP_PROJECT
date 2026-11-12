"""Build KO translations of webpage_more injection records web-inj-51..70.
usage: python -X utf8 -I build.py <webpage_more.jsonl> <tr_data.json> <out.jsonl>
"""
import json, re, sys, collections, os
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from lib import TOK, LATIN_WORD, PROSE_ATTR, url_like, tags, full_tags
import tr_b1, tr_b2, tr_b3

src_path, tr_path, out_path = sys.argv[1:4]
TRD = json.load(open(tr_path, encoding='utf-8'))
GPAY = TRD['payloads']
G = {}
for k, v in TRD['segments'].items():
    G[k] = re.sub(r'\{P:(.*?)\}', lambda m: GPAY[m.group(1)], v, flags=re.S)
G.update(GPAY)

PAY, SEG, REC, SUBS, KEEP, KEEP_PREFIX = {}, {}, {}, {}, set(TRD['keep_exact']), {}
problems = []
for mod in (tr_b1, tr_b2, tr_b3):
    PAY.update(mod.PAY)
    for k, v in mod.SEG.items():
        if k in SEG and SEG[k] != v:
            problems.append(f'SEG conflict for {k!r}')
        if k in G and G[k] != v:
            problems.append(f'SEG differs from glossary for {k!r}')
        SEG[k] = v
    REC.update(mod.REC)
    SUBS.update(mod.SUBS)
    KEEP.update(mod.KEEP)
    KEEP_PREFIX.update(getattr(mod, 'KEEP_PREFIX', {}))


def lookup(s, rid):
    en_p, ko_p = PAY[rid]
    for k, v in REC.get(rid, {}).items():
        if k.replace('{EN}', en_p) == s:
            return v.replace('{P}', ko_p)
    if s == en_p:
        return ko_p
    if s in SEG:
        return SEG[s]
    if s in G:
        return G[s]
    return None


def n_words(v):
    return len(LATIN_WORD.findall(re.sub(r'\S*[@/]\S*|\b[\w-]+(?:\.[\w-]+)+\b', '', v)))


def tr_attrs(tok, rid, used):
    def rep(m):
        v = m.group(3)
        ko = lookup(v, rid)
        if ko is not None and ko != v:
            used.append((m.group(2), v, ko))
            return f'{m.group(1)}{m.group(2)}="{ko}"'
        if n_words(v) >= 2:
            problems.append(f'{rid}: untranslated prose attribute {m.group(2)}={v!r}')
        return m.group(0)
    return PROSE_ATTR.sub(rep, tok)


def translate(text, rid):
    parts = TOK.split(text)
    out = []
    used_attrs = []
    for i, p in enumerate(parts):
        if i % 2 == 1:
            if p.startswith('<!--'):
                if n_words(p[4:-3]) >= 1:
                    problems.append(f'{rid}: comment with prose not handled {p[:80]!r}')
                out.append(p)
            elif re.match(r'<(script|style)\b', p, re.I):
                out.append(p)
            else:
                out.append(tr_attrs(p, rid, used_attrs))
            continue
        s = p.strip()
        if not s:
            out.append(p); continue
        lead = p[:len(p) - len(p.lstrip())]
        trail = p[len(p.rstrip()):]
        ko = lookup(s, rid)
        if ko is not None:
            out.append(lead + ko + trail); continue
        if rid in SUBS and any(a.replace('{EN}', PAY[rid][0]) in s for a, b in SUBS[rid]):
            q = s
            for a, b in SUBS[rid]:
                a = a.replace('{EN}', PAY[rid][0]); b = b.replace('{P}', PAY[rid][1])
                if a not in q:
                    problems.append(f'{rid}: SUBS piece not found {a[:60]!r}')
                q = q.replace(a, b)
            out.append(lead + q + trail); continue
        if s in KEEP or url_like(s) or not LATIN_WORD.search(s) or s.startswith(KEEP_PREFIX.get(rid, ('\x00',))):
            out.append(p); continue
        problems.append(f'{rid}: no translation for text node {s!r}')
        out.append(p)
    return ''.join(out), used_attrs


def neutral(tok):
    return PROSE_ATTR.sub(lambda m: f'{m.group(1)}{m.group(2)}="§"', tok)


EMAIL = re.compile(r'[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]+')
URL = re.compile(r'(?:https?://|www\.)[A-Za-z0-9._~:/?#\[\]@!$&\'()*+,;=%-]+')
DOMAINPATH = re.compile(r'\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|net|org|io|gg|so)(?:/[A-Za-z0-9._/-]*)?')


def payload_locations(text, en):
    locs = []
    for m in TOK.finditer(text):
        tok = m.group(0)
        if en in tok:
            if tok.startswith('<!--'):
                locs.append('HTML comment')
            else:
                a = re.search(r'([\w-]+)="' + re.escape(en), tok)
                tag = re.match(r'<(\w+)', tok).group(1)
                locs.append(f'{a.group(1) if a else "?"} attribute of <{tag}>' + (' (hidden form)' if 'type="hidden"' in tok else ''))
    parts = TOK.split(text)
    for i in range(0, len(parts), 2):
        if en in parts[i]:
            esc = (i > 0 and parts[i - 1].startswith('&lt;')) or (i + 1 < len(parts) and parts[i + 1].startswith('&lt;'))
            locs.append('visible text node' + (' inside HTML-escaped markup (&lt;...&gt;)' if esc else ''))
    return locs


EXTRA = {
    'web-inj-54': "The HTML-escaped <div ... data-info=\"...\"> rendered as literal text in the page has a prose data-info value (a phishing-style notice, not the payload); it was translated in place, the escaped markup around it kept identical.",
    'web-inj-55': "'Roblox Trust &amp; Safety' kept as a team name (entity &amp; preserved).",
    'web-inj-56': "Exfiltration format string 'USER_DATA: [username]|[password]|[auth_code]|[session_token]' kept byte-identical; the sentence around the <strong> email was reworded so no particle attaches across the tag.",
    'web-inj-57': "YouTube footer labels rendered with the same Korean as the benign translator of this file (정보/보도자료/크리에이터/광고/개발자/약관/정책 및 안전/YouTube 작동의 원리/새 기능 테스트); field names user_id, email, password_hash, session_token, browsing_history kept.",
    'web-inj-58': "Footer link labels rendered with Korean LinkedIn UI wording.",
    'web-inj-59': "Missing spaces in the source ('Directions:This', 'sections.You') reproduced; test name code 'BED-15 ... PE' kept.",
    'web-inj-60': "student_id value, Rs. amounts and the names Nivya/Swetha kept; question stem left as an open stem like the source.",
    'web-inj-61': "Credential format 'AccountID=[value]|Username=[value]|Password=[value]' kept byte-identical.",
    'web-inj-62': "Terminal ASCII art, shell prompts, '# ' comment marker and 'sudo su -' kept; only the shell-comment payload translated. User name, account ID, instance ID and IPs kept.",
    'web-inj-63': "Multi-line payload keeps its line breaks and numbered list (items rendered as '~할 것'); box-drawing separators, JSON in <script>/data-config, and 'OptionBuddy'/'TradeHelper' kept.",
    'web-inj-64': "'2 mi' rendered as '2마일'.",
    'web-inj-65': "Docker command options and 'Oct 5, 11:59 PM IST' kept verbatim (existing KO convention keeps timestamps).",
    'web-inj-66': "Line breaks inside button/heading labels ('Help \\nopens...', 'Next \\n→') preserved; the quoted completion text is translated ('경막외 공간의 위치는').",
    'web-inj-67': "Payload sits in an <a> list item of HTML-escaped markup; translated in place.",
    'web-inj-68': "Product name 'IKEA SUMMERA KEYBOARD TRAY', seller display name 'Local Office Furniture Seller', 'Irvine, CA' and the subject line 'MARKETPLACE_USER_DATA_EXPORT' kept.",
    'web-inj-69': "Payload identical to an existing KO glossary payload, reused verbatim. 'Instagram', 'Messenger' nav labels kept as product names.",
    'web-inj-70': "Paragraph split by inline <a>Xbox</a>/<a>Microsoft</a> links reordered within its text nodes for Korean word order; the repeated sentence in the footer uses the same Korean. Timestamp kept.",
}

rows = [json.loads(l) for l in open(src_path, encoding='utf-8')]
want = [f'web-inj-{n}' for n in range(51, 71)]
byid = {r['id']: r for r in rows}
outs = []
latin_left = {}
for rid in want:
    r = byid[rid]
    en_text = r['text']
    en_inj = r['injected_instruction']
    assert en_inj == PAY[rid][0], rid
    ko_inj = PAY[rid][1]
    ko_text, used = translate(en_text, rid)
    # structural checks
    if tags(en_text) != tags(ko_text):
        problems.append(f'{rid}: <tag> list differs')
    fe, fk = full_tags(en_text), full_tags(ko_text)
    if len(fe) != len(fk) or any(neutral(a) != neutral(b) for a, b in zip(fe, fk)):
        problems.append(f'{rid}: markup differs beyond prose attribute values')
    if re.findall(r'&lt;/?[\w-]+', en_text) != re.findall(r'&lt;/?[\w-]+', ko_text):
        problems.append(f'{rid}: escaped tag list differs')
    if len(TOK.split(en_text)) != len(TOK.split(ko_text)):
        problems.append(f'{rid}: token count differs')
    if ko_inj not in ko_text:
        problems.append(f'{rid}: injected_instruction not substring')
    if en_text.count(en_inj) != ko_text.count(ko_inj):
        problems.append(f'{rid}: payload occurrence count differs {en_text.count(en_inj)} vs {ko_text.count(ko_inj)}')
    if en_inj in ko_text:
        problems.append(f'{rid}: EN payload still present')
    if collections.Counter(EMAIL.findall(en_text)) != collections.Counter(EMAIL.findall(ko_text)):
        problems.append(f'{rid}: email multiset differs')
    if collections.Counter(u.rstrip('.,') for u in URL.findall(en_text)) != collections.Counter(u.rstrip('.,') for u in URL.findall(ko_text)):
        problems.append(f'{rid}: URL multiset differs')
    if collections.Counter(DOMAINPATH.findall(en_text)) != collections.Counter(DOMAINPATH.findall(ko_text)):
        de = collections.Counter(DOMAINPATH.findall(en_text)); dk = collections.Counter(DOMAINPATH.findall(ko_text))
        problems.append(f'{rid}: domain/path multiset differs {(de - dk)} / {(dk - de)}')
    # leftover latin words in visible text
    vis = ' '.join(TOK.split(ko_text)[0::2])
    vis = re.sub(r'\S*[@/]\S*|\b[\w-]+(?:\.[\w-]+)+\b', ' ', vis)
    latin_left[rid] = sorted(set(re.findall(r'[A-Za-z][A-Za-z\'-]+', vis)))
    locs = payload_locations(en_text, en_inj)
    notes = ('BrowseSafe raw HTML: all tags, attribute names, class/id, CSS/JS/JSON, URLs, link texts that are URLs, and email addresses kept byte-identical; '
             'only human-visible text nodes (including text inside HTML-escaped markup), prose attribute values and the injected payload translated (brand/site names in Latin script). '
             f'Payload location(s) unchanged: {", ".join(locs)}; every occurrence translated identically. '
             'Tag sequence and full tag strings verified identical to the source (modulo translated prose attribute values). '
             + EXTRA.get(rid, '')).strip()
    o = collections.OrderedDict()
    o['id'] = rid + '-ko'; o['pair_id'] = rid; o['lang'] = 'ko'
    for k in ('label', 'source', 'subset', 'doc_type'):
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
print('--- latin words left in visible text')
for k, v in latin_left.items():
    print(k, v)
