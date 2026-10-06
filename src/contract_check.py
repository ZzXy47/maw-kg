#!/usr/bin/env python3
"""MAW-KG contract checker — P0.

Reads contracts.yaml, resolves every provider/consumer symbol against the
CodeGraph sqlite index of each repo (exact match only), normalizes path
variants, and reports PASS/FAIL per contract. Exit non-zero on any FAIL.

Also supports --check-diff <repo> <ref>: given a git diff, report which
contracts touch the changed files.

Design principles (v3.1 §6): #1 explicit contracts, #2 bind to real symbols,
#3 exact match only, #4 path normalization up front, #8 generated files excluded.
"""
from __future__ import annotations
import argparse
import json
import re
import sqlite3
import subprocess
import shutil as _shutil
GIT_EXE = _shutil.which("git") or r"C:/Program Files/Git/cmd/git.exe"
import sys
from dataclasses import dataclass, field
from pathlib import Path

try:
    import yaml  # PyYAML
except ImportError:
    yaml = None

# --- config ---
REPO_ROOTS = {
    "ha-core": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-core",
    "ha-android": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-android",
    "ha-ios": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-ios",
    "homogram-arkts": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/homogram-arkts",
    "aaos-codelabs": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/aaos-car-codelabs",
}

# path prefixes that differ between consumers/providers (PATH-NORM, v3.1 §7)
PATH_NORM_PREFIXES = ["/api"]

WEBHOOK_ID = "{webhook_id}"


def normalize_path(p: str) -> str:
    """Normalize a path variant for comparison: strip known base-prefix deltas,
    unify webhook id placeholders, lowercase trailing verb params, strip query."""
    s = (p or "").strip()
    if not s.startswith("/"):
        s = "/" + s
    # unify webhook placeholders
    s = re.sub(r"\{webhook_?id\}", WEBHOOK_ID, s, flags=re.I)
    s = re.sub(r":webhook_?id\b", WEBHOOK_ID, s, flags=re.I)
    # drop query/hash
    s = s.split("?", 1)[0].split("#", 1)[0]
    # collapse slashes
    s = re.sub(r"/{2,}", "/", s)
    # common prefix-equivalence: HAAPI builds {base}/mobile_app/... where core is /api/mobile_app/...
    # → compare on the LAST TWO segments + presence of a known mount
    return s


def path_fingerprint(p: str) -> str:
    """The comparable fingerprint: last meaningful segments after stripping the
    mount-point ambiguity ('/api' present on one side only is allowed for the
    same underlying route when the remaining path is identical)."""
    s = normalize_path(p)
    for pref in PATH_NORM_PREFIXES:
        if s.startswith(pref + "/"):
            s = s[len(pref):]
            break
    return s.strip("/").lower()


@dataclass
class Endpoint:
    repo: str
    symbol: str
    file: str
    line: int
    path_variant: str = ""


@dataclass
class Contract:
    id: str
    kind: str
    description: str
    provider: Endpoint
    consumers: list
    checks: list = field(default_factory=list)
    meta: dict = field(default_factory=dict)


# --- CodeGraph index access ---
def db_path(repo: str) -> Path:
    return Path(REPO_ROOTS[repo]) / ".codegraph" / "codegraph.db"


def is_generated_or_errored(con, file_rel: str) -> tuple:
    row = con.execute(
        "SELECT generated, errors FROM files WHERE path = ?", (file_rel,)
    ).fetchone()
    if not row:
        return (False, None)  # not tracked as file row → treat as not-excluded
    gen, errs = row
    return (bool(gen), errs)


def find_symbol(con, file_rel: str, line: int, symbol_hint: str):
    """Exact-match resolution: the symbol node at/near file:line whose simple
    name matches the last segment of symbol_hint. Returns row or None."""
    hint = symbol_hint.split(".")[-1]
    rows = con.execute(
        """SELECT id, kind, name, qualified_name, file_path, start_line, end_line
           FROM nodes
           WHERE file_path = ? AND name = ? AND start_line <= ? AND end_line >= ?""",
        (file_rel, hint, line, line),
    ).fetchall()
    if not rows:
        # tolerate off-by-a-few line drift (symbol grew/shrank between anchor and now)
        rows = con.execute(
            """SELECT id, kind, name, qualified_name, file_path, start_line, end_line
               FROM nodes
               WHERE file_path = ? AND name = ? AND ABS(start_line - ?) <= 5""",
            (file_rel, hint, line),
        ).fetchall()
    return rows[0] if rows else None


