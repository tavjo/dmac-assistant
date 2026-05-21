"""DL-005: sys.path-insert pattern for tools.e2e.* imports under pytest.

Adapted from tools/hibayes/conftest.py:1-30. The repo root is reached at
parents[2] from this file's location (tools/e2e/conftest.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def pytest_configure(config) -> None:  # type: ignore[no-untyped-def]
    """Register custom markers used by tools/e2e/tests/* to avoid PytestUnknownMarkWarning."""
    config.addinivalue_line(
        "markers",
        "no_autostub_tb: opt out of the autouse _build_typebuilder_for_query stub.",
    )
