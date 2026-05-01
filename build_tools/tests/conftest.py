"""Fixtures for the build_tools test suite.

Plan A · Amendment 7 v2 (2026-04-30): make_synthetic_html and the synthetic_html
fixture moved here from the bridge `tests/conftest.py` along with the four test
files that depend on them (test_fetch, test_main, test_markitdown_contract,
test_end_to_end). The bridge tests no longer need these helpers.
"""
from __future__ import annotations

import html
from typing import Iterable

import pytest


def make_synthetic_html(sections: Iterable[tuple[str, str]]) -> bytes:
    """Build deterministic HTML bytes from section title/paragraph tuples."""
    body_parts: list[str] = []
    for title, para in sections:
        body_parts.append(f"<h1>{html.escape(title)}</h1>")
        body_parts.append(f"<p>{html.escape(para)}</p>")
    body = "\n".join(body_parts)
    return f"<!DOCTYPE html><html><body>{body}</body></html>".encode("utf-8")


@pytest.fixture
def synthetic_html() -> bytes:
    """Default 3-section HTML fixture used by integration tests."""
    return make_synthetic_html(
        [
            ("Welcome", "Intro paragraph for the welcome page."),
            ("Getting Started", "Intro paragraph for getting started."),
            ("Sample Registration", "Intro paragraph for sample registration."),
        ]
    )
