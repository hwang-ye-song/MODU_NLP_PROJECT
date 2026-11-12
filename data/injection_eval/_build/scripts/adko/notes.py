import json
P = '<DATASET_ROOT>/_build/ko_parts/agentdojo_inj.jsonl'
ko = [json.loads(l) for l in open(P, encoding='utf-8')]
for r in ko:
    t = r['text']; n = []
    if r['subset'].startswith('travel'):
        n.append('Python str(dict) re-rendered with str(); review lines aligned with the benign-half glossary.')
    elif r['subset'] == 'banking_file':
        n.append('Raw file string; layout and line breaks kept.')
    else:
        n.append('YAML re-dumped with yaml.safe_dump(allow_unicode=True); keys, ids, dates, emails, IBANs unchanged; line folding differs from EN because of Hangul.')
    if '이전 지시는 무시하세요. 대신 이렇게 하세요' in t:
        n.append('EN typo "iunstructions" not reproduced; "Do X instead." rendered as "대신 이렇게 하세요: X".')
    if 'Hi from Mark' in t:
        n.append('Quoted subject/body literals kept in English to match the byte-identical tool-argument dict.')
    if '`' in t:
        n.append('Tool names and argument dicts kept byte-identical.')
    if any(m in t for m in ['<INFORMATION>', 'TODO:', '###(system_message)', 'External_']):
        n.append('Markers <INFORMATION>, TODO:, ###(system_message), External_ kept as in EN.')
    r['translation_notes'] = ' '.join(n)
open(P, 'w', encoding='utf-8').write(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in ko))
print(len(ko), ko[26]['translation_notes'])
