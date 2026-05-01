"""Unit tests for build_tools.ingest_nextseek_docs.fetch."""
from __future__ import annotations

import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from build_tools.ingest_nextseek_docs import fetch as fetch_module
from build_tools.tests.conftest import make_synthetic_html


def _stub_client_returning(content: bytes) -> MagicMock:
    """Build a MagicMock matching httpx.Client's context-manager interface."""
    response = MagicMock()
    response.content = content
    response.raise_for_status = MagicMock()
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = response
    return client


def test_fetch_source_bytes_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub_client_returning(b"<!DOCTYPE html><html><body>hi</body></html>")
    monkeypatch.setattr(
        fetch_module.httpx,
        "Client",
        lambda *a, **kw: stub,
    )
    result = fetch_module.fetch_source_bytes("https://example.test/")
    assert result == b"<!DOCTYPE html><html><body>hi</body></html>"
    stub.get.assert_called_once_with("https://example.test/")


def test_fetch_source_bytes_uses_120s_timeout_and_follow_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    def fake_client(*args, **kwargs):
        captured.update(kwargs)
        return _stub_client_returning(b"x")

    monkeypatch.setattr(fetch_module.httpx, "Client", fake_client)
    fetch_module.fetch_source_bytes("https://example.test/")
    assert captured["timeout"] == 120.0
    assert captured["follow_redirects"] is True


def test_fetch_source_bytes_raises_on_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = MagicMock()
    response.raise_for_status = MagicMock(
        side_effect=httpx.HTTPStatusError(
            "404", request=MagicMock(), response=MagicMock(status_code=404)
        )
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.get.return_value = response
    monkeypatch.setattr(fetch_module.httpx, "Client", lambda *a, **kw: client)

    with pytest.raises(httpx.HTTPStatusError):
        fetch_module.fetch_source_bytes("https://example.test/")


def test_parse_source_to_markdown_preserves_h1_headings(
    synthetic_html: bytes,
) -> None:
    result = fetch_module.parse_source_to_markdown(synthetic_html)
    assert "# Welcome" in result
    assert "# Getting Started" in result
    assert "# Sample Registration" in result


def test_parse_source_to_markdown_cleans_up_tempfile() -> None:
    """Successful parse leaves no orphaned tempfile in the system tempdir."""
    before = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))
    fetch_module.parse_source_to_markdown(make_synthetic_html([("A", "B")]))
    after = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))
    assert after <= before


def test_parse_source_to_markdown_cleans_up_tempfile_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if MarkItDown.convert raises, the tempfile is unlinked."""
    before = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))

    class BoomMarkItDown:
        def convert(self, path: str):
            raise RuntimeError("boom")

    monkeypatch.setattr(fetch_module, "MarkItDown", lambda: BoomMarkItDown())
    with pytest.raises(RuntimeError, match="boom"):
        fetch_module.parse_source_to_markdown(b"anything")

    after = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))
    assert after <= before
