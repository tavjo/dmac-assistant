# task-01-test-infra

## 1. Overview

Scaffold the entire test infrastructure so downstream tasks never touch `pyproject.toml` or `uv.lock`. Installs all dev deps for the whole plan in one shot, writes pytest configuration, creates the test directory tree, defines the synthetic-HTML fixture, installs the autouse production-path guard, and writes the markitdown-contract test that pins the load-bearing assumption of the whole plan.

**Key invariants established by this task:**
- All dev deps (pytest, pytest-cov, pytest-socket) are present. No downstream task runs `uv add`.
- `pytest` runs with sockets disabled by default (`--disable-socket`) so any test that attempts a live HTTP call fails immediately.
- `tests/conftest.py` exposes `make_synthetic_html(sections) -> bytes` and a `synthetic_html` fixture returning a 3-section default.
- An autouse fixture replaces `build_tools.ingest_nextseek_docs.constants.DEFAULT_DOCS_DIR` and `DEFAULT_CLAUDE_MD_PATH` with sentinels that raise `RuntimeError` on any filesystem access. Structural prevention of test pollution.
- The markitdown contract test validates that `MarkItDown().convert(...)` on bytes from `make_synthetic_html([...])` written to a `.pdf`-suffixed tempfile returns markdown with `# ` headings preserved. If this test fails in CI, every other task's assumptions are invalid.

## 2. Dependencies

- **Predecessor tasks**: none
- **Artifacts consumed**: none (greenfield scaffolding)
- **External packages** (added in this task via `uv add --dev`):
  - `pytest>=8.0`
  - `pytest-cov>=5.0`
  - `pytest-socket>=0.7`

  Production deps (already present from prior work; this task must not modify them):
  - `httpx>=0.28.1`
  - `markitdown[all]>=0.1.5`

## 3. Key Design Decisions

- **D2**: Use `markitdown[all]` — *Constraint*: the contract test and all downstream code import `MarkItDown` from the `markitdown` package; no other PDF/HTML library is added.
- **D3**: Fetch returns HTML; markitdown auto-detects by content — *Constraint*: the contract test uses HTML input (from `make_synthetic_html`), not PDF, and writes it to a `.pdf`-suffixed tempfile to exactly mirror the production code path.
- **D9**: Synthetic HTML fixture (pure string) — *Constraint*: `make_synthetic_html` must not import `reportlab` or any PDF-generating library. String concatenation only.
- **D10**: Dependency injection — *Constraint*: conftest does not monkeypatch `httpx.Client` or the real fetcher; tests rely on DI from T7.
- **R3 resolution**: all deps hoisted here — *Constraint*: T3–T6 specs must not include `uv add` anywhere.
- **R5 resolution**: autouse conftest guard — *Constraint*: the guard raises `RuntimeError` synchronously when a sentinel path's `__fspath__` is called, not just on write. This catches `.exists()`, `open()`, `Path.iterdir()` accesses.
- **Coverage floor**: 95% applies from the next task onward. This task creates test infrastructure; its own "coverage" is meaningful only to the extent the conftest code runs (it does — autouse). A `conftest.py` with only fixtures does not need a separate coverage pass.

## 4. TDD Implementation Order

**Coverage target**: 95% for `tests/conftest.py` by virtue of every test file triggering the autouse fixture; no separate impl module is created by this task. Coverage is reported in subsequent tasks.

**Step 1 — Install deps**:
```bash
uv add --dev "pytest>=8.0" "pytest-cov>=5.0" "pytest-socket>=0.7"
```
Expected: `pyproject.toml` gains a `[dependency-groups]` `dev` list with the three packages; `uv.lock` updates.

**Step 2 — Configure pytest** in `pyproject.toml`:
```toml
[tool.pytest.ini_options]
addopts = "--disable-socket -q --cov=build_tools --cov-report=term-missing --cov-fail-under=95"
testpaths = ["tests"]
```

**Step 3 — Create directory tree**:
```bash
mkdir -p tests/unit tests/integration
touch tests/__init__.py tests/unit/__init__.py tests/integration/__init__.py
```

**Step 4 — Write `tests/conftest.py`** per Section 6.

**Step 5 — RED: contract test that will fail because markitdown is not wired**:
  File: `tests/integration/test_markitdown_contract.py`
  ```bash
  uv run pytest tests/integration/test_markitdown_contract.py --no-cov -q
  ```
  Expected: import fails or test fails — prove RED.

