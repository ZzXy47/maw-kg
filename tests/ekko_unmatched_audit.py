#!/usr/bin/env python3
"""ekko-studio unmatched-routes audit (Task B).

For each of the 208 routes with no client request() match, classify:
  client-string  — path string appears in client source but our extractor missed
                   the call form (extractor gap → improve)
  bin-mcp        — consumed by bin/*.mjs (MCP servers / CLI)
  desktop        — consumed by packages/desktop (Electron shell)
  test-only      — only referenced in tests/ (e.g. e2e)
  server-internal— referenced only by other server code (proxy/forward)
  docs-only      — only in docs
  no-reference   — no consumer anywhere in repo (possibly dead / external)
"""
import json, re, sys
from pathlib import Path
from collections import Counter

sys.path.insert(0, 'src')
from extractors import ts_koa_route, ts_request_template, path_norm, read

ROOT = Path('work/ekko-studio')

# rebuild route + call sets
routes = []
for f in (ROOT / 'packages/server/src/modules').rglob('routes/*.ts'):
    routes += ts_koa_route(read(f), f.relative_to(ROOT).as_posix())
calls = []
client_files = [f for f in (ROOT / 'packages/client/src').rglob('*')
                if f.is_file() and f.suffix in ('.ts', '.vue')]
for f in client_files:
    calls += ts_request_template(read(f), f.relative_to(ROOT).as_posix())

matched = set()
for r in routes:
    for c in calls:
        if r.method == c.method and path_norm(r.path, c.path):
            matched.add((r.method, r.path))
unmatched = [(r.method, r.path) for r in routes if (r.method, r.path) not in matched]
print(f'providers={len(routes)} matched={len(matched)} unmatched={len(unmatched)}')

# pre-load searchable text buckets
buckets = {}
def bucket(name, globs):
    parts = []
    for g in globs:
        for f in ROOT.glob(g):
            if f.is_file() and f.stat().st_size < 2_000_000:
                try: parts.append(f.read_text(encoding='utf-8', errors='replace'))
                except Exception: pass
    buckets[name] = '\n'.join(parts)

bucket('client',   ['packages/client/src/**/*.ts', 'packages/client/src/**/*.vue'])
bucket('bin',      ['bin/*.mjs', 'bin/**/*.mjs'])
bucket('desktop',  ['packages/desktop/**/*.ts', 'packages/desktop/**/*.js'])
bucket('tests',    ['tests/**/*.ts', 'tests/**/*.mjs'])
bucket('server',   ['packages/server/src/**/*.ts'])
bucket('docs',     ['docs/**/*.md', 'docs/**/*.json'])
bucket('ekko-agent', ['packages/ekko-agent/**/*.ts'])

def strip_params(p):
    return re.sub(r'/:[\w]+', '', p)

rows = []
for method, path in unmatched:
    # try exact path, then param-stripped, then prefix fragments
    base = strip_params(path)
    frags = [f for f in path.strip('/').split('/') if f and not f.startswith(':')]
    label = None
    for name in ('client', 'bin', 'desktop', 'tests', 'ekko-agent', 'server', 'docs'):
        text = buckets.get(name)
        if not text: continue
        if path in text or base in text:
            label = name if name != 'client' else 'client-string'
            break
    if label is None and len(frags) >= 2:
        # 2+ distinctive consecutive segments anywhere
        probe = '/'.join(frags[:2])
        for name in ('client', 'bin', 'desktop', 'tests', 'ekko-agent', 'server', 'docs'):
            text = buckets.get(name)
            if text and probe in text:
                label = name if name != 'client' else 'client-string'
                break
    if label is None:
        label = 'no-reference'
    rows.append({'method': method, 'path': path, 'bucket': label})

cnt = Counter(r['bucket'] for r in rows)
print('classification:', dict(cnt))
out = Path('tests/ekko-unmatched-audit.json')
out.write_text(json.dumps({'unmatched': len(rows), 'classification': dict(cnt), 'routes': rows},
                          ensure_ascii=False, indent=2), encoding='utf-8')
print('written:', out)
for b in ('client-string', 'no-reference'):
    sample = [r for r in rows if r['bucket'] == b][:8]
    print(f'\n--- {b} sample ({cnt.get(b,0)} total) ---')
    for r in sample: print(' ', r['method'], r['path'])
