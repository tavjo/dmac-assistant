"""Self-test for the autouse production-path guard."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest


def test_production_docs_dir_is_poisoned() -> None:
    """Using the default docs dir inside a test must raise RuntimeError."""
    try:
        constants = import_module("build_tools.ingest_nextseek_docs.constants")
    except ModuleNotFoundError:
        pytest.skip("constants module not yet created (pre-T2)")

    with pytest.raises(RuntimeError, match="production default path"):
        Path(constants.DEFAULT_DOCS_DIR).exists()


def test_production_claude_md_path_is_poisoned() -> None:
    """Using the default container CLAUDE.md path inside a test must raise."""
    try:
        constants = import_module("build_tools.ingest_nextseek_docs.constants")
    except ModuleNotFoundError:
        pytest.skip("constants module not yet created (pre-T2)")

    with pytest.raises(RuntimeError, match="production default path"):
        Path(constants.DEFAULT_CLAUDE_MD_PATH).exists()
