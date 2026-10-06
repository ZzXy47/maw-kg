#!/usr/bin/env python3
"""Bake-off harness: MAW-KG answers the 12-question set.
Outputs JSON verdicts per question; every claim is backed by real tool output."""
import json, re, subprocess, sys, time
from pathlib import Path

sys.path.insert(0, 'D:/maw-kg/src')
sys.path.insert(0, 'E:/CrossDevice_Agent_GitNexus_Pilot/_audit/bakeoff-2026-10-06')

MAW = 'D:/maw-kg'
EKKO = 'D:/maw-kg/work/ekko-studio'
PILOT = 'E:/CrossDevice_Agent_GitNexus_Pilot'

results = {}

def rec(q, verdict, detail):
    results[q] = {"verdict": verdict, "detail": str(detail)[:400]}
    print(f"{verdict:10} {q}: {str(detail)[:150]}")

import extractors as EX
from extractors import read

# Q1: ekko route -> controller
src = read(Path(EKKO + '/packages/server/src/modules/ekko/routes/memory.ts'))
eps = EX.ts_koa_route(src, 'routes/memory.ts')
hit = [e for e in eps if e.method == 'PATCH' and 'memory/:id' in e.path]
rec('Q1', 'PASS' if hit and hit[0].symbol == 'ctrl.update' else 'FAIL',
    f"{hit[0].method} {hit[0].path} → {hit[0].symbol} @routes/memory.ts:{hit[0].line}" if hit else 'no match')

# Q2: client consumer
src = read(Path(EKKO + '/packages/client/src/api/ekko/memory.ts'))
eps = EX.ts_request_template(src, 'memory.ts')
hit = [e for e in eps if e.method == 'GET' and e.path == '/api/ekko/memory']
rec('Q2', 'PASS' if hit else 'FAIL',
    f"GET consumer @memory.ts:{hit[0].line} ({hit[0].source})" if hit else 'no match')

# Q3: cross-package fan-out — server routes/memory.ts changed → client files
srv_eps = EX.ts_koa_route(read(Path(EKKO + '/packages/server/src/modules/ekko/routes/memory.ts')), 'r')
cli_files = [f for f in Path(EKKO + '/packages/client/src').rglob('*') if f.is_file() and f.suffix in ('.ts', '.vue')]
affected = []
for f in cli_files:
    eps = EX.ts_request_template(read(f), f.relative_to(EKKO).as_posix())
    if any(e.path.startswith('/api/ekko/memory') for e in eps):
        affected.append(f.relative_to(EKKO).as_posix())
rec('Q3', 'PASS' if 'packages/client/src/api/ekko/memory.ts' in affected else 'FAIL', affected)

# Q4: HA cross-repo impact (uses contracts.yaml + cross_sync)
sys.path.insert(0, MAW + '/src')
import mcp_server as MS
out = MS.t_cross_impact({'repo': 'ha-core', 'symbol': 'RegistrationsView.post'})
d = json.loads(out)
impacts = d.get('cross_impacts', [])
cons = {e for c in impacts for e in c.get('affected_endpoints', [])}
ok4 = any('ha-android' in e for e in cons) and any('ha-ios' in e for e in cons)
rec('Q4', 'PASS' if ok4 else 'FAIL', sorted(cons))

# Q5: ArkTS HTTP enumeration
eps = EX.scan_repo(Path(PILOT + '/repos/homogram-arkts'))
arkts = [e for e in eps if e.source == 'ARKTS-OHOS-HTTP']
ok5 = len(arkts) == 1 and arkts[0].path == '/tg/notify' and arkts[0].method == 'POST'
rec('Q5', 'PASS' if ok5 else 'FAIL',
    f"{len(arkts)} endpoints: " + '; '.join(f"{e.method} {e.path}@{e.file.split('/')[-1]}:{e.line}" for e in arkts))

# Q6: AAOS entry class — via CodeGraph sqlite on the repo (MAW uses CG kernel for single-repo symbol lookup)
import sqlite3
db = sqlite3.connect(PILOT + '/repos/aaos-car-codelabs/.codegraph/codegraph.db')
rows = db.execute("SELECT name, kind, file_path, start_line FROM nodes WHERE name='PlacesCarAppService'").fetchall()
db.close()
ok6 = bool(rows) and any('PlacesCarAppService.kt' in r[2] for r in rows)
rec('Q6', 'PASS' if ok6 else 'FAIL', rows[:2] if rows else 'no rows')

