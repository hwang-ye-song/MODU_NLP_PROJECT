"""Shared HTML tokenizing helpers for the KO translation of web-ben-51..70."""
import re

TOK = re.compile(r'(<!--.*?-->|<[^>]*>)', re.S)
ATTR = re.compile(r'(\s)([\w:-]+)(=)("([^"]*)"|\'([^\']*)\')', re.S)
PROSE_ATTRS = {'alt', 'title', 'placeholder', 'aria-label', 'data-tooltip', 'data-title',
               'data-label', 'data-placeholder', 'aria-description', 'data-text'}
LATIN = re.compile(r'[A-Za-z]{2,}')


def tokens(text):
    """Yield (kind, string) where kind in tag/comment/text/code (code = inside script/style)."""
    parts = TOK.split(text)
    in_code = None
    for i, p in enumerate(parts):
        if i % 2 == 1:
            if p.startswith('<!--'):
                yield ('comment', p)
            else:
                m = re.match(r'<\s*(/?)\s*([A-Za-z][\w-]*)', p)
                if m:
                    name = m.group(2).lower()
                    if not m.group(1) and name in ('script', 'style'):
                        in_code = name
                    elif m.group(1) and name == in_code:
                        in_code = None
                yield ('tag', p)
        else:
            if p == '':
                continue
            yield ('code' if in_code else 'text', p)


def prose_attr(name, tagstr):
    n = name.lower()
    if n in PROSE_ATTRS:
        return True
    if n.startswith('data-') and n not in ('data-id', 'data-testid', 'data-url', 'data-href', 'data-src'):
        return 'maybe'
    if n == 'content' and re.search(r'name="(description|keywords)"|property="og:(title|description)"', tagstr):
        return True
    if n == 'value' and re.search(r'type="(submit|button)"', tagstr):
        return True
    return False


def tag_names(t):
    return re.findall(r'<\s*/?\s*([A-Za-z!][\w-]*)', t)

ESC = re.compile(r'(&lt;!--.*?--&gt;|&lt;.*?&gt;)', re.S)


def esc_tokens(s):
    """Split a text node holding HTML-escaped markup into (kind, str) pieces."""
    for i, p in enumerate(ESC.split(s)):
        if i % 2 == 1:
            yield ('ecomment' if p.startswith('&lt;!--') else 'etag', p)
        elif p:
            yield ('text', p)
