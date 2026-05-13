"""Structural test for src/dmac_assistant/eval/hibayes_runtime_reliability/README.md.

Asserts presence + required H2 sections + minimum size + no stub markers.
Phase 4 reviewers read the README for substance; this test guards regressions
against rename/stub commits.
"""
from __future__ import annotations

from pathlib import Path

import pytest

README_PATH = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "dmac_assistant"
    / "eval"
    / "hibayes_runtime_reliability"
    / "README.md"
)

REQUIRED_H2 = (
    "## What this answers",
    "## What this does NOT answer",
    "## How to run",
    "## Running the analysis (Docker)",
    "## Interpreting the report",
    "## Adding predictors later",
)

RUNTIME_SUCCESS_QUOTE = "Runtime-success only — NOT answer correctness."

STUB_MARKERS = ("TODO", "FIXME", "XXX", "???")

MIN_BYTES = 2048


def test_readme_exists() -> None:
    assert README_PATH.exists(), f"README missing at {README_PATH}"


def test_readme_minimum_size() -> None:
    size = README_PATH.stat().st_size
    assert size >= MIN_BYTES, (
        f"README is {size} bytes; expected ≥ {MIN_BYTES} bytes "
        f"(stub-commit guard)"
    )


@pytest.mark.parametrize("h2", REQUIRED_H2)
def test_readme_has_required_h2(h2: str) -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert h2 in text, f"README missing required H2 heading: {h2!r}"


def test_readme_quotes_runtime_success_framing() -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert RUNTIME_SUCCESS_QUOTE in text, (
        f"README must contain DD-01 framing quote {RUNTIME_SUCCESS_QUOTE!r}"
    )


@pytest.mark.parametrize("marker", STUB_MARKERS)
def test_readme_has_no_stub_markers(marker: str) -> None:
    text = README_PATH.read_text(encoding="utf-8")
    assert marker not in text, (
        f"README contains stub marker {marker!r}; remove before commit"
    )
