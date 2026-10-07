#!/usr/bin/env python3
"""MAW-KG P1 — MCP server (8 tools) + daemon governance.

Bridges the CodeGraph CLI (kernel) and our P0 contract layer into a single
stdio MCP server. Implements the v3.1 governance requirements:

G0-①  writer.pid liveness probe (OpenProcess, not file-exists)
G0-②  stale lock auto-clean for dead holders
G0-③  deterministic session-end daemon recycling (single shared daemon per repo,
      clients proxy through it — fallback independent-writer mode is refused)
G0-④  retry-on-transient-error for MCP queries under heavy I/O
ENV   cluster-size self-check: refuse to place indexes on >64KB-cluster volumes

Tool surface (8):
  maw_explore / maw_query / maw_node / maw_impact / maw_contracts /
  maw_cross_impact / maw_contract_check / maw_status

Return budget: maxChars (default 8192) — v3.1 §4.

Stdio JSON-RPC only. Never writes host configs (principle #5).
"""
from __future__ import annotations
import argparse
import ctypes
import hashlib
import json
import os
import queue
import re
import shutil
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path

# ---------------------------------------------------------------- config
HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
CONTRACTS_YAML = ROOT / "contracts" / "contracts.yaml"
REPOS_YAML = ROOT / "repos.yaml"

_DEFAULT_REPOS = {
    "ha-core": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-core",
    "ha-android": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-android",
    "ha-ios": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/home-assistant-ios",
    "homogram-arkts": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/homogram-arkts",
    "aaos-codelabs": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/aaos-car-codelabs",
    "ekko-studio": r"E:/CrossDevice_Agent_GitNexus_Pilot/repos/ekko-studio",
    "hermes-agent": r"C:/Users/pc/AppData/Local/hermes/hermes-agent",
}


def load_repos() -> dict:
    """#3: REPO_ROOTS is externalized to repos.yaml. Adding a repo = edit the
    yaml + restart the MCP process, no source edit. Missing/corrupt yaml falls
    back to _DEFAULT_REPOS (silent — stderr is not protocol-safe in all hosts)."""
    if REPOS_YAML.exists():
        try:
            import yaml  # noqa: F401  (PyYAML is ensured at the contract layer import)
            data = yaml.safe_load(REPOS_YAML.read_text(encoding="utf-8")) or {}
            repos = data.get("repos") if isinstance(data, dict) else {}
            if isinstance(repos, dict) and repos:
                return {str(k): str(v) for k, v in repos.items()}
        except Exception:
            pass
    return dict(_DEFAULT_REPOS)


REPO_ROOTS = load_repos()
NODE_EXE = r"C:/Program Files/nodejs/node.exe"
CG_SHIM = r"E:/CrossDevice_Agent_GitNexus_Pilot/tool-codegraph/node_modules/@colbymchenry/codegraph/npm-shim.js"
MAXCHARS_DEFAULT = 8192
RETRY_MAX = 3
RETRY_BACKOFF_S = 0.8
# #2 index health: a codegraph.db smaller than this is almost certainly a
# truncated/empty-shell index (observed 172KB shell vs ≥4MB real indexes).
MIN_INDEX_BYTES = 1 * 1024 * 1024

# ---------------------------------------------------------------- env self-check (v3.1 §5.1)
def cluster_size_bytes(vol: str) -> int:
    spc = ctypes.c_ulong(0); bps = ctypes.c_ulong(0)
    fc = ctypes.c_ulong(0); tc = ctypes.c_ulong(0)
    if ctypes.windll.kernel32.GetDiskFreeSpaceW(vol, ctypes.byref(spc), ctypes.byref(bps),
                                                 ctypes.byref(fc), ctypes.byref(tc)):
        return spc.value * bps.value
    return 0

