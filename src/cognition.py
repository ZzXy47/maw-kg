#!/usr/bin/env python3
"""MAW-KG P4 — L4 contract cognition: FRAS entries + drift detection.

Alignment metric (v3.1 §2 L4): contract coverage = entries present / contracts
registered. NOT whole-repo file counts — partial authoring never red-flags the
governance state as long as registered contracts all have entries.

Drift classes (AOCI-informed):
  Missing   — contract has no L4 entry
  Stale     — entry exists but the provider file hash changed since entry authoring
  Orphan    — entry exists for a contract no longer registered
"""
from __future__ import annotations
import hashlib
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import contract_check as CC  # noqa: E402
from mcp_server import REPO_ROOTS  # noqa: E402

CONTRACTS = ROOT / "contracts" / "contracts.yaml"
COGNITION = ROOT / "contracts" / "cognition.yaml"


def file_hash(repo: str, rel: str) -> str:
    p = Path(REPO_ROOTS[repo]) / rel
    if not p.exists():
        return ""
    return hashlib.sha256(p.read_bytes()).hexdigest()


def provider_file(c) -> str:
    return c.provider.file


def run() -> dict:
    contracts = {c.id: c for c in CC.load_contracts(CONTRACTS)}
    cog = yaml.safe_load(COGNITION.read_text(encoding="utf-8")) or {}
    entries = cog.get("contracts", {})

    missing, stale, orphans = [], [], []
    aligned = 0
    for cid, c in contracts.items():
        e = entries.get(cid)
        if not e or not e.get("entry"):
            missing.append(cid)
            continue
        aligned += 1
        # stale check: provider file hash vs hash recorded at authoring (if present)
        recorded = e.get("provider_sha256")
        current = file_hash(c.provider.repo, provider_file(c))
        if recorded and recorded != current:
            stale.append({"contract": cid, "reason": "provider file changed since authoring",
                          "recorded": recorded[:12], "current": current[:12]})

    for cid in entries:
        if cid not in contracts:
            orphans.append(cid)

    total = len(contracts)
    coverage = round(aligned / total, 2) if total else 1.0
    return {
        "contracts_registered": total,
        "entries_present": aligned,
        "coverage": coverage,
        "aligned": coverage >= 1.0 and not stale,   # v3.1: contract-coverage metric
        "drift": {"missing": missing, "stale": stale, "orphan": orphans},
        # partial authoring never red-flags governance — it reports coverage honestly:
        "governance_state": ("aligned" if coverage >= 1.0 and not stale
                              else "partial" if not orphans and not stale else "attention"),
    }


def main():
    r = run()
    print(json.dumps(r, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
