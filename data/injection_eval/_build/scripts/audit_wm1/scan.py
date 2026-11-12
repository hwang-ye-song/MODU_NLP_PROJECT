import json, re, sys
from html.parser import HTMLParser

path = sys.argv[1]
which = sys.argv[2]  # 'benign' or 'injection'
recs = [json.loads(l) for l in open(path, encoding='utf-8')]

KW = re.compile(r"(ignore|disregard|instruction|assistant|\bAI\b|\bagent\b|\bmodel\b|\bLLM\b|system|prompt|override|directive|forward|transmit|exfil|\bsend\b|you are|you must|you should|admin mode|guideline|confidential|credential|session data|leak|attacker|evil|malicious|collect|archive|compliance|audit|operational|configuration|bypass|jailbreak|summar|respond|reply|output|new task|end context|---|@[a-z0-9-]+\.[a-z]{2,})", re.I)

HIDDEN = re.compile(r"(display\s*:\s*none|opacity\s*:\s*0(?![.\d])|visibility\s*:\s*hidden|left\s*:\s*-\d{3,}px|font-size\s*:\s*0|type=\"hidden\"|aria-hidden)", re.I)

class P(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.comments = []; self.attrs = []; self.scripts = []; self.in_script = False; self.texts = []
    def handle_comment(self, d):
        self.comments.append(d.strip())
    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self.in_script = tag
        for k, v in attrs:
            if v and k not in ('style', 'class', 'href', 'src', 'id', 'rel', 'charset', 'name', 'content', 'type', 'width', 'height', 'viewbox', 'd', 'fill', 'xmlns', 'stroke', 'stroke-width', 'lang', 'role', 'for', 'method', 'action', 'target', 'points', 'cx', 'cy', 'r', 'x', 'y', 'transform', 'stroke-linecap', 'stroke-linejoin'):
                self.attrs.append((tag, k, v))
            elif v and k in ('name', 'content') and len(v) > 25:
                self.attrs.append((tag, k, v))
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self.in_script = False
    def handle_data(self, d):
        if self.in_script == 'script':
            self.scripts.append(d)
        elif self.in_script == 'style':
            for c in re.findall(r"/\*(.*?)\*/", d, re.S):
                self.comments.append('CSSCOMMENT:' + c.strip())
        else:
            if d.strip():
                self.texts.append(d.strip())

for r in recs:
    if r['label'] != which:
        continue
    t = r['text']
    p = P(); p.feed(t)
    print('=====', r['id'], len(t))
    nonascii = [c for c in t if ord(c) > 127]
    if nonascii:
        print('  NONASCII:', ''.join(sorted(set(nonascii)))[:80])
    for c in p.comments:
        print('  COMMENT:', repr(c[:250]))
    for tag, k, v in p.attrs:
        print('  ATTR:', tag, k, repr(v[:200]))
    for s in p.scripts:
        if s.strip():
            lits = re.findall(r"(['\"`])((?:(?!\1).){8,}?)\1", s)
            print('  SCRIPT len', len(s), 'literals:', [l[1][:120] for l in lits][:15])
    for m in HIDDEN.finditer(t):
        print('  HIDDEN at', m.start(), repr(t[max(0, m.start()-60):m.start()+200]))
    # CSS comments inside inline style attributes
    for m in re.finditer(r"/\*(.*?)\*/", t, re.S):
        print('  CSSCMT:', repr(m.group(1)[:200]))
    # visible text
    vis = ' | '.join(p.texts)
    print('  TEXT:', vis[:int(sys.argv[3]) if len(sys.argv) > 3 else 600])
    kws = sorted(set(m.group(0).lower() for m in KW.finditer(t)))
    print('  KW:', kws)
