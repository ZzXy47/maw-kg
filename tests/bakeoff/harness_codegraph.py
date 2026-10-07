#!/usr/bin/env python3
"""Bake-off harness: CodeGraph (raw kernel, no MAW layer) answers the same 12."""
import json, os, re, sqlite3, subprocess, sys, time
from pathlib import Path

MAW = 'D:/maw-kg'
EKKO = 'D:/maw-kg/work/ekko-studio'
import os as _os
PILOT = _os.environ.get('MAW_KG_TEST_PILOT', '.')
NODE = 'C:/Program Files/nodejs/node.exe'
CG = PILOT + '/tool-codegraph/node_modules/@colbymchenry/codegraph/npm-shim.js'
ENV = {**os.environ, 'CODEGRAPH_TELEMETRY': '0', 'PATH': 'C:/Program Files/nodejs;' + os.environ.get('PATH', '')}

results = {}
def rec(q, verdict, detail):
    results[q] = {"verdict": verdict, "detail": str(detail)[:400]}
    print(f"{verdict:10} {q}: {str(detail)[:150]}")

def cg(*args, cwd, timeout=120):
    r = subprocess.run([NODE, CG, *args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', cwd=cwd, timeout=timeout, env=ENV)
    return r

# Q1: ekko route→handler. CodeGraph has no route-semantics; try query by route path string and by controller name.
r = cg('query', 'ekkoMemoryRoutes', cwd=EKKO, timeout=180)
hit = 'ekkoMemoryRoutes' in r.stdout
r2 = cg('query', 'update', cwd=EKKO, timeout=180)
ctrl = 'controllers/memory' in r2.stdout
rec('Q1', 'PARTIAL' if hit and ctrl else ('MISS', f'routeVar={hit} ctrlFile={ctrl}') if not (hit and ctrl) else 'ok',
    f"symbol query finds router var={hit}, controller fn in results={ctrl}; no route→handler semantics")

# Q2: client consumer. CG query for fetchEkkoMemory:
r = cg('query', 'fetchEkkoMemory', cwd=EKKO, timeout=180)
ok = 'fetchEkkoMemory' in r.stdout and 'memory' in r.stdout
rec('Q2', 'PASS' if ok else 'MISS', r.stdout[:120] if ok else 'not found')

# Q3: cross-package fan-out. CG has no cross-package contract layer; impact is symbol-graph only within repo.
r = cg('impact', 'ekkoMemoryRoutes', cwd=EKKO, timeout=180)
txt = r.stdout
ok = 'client' in txt.lower()
rec('Q3', 'MISS' if not ok else 'PARTIAL', f"impact output mentions client={ok}; single-repo symbol graph only, no server→client contract fan-out")

# Q4: HA cross-repo. CG is strictly single-repo: query each repo, no cross edges.
r = cg('impact', 'RegistrationsView', cwd=PILOT + '/repos/home-assistant-core', timeout=180)
cross = 'android' in r.stdout.lower() or 'ios' in r.stdout.lower() or 'home-assistant-android' in r.stdout.lower()
rec('Q4', 'MISS' if not cross else 'PARTIAL', f"cross-repo mentions in impact={cross} (strictly single-repo tool)")

# Q5: ArkTS enumeration — CG indexes .ets as File nodes only (zero symbols). No HTTP semantics.
db = sqlite3.connect(PILOT + '/repos/homogram-arkts/.codegraph/codegraph.db')
n_ets = db.execute("SELECT COUNT(*) FROM nodes WHERE kind='file' AND file_path LIKE '%.ets'").fetchone()[0]
n_sym = db.execute("SELECT COUNT(*) FROM nodes WHERE kind != 'file' AND file_path LIKE '%.ets'").fetchone()[0]
db.close()
rec('Q5', 'MISS' if n_sym == 0 else 'PARTIAL', f".ets: {n_ets} File nodes, {n_sym} symbol nodes — zero ArkTS symbols, no HTTP endpoint semantics")

# Q6: AAOS class lookup
db = sqlite3.connect(PILOT + '/repos/aaos-car-codelabs/.codegraph/codegraph.db')
rows = db.execute("SELECT name, file_path FROM nodes WHERE name='PlacesCarAppService'").fetchall()
db.close()
rec('Q6', 'PASS' if rows else 'MISS', rows[:1] if rows else 'no rows')

# Q7: freshness
repo = PILOT + '/repos/home-assistant-android'
p = Path(repo + '/common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt')
orig = p.read_text(encoding='utf-8')
t0 = time.time()
p.write_text(orig + '\nfun cgFreshnessProbe(): Int = 42\n', encoding='utf-8')
try:
    r = cg('sync', cwd=repo, timeout=300)
    db = sqlite3.connect(repo + '/.codegraph/codegraph.db')
    row = db.execute("SELECT name FROM nodes WHERE name='cgFreshnessProbe'").fetchone()
    db.close()
    dt = time.time() - t0
    rec('Q7', 'PASS' if row else 'FAIL', f"sync rc={r.returncode}, probe visible in {dt:.1f}s")
finally:
    p.write_text(orig, encoding='utf-8')
    subprocess.run(['git', '-C', repo, 'checkout', '--', str(p)], capture_output=True)

# Q8: FP probe
r = cg('query', 'ZzNotARealSymbolXyzzy', cwd=repo, timeout=120)
fab = bool(re.search(r'Found \d+ symbols', r.stdout)) or bool(re.search(r'^\w+\s{2,}\S', r.stdout, re.M))
rec('Q8', 'FABRICATED' if fab else 'PASS', (r.stdout[:150] or r.stderr[:100]).replace('\n', ' | '))

# Q9: worktree isolation — CG query is fuzzy segment match (WT_B query returns WT_A in wt-a index)
r = cg('query', 'WT_B_MARKER', cwd='C:/maw-kg-tmp/core-wt-a', timeout=120)
contam = 'WT_A_MARKER' in r.stdout
rec('Q9', 'FAIL' if contam else 'PASS', f"query WT_B in wt-a returned WT_A hit: {contam} (fuzzy segment match)")

# Q10: exact-match discipline
r = cg('query', 'post', cwd=PILOT + '/repos/home-assistant-core', timeout=180)
names = set(re.findall(r'^(?:class|method|function|variable|constant|field|interface|enum|file|property|type_alias|namespace|struct|enum_member)\s+(\S+)', r.stdout, re.M))
bad = sorted(n for n in names if not n.lower().startswith('post'))[:5]
rec('Q10', 'FUZZY' if bad else 'PASS', f"{len(names)} names; non-exact sample: {bad}" if bad else f"{len(names)} names")

# Q11: contracts — no contract layer at all
rec('Q11', 'MISS', 'no contract concept in tool')

# Q12: governance — CG CLI creates/kills its own daemon per invocation; stale writer.pid handling unknown. Simulate:
lock = Path(repo + '/.codegraph/writer.pid')
bak = lock.read_bytes() if lock.exists() else None
lock.parent.mkdir(parents=True, exist_ok=True)
lock.write_text(json.dumps({'pid': 99999999, 'mode': 'fallback', 'startedAt': 0, 'ready': True}), encoding='utf-8')
try:
    t0 = time.time()
    r = cg('query', 'registerDevice', cwd=repo, timeout=120)
    ok = 'registerDevice' in r.stdout and r.returncode == 0
    rec('Q12', 'PASS' if ok else 'FAIL', f"rc={r.returncode}, query ok={ok} in {time.time()-t0:.1f}s")
finally:
    if bak is not None:
        lock.write_bytes(bak)
    elif lock.exists():
        lock.unlink()

Path(PILOT + '/_audit/bakeoff-2026-10-06/codegraph-results.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
np = sum(1 for v in results.values() if v['verdict'] == 'PASS')
print(f"\nCodeGraph(raw): {np}/12 PASS")
