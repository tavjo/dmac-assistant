"""Structural tests for the top-level README.md.

Task-09: README must mirror the SKILL.md shim list and never reference the
legacy nextseek-get name.
"""
from __future__ import annotations

from pathlib import Path

# tests/test_readme_md.py — 4 parents up = plugin root
PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
README_FILE = PLUGIN_ROOT / "README.md"


REQUIRED_SHIMS = [
    "nextseek-init",
    "nextseek-spec",
    "nextseek-validate",
    "nextseek-exec",
    "nextseek-call",
    "nextseek-vocab",
    "nextseek-session",
]


def test_readme_lists_all_shims() -> None:
    text = README_FILE.read_text()
    for shim in REQUIRED_SHIMS:
        assert shim in text, f"README.md missing shim reference: {shim!r}"


def test_readme_has_no_legacy_nextseek_get() -> None:
    text = README_FILE.read_text()
    assert "nextseek-get" not in text, (
        "README.md must not reference the legacy nextseek-get shim name"
    )


def test_readme_mentions_v2_cache_path() -> None:
    text = README_FILE.read_text()
    assert "v2" in text, "README.md should mention the v2 cache generation"
