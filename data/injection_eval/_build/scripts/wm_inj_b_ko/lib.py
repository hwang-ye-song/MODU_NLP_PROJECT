import re

# markup tokens: comments, script/style blocks (kept whole), real tags, escaped tags
TOK = re.compile(r'(<!--.*?-->|<script\b[^>]*>.*?</script>|<style\b[^>]*>.*?</style>|<[^>]*>|&lt;.*?&gt;)', re.S | re.I)
LATIN_WORD = re.compile(r'[A-Za-z]{2,}')
URLISH = re.compile(r'^(\S+@\S+\.\w+|\S*/\S*|[\w-]+(?:\.[\w-]+)+[\w/.-]*|\||•|·|©|-|—|–|\*|&amp;)$')
# attributes whose values may hold human-readable prose
PROSE_ATTR = re.compile(r'(\s)((?:data-[\w-]+|alt|title|placeholder|aria-label|aria-description|content|value|label))="([^"]*)"')


def url_like(s):
    return all(URLISH.match(w) for w in s.split())


def is_prose(v):
    v2 = re.sub(r'\S*[.@/]\S*', '', v)
    return len(LATIN_WORD.findall(v2)) >= 1 and not url_like(v)


def text_nodes(text):
    """yield (kind, string) for every translatable unit"""
    parts = TOK.split(text)
    for i, p in enumerate(parts):
        if i % 2 == 1:
            if p.startswith('<!--'):
                yield ('comment', p[4:-3])
            elif p.lower().startswith('<script') or p.lower().startswith('<style'):
                yield ('code', p)
            else:
                for m in PROSE_ATTR.finditer(p):
                    yield ('attr:' + m.group(2), m.group(3))
        else:
            s = p.strip()
            if s:
                yield ('text', s)


def tags(t):
    return re.findall(r'<\s*/?\s*([A-Za-z!][\w-]*)', t)


def full_tags(t):
    return TOK.findall(t)
