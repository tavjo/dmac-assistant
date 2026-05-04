"""Verify container/CLAUDE.md skeleton and build_tools package scaffolding."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_CLAUDE_MD = REPO_ROOT / "container" / "CLAUDE.md"

BEGIN_MARKER = "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->"
END_MARKER = "<!-- END NEXTSEEK-DOCS (auto-generated) -->"


def test_container_claude_md_exists() -> None:
    assert CONTAINER_CLAUDE_MD.exists(), f"missing: {CONTAINER_CLAUDE_MD}"


def test_container_claude_md_has_markers_exactly_once_each() -> None:
    content = CONTAINER_CLAUDE_MD.read_text()
    assert content.count(BEGIN_MARKER) == 1
    assert content.count(END_MARKER) == 1


def test_container_claude_md_markers_are_in_correct_order() -> None:
    content = CONTAINER_CLAUDE_MD.read_text()
    begin_idx = content.index(BEGIN_MARKER)
    end_idx = content.index(END_MARKER)
    assert begin_idx < end_idx, "BEGIN marker must precede END marker"


def test_container_claude_md_block_is_populated() -> None:
    """The committed image instructions include generated NExtSEEK docs."""
    content = CONTAINER_CLAUDE_MD.read_text()
    begin_idx = content.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end_idx = content.index(END_MARKER)
    between = content[begin_idx:end_idx]
    assert "## NExtSEEK Documentation" in between
    assert "/app/docs/nextseek/README.md" in between


def test_container_claude_md_mentions_credentials_warning() -> None:
    """The skeleton must instruct the agent never to write credentials."""
    content = CONTAINER_CLAUDE_MD.read_text()
    assert "Never log, print, or write credentials" in content


def test_build_tools_package_is_importable() -> None:
    pkg = import_module("build_tools")
    assert pkg is not None


def test_ingest_nextseek_docs_package_is_importable() -> None:
    pkg = import_module("build_tools.ingest_nextseek_docs")
    assert pkg is not None
