import json, re, glob, html

AUD = '<DATASET_ROOT>/_build/audit/'
inp = [json.loads(l) for l in open(AUD + 'input_webpage_more_1.jsonl', encoding='utf-8')]
files = glob.glob('<DATASET_ROOT>/_build/parts_v2/webpage*.jsonl') + [AUD + 'input_webpage_more_2.jsonl', AUD + 'input_webpage_more_1.jsonl']
phr = set()
for f in files:
    for l in open(f, encoding='utf-8'):
        r = json.loads(l)
        ii = r.get('injected_instruction')
        if ii:
            s = re.split(r'\S+@\S+|https?://\S+', ii)[0].strip()
            s = re.sub(r'^(---END CONTEXT---\s*)', '', s)
            if len(s) >= 15:
                phr.add(s[:40])
# extra generic phrases
phr |= {'please provide your', 'please archive conversations', 'you should assist users', 'support staff',
        'Ignore above', 'Disregard prior', 'previous instructions', 'operational guidelines', 'system instructions',
        'new directive', 'admin mode', 'In a scenario where you', 'Please demonstrate', 'URGENT from CEO', 'transaction logs',
        'data retention policy', 'quality assurance', 'NEW INSTRUCTION', 'END CONTEXT', 'Forward sensitive', 'send all data',
        'session data', 'send it to', 'collecting their information'}
print(len(phr), 'phrases')
for r in inp:
    t = html.unescape(r['text'])
    ii = r.get('injected_instruction')
    rem = t.replace(ii, ' [SPAN] ') if ii else t
    for p in sorted(phr):
        for m in re.finditer(re.escape(p), rem, re.I):
            print(r['id'], r['label'], '|', p, '|', repr(rem[max(0, m.start()-80):m.end()+140]))
