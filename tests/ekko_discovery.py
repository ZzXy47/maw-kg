#!/usr/bin/env python3
"""ekko-studio contract auto-discovery via MAW-KG extractors (forms 7+8)."""
import sys, json
from pathlib import Path

sys.path.insert(0, 'src')
from extractors import ts_koa_route, ts_request_template, path_norm, read

ROOT = Path('D:/maw-kg/work/ekko-studio')
routes, calls = [], []
route_files = list((ROOT / 'packages/server/src/modules').rglob('routes/*.ts'))
for f in route_files:
    rel = f.relative_to(ROOT).as_posix()
    routes += ts_koa_route(read(f), rel)
api_files = list((ROOT / 'packages/client/src/api').rglob('*.ts'))
for f in api_files:
    rel = f.relative_to(ROOT).as_posix()
    calls += ts_request_template(read(f), rel)
print(f'route files: {len(route_files)} | provider endpoints: {len(routes)}')
print(f'client api files: {len(api_files)} | consumer calls: {len(calls)}')

joined = []
for r in routes:
    for c in calls:
        if r.method == c.method and path_norm(r.path, c.path):
            joined.append((r.method, r.path, r.symbol, r.file, c.file, c.line))
print(f'auto-discovered route<->client matches: {len(joined)}')
for m, p, psym, pf, cf, cl in joined[:12]:
    print(f'  {m} {p}  {psym}  [{pf.split("/")[-1]}] <- client [{cf.split("/")[-1]}:{cl}]')

rpaths = {(r.method, r.path) for r in routes}
matched = {(m, p) for m, p, _, _, _, _ in joined}
unmatched = rpaths - matched
print(f'routes without client match: {len(unmatched)} (sample): {sorted(unmatched)[:5]}')

out = Path('tests/ekko-discovery.json')
out.write_text(json.dumps({
    'repo': 'ekko-studio', 'head': '0c28364',
    'route_files': len(route_files), 'providers': len(routes),
    'client_api_files': len(api_files), 'consumers': len(calls),
    'matches': [{'method': m, 'path': p, 'provider_symbol': s, 'provider_file': pf,
                 'consumer_file': cf, 'consumer_line': cl}
                for m, p, s, pf, cf, cl in joined],
}, ensure_ascii=False, indent=2), encoding='utf-8')
print(f'written: {out}')
