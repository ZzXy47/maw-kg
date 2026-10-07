#!/usr/bin/env python3
"""MAW-KG shared config resolution (single source of truth).

All machine-specific locations resolve in this order:
  1. Environment variables (MAW_KG_* — highest priority)
  2. repos.yaml next to the repo root (user-maintained, gitignored)
  3. Sensible defaults via shutil.which / standard install locations

Nothing in this file may hardcode a user's absolute paths (GitHub-ready).
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REPOS_YAML = ROOT / "repos.yaml"
CONTRACTS_YAML = ROOT / "contracts" / "contracts.yaml"

ENV_PREFIX = "MAW_KG_"


def env(name: str, default: str = "") -> str:
    """MAW_KG_<NAME> environment variable, or default."""
    return os.environ.get(ENV_PREFIX + name, "").strip() or default


def _repos_yaml_extra() -> dict:
    """Optional top-level keys in repos.yaml (besides `repos:`):
    node_exe / cg_shim / git_exe — machine-local tool paths, gitignored."""
    if REPOS_YAML.exists():
        try:
            import yaml  # noqa: F401
            data = yaml.safe_load(REPOS_YAML.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}
        except Exception:
            pass
    return {}


def resolve_node_exe() -> str:
    """Node.js interpreter: MAW_KG_NODE_EXE > repos.yaml node_exe >
    `node` on PATH > common installs."""
    v = env("NODE_EXE")
    if not v:
        v = str(_repos_yaml_extra().get("node_exe", "")).strip()
    if v and Path(v).exists():
        return v
    w = shutil.which("node")
    if w:
        return w
    for c in (r"C:\Program Files\nodejs\node.exe",
              "/usr/local/bin/node", "/usr/bin/node",
              "/opt/homebrew/bin/node"):
        if Path(c).exists():
            return c
    return "node"  # let subprocess raise the readable error


def resolve_cg_shim() -> str:
    """CodeGraph CLI shim (npm): MAW_KG_CG_SHIM > repos.yaml cg_shim >
    sibling tool-codegraph layout > `codegraph` on PATH."""
    v = env("CG_SHIM")
    if not v:
        v = str(_repos_yaml_extra().get("cg_shim", "")).strip()
    if v and Path(v).exists():
        return v
    # sibling install layout used by this repo's docs
    # <pilot>/tool-codegraph/node_modules/@colbymchenry/codegraph/npm-shim.js
    here = ROOT
    for base in (here.parent, here.parent.parent):
        cand = base / "tool-codegraph" / "node_modules" / "@colbymchenry" / "codegraph" / "npm-shim.js"
        if cand.exists():
            return str(cand)
    # a global/local node_modules install on disk
    w = shutil.which("codegraph")
    if w:
        return w
    return ""  # callers surface a clear error


def resolve_git_exe() -> str:
    """git: MAW_KG_GIT_EXE > repos.yaml git_exe > `git` on PATH > common Windows install."""
    v = env("GIT_EXE")
    if not v:
        v = str(_repos_yaml_extra().get("git_exe", "")).strip()
    if v and Path(v).exists():
        return v
    w = shutil.which("git")
    if w:
        return w
    for c in (r"C:\Program Files\Git\cmd\git.exe",):
        if Path(c).exists():
            return c
    return "git"


def node_path_prefix() -> str:
    """PATH addition for node children (Windows): dir of the resolved node exe."""
    node = resolve_node_exe()
    d = str(Path(node).parent) if node and Path(node).exists() else ""
    cur = os.environ.get("PATH", "")
    if d and d not in cur:
        return d + (os.pathsep if os.name == "nt" else ":") + cur
    return cur


def load_repos() -> dict:
    """Repo registry: repos.yaml `repos:` block > empty dict.

    repos.yaml is USER DATA (gitignored); the published tree ships
    repos.yaml.example only. Missing/corrupt yaml degrades to {} — callers
    must tell the user to copy the example file (never guess paths)."""
    if REPOS_YAML.exists():
        try:
            import yaml  # noqa: F401
            data = yaml.safe_load(REPOS_YAML.read_text(encoding="utf-8")) or {}
            repos = data.get("repos") if isinstance(data, dict) else {}
            if isinstance(repos, dict) and repos:
                return {str(k): str(v) for k, v in repos.items()}
        except Exception:
            pass
    return {}


REPO_ROOTS = load_repos()

NODE_EXE = resolve_node_exe()
CG_SHIM = resolve_cg_shim()
GIT_EXE = resolve_git_exe()