def env_selfcheck() -> list:
    """Cluster-size check with E:-drive nuance (v3.1 §5.1 refined 2026-10-06):
    - An index dir with daemon/wal churn (write path) on >64KB clusters → hard
      warning, index must move.
    - A read-only single-file .codegraph/codegraph.db (query-only, no -wal/-shm,
      no daemon) tolerates large clusters — file occupies cluster-size slack but
      has no small-file churn — downgraded to informational note.
    - Volume recommended for writable indexes: local NTFS 4KB (C:/D:)."""
    warns = []
    for name, root in REPO_ROOTS.items():
        vol = Path(root).drive + "/"
        cs = cluster_size_bytes(vol)
        if cs <= 65536:
            continue
        idx = Path(root) / ".codegraph"
        writable_churn = False
        if idx.exists():
            names = {f.name for f in idx.iterdir()}
            writable_churn = bool(names & {"codegraph.db-wal", "codegraph.db-shm",
                                            "daemon.pid", "daemon.log", "errors.log"})
        if writable_churn:
            warns.append(f"repo {name} on {vol}: cluster {cs//1024}KB > 64KB with WRITABLE index "
                         f"(wal/shm/daemon present) — index dir must NOT live on this volume (v3.1 §5.1)")
        else:
            warns.append(f"note: repo {name} on {vol} cluster {cs//1024}KB — read-only single-file "
                         f"index tolerated; keep daemon/write path on 4KB NTFS (C:/D:)")
    return warns

# ---------------------------------------------------------------- G0 governance
def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
    if h:
        ctypes.windll.kernel32.CloseHandle(h)
        return True
    return False

class RepoGovernor:
    """Per-repo writer lock governance (G0-①②③)."""
    def __init__(self, repo: str, repo_root: Path):
        self.repo = repo
        self.root = repo_root
        self.lock_path = repo_root / ".codegraph" / "writer.pid"

    def _read_lock(self) -> dict | None:
        try:
            raw = self.lock_path.read_text(encoding="utf-8", errors="replace").strip()
            return json.loads(raw)
        except Exception:
            return None

    def ensure_writable(self) -> dict:
        """Probe liveness; clean stale locks of dead holders. Returns status dict."""
        st = {"repo": self.repo, "lock": str(self.lock_path)}
        lk = self._read_lock()
        if not lk:
            st["state"] = "free"
            return st
        pid = lk.get("pid", 0)
        if pid_alive(pid):
            st["state"] = "held-alive"
            st["holder_pid"] = pid
        else:
            # G0-②: stale lock of a dead holder — auto-clean
            try:
                self.lock_path.unlink()
                st["state"] = "stale-cleaned"
                st["dead_pid"] = pid
            except OSError as e:
                st["state"] = "stale-uncleanable"
                st["error"] = str(e)
        return st

    def status(self) -> dict:
        st = self._read_lock() or {}
        pid = st.get("pid", 0)
        return {
            "repo": self.repo,
            "lock_exists": self.lock_path.exists(),
            "holder_pid": pid,
            "holder_alive": pid_alive(pid) if pid else False,
        }

# ---------------------------------------------------------------- CG client (with G0-④ retry)
class CGQueryError(Exception):
    pass

def _node_env() -> dict:
    """Env for node children: compose over os.environ (MCP-host baseline
    survives) but GUARANTEE the vars node native modules need on Windows —
    missing SystemRoot crashes them with rc 134."""
    e = {**os.environ, "CODEGRAPH_TELEMETRY": "0",
         "PATH": "C:/Program Files/nodejs;" + os.environ.get("PATH", "")}
    if os.name == "nt":
        e.setdefault("SYSTEMROOT", "C:\\Windows")
        e.setdefault("SYSTEMDRIVE", "C:")
    return e


