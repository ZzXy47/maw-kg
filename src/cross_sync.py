#!/usr/bin/env python3
"""MAW-KG P2 — cross-repo contract sync (GitNexus group semantics, re-implemented)
+ detect-changes flow-impact on the CONTRACT LOCAL SUBGRAPH.

v3.1 §8 P2 scope:
- Contract sync = bind every contracts.yaml endpoint to real CodeGraph symbols.
  ANY binding failure → non-zero exit + failure list (no synthetic fallback).
- detect-changes (local subgraph): for changed files in a repo, walk the
  CodeGraph calls/imports edges *from the changed symbols up to the contract
  endpoints* — blast radius computed only over symbols that participate in a
  contract's subgraph (bounded by depth), never the whole 2M-edge graph.
"""
from __future__ import annotations
import json
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import contract_check as CC  # noqa: E402
from mcp_server import REPO_ROOTS, db_path, RepoGovernor  # noqa: E402

import shutil as _shutil
GIT_EXE = _shutil.which("git") or r"C:/Program Files/Git/cmd/git.exe"


MAX_SUBGRAPH_DEPTH = 4


def sync_contracts(contracts) -> dict:
    """Bind all endpoints to real symbols. Returns sync report; raises SystemExit
    on any failure (v3.1 principle #2 — no synthetic UIDs ever)."""
    report = {"contracts": [], "bindings": [], "failures": [], "ok": False}
    for c in contracts:
        entry = {"contract": c.id, "endpoints": []}
        eps = [("provider", c.provider)] + [(f"consumer[{i}]", ep) for i, ep in enumerate(c.consumers)]
        for role, ep in eps:
            dbp = db_path(ep.repo)
            if not dbp.exists():
                report["failures"].append(f"{c.id}/{role}: index missing for {ep.repo}")
                continue
            con = sqlite3.connect(str(dbp))
            try:
                row = CC.find_symbol(con, ep.file, ep.line, ep.symbol)
                if not row:
                    report["failures"].append(
                        f"{c.id}/{role}: {ep.symbol} not found at {ep.repo}:{ep.file}:{ep.line}")
                    continue
                report["bindings"].append({
                    "contract": c.id, "role": role,
                    "uid": row[0], "qualified_name": row[3],
                    "file": row[4], "line": row[5],
                    "real": not str(row[0]).startswith("manifest::"),
                })
                entry["endpoints"].append(f"{role}:{ep.repo}:{ep.symbol}")
            finally:
                con.close()
        report["contracts"].append(entry)
    report["ok"] = not report["failures"]
    if not report["ok"]:
        # principle #2: fail loudly, no synthetic degradation
        raise SystemExit(json.dumps({"sync": "FAILED", "failures": report["failures"]},
                                    ensure_ascii=False, indent=1))
    return report


def changed_files(repo: str, ref: str = "HEAD") -> set:
    r = subprocess.run([GIT_EXE, "-C", REPO_ROOTS[repo], "diff", "--name-only", ref],
                       capture_output=True, text=True)
    return {l.strip().replace("\\", "/") for l in r.stdout.splitlines() if l.strip()}


def local_subgraph_impact(contracts, repo: str, changed: set, depth: int = MAX_SUBGRAPH_DEPTH) -> dict:
    """For each contract endpoint in `repo`, walk UP the calls/references/imports
    edges (reverse) from the endpoint symbol, bounded by depth. If a changed
    file's symbol is reachable, the contract is impacted. Only contract-relevant
    edges are traversed — the full graph is never loaded."""
    t0 = time.time()
    impacts = []
    con = sqlite3.connect(str(db_path(repo)))
    try:
        for c in contracts:
            eps = [c.provider] + list(c.consumers)
            mine = [ep for ep in eps if ep.repo == repo]
            if not mine:
                continue
            # roots: all symbols defined in changed files
            roots = []
            qmarks = ",".join("?" * len(changed)) if changed else "''"
            for f in changed:
                roots.extend(r[0] for r in con.execute(
                    "SELECT id FROM nodes WHERE file_path = ?", (f,)))
            if not roots:
                continue
            # reverse BFS from contract endpoints upward; hit any root → impacted
            frontier = []
            for ep in mine:
                con2 = sqlite3.connect(str(db_path(ep.repo))) if ep.repo != repo else con
                try:
                    row = CC.find_symbol(con2, ep.file, ep.line, ep.symbol)
                    if row:
                        frontier.append(row[0])
                finally:
                    if ep.repo != repo:
                        con2.close()
            seen = set(frontier)
            reached_root = any(f in roots for f in frontier)  # endpoint itself in a changed file
            for d in range(depth):
                if reached_root or not frontier:
                    break
                qm = ",".join("?" * len(frontier))
                nxt = []
                for (src, dst) in con.execute(
                        f"""SELECT source,target FROM edges
                            WHERE target IN ({qm}) AND kind IN ('calls','references','imports')""",
                        frontier):
                    if src not in seen:
                        seen.add(src)
                        nxt.append(src)
                        if src in roots:
                            reached_root = True
                            break
                if reached_root:
                    break
                frontier = nxt
            if reached_root:
                impacts.append({
                    "contract": c.id,
                    "via": f"{repo} local subgraph (depth<={depth})",
                    "changed_files": sorted(changed),
                    "affected_endpoints": [f"{ep.repo}:{ep.symbol}" for ep in eps],
                })
    finally:
        con.close()
    return {"impacts": impacts, "elapsed_s": round(time.time() - t0, 2),
            "graph_scope": f"local-subgraph depth<={depth} (not full graph)"}


def main():
    contracts = CC.load_contracts(Path(ROOT / "contracts" / "contracts.yaml"))

    print("== P2 contract sync ==")
    report = sync_contracts(contracts)  # exits non-zero on failure
    real = sum(1 for b in report["bindings"] if b["real"])
    print(json.dumps({"sync": "OK", "bindings": len(report["bindings"]),
                      "real_symbol_bindings": real,
                      "synthetic": len(report["bindings"]) - real}, ensure_ascii=False))

    if len(sys.argv) > 2 and sys.argv[1] == "--detect-changes":
        repo, ref = sys.argv[2], sys.argv[3]
        changed = changed_files(repo, ref)
        if not changed:
            print(json.dumps({"detect_changes": "no changes"}, ensure_ascii=False))
            return
        result = local_subgraph_impact(contracts, repo, changed)
        print(json.dumps({"repo": repo, "ref": ref, **result}, ensure_ascii=False, indent=1))
    else:
        print(json.dumps({"sync_report": {"contracts": report["contracts"]}},
                         ensure_ascii=False, indent=1)[:1200])


if __name__ == "__main__":
    main()
