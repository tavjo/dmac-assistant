"""Shared fixtures and autouse guards for the DMAC ingestion test suite."""
from __future__ import annotations

import html
from importlib import import_module
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


class _PoisonedPath:
    """Path-like object that raises on any filesystem use."""

    def __init__(self, label: str) -> None:
        self._label = label

    def __fspath__(self) -> str:
        raise RuntimeError(
            f"test used production default path: {self._label}. "
            "Pass an explicit tmp_path override to ingest()."
        )

    def __str__(self) -> str:
        raise RuntimeError(
            f"test used production default path: {self._label}. "
            "Pass an explicit tmp_path override to ingest()."
        )

    def __repr__(self) -> str:
        return f"<_PoisonedPath label={self._label!r}>"


@pytest.fixture(autouse=True)
def _block_production_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace production default paths with sentinels during tests."""
    try:
        constants = import_module("build_tools.ingest_nextseek_docs.constants")
    except ModuleNotFoundError:
        return

    monkeypatch.setattr(
        constants,
        "DEFAULT_DOCS_DIR",
        _PoisonedPath("DEFAULT_DOCS_DIR"),
        raising=True,
    )
    monkeypatch.setattr(
        constants,
        "DEFAULT_CLAUDE_MD_PATH",
        _PoisonedPath("DEFAULT_CLAUDE_MD_PATH"),
        raising=True,
    )
