#!/usr/bin/env python3
"""Classify the 74 client-string gaps by cause."""
import json, re, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, 'src')
from extractors import read

ROOT = Path('work/ekko-studio')
audit = json.load(open('tests/ekko-unmatched-audit.json', encoding='utf-8'))
rows = [r for r in audit['routes'] if r['bucket'] == 'client-string']

# gather all client files (ts + vue) incl. outside api/
client_files = [f for f in (ROOT/'packages/client/src').rglob('*') if f.suffix in ('.ts','.vue') and f.is_file()]
texts = {f: read(f) for f in client_files}

def strip_params(p): return re.sub(r'/:[\w]+', '', p)

causes = Counter()
detail = {}
for r in rows:
    base = strip_params(r['path'])
    cause = 'no-text-hit'
    for f, t in texts.items():
        if base not in t: continue
        rel = f.relative_to(ROOT).as_posix()
        # find each occurrence and inspect the surrounding call form
        for m in re.finditer(re.escape(base), t):
            ctx = t[max(0,m.start()-160):m.end()+200]
            if '?include' in ctx or '?' in t[m.end():m.end()+40].split("'")[0].split('"')[0].split('`')[0]:
                cause = 'query-string'; break
            if re.search(r'appendQuery\(|\bqs\b|URLSearchParams|buildQuery|withQuery', ctx):
                cause = 'query-helper'; break
            if re.search(r'const\s+\w*[Pp]ath\s*=\s*\(|=>\s*`', ctx) or re.search(r'\$\{[^}]*\}', t[m.start():m.end()+60]):
                cause = 'path-builder'; break
            if rel.endswith('.vue'):
                cause = 'vue-component'; break
            if 'request' not in ctx and 'fetch' not in ctx and 'http' not in ctx:
                cause = 'other-string-use'; break
            cause = 'request-in-file'
        if cause != 'no-text-hit': break
    causes[cause] += 1
    detail.setdefault(cause, []).append(f"{r['method']} {r['path']}")

print('causes:', dict(causes))
for c, items in detail.items():
    print(f'\n--- {c} ({len(items)}) sample ---')
    for i in items[:5]: print(' ', i)
json.dump({'causes': dict(causes), 'detail': detail}, open('tests/ekko-gap-causes.json','w',encoding='utf-8'), ensure_ascii=False, indent=2)