# --- checks ---
def check_contract(c: Contract) -> list:
    findings = []

    def bind(ep: Endpoint, role: str):
        dbp = db_path(ep.repo)
        if not dbp.exists():
            findings.append(("FAIL", f"[{c.id}] {role} repo {ep.repo}: index missing at {dbp}"))
            return None
        con = sqlite3.connect(str(dbp))
        try:
            gen, errs = is_generated_or_errored(con, ep.file)
            if gen:
                findings.append(("FAIL", f"[{c.id}] {role} file {ep.file} is GENERATED — excluded from contract binding (principle #8)"))
                return None
            if "symbol_exists" in [x if isinstance(x, str) else x.get("check") for x in ([] if not c.checks else c.checks)] or True:
                row = find_symbol(con, ep.file, ep.line, ep.symbol)
                if not row:
                    findings.append(("FAIL", f"[{c.id}] {role} symbol {ep.symbol} not found at {ep.file}:{ep.line} (exact match only, principle #3)"))
                    return None
                findings.append(("PASS", f"[{c.id}] {role} {ep.symbol} → {row[3]} @ {ep.file}:{row[5]}"))
                return row
        finally:
            con.close()

    prow = bind(c.provider, "provider")
    crows = [bind(ep, f"consumer[{i}]") for i, ep in enumerate(c.consumers)]

    if "path_match" in [x if isinstance(x, str) else x.get("check") for x in c.checks] or any("path_match" in str(x) for x in c.checks):
        fps = {}
        if c.provider.path_variant:
            fps["provider"] = path_fingerprint(c.provider.path_variant)
        for i, ep in enumerate(c.consumers):
            if ep.path_variant:
                fps[f"consumer[{i}]"] = path_fingerprint(ep.path_variant)
        vals = set(fps.values())
        if len(vals) > 1:
            findings.append(("FAIL", f"[{c.id}] path normalization mismatch: {fps}"))
        elif len(vals) == 1:
            findings.append(("PASS", f"[{c.id}] path variants normalized → '{vals.pop()}'"))
        # empty variant(s) are tolerated (not all kinds carry paths)

    bound_ok = prow is not None and all(r is not None for r in crows)
    if bound_ok:
        findings.append(("PASS", f"[{c.id}] all {1+len(c.consumers)} endpoints bound to real symbols"))
    return findings


def git_diff_files(repo: str, ref: str) -> set:
    r = subprocess.run(
        [GIT_EXE, "-C", REPO_ROOTS[repo], "diff", "--name-only", ref],
        capture_output=True, text=True,
    )
    return set(l.strip().replace("\\", "/") for l in r.stdout.splitlines() if l.strip())


def check_diff(contracts, repo: str, ref: str):
    changed = git_diff_files(repo, ref)
    hits = []
    for c in contracts:
        eps = [c.provider] + list(c.consumers)
        touched = [ep for ep in eps if ep.repo == repo and ep.file in changed]
        if touched:
            hits.append((c.id, [f"{ep.symbol} ({ep.file})" for ep in touched]))
    return hits


# --- yaml loading (stdlib fallback: tiny subset parser is NOT attempted; require PyYAML) ---
def load_contracts(path: Path) -> list:
    if yaml is None:
        print("ERROR: PyYAML required (pip install pyyaml)", file=sys.stderr)
        sys.exit(2)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    out = []
    for raw in data.get("contracts", []):
        prov = Endpoint(**raw["provider"])
        cons = [Endpoint(**x) for x in raw.get("consumers", [])]
        checks = []
        for ck in raw.get("checks", []):
            checks.append(ck if isinstance(ck, str) else ck.get("check", str(ck)))
        out.append(Contract(id=raw["id"], kind=raw.get("kind", "http"),
                            description=raw.get("description", ""),
                            provider=prov, consumers=cons, checks=checks,
                            meta=raw.get("meta", {})))
    return out


def main():
    ap = argparse.ArgumentParser(description="MAW-KG contract checker (P0)")
    ap.add_argument("--contracts", default="contracts/contracts.yaml")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--check-diff", nargs=2, metavar=("REPO", "REF"),
                    help="report contracts touched by a git diff in REPO vs REF")
    args = ap.parse_args()

    contracts = load_contracts(Path(args.contracts))

    if args.check_diff:
        repo, ref = args.check_diff
        hits = check_diff(contracts, repo, ref)
        if args.json:
            print(json.dumps({"repo": repo, "ref": ref, "affected": [
                {"contract": cid, "endpoints": eps} for cid, eps in hits]}, ensure_ascii=False, indent=1))
        else:
            print(f"Contracts affected by diff {repo} vs {ref}:")
            if not hits:
                print("  (none)")
            for cid, eps in hits:
                print(f"  ⚖ {cid}:")
                for e in eps:
                    print(f"      - {e}")
        return 0

    all_findings = []
    for c in contracts:
        all_findings.extend(check_contract(c))

    fails = [f for f in all_findings if f[0] == "FAIL"]
    passes = [f for f in all_findings if f[0] == "PASS"]

    if args.json:
        print(json.dumps({
            "contracts": len(contracts),
            "pass": len(passes), "fail": len(fails),
            "findings": [{"status": s, "msg": m} for s, m in all_findings],
        }, ensure_ascii=False, indent=1))
    else:
        for s, m in all_findings:
            print(f"{s}  {m}")
        print(f"\n{len(contracts)} contracts | {len(passes)} pass | {len(fails)} fail")
        if fails:
            print("RESULT: FAIL (bindings must resolve exactly — no silent degradation)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
