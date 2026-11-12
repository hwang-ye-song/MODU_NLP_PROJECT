"""Shared filters copied verbatim from WD/_build/scripts/webpage_v2/build_webpage.py."""
import collections, re
NONLATIN = re.compile(r"[Ͱ-ϿЀ-ӿ֐-׿؀-ۿऀ-෿฀-๿぀-ヿ㐀-鿿가-힯]")
FOREIGN = re.compile(r"\b(de|la|le|les|des|et|pour|para|con|el|los|und|der|die|das|que|una|une|est|sur|avec|mit|für|não|é|las|del|nicht|noch|jetzt|ist|sie|ihr|ihre|auf|wird|zu|innerhalb|erforderlich|vous|votre|dans|pas|por|su|sus|uma|het|een|van)\b", re.I)
ARTIFACT = re.compile(r"I appreciate (the|your) (detailed instructions|request)|prior assistant response|I cannot (complete|convert) th", re.I)
SITE = re.compile(r"\b([a-z0-9-]+)\.(com|so|in|net|org|io|gg)\b")
SKIP_SITES = {"evil", "badsite", "external-server", "malicious-site", "external", "example-collector", "evil-domain",
              "apps", "apple", "fedex", "instagram", "discord", "youtube", "track", "parceltrack", "notifications", "w3", "googleapis", "gstatic"}


def visible(h):
    h = re.sub(r"<!--.*?-->|<style.*?</style>|<script.*?</script>", " ", h, flags=re.S)
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)).strip()


def site_of(h):
    c = collections.Counter(m.group(1) for m in SITE.finditer(h.lower()) if m.group(1) not in SKIP_SITES)
    if not c:
        c = collections.Counter(m.group(1) for m in SITE.finditer(h.lower()) if m.group(1) not in {"evil", "badsite", "external-server", "malicious-site", "external", "example-collector", "evil-domain", "apps", "apple", "notifications"})
    return c.most_common(1)[0][0] if c else "unknown"


def english_ok(h):
    if len(h) < 300:  # skip near-empty stub pages (both labels)
        return False
    if re.search(r'lang="(?!en)[a-z]', h, re.I):
        return False
    if NONLATIN.search(h):
        return False
    v = visible(h)
    return len(FOREIGN.findall(v)) <= 1 and "é" not in v and "ñ" not in v and "ü" not in v and "ö" not in v
