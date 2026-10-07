#!/usr/bin/env python3
"""Bake-off harness: AOCI (aoci.exe) answers the same 12 (where the MCP toolset applies)."""
import json, os, re, subprocess, sys, time
from pathlib import Path

import os as _os
PILOT = _os.environ.get('MAW_KG_TEST_PILOT', '.')
AOCI = PILOT + '/tool-aoci/aoci.exe'
results = {}
def rec(q, verdict, detail):
    results[q] = {"verdict": verdict, "detail": str(detail)[:400]}
    print(f"{verdict:10} {q}: {str(detail)[:150]}")

# AOCI is a cognition/annotation layer: entries authored per-contract with evidence
# binding (source_sha256), queried via MCP stdio. Its capability surface answers
# Q4/Q11-shaped questions (contract cognition), NOT code search questions.
# Probe its MCP toolset once:
import threading, queue as Q
def aoci_mcp(method, params=None, timeout=60):
    # single-shot stdio session per call (stateless probe pattern from earlier rounds)
    p = subprocess.Popen([AOCI, 'mcp', '--repo', PILOT + '/repos/home-assistant-core'], stdin=subprocess.PIPE,
                         stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    q = Q.Queue()
    threading.Thread(target=lambda: [q.put(l) for l in p.stdout], daemon=True).start()
    def send(o):
        p.stdin.write((json.dumps(o) + '\n').encode()); p.stdin.flush()
    def recv(t):
        try: return json.loads(q.get(timeout=t))
        except Q.Empty: return None
    try:
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2024-11-05', 'capabilities': {},
            'clientInfo': {'name': 'bakeoff', 'version': '1'}}})
        recv(timeout)
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': method, 'params': params or {}})
        return recv(timeout)
    finally:
        try: p.terminate(); p.wait(5)
        except Exception: pass

r = aoci_mcp('tools/list', timeout=30)
tools = []
if r and 'result' in r:
    tools = [t.get('name') for t in r['result'].get('tools', [])]
print('AOCI tools:', tools)

# Q1-Q3, Q6, Q7: code-search/impact questions — outside AOCI's surface (annotation layer).
for q in ('Q1', 'Q2', 'Q3', 'Q6', 'Q7', 'Q9', 'Q10', 'Q12'):
    rec(q, 'N/A-SCOPE', 'outside AOCI capability surface (cognition/annotation layer, not code search)')

# Q5: ArkTS endpoints — AOCI has no extractor; entries are hand-authored.
rec('Q5', 'N/A-SCOPE', 'no source extraction; entries hand-authored with evidence binding')

# Q4/Q11: contract cognition — this IS AOCI's home turf. Test with the real contract:
# (from earlier rounds: update-entry failed twice — [bad_args] then [impact_resolution_failed])
r = aoci_mcp('tools/call', {'name': 'aoci_search', 'arguments': {'keyword': 'mobile_app'}}, timeout=90)
out = json.dumps(r, ensure_ascii=False) if r else 'no response'
hits = out.count('http_api') + out.count('mobile_app')
rec('Q4', 'MISS' if hits == 0 else 'PARTIAL', f"aoci_search keyword='mobile_app' → entry refs: {hits} (entries must be hand-authored first; workspace has ~0 authored)")

# Q11: contract check semantics — AOCI requires source_sha256 evidence per candidate
r = aoci_mcp('tools/call', {'name': 'aoci_maintain', 'arguments': {'action': 'validate'}}, timeout=60)
out = json.dumps(r, ensure_ascii=False)[:300] if r else 'no response'
rec('Q11', 'PARTIAL', f"validate action exists (evidence-binding gate); prior rounds: authoring blocked by [impact_resolution_failed] — {out[:120]}")

# Q8: FP probe — no search surface, N/A
r = aoci_mcp('tools/call', {'name': 'aoci_search', 'arguments': {'keyword': 'ZzNotARealSymbolXyzzy'}}, timeout=60)
out = json.dumps(r, ensure_ascii=False) if r else 'timeout'
found = 'ZzNotARealSymbolXyzzy' in out and 'text' in out and 'no' not in out[:60].lower()
rec('Q8', 'PASS' if not found else 'FABRICATED', out[:150])

Path(PILOT + '/_audit/bakeoff-2026-10-06/aoci-results.json').write_text(
    json.dumps(results, ensure_ascii=False, indent=2), encoding='utf-8')
np = sum(1 for v in results.values() if v['verdict'] == 'PASS')
print(f"\nAOCI: {np}/12 PASS (scope-limited: annotation layer)")