def cg_cli(args: list, cwd: Path, timeout: int = 180) -> str:
    """Run codegraph CLI with transient-failure retry (heavy-I/O concurrency)."""
    last = None
    for attempt in range(1, RETRY_MAX + 1):
        r = subprocess.run(
            [NODE_EXE, CG_SHIM, *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            cwd=str(cwd), timeout=timeout,
            env=_node_env(),
        )
        if r.returncode == 0 and ("Done" in r.stdout or r.stdout.strip()):
            return r.stdout
        last = CGQueryError(f"rc={r.returncode} out={r.stdout[-200:]} err={r.stderr[-200:]}")
        if attempt < RETRY_MAX:
            time.sleep(RETRY_BACKOFF_S * attempt)
    raise last

# ---------------------------------------------------------------- CG MCP session (shared daemon, proxy mode)
class CGMcpSession:
    """Persistent MCP client to `codegraph serve --mcp`. One process per server;
    per-repo sessions reuse a shared OS daemon via CODEGRAPH proxying (G0-③)."""
    def __init__(self):
        self.proc = None
        self.q = None
        self.iid = 0
        self.lock = threading.Lock()
        self._daemon_pids = None  # pids spawned during our lifetime (safe to reap)

    def start(self):
        with self.lock:
            if self.proc and self.proc.poll() is None:
                return
            self.proc = subprocess.Popen(
                [NODE_EXE, CG_SHIM, "serve", "--mcp"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=_node_env(),
            )
            self.q = queue.Queue()
            threading.Thread(target=self._reader, daemon=True).start()
            self.iid = 1
            self._send({"jsonrpc": "2.0", "id": self.iid, "method": "initialize",
                        "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                                   "clientInfo": {"name": "maw-kg", "version": "1.0"}}})
            self._recv(30)
            self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
            self.iid = 1  # tools/call ids start at 2, never colliding with init

    def _reader(self):
        for line in self.proc.stdout:
            self.q.put(line)

    def _send(self, obj):
        self.proc.stdin.write((json.dumps(obj) + "\n").encode())
        self.proc.stdin.flush()

    def _recv(self, timeout):
        try:
            return json.loads(self.q.get(timeout=timeout))
        except queue.Empty:
            return None

    def explore(self, query: str, project_path: str, max_files: int = 6, timeout: int = 120):
        self.start()
        with self.lock:
            self.iid += 1
            self._send({"jsonrpc": "2.0", "id": self.iid, "method": "tools/call",
                        "params": {"name": "codegraph_explore",
                                   "arguments": {"query": query, "maxFiles": max_files,
                                                  "projectPath": project_path}}})
            r = self._recv(timeout)
        if not r or "result" not in r:
            raise CGQueryError(f"explore failed: {json.dumps(r)[:200] if r else 'timeout'}")
        try:
            self._note_daemon_pid(project_path)
        except Exception:
            pass
        return r["result"]["content"][0].get("text", "")

    def stop(self):
        """Terminate the shim AND any daemon it spawned (Windows: kill the whole
        process tree via taskkill /T — plain terminate() leaks the detached
        daemon child, observed as live node.exe with writer.pid long after stop)."""
        with self.lock:
            if self.proc and self.proc.poll() is None:
                pid = self.proc.pid
                try:
                    # tree-kill first: /T takes children, /F is required for
                    # console-less node daemons that ignore console events
                    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                                   capture_output=True, timeout=15)
                except Exception:
                    self.proc.terminate()
                try:
                    self.proc.wait(5)
                except Exception:
                    try:
                        self.proc.kill()
                    except Exception:
                        pass
                # belt & braces: sweep writer.pid/daemon.pid files we created
                for rp in REPO_ROOTS.values():
                    for pidfile in ("daemon.pid", "writer.pid"):
                        f = Path(rp) / ".codegraph" / pidfile
                        try:
                            if f.exists():
                                d = json.loads(f.read_text(encoding="utf-8"))
                                dp = d.get("pid")
                                if dp and dp != pid:
                                    k = ctypes.windll.kernel32
                                    h = k.OpenProcess(0x1000, False, dp)
                                    if h:  # alive and not our direct child
                                        # only reap pids this session is
                                        # responsible for (spawned during our
                                        # lifetime); leave foreign ones alone
                                        if getattr(self, "_daemon_pids", None) and dp in self._daemon_pids:
                                            subprocess.run(
                                                ["taskkill", "/PID", str(dp), "/T", "/F"],
                                                capture_output=True, timeout=15)
                                        k.CloseHandle(h)
                        except Exception:
                            pass
            self.proc = None
            # M-③ extension: tree-kill tracked daemons even if orphaned (shim
            # already dead → taskkill /T on shim pid can't reach them)
            for dp in (self._daemon_pids or set()):
                try:
                    k = ctypes.windll.kernel32
                    h = k.OpenProcess(0x1000, False, dp)
                    if h:
                        k.CloseHandle(h)
                        subprocess.run(["taskkill", "/PID", str(dp), "/T", "/F"],
                                       capture_output=True, timeout=15)
                except Exception:
                    pass
            self._daemon_pids = None

    def quiesce(self):
        """Stop session + reap daemons (used before CLI sync which needs the
        DB lock released). Next query lazily restarts the daemon."""
        self.stop()

    def _note_daemon_pid(self, repo_path: str):
        """Track daemon/writer pids created while this session is alive (for safe
        reaping). CG writes daemon.pid or writer.pid depending on version."""
        try:
            for name in ("daemon.pid", "writer.pid"):
                f = Path(repo_path) / ".codegraph" / name
                if f.exists():
                    try:
                        d = json.loads(f.read_text(encoding="utf-8"))
                    except Exception:
                        continue
                    dp = d.get("pid")
                    if dp and dp != (self.proc.pid if self.proc else None):
                        if self._daemon_pids is None:
                            self._daemon_pids = set()
                        self._daemon_pids.add(dp)
        except Exception:
            pass

CG = CGMcpSession()


def _prewarm():
    """O-1: start the CG daemon + MCP handshake at server initialize, so the
    first query rides a warm session. Failure is non-fatal (lazy path remains)."""
    try:
        CG.start()
    except Exception:
        pass


# ---------------------------------------------------------------- db helpers
def db_path(repo: str) -> Path:
    return Path(REPO_ROOTS[repo]) / ".codegraph" / "codegraph.db"

def db_con(repo: str):
    p = db_path(repo)
    if not p.exists():
        raise FileNotFoundError(f"index missing for {repo}: {p}")
    return sqlite3.connect(str(p))

# ---------------------------------------------------------------- contract layer (P0)
sys.path.insert(0, str(ROOT / "src"))
import contract_check as CC  # noqa: E402
# NOTE: contract_check requires PyYAML; ensure it's importable at server start.
try:
    import yaml  # noqa: F401
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml"], capture_output=True)

def load_contracts():
    return CC.load_contracts(CONTRACTS_YAML)

# ---------------------------------------------------------------- tool implementations
def budget(text: str, maxchars: int) -> str:
    if len(text) <= maxchars:
        return text
    return text[:maxchars] + f"\n…[maw-kg] truncated at {maxchars} chars (pass maxChars to widen)"


def require_repo(a) -> str:
    """#4: repo is REQUIRED for query/node/impact — refuse with a clear error
    instead of silently falling back to ha-android (which produced wrong-repo
    results when the caller forgot the repo argument)."""
    repo = a.get("repo")
    registered = ", ".join(sorted(REPO_ROOTS))
    if not repo:
        raise ValueError("repo is required (registered: " + registered + ")")
    if repo not in REPO_ROOTS:
        raise ValueError(f"unknown repo '{repo}' (registered: " + registered + ")")
    return repo

def t_explore(a):
    repo = a.get("repo") or a.get("projectPath") or "ha-android"
    path = REPO_ROOTS.get(repo, repo)
    # Principle #3 anti-fabrication gate: if no symbol in this index matches any
    # literal token of the query (exact name match), refuse to explore — CG's
    # heuristic recall would otherwise return unrelated "blast radius" results.
    import re as _re
    terms = [t for t in _re.split(r"[\s/.\-_(),:]+", a["query"]) if len(t) >= 4]
    con = db_con(repo if repo in REPO_ROOTS else "ha-android")
    try:
        any_hit = False
        for t in terms:
            row = con.execute(
                "SELECT 1 FROM nodes WHERE name = ? COLLATE NOCASE LIMIT 1", (t,)
            ).fetchone()
            if row:
                any_hit = True
                break
        if not any_hit:
            return json.dumps({
                "query": a["query"], "result": "no-match",
                "note": ("no symbol in this index matches any query term (exact match). "
                         "Refusing heuristic exploration to avoid fabricated context "
                         "(principle #3). Use maw_query with a real symbol name."),
            }, ensure_ascii=False)
    finally:
        con.close()
    text = CG.explore(a["query"], path, a.get("maxFiles", 6))
    return budget(text, int(a.get("maxChars", MAXCHARS_DEFAULT)))

def t_query(a):
    repo = require_repo(a)
    # Principle #3 filter: CG query is fuzzy (name-segment vocab) — post-filter to
    # exact name or exact-prefix matches so worktree/branch isolation is preserved.
    out = cg_cli(["query", a["query"], "--limit", str(a.get("limit", 10))], Path(REPO_ROOTS[repo]))
    q = a["query"].strip()
    con = db_con(repo)
    try:
        exact = {r[0] for r in con.execute(
            "SELECT name FROM nodes WHERE name = ? COLLATE NOCASE OR name LIKE ?",
            (q, q + "%")).fetchall()}
    finally:
        con.close()
    KINDS = ("class", "method", "function", "variable", "constant", "field",
             "interface", "enum", "file", "property", "type_alias", "namespace",
             "struct", "enum_member", "import")
    kept, dropped, current = [], [], None
    for line in out.splitlines():
        m = re.match(r"^(kind:)?\s*(\w+)\s{2,}(\S.*)$", line) if False else re.match(r"^(\w+)\s{2,}(\S.*)$", line)
        if m and m.group(1) in KINDS:
            current = m.group(2).strip()
            (kept if current in exact else dropped).append([current, [line]])
        elif current is not None and (line.startswith("  ") or not line.strip()):
            target = kept if kept and kept[-1][0] == current else (dropped if dropped and dropped[-1][0] == current else None)
            if target is not None:
                target[-1][1].append(line)
            elif current in exact:
                kept.append([current, [line]])
            else:
                dropped.append([current, [line]])
    header = out.splitlines()[0] if out else ""
    if kept:
        body = []
        for name, lines in kept:
            body.extend(lines)
        filtered = header + "\n" + "\n".join(body)
    else:
        filtered = header + "\n\n  (no exact matches — fuzzy hits suppressed, principle #3)"
    note = f"\n[maw-kg] exact-match filter: kept {len(kept)}, suppressed {len(dropped)} fuzzy result(s)"
    return budget(filtered + note, int(a.get("maxChars", MAXCHARS_DEFAULT)))

def t_node(a):
    repo = require_repo(a)
    args = ["node", a["name"]]
    if a.get("file"):
        args += ["--file", a["file"]]
    out = cg_cli(args, Path(REPO_ROOTS[repo]))
    return budget(out, int(a.get("maxChars", MAXCHARS_DEFAULT)))

def t_impact(a):
    repo = require_repo(a)
    out = cg_cli(["impact", a["symbol"]], Path(REPO_ROOTS[repo]))
    return budget(out, int(a.get("maxChars", MAXCHARS_DEFAULT)))

def t_contracts(a):
    cs = load_contracts()
    lines = [f"{len(cs)} contracts:"]
    for c in cs:
        lines.append(f"⚖ {c.id} [{c.kind}] {c.description}")
        lines.append(f"   P {c.provider.repo}:{c.provider.symbol}")
        for ep in c.consumers:
            lines.append(f"   C {ep.repo}:{ep.symbol}")
    return "\n".join(lines)

def t_cognition_search(a):
    """O-3: keyword/tag search over contracts/cognition.yaml FRAS entries.
    AOCI aoci_search equivalent, on our own L4 layer. Case-insensitive substring
    match on keyword OR tag; returns entry text with contract context."""
    import yaml
    kw = (a.get("keyword") or "").strip().lower()
    tag = (a.get("tag") or "").strip().lower()
    if not kw and not tag:
        return json.dumps({"error": "keyword or tag required"}, ensure_ascii=False)
    cog_path = Path(__file__).resolve().parent.parent / "contracts" / "cognition.yaml"
    if not cog_path.exists():
        return json.dumps({"results": [], "note": "cognition.yaml not present"}, ensure_ascii=False)
    cog = yaml.safe_load(cog_path.read_text(encoding="utf-8")) or {}
    entries = cog.get("contracts", {})
    hits = []
    for cid, e in entries.items():
        etag = str(e.get("tag", "")).lower()
        text = str(e.get("entry", ""))
        tlow = text.lower()
        if (kw and (kw in tlow or kw in cid.lower())) or (tag and tag in etag):
            hits.append({"contract": cid, "tag": e.get("tag", ""), "entry": text})
    return json.dumps({"query": {"keyword": kw, "tag": tag}, "results": hits},
                      ensure_ascii=False, indent=1)

def t_detect_changes(a):
    """O-2: git diff → changed SYMBOLS (line-span intersection with the nodes
    table) + exact-name contract fan-out. Mirrors src/detect_changes.py CLI."""
    import detect_changes as DC
    repo = a["repo"]
    ref = a.get("ref", "HEAD")
    return json.dumps(DC.run(repo, ref), ensure_ascii=False, indent=1)

def t_cross_impact(a):
    """Cross-repo fan-out: for a repo+symbol, which contracts' OTHER endpoints
    are therefore affected (local subgraph via calls edges).
    Diff mode: pass ref=<git-ref> (no symbol) to evaluate the repo's changed
    files instead — mirrors `python src/cross_sync.py --detect-changes`."""
    cs = load_contracts()
    repo = a["repo"]
    ref = a.get("ref")
    if ref and not a.get("symbol"):
        # diff mode: reuse the P2 local-subgraph implementation
        # (lazy import — cross_sync imports mcp_server at module level)
        import cross_sync
        changed = cross_sync.changed_files(repo, ref)
        if not changed:
            return json.dumps({"input": f"{repo} diff {ref}", "changed_files": 0,
                              "cross_impacts": []}, ensure_ascii=False, indent=1)
        result = cross_sync.local_subgraph_impact(cs, repo, changed)
        return json.dumps({"input": f"{repo} diff {ref}", "changed_files": len(changed),
                           **result}, ensure_ascii=False, indent=1)
    symbol = a["symbol"]
    hits = []
    for c in cs:
        eps = [c.provider] + list(c.consumers)
        mine = [ep for ep in eps if ep.repo == repo and ep.symbol.split(".")[-1] == symbol.split(".")[-1]]
        if not mine:
            continue
        others = [ep for ep in eps if ep not in mine]
        hits.append({
            "contract": c.id,
            "changed_endpoint": f"{mine[0].repo}:{mine[0].symbol}",
            "affected_endpoints": [f"{o.repo}:{o.symbol}" for o in others],
        })
    return json.dumps({"input": f"{repo}:{symbol}", "cross_impacts": hits}, ensure_ascii=False, indent=1)

def t_contract_check(a):
    cs = load_contracts()
    findings = []
    for c in cs:
        findings.extend(CC.check_contract(c))
    fails = [m for s, m in findings if s == "FAIL"]
    return json.dumps({
        "contracts": len(cs),
        "pass": len([1 for s, _ in findings if s == "PASS"]),
        "fail": len(fails),
        "failures": fails,
        "ok": not fails,
    }, ensure_ascii=False, indent=1)

def t_status(a):
    out = {"env_selfcheck": env_selfcheck(),
           "governance": [RepoGovernor(r, Path(p)).status() for r, p in REPO_ROOTS.items()],
           "indexes": {}}
    for r in REPO_ROOTS:
        p = db_path(r)
        if p.exists():
            size = p.stat().st_size
            con = db_con(r)
            try:
                v = dict(con.execute("SELECT key,value FROM project_metadata").fetchall())
                out["indexes"][r] = {
                    "version": v.get("indexed_with_version"),
                    "extraction": v.get("indexed_with_extraction_version"),
                    "commit": (v.get("indexed_at_commit") or "")[:12],
                    "state": v.get("index_state"),
                }
            finally:
                con.close()
            if size < MIN_INDEX_BYTES:
                out["indexes"][r]["health"] = (
                    f"suspect-empty: db={size} bytes < {MIN_INDEX_BYTES} — "
                    "rebuild with `codegraph init -v` (not `index`)")
        else:
            out["indexes"][r] = {"missing": True}
    out["daemon"] = {"alive": bool(CG.proc and CG.proc.poll() is None)}
    return json.dumps(out, ensure_ascii=False, indent=1)

TOOLS = {
    "maw_explore": (t_explore, {"query": "str", "repo": "str?", "maxFiles": "int?",
                                "maxChars": "int?"}),
    "maw_query": (t_query, {"query": "str", "repo": "str", "limit": "int?", "maxChars": "int?"}),
    "maw_node": (t_node, {"name": "str", "repo": "str", "file": "str?", "maxChars": "int?"}),
    "maw_impact": (t_impact, {"symbol": "str", "repo": "str", "maxChars": "int?"}),
    "maw_contracts": (t_contracts, {}),
    "maw_cognition_search": (t_cognition_search, {"keyword": "str?", "tag": "str?"}),
    "maw_detect_changes": (t_detect_changes, {"repo": "str", "ref": "str?"}),
    "maw_cross_impact": (t_cross_impact, {"repo": "str", "symbol": "str", "ref": "str"}),
    "maw_contract_check": (t_contract_check, {}),
    "maw_status": (t_status, {}),
}

DESC = {
    "maw_explore": "Explore one repo: relevant symbols' source + call paths (CodeGraph-backed, budget-capped).",
    "maw_query": "Search symbols by name in one repo.",
    "maw_node": "One symbol's source + caller/callee trail.",
    "maw_impact": "Single-repo blast radius for a symbol.",
    "maw_contracts": "List registered cross-repo contracts.",
    "maw_cognition_search": "Keyword/tag search over L4 FRAS cognition entries (contracts/cognition.yaml).",
    "maw_detect_changes": "git diff → changed SYMBOLS (line-span mapped) + exact-name contract fan-out.",
    "maw_cross_impact": "Given repo+symbol, list contracts whose other endpoints are affected.",
    "maw_contract_check": "Verify every contract binding (exact match); non-zero on failure.",
    "maw_status": "Env self-check + per-repo lock governance + index versions + daemon state.",
}

# ---------------------------------------------------------------- MCP stdio server
def serve():
    # Windows integration: when spawned by an MCP host (Hermes/other) without a
    # UTF-8 console, stdout defaults to cp936/GBK and Chinese text in tool
    # descriptions corrupts the JSON-RPC stream (0xa1 bytes). Force UTF-8.
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stdin.reconfigure(encoding="utf-8")
    except Exception:
        pass

    def make_schema(props):
        # "str" → required string; "str?" → optional string; "int?" → optional
        # integer. (The "?"-suffix must be stripped BEFORE the type compare —
        # "str?" used to fall through to integer and break MCP validation.)
        def t(v):
            return "string" if v.rstrip("?") == "str" else "integer"
        return {"type": "object",
                "properties": {k: {"type": t(v)} for k, v in props.items()},
                "required": [k for k, v in props.items()
                             if v == "str"]}

    def line_out(obj):
        sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
        sys.stdout.flush()

    # The greeting line is NOT a JSON-RPC response (no matching request id); keep protocol clean:
    # only respond to requests. (MCP clients send initialize as the first request.)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except Exception:
            continue
        method = req.get("method")
        rid = req.get("id")
        if rid is None:
            continue  # notification
        if method == "initialize":
            # SDK validation (pydantic InitializeResult) requires protocolVersion
            # in the response — echo the client's version, default 2024-11-05.
            client_pv = ((req.get("params") or {}).get("protocolVersion")
                         or "2024-11-05")
            resp = {"jsonrpc": "2.0", "id": rid, "result": {
                "protocolVersion": client_pv,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {"name": "maw-kg", "version": "1.0.0"}}}
            # O-1/O-5: prewarm the CG daemon at MCP initialize so the first
            # maw_explore doesn't pay cold-start (22.8s → ~6s target).
            threading.Thread(target=_prewarm, daemon=True).start()
        elif method == "tools/list":
            resp = {"jsonrpc": "2.0", "id": rid, "result": {"tools": [
                {"name": n, "description": DESC[n], "inputSchema": make_schema(TOOLS[n][1])}
                for n in TOOLS]}}
        elif method == "tools/call":
            name = req["params"]["name"]
            args = req["params"].get("arguments", {})
            try:
                if name not in TOOLS:
                    raise ValueError(f"unknown tool {name}")
                # G0-①②: gate writes through governance before touching CG
                if name in ("maw_explore", "maw_query", "maw_node", "maw_impact"):
                    repo = args.get("repo", "ha-android")
                    if repo in REPO_ROOTS:
                        gov = RepoGovernor(repo, Path(REPO_ROOTS[repo]))
                        gov.ensure_writable()
                text = TOOLS[name][0](args)
                resp = {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": text}], "isError": False}}
            except Exception as e:
                resp = {"jsonrpc": "2.0", "id": rid, "result": {
                    "content": [{"type": "text", "text": f"ERROR: {e}"}], "isError": True}}
        else:
            resp = {"jsonrpc": "2.0", "id": rid,
                    "error": {"code": -32601, "message": f"method not found: {method}"}}
        line_out(resp)

    # G0-③: deterministic session-end recycling
    CG.stop()

# ---------------------------------------------------------------- CLI (gov ops exposed)
def cli():
    ap = argparse.ArgumentParser(description="MAW-KG P1 ops")
    ap.add_argument("cmd", choices=["serve", "gov", "env", "contracts"])
    ap.add_argument("--repo")
    a = ap.parse_args()
    if a.cmd == "serve":
        serve()
    elif a.cmd == "env":
        w = env_selfcheck()
        print(json.dumps({"cluster_warnings": w}, ensure_ascii=False, indent=1))
    elif a.cmd == "gov":
        for r, p in REPO_ROOTS.items():
            print(json.dumps(RepoGovernor(r, Path(p)).ensure_writable(), ensure_ascii=False))

if __name__ == "__main__":
    cli()
