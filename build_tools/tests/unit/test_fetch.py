"""Unit tests for build_tools.ingest_nextseek_docs.fetch."""
from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from build_tools.ingest_nextseek_docs import fetch as fetch_module

SITE_INDEX_URL = (
    "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/"
    "~gitbook/site-index"
)


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


def _site_index_payload(pages: list[dict]) -> bytes:
    return json.dumps({"version": 1, "pages": pages}).encode("utf-8")


def test_fetch_source_bytes_returns_content(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = _stub_client_returning(b'{"pages":[]}')
    monkeypatch.setattr(
        fetch_module.httpx,
        "Client",
        lambda *a, **kw: stub,
    )
    result = fetch_module.fetch_source_bytes("https://example.test/")
    assert result == b'{"pages":[]}'
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


def test_load_site_index_pages_resolves_pages_dynamically(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _site_index_payload(
        [
            {
                "title": "Fresh New Page",
                "pathname": "/mit-data-management-analysis-core/fresh-new-page",
            },
            {
                "title": "Nested Entry",
                "pathname": "/mit-data-management-analysis-core/section/nested-entry",
            },
        ]
    )
    monkeypatch.setattr(fetch_module, "fetch_source_bytes", lambda url: payload)

    pages = fetch_module.load_site_index_pages(SITE_INDEX_URL)

    assert [page.title for page in pages] == ["Fresh New Page", "Nested Entry"]
    assert pages[0].markdown_url.endswith(
        "/mit-data-management-analysis-core/fresh-new-page.md"
    )
    assert pages[1].markdown_url.endswith(
        "/mit-data-management-analysis-core/section/nested-entry.md"
    )


def test_load_site_index_pages_resolves_root_from_dynamic_title(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _site_index_payload(
        [
            {
                "title": "Renamed Landing Page",
                "pathname": "/mit-data-management-analysis-core",
            },
        ]
    )
    monkeypatch.setattr(fetch_module, "fetch_source_bytes", lambda url: payload)

    pages = fetch_module.load_site_index_pages(SITE_INDEX_URL)

    assert len(pages) == 1
    assert pages[0].markdown_url.endswith(
        "/mit-data-management-analysis-core/renamed-landing-page.md"
    )


def test_load_site_index_pages_rejects_missing_pages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(fetch_module, "fetch_source_bytes", lambda url: b"{}")

    with pytest.raises(ValueError, match="missing pages list"):
        fetch_module.load_site_index_pages(SITE_INDEX_URL)


def test_strip_gitbook_agent_instructions_removes_trailing_boilerplate() -> None:
    markdown = (
        "# Uploading\n\nBody.\n\n"
        "---\n\n"
        "# Agent Instructions: Querying This Documentation\n\n"
        "GET https://example.test/page.md?ask=<question>\n"
    )

    stripped = fetch_module.strip_gitbook_agent_instructions(markdown)

    assert stripped == "# Uploading\n\nBody.\n"
    assert "Agent Instructions" not in stripped


def test_load_gitbook_markdown_corpus_uses_site_index_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _site_index_payload(
        [
            {
                "title": "Second In Alphabet",
                "pathname": "/mit-data-management-analysis-core/second",
            },
            {
                "title": "First In Alphabet",
                "pathname": "/mit-data-management-analysis-core/first",
            },
        ]
    )
    responses = {
        SITE_INDEX_URL: payload,
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/second.md": (
            b"# Second In Alphabet\n\nBody two.\n"
        ),
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/first.md": (
            b"# First In Alphabet\n\nBody one.\n"
        ),
    }
    requested: list[str] = []

    def fake_fetch(url: str) -> bytes:
        requested.append(url)
        return responses[url]

    monkeypatch.setattr(fetch_module, "fetch_source_bytes", fake_fetch)

    corpus = fetch_module.load_gitbook_markdown_corpus(SITE_INDEX_URL)

    assert corpus.index("# Second In Alphabet") < corpus.index("# First In Alphabet")
    assert requested == [
        SITE_INDEX_URL,
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/second.md",
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/first.md",
    ]


def test_load_gitbook_markdown_corpus_demotes_nested_h1s(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _site_index_payload(
        [
            {
                "title": "Workflow",
                "pathname": "/mit-data-management-analysis-core/workflow",
            },
        ]
    )
    responses = {
        SITE_INDEX_URL: payload,
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/workflow.md": (
            b"# Workflow\n\nIntro.\n\n# Internal Topic\n\nDetails.\n"
        ),
    }
    monkeypatch.setattr(fetch_module, "fetch_source_bytes", lambda url: responses[url])

    corpus = fetch_module.load_gitbook_markdown_corpus(SITE_INDEX_URL)

    assert "# Workflow" in corpus
    assert "\n## Internal Topic" in corpus
    assert "\n# Internal Topic" not in corpus


def test_load_gitbook_markdown_corpus_rejects_html_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _site_index_payload(
        [
            {
                "title": "Welcome",
                "pathname": "/mit-data-management-analysis-core/welcome",
            },
        ]
    )
    responses = {
        SITE_INDEX_URL: payload,
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/welcome.md": (
            b"<!DOCTYPE html><html></html>"
        ),
    }
    monkeypatch.setattr(fetch_module, "fetch_source_bytes", lambda url: responses[url])

    with pytest.raises(ValueError, match="returned HTML"):
        fetch_module.load_gitbook_markdown_corpus(SITE_INDEX_URL)


def test_load_gitbook_markdown_corpus_rejects_page_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _site_index_payload(
        [
            {
                "title": "Welcome",
                "pathname": "/mit-data-management-analysis-core/welcome",
            },
        ]
    )
    responses = {
        SITE_INDEX_URL: payload,
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/welcome.md": (
            b"# Page Not Found\n\nNope.\n"
        ),
    }
    monkeypatch.setattr(fetch_module, "fetch_source_bytes", lambda url: responses[url])

    with pytest.raises(ValueError, match="Page Not Found"):
        fetch_module.load_gitbook_markdown_corpus(SITE_INDEX_URL)