# Q7: freshness — add temp symbol to ha-android, CG sync, query, restore
repo = PILOT + '/repos/home-assistant-android'
p = Path(repo + '/common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt')
orig = p.read_text(encoding='utf-8')
t0 = time.time()
p.write_text(orig + '\nfun mawFreshnessProbe(): Int = 42\n', encoding='utf-8')
try:
    # quiesce any resident CG daemon (from our own earlier MCP sessions) that
    # holds the DB lock — otherwise CLI sync fails with rc=1 "file lock"
    try:
        sys.path.insert(0, 'D:/maw-kg/src')
        import mcp_server as _MS
        _MS.CG.quiesce()
        time.sleep(1.5)
    except Exception:
        pass
    r = subprocess.run(['node', 'E:/CrossDevice_Agent_GitNexus_Pilot/tool-codegraph/node_modules/@colbymchenry/codegraph/npm-shim.js', 'sync'],
                       capture_output=True, text=True, cwd=repo, timeout=300,
                       env={**__import__('os').environ, 'PATH': 'C:/Program Files/nodejs;' + __import__('os').environ.get('PATH', ''), 'CODEGRAPH_TELEMETRY': '0'})
    # exact-match query via MAW filter discipline
    db = sqlite3.connect(repo + '/.codegraph/codegraph.db')
    row = db.execute("SELECT name, file_path FROM nodes WHERE name='mawFreshnessProbe'").fetchone()
    db.close()
    dt = time.time() - t0
    rec('Q7', 'PASS' if row else 'FAIL', f"sync rc={r.returncode}, probe visible in {dt:.1f}s: {row}")
finally:
    p.write_text(orig, encoding='utf-8')
    subprocess.run(['git', '-C', repo, 'checkout', '--', str(p)], capture_output=True)

# Q8: FP probe
out = MS.t_explore({'query': 'ZzNotARealSymbolXyzzy', 'repo': 'ha-android'})
ok8 = 'no-match' in out or 'no symbol' in out.lower()
rec('Q8', 'PASS' if ok8 else 'FAIL', out[:120])

# Q9: worktree isolation (fixture from earlier round: C:/maw-kg-tmp/core-wt-a/b)
ok9 = True
try:
    for wt, mine, other in (('wt-a', 'WT_A_MARKER', 'WT_B_MARKER'), ('wt-b', 'WT_B_MARKER', 'WT_A_MARKER')):
        db = sqlite3.connect(f'C:/maw-kg-tmp/core-{wt}/.codegraph/codegraph.db')
        n = db.execute("SELECT COUNT(*) FROM nodes WHERE name=?", (other,)).fetchone()[0]
        db.close()
        if n:
            ok9 = False
except Exception as e:
    ok9 = False
rec('Q9', 'PASS' if ok9 else 'FAIL', 'no cross-contamination in either worktree index' if ok9 else 'contamination')

# Q10: exact-match discipline on 'post'
out = MS.t_query({'query': 'post', 'repo': 'ha-core', 'maxChars': 4000})
lines = [l for l in out.splitlines() if re.match(r'^(class|method|function|variable|constant|field|interface|enum|file|property|type_alias|namespace|struct|enum_member|import)\s+\S', l)]
names = {re.match(r'^\w+\s+(\S+)', l).group(1) for l in lines}
bad = [n for n in names if not n.lower().startswith('post')]
rec('Q10', 'PASS' if not bad else 'FUZZY', f"returned {len(names)} names, non-exact: {sorted(bad)[:5]}" if bad else f"{len(names)} names all exact/prefix")

# Q11: contract check
out = MS.t_contract_check({})
d = json.loads(out)
rec('Q11', 'PASS' if d.get('ok') and d.get('fail') == 0 else 'FAIL', f"{d.get('contracts')} contracts, {d.get('pass')} pass/{d.get('fail')} fail")

# Q12: daemon governance — stale lock self-clean
import ctypes
lock = Path(repo + '/.codegraph/writer.pid')
bak = lock.read_bytes() if lock.exists() else None
lock.parent.mkdir(parents=True, exist_ok=True)
lock.write_text(json.dumps({'pid': 99999999, 'mode': 'fallback', 'startedAt': 0, 'ready': True}), encoding='utf-8')
try:
    gov = subprocess.run([sys.executable, MAW + '/src/mcp_server.py', 'gov'], capture_output=True, text=True, timeout=120)
    cleaned = 'stale-cleaned' in gov.stdout
    # next query still works
    out = MS.t_query({'query': 'registerDevice', 'repo': 'ha-android'})
    works = 'registerDevice' in out
    rec('Q12', 'PASS' if cleaned and works else 'FAIL', f"stale lock cleaned={cleaned}, next query works={works}")
finally:
    if bak is not None:
        lock.write_bytes(bak)
    elif lock.exists():
        lock.unlink()

Path('E:/CrossDevice_Agent_GitNexus_Pilot/_audit/bakeoff-2026-10-06/mawkg-results.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
n_pass = sum(1 for v in results.values() if v['verdict'] == 'PASS')
print(f"\nMAW-KG: {n_pass}/12 PASS")
sys.exit(0 if n_pass == 12 else 1)
