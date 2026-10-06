#!/usr/bin/env python3
"""O-2: maw_detect_changes — git diff → changed SYMBOLS + contract association.

Borrowed semantics: GitNexus detect-changes maps diff hunks to indexed symbols
(Function X → file.kt). MAW-KG version: git diff -U0 hunks → nodes table
(file_path + line-span intersection) → changed symbols → contract fan-out via
the P2 local subgraph. Everything binds to real symbols; no synthesis.
"""
from __future__ import annotations
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from mcp_server import REPO_ROOTS, db_path  # noqa: E402
import contract_check as CC  # noqa: E402


def sync_repo(repo: str) -> bool:
    """Incremental CG sync so the nodes table matches the working tree.
    The resident CG daemon (MCP session) holds the DB lock — quiesce it first
    (tree-kill, orphan-safe), sync via CLI, then let the next query respawn."""
    import os
    import time as _t
    import mcp_server as MS
    try:
        MS.CG.quiesce()
    except Exception:
        pass
    _t.sleep(1.5)  # OS-level file-lock release after tree-kill
    env = {**os.environ, "CODEGRAPH_TELEMETRY": "0",
           "PATH": "C:/Program Files/nodejs;" + os.environ.get("PATH", "")}
    for attempt in range(3):
        r = subprocess.run(
            ["node", CG_SHIM, "sync"], capture_output=True, text=True,
            cwd=str(REPO_ROOTS[repo]), timeout=600, env=env)
        if r.returncode == 0:
            return True
        if "lock" not in (r.stderr or "").lower():
            return False
        _t.sleep(2.0 * (attempt + 1))  # locked → wait and retry
    return False


CG_SHIM = r"E:/CrossDevice_Agent_GitNexus_Pilot/tool-codegraph/node_modules/@colbymchenry/codegraph/npm-shim.js"


def _hunks(repo: str, ref: str) -> dict:
    """git diff -U0 → {file: [changed_line_numbers]}."""
    r = subprocess.run(
        ["git", "-C", REPO_ROOTS[repo], "diff", "-U0", "--name-only", ref],
        capture_output=True, text=True)
    files = [l.strip().replace("\\", "/") for l in r.stdout.splitlines() if l.strip()]
    r2 = subprocess.run(
        ["git", "-C", REPO_ROOTS[repo], "diff", "-U0", ref, "--numstat"],
        capture_output=True, text=True)
    # full hunk parse for line numbers:
    r3 = subprocess.run(
        ["git", "-C", REPO_ROOTS[repo], "diff", "-U0", ref],
        capture_output=True, text=True, encoding="utf-8", errors="replace")
    hunks = {}
    cur_file = None
    for line in r3.stdout.splitlines():
        if line.startswith("+++ b/"):
            cur_file = line[6:].replace("\\", "/")
            hunks.setdefault(cur_file, [])
        elif line.startswith("@@") and cur_file:
            m = re.match(r"@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@", line)
            if m:
                start = int(m.group(1))
                count = int(m.group(2) or 1)
                hunks[cur_file].extend(range(start, start + count))
    return hunks


def changed_symbols(repo: str, ref: str = "HEAD") -> list:
    """Map diff hunks to indexed symbols via line-span intersection."""
    hunks = _hunks(repo, ref)
    if not hunks:
        return []
    out = []
    con = sqlite3.connect(str(db_path(repo)))
    try:
        for f, lines in hunks.items():
            if not lines:
                continue
            lo, hi = min(lines), max(lines)
            for row in con.execute(
                "SELECT name, kind, file_path, start_line, end_line, qualified_name "
                "FROM nodes WHERE file_path = ? AND kind != 'file' "
                "AND start_line <= ? AND (end_line >= ? OR end_line = 0)",
                (f, hi, lo)):
                name, kind, fp, sl, el, qn = row
                span_lo, span_hi = sl, (el or sl)
                if span_lo <= hi and span_hi >= lo:  # line-span intersection
                    out.append({"symbol": name, "kind": kind, "file": fp,
                                "start_line": sl, "end_line": el,
                                "qualified_name": qn})
    finally:
        con.close()
    return out


def contract_fanout(repo: str, symbols: list) -> list:
    """Which contracts' endpoints ARE changed symbols (exact-name match only —
    no file-level heuristic: an unrelated new fn in an endpoint's file must NOT
    claim contract association; that's fabrication)."""
    contracts = CC.load_contracts(Path(__file__).resolve().parent.parent / "contracts" / "contracts.yaml")
    names = {s["symbol"] for s in symbols}
    hits = []
    for c in contracts:
        eps = [c.provider] + list(c.consumers)
        for ep in eps:
            if ep.repo == repo and ep.symbol.split(".")[-1] in names:
                hits.append({"contract": c.id,
                             "endpoint": f"{ep.repo}:{ep.symbol}",
                             "via": "direct-symbol-change"})
    return hits


def run(repo: str, ref: str = "HEAD") -> dict:
    # the index must reflect the CURRENT working tree for symbol mapping to be
    # truthful — sync first (CG incremental, typically <10s on small diffs)
    sync_repo(repo)
    syms = changed_symbols(repo, ref)
    return {
        "repo": repo, "ref": ref,
        "changed_files": len({s["file"] for s in syms}),
        "changed_symbols": syms,
        "contract_hits": contract_fanout(repo, syms),
    }


if __name__ == "__main__":
    repo = sys.argv[1] if len(sys.argv) > 1 else "ha-android"
    ref = sys.argv[2] if len(sys.argv) > 2 else "HEAD"
    import json
    print(json.dumps(run(repo, ref), ensure_ascii=False, indent=1))
