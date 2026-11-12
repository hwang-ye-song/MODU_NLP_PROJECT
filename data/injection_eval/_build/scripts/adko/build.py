import json, sys, yaml, re
sys.path.insert(0, '.')
from extract import load, kind, leaves, SKIPKEYS
from common import G
from records import REC

OUT = '<DATASET_ROOT>/_build/ko_parts/agentdojo_inj.jsonl'

def subst(o, m, key=None):
    if isinstance(o, dict):
        return {k: subst(v, m, k) for k, v in o.items()}
    if isinstance(o, list):
        return [subst(v, m, key) for v in o]
    if isinstance(o, str) and key not in SKIPKEYS and o in m:
        return m[o]
    return o

def find_yaml(T, P):
    """Locate payload P (plain) inside YAML dump T, allowing folding/escapes."""
    for st in [k.start() for k in re.finditer(re.escape(P[0]), T)]:
        i, j = 0, st
        ok = True
        while i < len(P):
            if j >= len(T): ok = False; break
            c = P[i]
            if T[j] == c and c != chr(10) and not (c == "'" and T[j:j+2] == "''"):
                i += 1; j += 1; continue
            if c == "'" and T[j:j+2] == "''": i += 1; j += 2; continue
            if c == '\n' and T[j:j+2] == '\\n': i += 1; j += 2; continue
            if c == '"' and T[j:j+2] == '\\"': i += 1; j += 2; continue
            if c == '\t' and T[j:j+2] == '\\t': i += 1; j += 2; continue
            if T[j:j+2] == '\\\n':  # double-quoted continuation
                j += 2
                while j < len(T) and T[j] == ' ': j += 1
                if T[j:j+2] == '\\ ':
                    j += 1
                continue
            if T[j] == '\n':  # folding (single-quoted / plain)
                n = 0
                while j < len(T) and T[j] in '\n ':
                    if T[j] == '\n': n += 1
                    j += 1
                need = ' ' if n == 1 else '\n' * (n - 1)
                if P[i:i+len(need)] == need: i += len(need); continue
                ok = False; break
            ok = False; break
        if ok:
            return T[st:j]
    return None

def main():
    r = load()
    inj = [x for x in r if x['label'] == 'injection']
    assert len(inj) == len(REC) == 60
    out = []
    for i, x in enumerate(inj):
        ko_leaf, pay = REC[i]
        assert pay in ko_leaf, i
        k, o = kind(x['text'])
        if k == 'raw':
            text = ko_leaf
            ii = pay
        else:
            ls = leaves(o)
            rest = [s for s in dict.fromkeys(ls) if s not in G]
            assert len(rest) == 1, (i, rest)
            m = dict(G); m[rest[0]] = ko_leaf
            # repr keys (names) are in G and unchanged
            o2 = subst(o, m)
            if k == 'yaml':
                text = yaml.safe_dump(o2, allow_unicode=True).strip()
                assert subst(yaml.safe_load(text), {}) == o2
                ii = find_yaml(text, pay)
            else:
                text = str(o2)
                rp = repr(ko_leaf)
                q = rp[0]
                enc = repr(pay + q + '"')[1:-1]  # force escaping consistent? use direct method below
                ii = None
                # encode payload the same way as within the leaf's repr
                body = rp[1:-1]
                for a in range(len(body)):
                    pass
                e = pay.replace('\\', '\\\\').replace('\n', '\\n').replace('\t', '\\t')
                if q == "'": e = e.replace("'", "\\'")
                ii = e
        assert ii and ii in text, (i, ii)
        rec = {k2: x[k2] for k2 in ['label', 'source', 'subset', 'doc_type']}
        rec.update({'lang': 'ko', 'pair_id': x['id'], 'id': x['id'] + '-ko', 'text': text, 'injected_instruction': ii,
                    'origin': x['origin'], 'notes': x['notes'], 'core': x['core'], 'translation_notes': ''})
        out.append(rec)
    with open(OUT, 'w', encoding='utf-8') as f:
        for rec in out:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    print('wrote', len(out))

if __name__ == '__main__':
    main()
