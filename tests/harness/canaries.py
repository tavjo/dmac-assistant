"""Canary sentinels for secret-leak tests.

This module starts minimal in T06. Later waves extend it; they do not rename
the stable symbols introduced here.
"""
from __future__ import annotations

from pathlib import Path


CANARY_SECRET: str = "CANARY-SMOKE-06-e3f8a2c1"


def scan_dir_for_secret(root: Path, needle: bytes) -> list[Path]:
    """Recursively find files beneath ``root`` that contain ``needle`` bytes.

    Later waves may add richer sentinel helpers, but this signature remains
    stable so existing smoke/live tests do not need to change.
    """
    hits: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        try:
            if needle in path.read_bytes():
                hits.append(path)
        except OSError:
            continue
    return hits
