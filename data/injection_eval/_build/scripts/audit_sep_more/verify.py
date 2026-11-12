import json, glob, difflib, re, os
OLD = '<SCRATCH>'
src = json.load(open(OLD + '/dl/sep/repo/datasets/SEP_dataset.json', encoding='utf-8'))
print('src type', type(src), len(src), list(src[0].keys()) if isinstance(src, list) else '')
recs = [json.loads(l) for l in open('<DATASET_ROOT>/_build/parts_v2/sep_more.jsonl', encoding='utf-8')]
for r in recs:
    o = r['origin']; s = src[o['index']]
    fld = o['field']
    exp = 'prompt_instructed' if r['label'] == 'injection' else 'prompt_clean'
    m = s.get(fld) == r['text']
    issues = []
    if fld != exp: issues.append(f'field={fld}')
    if not m: issues.append('TEXT!=SRC')
    if s.get('system_prompt_clean') and o.get('task_prompt') and o['task_prompt'] not in s.get('system_prompt_clean',''): issues.append('task mismatch')
    if r['label'] == 'injection':
        clean = s['prompt_clean']
        rest = r['text'].replace(r['injected_instruction'], '').strip()
        if rest != clean.strip(): issues.append('clean+probe mismatch')
        if s.get('witness') != o.get('witness'): issues.append('witness')
        pos = 'start' if r['text'].startswith(r['injected_instruction']) else ('end' if r['text'].endswith(r['injected_instruction']) else 'mid')
        if pos != o.get('probe_position_in_data'): issues.append(f'pos {pos}')
        if r['text'].count(r['injected_instruction']) != 1: issues.append('ii count')
    nonascii = sorted(set(c for c in r['text'] if ord(c) > 127))
    if re.search(r'[ÃâÂ]\S|\ufffd|\{[a-z_]+\}|<[A-Z][a-z]+ [A-Z]', r['text']): issues.append('mojibake/placeholder?')
    print(r['id'], 'OK' if not issues else issues, nonascii if nonascii else '')
