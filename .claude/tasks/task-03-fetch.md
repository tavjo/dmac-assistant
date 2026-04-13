# task-03-fetch

## 1. Overview

Port the fetch + parse functions from `smart-form-tool/packages/core/src/smart_form_core/utils/nextseek_docs.py` lines 123–169 into `build_tools/ingest_nextseek_docs/fetch.py`, renamed to reflect reality:
- `fetch_pdf_content` → `fetch_source_bytes(url: str) -> bytes`
- `parse_pdf_with_markitdown` → `parse_source_to_markdown(source_bytes: bytes) -> str`

Also add a stale-imports gate test under `tests/unit/` that fails if any module under `build_tools/` ever imports `baml`, `duckdb`, `leiden`, `smart_form_*`, or `openai` — prevents silent drift from the upstream project's heavier RAG pipeline.

**Key invariants:**
- The implementations are functionally identical to smart-form-tool's (verbatim behavior; only function names and log messages differ).
- `fetch_source_bytes` calls `httpx.Client` with `timeout=120.0, follow_redirects=True` exactly, and uses the context-manager form. Calls `response.raise_for_status()`. Returns `response.content`.
- `parse_source_to_markdown` writes bytes to a `NamedTemporaryFile(suffix=".pdf", delete=False)`, instantiates `MarkItDown()`, calls `.convert(temp_path)`, returns `.text_content`, and **always** unlinks the tempfile (finally block).
- Module does not import anything from `baml`, `duckdb`, `leiden`, `smart_form_*`, or `openai`.

## 2. Dependencies

- **Predecessor tasks**: T2 (package scaffolding exists).
- **Artifacts consumed**: `build_tools/ingest_nextseek_docs/__init__.py` (empty package).
- **External packages** (already installed by T1; DO NOT `uv add`):
  - `httpx>=0.28.1`
  - `markitdown[all]>=0.1.5`
  - `pytest`, `pytest-cov`, `pytest-socket` (dev)

## 3. Key Design Decisions

- **D2**: Use `markitdown[all]` — *Constraint*: import path is `from markitdown import MarkItDown`, no other PDF library is imported.
- **D3**: Fetch returns HTML; markitdown auto-detects — *Constraint*: function names must reflect `source_bytes` / `source_to_markdown`, not `pdf`. Docstrings acknowledge that bytes may be HTML despite `.pdf` tempfile suffix.
- **R4 resolution**: DI in `__main__.py` (T7) — *Constraint*: `fetch.py`'s functions have no `fetcher` or `parser` parameters. They are the defaults that `__main__.ingest()` injects. This task has no stubbing/DI; it's the real implementation.
- **R9 resolution**: stale-imports gate — *Constraint*: the gate test (`tests/unit/test_no_stale_imports.py`) greps the actual `build_tools/` source tree; a maintainer disabling the test is a reviewable event.
- **Port fidelity**: signature args/return types must match smart-form-tool line-by-line except for the renames. Logging format preserved. This is deliberate (D2/D3) so behavior remains aligned with a project that has demonstrably working downstream artifacts.

## 4. TDD Implementation Order

**Coverage target**: 100% for `fetch.py` (two small functions; all branches are reachable with stubs).

**Step 1 — RED (fetch, happy path)**: write failing test asserting `fetch_source_bytes` returns stub client's content.
  File: `tests/unit/test_fetch.py`
  ```bash
  uv run pytest tests/unit/test_fetch.py -q --no-cov
  ```
  Expected: `ImportError` or assertion failure — function does not exist.

**Step 2 — GREEN**: implement `fetch_source_bytes` per Section 6.
  ```bash
  uv run pytest tests/unit/test_fetch.py::test_fetch_source_bytes_returns_content -q --no-cov
  ```

**Step 3 — RED (fetch, HTTP error)**: add test that stubs `response.raise_for_status()` to raise `httpx.HTTPStatusError`.

**Step 4 — GREEN**: already covered by the reference impl's use of `raise_for_status`; test should pass once added.

**Step 5 — RED (parse happy path)**: add test using `synthetic_html` fixture; assert `# Hello` appears in returned markdown.

**Step 6 — GREEN**: implement `parse_source_to_markdown`.

**Step 7 — RED (parse cleans up tempfile)**: test asserts no orphaned temp files after a successful parse.

**Step 8 — GREEN**: reference impl's `finally: os.unlink(...)` satisfies.

**Step 9 — RED (parse cleans up tempfile on markitdown error)**: test monkeypatches `MarkItDown.convert` to raise; asserts tempfile still unlinked.

**Step 10 — GREEN**: refactor if needed (probably not — the `try/finally` handles it).

**Step 11 — RED (stale imports)**: `tests/unit/test_no_stale_imports.py` scans `build_tools/` with regex.

**Step 12 — GREEN**: confirm grep passes (no forbidden imports present).

**Step 13 — VERIFY**:
  ```bash
  uv run pytest tests/unit/test_fetch.py tests/unit/test_no_stale_imports.py -q
  uv run pytest -q
  ```
  Expected: all pass; coverage ≥95% for `fetch.py`.

## 5. Behavioral Contract (Tests)

### `tests/unit/test_fetch.py`

