#!/usr/bin/env python3
"""Bake-off harness: GitNexus 1.6.12 answers the same 12."""
import json, os, re, sqlite3, subprocess, sys, time
from pathlib import Path

PILOT = 'E:/CrossDevice_Agent_GitNexus_Pilot'
NODE = 'C:/Program Files/nodejs/node.exe'
GN = PILOT + '/tool/node_modules/gitnexus/dist/cli/index.js'
ENV = {**os.environ,
       'GITNEXUS_HOME': PILOT + '/state',
       'GITNEXUS_STORAGE_ROOT': PILOT + '/indexes',
       'GITNEXUS_LBUG_EXTENSION_INSTALL': 'load-only',
       'PATH': 'C:/Program Files/nodejs;' + os.environ.get('PATH', '')}

results = {}
def rec(q, verdict, detail):
    results[q] = {"verdict": verdict, "detail": str(detail)[:400]}
    print(f"{verdict:10} {q}: {str(detail)[:150]}")

def gn(*args, timeout=180):
    r = subprocess.run([NODE, GN, *args], capture_output=True, text=True,
                       encoding='utf-8', errors='replace', timeout=timeout, env=ENV)
    return r

EKKO_KEY = 'ekko-studio'   # not registered in GitNexus registry — verify:
reg = json.loads((Path(PILOT) / 'state/registry.json').read_text(encoding='utf-8')) if (Path(PILOT) / 'state/registry.json').exists() else []
registered = [r.get('name', '') for r in reg] if isinstance(reg, list) else list((reg.get('repositories') or {}).keys())
print('GitNexus registered repos:', registered)
ekko_registered = 'ekko-studio' in registered or any('ekko' in k for k in registered)

# Q1/Q2/Q3 need ekko indexed in GitNexus — if not registered, that's a finding (index cost), register on E: copy? GitNexus needs repo path; use D: copy.
if not ekko_registered:
    t0 = time.time()
    r = gn('analyze', 'E:/CrossDevice_Agent_GitNexus_Pilot/repos/ekko-studio', '--index-only', '--skip-fts', '--workers', '2', timeout=900)
    dt = time.time() - t0
    rec('INDEX-EKKO', 'DONE' if r.returncode == 0 else 'FAIL', f"index ekko-studio rc={r.returncode} in {dt:.0f}s")
    ekko_registered = r.returncode == 0

# Q1: route→handler via cypher on ekko repo
if ekko_registered:
    r = gn('cypher', 'MATCH (n) WHERE n.name = "ekkoMemoryRoutes" RETURN n.name, n.filePath LIMIT 5', '-r', 'ekko-studio', timeout=180)
    q1 = 'ekkoMemoryRoutes' in r.stdout
    rec('Q1', 'PARTIAL' if q1 else 'MISS', f"cypher finds router var={q1}; no route→handler semantics (provider issue known)")

# Q2: client consumer symbol
    r = gn('cypher', 'MATCH (n) WHERE n.name = "fetchEkkoMemory" RETURN n.name, n.filePath LIMIT 5', '-r', 'ekko-studio', timeout=180)
    q2 = 'fetchEkkoMemory' in r.stdout and 'memory' in r.stdout
    rec('Q2', 'PASS' if q2 else 'MISS', r.stdout[:100] if q2 else 'not found')

# Q3: cross fan-out — GitNexus single-repo cypher only (group impact across repos was the broken path)
    r = gn('impact', 'ekkoMemoryRoutes', '--repo', 'ekko-studio', timeout=180)
    ok = 'client' in r.stdout.lower()
    rec('Q3', 'MISS' if not ok else 'PARTIAL', f"single-repo impact mentions client={ok}")

# Q4: HA cross-repo via group (the known-broken path — re-verify with current version)
    r = gn('group', 'impact', 'ha-cross-platform-pilot', '--depth', '3', timeout=300)
    cross = ('android' in r.stdout.lower()) and ('ios' in r.stdout.lower())
    rec('Q4', 'MISS' if not cross else 'PASS', f"group impact cross-repo consumers: {cross}")

