"""Opt-in live tests for regenerating the pinned stream-json init fixture."""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.live_docker
@pytest.mark.slow
def test_live_fixture_exists_for_pinned_image() -> None:
    fixture_dir = Path(__file__).parent / "fixtures"
    assert any(fixture_dir.glob("streamjson_init_*.jsonl"))