```python
"""Unit tests for build_tools.ingest_nextseek_docs.fetch."""
from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from build_tools.ingest_nextseek_docs import fetch as fetch_module
from tests.conftest import make_synthetic_html


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


def test_parse_source_to_markdown_cleans_up_tempfile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Successful parse leaves no orphaned tempfile in the system tempdir."""
    before = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))
    fetch_module.parse_source_to_markdown(make_synthetic_html([("A", "B")]))
    after = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))
    # No new .pdf-suffixed tempfiles remain
    assert after <= before


def test_parse_source_to_markdown_cleans_up_tempfile_on_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if MarkItDown.convert raises, the tempfile is unlinked."""
    before = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))

    class BoomMarkItDown:
        def convert(self, path: str):  # noqa: D401
            raise RuntimeError("boom")

    monkeypatch.setattr(fetch_module, "MarkItDown", lambda: BoomMarkItDown())
    with pytest.raises(RuntimeError, match="boom"):
        fetch_module.parse_source_to_markdown(b"anything")

    after = set(Path(tempfile.gettempdir()).glob("tmp*.pdf"))
    assert after <= before
```

### `tests/unit/test_no_stale_imports.py`

```python
"""Gate test: build_tools/ must not import smart-form-tool's heavy RAG deps."""
from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+(baml|duckdb|leiden|smart_form|openai)\b",
    re.MULTILINE,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_TOOLS = REPO_ROOT / "build_tools"


def test_build_tools_has_no_forbidden_imports() -> None:
    violations: list[tuple[Path, str]] = []
    for py in BUILD_TOOLS.rglob("*.py"):
        src = py.read_text()
        for match in FORBIDDEN.finditer(src):
            violations.append((py.relative_to(REPO_ROOT), match.group(0).strip()))
    assert violations == [], (
        "build_tools/ contains forbidden imports (smart-form-tool RAG framework):\n"
        + "\n".join(f"  {p}: {line}" for p, line in violations)
    )
```

## 6. Reference Implementation

### `build_tools/ingest_nextseek_docs/fetch.py` (new)

```python
"""Fetch GitBook source bytes and convert to markdown via markitdown.

Ported from smart-form-tool/packages/core/src/smart_form_core/utils/nextseek_docs.py
lines 123-169 (fetch_pdf_content + parse_pdf_with_markitdown). Renamed to
drop the 'pdf' misnomer — the fetched bytes are HTML in current GitBook
behavior, and markitdown auto-detects content type from the bytes regardless
of the tempfile suffix.
"""
from __future__ import annotations

import logging
import os
import tempfile

import httpx
from markitdown import MarkItDown

logger = logging.getLogger(__name__)


def fetch_source_bytes(url: str) -> bytes:
    """Fetch raw bytes from a URL, following redirects.

    Args:
        url: URL to fetch (typically a GitBook space export endpoint).

    Returns:
        Raw response bytes. Content type may be HTML or PDF; the caller passes
        these bytes to `parse_source_to_markdown` which delegates content-type
        detection to markitdown.

    Raises:
        httpx.HTTPStatusError: if the server returns a non-2xx status.
        httpx.RequestError: on network / DNS / TLS failure.
    """
    logger.info("Fetching source bytes from: %s", url)
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    logger.info("Fetched %d bytes", len(response.content))
    return response.content


def parse_source_to_markdown(source_bytes: bytes) -> str:
    """Convert fetched bytes to markdown using markitdown's content-type auto-detection.

    Writes `source_bytes` to a temporary file with a `.pdf` suffix (inherited from
    the upstream project's pattern; markitdown ignores the suffix and sniffs the
    actual content). Always cleans up the tempfile.

    Args:
        source_bytes: Raw bytes from `fetch_source_bytes`.

    Returns:
        Markdown string. For GitBook HTML input, `<h1>` tags are preserved as
        `# ` markdown headings.
    """
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(source_bytes)
        temp_path = f.name
    try:
        md = MarkItDown()
        result = md.convert(temp_path)
        text = result.text_content
        logger.info("Extracted %d characters of markdown", len(text))
        return text
    finally:
        os.unlink(temp_path)
```

## 7. Modified Files (exact diffs)

None — all new files.

## 8. Verification

```bash
# New tests pass
uv run pytest tests/unit/test_fetch.py tests/unit/test_no_stale_imports.py -q

# Full suite, including coverage floor
uv run pytest -q

# Coverage for fetch.py specifically
uv run pytest --cov=build_tools.ingest_nextseek_docs.fetch \
    --cov-report=term-missing tests/unit/test_fetch.py -q

# No live network call escaped
uv run pytest tests/unit/test_fetch.py -q 2>&1 | grep -i "SocketBlocked" || echo "no socket block triggered (expected)"

# No forbidden imports (belt-and-suspenders)
grep -EnR "^(from|import) (baml|duckdb|leiden|smart_form|openai)" build_tools/ && exit 1 || echo "clean"
```

**Expected test count**: 6 new tests in `test_fetch.py`, 1 new test in `test_no_stale_imports.py` = 7 new tests.

**Expected coverage**: `fetch.py` ≥ 95% (targeting 100% — only the `logger.info` calls and the return are unconditional; both error paths tested).

## 9. Implementation Notes

- The tempfile suffix `.pdf` is inherited from smart-form-tool verbatim. Do not change it to `.html` — markitdown's detection uses bytes, not suffix, and changing the suffix introduces a spurious divergence from the verified-working upstream pattern.
- `os.unlink` is used instead of `Path.unlink` to match smart-form-tool's idiom (nextseek_docs.py:169).
- The logger uses the standard `logging.getLogger(__name__)` pattern. Configuration happens in `__main__.py` (T7). Tests do not assert on log output.
- When monkeypatching `httpx.Client`, always attach `__enter__` and `__exit__` to the mock because the production code uses `with httpx.Client(...) as client`.

## 10. Worktree & Branch

- **Branch**: `task/03-fetch`
- **Worktree**: `.claude/worktrees/task-03-fetch/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass; `fetch.py` coverage ≥ 95%.