**Step 6 — GREEN: test should pass immediately after conftest + markitdown already installed** (markitdown[all] is already a prod dep):
  ```bash
  uv run pytest tests/integration/test_markitdown_contract.py --no-cov -q
  ```
  Expected: 1 test passes.

**Step 7 — RED for autouse guard self-test**:
  File: `tests/unit/test_autouse_guard.py`
  Write a test that attempts to call `Path(build_tools.ingest_nextseek_docs.constants.DEFAULT_DOCS_DIR).exists()` and asserts `RuntimeError` is raised. The test will fail because `build_tools.ingest_nextseek_docs.constants` does not yet exist (module not created until T2).

**Step 8 — GREEN via lazy guard**: update conftest to make the autouse fixture tolerate missing module at import-time, then install the guard when the module appears. See reference implementation.
  ```bash
  uv run pytest tests/unit/test_autouse_guard.py --no-cov -q
  ```

  Since T1 runs before T2, the module is absent and the autouse fixture skips its patching cleanly. The self-test must be **skipped** (`pytest.skip`) when the module is absent, not passed. Guard becomes active as soon as T2 creates the module.

**Step 9 — VERIFY (end of task)**:
  ```bash
  uv run pytest -q
  ```
  Expected: all tests pass or skip; no test fails; coverage not enforced yet (no impl modules).

## 5. Behavioral Contract (Tests)

### `tests/conftest.py`

```python
"""Shared fixtures and autouse guards for the DMAC ingestion test suite."""
from __future__ import annotations

import html
from importlib import import_module
from pathlib import Path
from typing import Iterable

import pytest


def make_synthetic_html(sections: Iterable[tuple[str, str]]) -> bytes:
    """Build HTML bytes with `<h1>` + `<p>` for each (title, paragraph) tuple.

    Deterministic, dependency-free (pure string concatenation). Used anywhere a
    test needs something that mimics a GitBook-rendered HTML page that markitdown
    can parse into markdown with heading markers preserved.
    """
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
    """Path-shaped object that raises RuntimeError on any use.

    Used by the autouse guard to replace production default paths during tests.
    Any call to `.exists()`, `.iterdir()`, `os.fspath(...)`, `open(self)`, etc.
    goes through `__fspath__`, which raises.
    """

    def __init__(self, label: str) -> None:
        self._label = label

    def __fspath__(self) -> str:  # noqa: D401
        raise RuntimeError(
            f"test used production default path: {self._label}. "
            f"Pass an explicit tmp_path override to ingest()."
        )

    def __str__(self) -> str:
        raise RuntimeError(
            f"test used production default path: {self._label}. "
            f"Pass an explicit tmp_path override to ingest()."
        )

    def __repr__(self) -> str:
        return f"<_PoisonedPath label={self._label!r}>"


@pytest.fixture(autouse=True)
def _block_production_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    """Replace `DEFAULT_DOCS_DIR` and `DEFAULT_CLAUDE_MD_PATH` with sentinels.

    Any test that accidentally uses the production default paths triggers
    `RuntimeError` from `_PoisonedPath`. Harmless when the constants module
    does not yet exist (early tasks) — the patch is simply skipped.
    """
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
```

### `tests/integration/test_markitdown_contract.py`

```python
"""Pin the load-bearing assumption that markitdown preserves <h1> as # from HTML.

If this test fails in CI, every downstream task's splitter logic is invalid.
"""
from __future__ import annotations

import os
import tempfile

from markitdown import MarkItDown

from tests.conftest import make_synthetic_html


def test_markitdown_preserves_h1_from_html_in_pdf_suffixed_tempfile() -> None:
    """HTML bytes written to a .pdf tempfile must yield '# <title>' markdown.

    Production code path (fetch.py) writes fetched bytes to a NamedTemporaryFile
    with suffix='.pdf' regardless of actual content. markitdown sniffs content
    type from bytes, not the suffix, so HTML is parsed as HTML. This test
    replicates that exact path and asserts the heading-preservation contract.
    """
    source_bytes = make_synthetic_html([("Hello World", "Body paragraph here.")])

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
        f.write(source_bytes)
        path = f.name
    try:
        result = MarkItDown().convert(path)
        text = result.text_content
    finally:
        os.unlink(path)

    assert "# Hello World" in text, (
        f"markitdown did not preserve <h1> as '# Hello World'. "
        f"Got: {text[:500]!r}"
    )
    assert "Body paragraph here." in text
```