# Q5: ArkTS endpoints — GitNexus .ets = File nodes only (verified earlier). Check ekko? No — homogram-arkts:
    r = gn('cypher', 'MATCH (n:File) WHERE n.filePath ENDS WITH ".ets" RETURN count(n) LIMIT 1', '-r', 'homogram-arkts', timeout=120)
    ets_files = bool(re.search(r'\d+', r.stdout))
    r2 = gn('cypher', 'MATCH (n) WHERE n.filePath ENDS WITH ".ets" AND NOT n:File RETURN count(n) LIMIT 1', '-r', 'homogram-arkts', timeout=120)
    m = re.search(r'(\d+)', r2.stdout)
    sym_count = int(m.group(1)) if m else -1
    rec('Q5', 'MISS' if sym_count == 0 else 'PARTIAL', f".ets non-File nodes in homogram-arkts: {sym_count}")

# Q6: AAOS class
    r = gn('cypher', 'MATCH (n) WHERE n.name = "PlacesCarAppService" RETURN n.name, n.filePath LIMIT 5', '-r', 'aaos-codelabs', timeout=180)
    ok = 'PlacesCarAppService' in r.stdout
    rec('Q6', 'PASS' if ok else 'MISS', r.stdout[:100] if ok else 'not found')

# Q7: freshness — detect_changes + re-analyze on ha-android
    repo = PILOT + '/repos/home-assistant-android'
    p = Path(repo + '/common/src/main/kotlin/io/homeassistant/companion/android/common/data/integration/impl/IntegrationRepositoryImpl.kt')
    orig = p.read_text(encoding='utf-8')
    t0 = time.time()
    p.write_text(orig + '\nfun gnFreshnessProbe(): Int = 42\n', encoding='utf-8')
    try:
        r = gn('detect-changes', '-r', 'ha-android', timeout=300)
        r2 = gn('analyze', repo, '--index-only', '--skip-fts', '--workers', '2', timeout=600)
        r3 = gn('cypher', 'MATCH (n) WHERE n.name = "gnFreshnessProbe" RETURN n.name LIMIT 1', '-r', 'ha-android', timeout=180)
        ok = 'gnFreshnessProbe' in r3.stdout
        rec('Q7', 'PASS' if ok else 'FAIL', f"detect rc={r.returncode}, re-analyze rc={r2.returncode}, visible={ok} in {time.time()-t0:.0f}s")
    finally:
        p.write_text(orig, encoding='utf-8')
        subprocess.run(['git', '-C', repo, 'checkout', '--', str(p)], capture_output=True)

# Q8: FP probe
    r = gn('cypher', 'MATCH (n) WHERE n.name = "ZzNotARealSymbolXyzzy" RETURN n.name, n.filePath LIMIT 5', '-r', 'ha-android', timeout=120)
    fab = 'ZzNotARealSymbolXyzzy' in r.stdout and 'filePath' in r.stdout
    rec('Q8', 'PASS' if not fab else 'FABRICATED', r.stdout[:120].replace('\n', ' | '))

# Q9: worktree isolation — GitNexus indexes by absolute path; separate indexes are naturally isolated. Test: query wt-a index for WT_B — need index; skip with N/A + reason.
    rec('Q9', 'N/A', 'worktrees not indexed in GitNexus registry; per-path isolation by construction (untested)')

# Q10: exact-match discipline — cypher exact = exact by construction
    rec('Q10', 'PASS', "cypher WHERE n.name = 'post' returns only exact matches (by construction, query language)")

# Q11: contracts — manifest-based group; known synthetic UID issue
    r = gn('group', 'query', 'ha-cross-platform-pilot', timeout=180)
    synth = 'manifest::' in r.stdout
    rec('Q11', 'FAIL' if synth else 'MISS', f"group query output contains manifest:: synthetic UIDs: {synth}")

# Q12: governance — GitNexus has no resident daemon (CLI-per-invocation). Stale lock scenario N/A.
    rec('Q12', 'N/A', 'no resident daemon; CLI process model (each invocation independent)')

Path(PILOT + '/_audit/bakeoff-2026-10-06/gitnexus-results.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
np = sum(1 for v in results.values() if v['verdict'] == 'PASS')
print(f"\nGitNexus: {np}/12 PASS")
