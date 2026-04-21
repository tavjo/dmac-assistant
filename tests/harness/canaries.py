"""Canary sentinels + scanner for T09's secret-leak suite.

Each per-credential constant is generated fresh at module import via
:func:`secrets.token_hex`, so every pytest session gets distinct values.
A leaked sentinel from a prior run cannot false-positive a later run, and
committing a transient sentinel to the repo by accident is self-correcting
on the next import.

The scanner deliberately operates at the byte level: it does not split on
word boundaries, does not normalize casing, and does not care whether the
file is binary. Any occurrence of the raw sentinel string counts.

F7: directory traversal uses ``os.walk(..., followlinks=False)`` to
guarantee the scanner cannot be made to infinite-loop by a self-referential
symlink in a mounted tree. `Path.rglob` would follow symlinks by default.
"""
from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Iterable


# --- sentinels (fresh per process) -----------------------------------------

CANARY_AWS: str = f"CANARY-AWS-{secrets.token_hex(6)}"
CANARY_NX_USER: str = f"CANARY-NX-USER-{secrets.token_hex(6)}"
CANARY_NX_PASS: str = f"CANARY-NX-PASS-{secrets.token_hex(6)}"
# NEXTSEEK_URL: static (not random). Must contain a 'dev' segment to satisfy
# DD-21's hostname-segment allowlist. Still treated as a literal we want to
# detect on unexpected surfaces (e.g. a stack trace echoing the URL alongside
# credentials), so it joins ALL_CANARIES per DD-27/F5.
CANARY_NX_URL: str = "https://dev-nextseek.fake.mit.edu"

# T06 frozen symbol — stable sentinel shared with the smoke test.
# T06's merge condition in task-06-smoke-test.md explicitly pins this
# name + value; T09 is T06's extension, not a replacement.
# Must not change without coordinated updates to T06.
CANARY_SECRET: str = "CANARY-SMOKE-06-e3f8a2c1"

ALL_CANARIES: list[str] = [
    CANARY_AWS,
    CANARY_NX_USER,
    CANARY_NX_PASS,
    CANARY_NX_URL,
]


# --- scanner ---------------------------------------------------------------

def _iter_files(paths: Iterable[Path]) -> Iterable[Path]:
    """Yield every regular file under ``paths``, WITHOUT following symlinks.

    F7: `Path.rglob` follows symlinks by default, so a self-referential
    symlink in a mounted tree would cause an infinite loop. We use
    ``os.walk(p, followlinks=False)`` to bound the walk.
    """
    for p in paths:
        if not p.exists():
            continue
        if p.is_file():
            yield p
        elif p.is_dir():
            for root, _dirs, files in os.walk(p, followlinks=False):
                for name in files:
                    yield Path(root) / name


def scan_for_canaries(
    streams: list[bytes | str],
    paths: list[Path],
    canaries: list[str],
) -> list[tuple[str, str]]:
    """Scan the given streams and filesystem paths for any canary sentinel.

    Each stream element is addressed as ``stream[<idx>]`` in the returned
    ``where_found``. Files are scanned at byte level; binary files are safe.
    Missing paths are silently skipped. Directories are walked recursively
    without following symlinks (F7).
    """
    canary_bytes = [(c, c.encode("utf-8")) for c in canaries]
    hits: list[tuple[str, str]] = []

    for idx, payload in enumerate(streams):
        if isinstance(payload, str):
            payload = payload.encode("utf-8")
        for canary, needle in canary_bytes:
            if needle in payload:
                hits.append((canary, f"stream[{idx}]"))

    for path in _iter_files(paths):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        for canary, needle in canary_bytes:
            if needle in data:
                hits.append((canary, str(path)))

    return hits


def scan_dir_for_secret(root: Path, needle: bytes) -> list[Path]:
    """Return every regular file under ``root`` that contains ``needle``.

    Cross-spec helper consumed by T07 and T08 to scan the ``.claude/`` mount
    and ``/data/scratch`` trees for a single secret after a live run. Does
    not follow symlinks (F7). Missing roots are silently treated as empty.
    """
    hits: list[Path] = []
    for path in _iter_files([root]):
        try:
            data = path.read_bytes()
        except OSError:
            continue
        if needle in data:
            hits.append(path)
    return hits
