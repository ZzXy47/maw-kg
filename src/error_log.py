#!/usr/bin/env python3
"""MAW-KG local error log — the capture layer of the report pipeline.

Design contract (privacy red line):
- This module ONLY writes to the user's own disk (work/errors.jsonl,
  gitignored). It never opens a socket. Nothing leaves the machine.
- Sending a report is a SEPARATE, explicit user action (src/report.py).

Each entry is one JSON line: timestamp, tool, error class/message, and the
minimum context needed to reproduce (repo key, sanitized arg shapes — values
are NOT recorded, only which keys were present, to avoid leaking user paths
or code snippets into a file users may later share).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

_ERROR_LOG = Path(__file__).resolve().parent.parent / "work" / "errors.jsonl"
_MAX_ENTRIES = 500          # ring buffer: keep the newest 500
_SENSITIVE_KEY_RE = re.compile(r"(token|key|secret|password|auth)", re.I)


def _shape(value) -> str:
    """Describe an argument's SHAPE, not its value (privacy: report bodies
    must never carry user code or paths unless the user pastes them)."""
    if isinstance(value, dict):
        return "{" + ",".join(sorted(
            f"{k}:{_shape(v)}" for k, v in value.items()
            if not _SENSITIVE_KEY_RE.search(str(k)))) + "}"
    if isinstance(value, (list, tuple)):
        return f"[{len(value)}x{type(value[0]).__name__ if value else '-'}]" if value else "[]"
    if isinstance(value, str):
        return f"str({len(value)})"
    return type(value).__name__


def record_error(tool: str, error: BaseException, args: dict | None = None,
                 extra: dict | None = None) -> None:
    """Append one error entry. Failure of the logger itself is swallowed —
    logging must never break the tool that is already failing."""
    try:
        _ERROR_LOG.parent.mkdir(parents=True, exist_ok=True)
        entry: dict = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime()),
            "tool": str(tool)[:64],
            "error": f"{type(error).__name__}: {error}"[:500],
            "arg_shapes": _shape(args or {}),
        }
        if extra:
            entry["extra"] = {k: str(v)[:200] for k, v in extra.items()}
        with open(_ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        _trim()
    except Exception:
        pass


def _trim() -> None:
    """Keep only the newest _MAX_ENTRIES lines (ring buffer)."""
    try:
        if not _ERROR_LOG.exists():
            return
        lines = _ERROR_LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > _MAX_ENTRIES:
            keep = lines[-_MAX_ENTRIES:]
            tmp = _ERROR_LOG.with_suffix(".tmp")
            tmp.write_text("\n".join(keep) + "\n", encoding="utf-8")
            os.replace(tmp, _ERROR_LOG)
    except Exception:
        pass


def read_entries(limit: int = 100) -> list[dict]:
    """Newest-first parsed entries (for report.py)."""
    try:
        if not _ERROR_LOG.exists():
            return []
        lines = _ERROR_LOG.read_text(encoding="utf-8").splitlines()
        out = []
        for line in reversed(lines[-limit:]):
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
        return out
    except Exception:
        return []