### `tests/unit/test_autouse_guard.py`

```python
"""Self-test for the autouse production-path guard.

Skipped when build_tools.ingest_nextseek_docs.constants does not exist yet
(which is the case during T1 itself). Becomes active and meaningful from T2
onward once constants.py is created.
"""
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
    try:
        constants = import_module("build_tools.ingest_nextseek_docs.constants")
    except ModuleNotFoundError:
        pytest.skip("constants module not yet created (pre-T2)")
    with pytest.raises(RuntimeError, match="production default path"):
        Path(constants.DEFAULT_CLAUDE_MD_PATH).exists()
```

## 6. Reference Implementation

No application code in this task — the "implementation" is entirely `conftest.py` and the two test files above. The contents in Section 5 are the complete, final content for those files.

Nothing is created under `build_tools/`; that happens in T2.

## 7. Modified Files (exact diffs)

### Edit 1: `pyproject.toml`

**OLD:**
```toml
[dependency-groups]
dev = []
```

**NEW:**
```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-cov>=5.0",
    "pytest-socket>=0.7",
]

[tool.pytest.ini_options]
addopts = "--disable-socket -q --cov=build_tools --cov-report=term-missing --cov-fail-under=95"
testpaths = ["tests"]
```

(Note: adding `pytest.ini_options` requires it to appear once in the file. Place it after the `[dependency-groups]` block. The `uv add --dev` command handles the dev list population; pytest config is a manual `pyproject.toml` edit.)

## 8. Verification

```bash
# Deps installed
uv run python -c "import pytest, pytest_socket, pytest_cov; print('ok')"

# Pytest config read
uv run pytest --collect-only 2>&1 | grep -E "test_markitdown_contract|test_autouse_guard|test_production"

# Contract test passes (critical)
uv run pytest tests/integration/test_markitdown_contract.py --no-cov -q

# Autouse self-test skips cleanly (constants not yet created)
uv run pytest tests/unit/test_autouse_guard.py --no-cov -q

# Full suite runs
uv run pytest --no-cov -q

# Verify sockets are disabled
uv run python -c "
import subprocess, sys
r = subprocess.run(
    ['uv', 'run', 'pytest', '-q', '--no-cov', '-p', 'no:socket', '-k', 'nonexistent'],
    capture_output=True, text=True,
)
print('socket-disable working')
"
```

**Expected test count**: 3 collected (1 integration, 2 unit). Unit tests currently skip with reason `constants module not yet created (pre-T2)`. Integration test passes.

**Expected coverage**: N/A for this task (no impl modules yet). The `--cov-fail-under=95` flag is already in `addopts` but the current run reports no coverage because no `build_tools/` code exists; it will take effect from T3 onward.

**Override for this task only**: the verification commands use `--no-cov` to suppress the coverage-floor check during T1's own verification. From T3 onward, tasks run `uv run pytest` without `--no-cov` and must satisfy ≥95%.

## 9. Implementation Notes

- The autouse fixture uses `import_module` inside a try/except rather than a top-level import so the fixture file itself never crashes if `build_tools.ingest_nextseek_docs.constants` is missing. Critical for T1 because T2 is what creates that module.
- `_PoisonedPath` intentionally does not inherit from `pathlib.Path` — subclassing `Path` is brittle across Python versions. A plain class that raises in `__fspath__` is enough for any `Path(...)` or `open(...)` to fail loudly.
- Note that `Path(_PoisonedPath(...))` calls `__fspath__` on the argument, which raises — so the `Path(...)` constructor itself raises. The assertions in `test_autouse_guard.py` rely on this.
- `pytest-socket` globally disables sockets when `addopts` contains `--disable-socket`. A test that legitimately needs a socket can re-enable with `@pytest.mark.enable_socket`, but nothing in this plan should need that.
- Do NOT add `pytest-asyncio`, `respx`, or any other test-helper deps. If a future task demands them, amend via `/ultraplan amend`.

## 10. Worktree & Branch

- **Branch**: `task/01-test-infra`
- **Worktree**: `.claude/worktrees/task-01-test-infra/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 verification commands pass; integration contract test green; autouse tests skip cleanly.
