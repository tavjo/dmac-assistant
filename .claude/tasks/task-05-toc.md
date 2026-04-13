# task-05-toc

## 1. Overview

Implement three pure functions plus the shared constants module that the rest of the ingestion pipeline depends on:

- `build_tools/ingest_nextseek_docs/constants.py` — central string/path constants.
- `build_tools/ingest_nextseek_docs/toc.py`:
  - `render_readme(sections, source_url, content_hash) -> str` — generates `docs/nextseek/README.md`.
  - `render_claude_md_block(sections, overview_paragraph) -> str` — generates the content between the `<!-- BEGIN NEXTSEEK-DOCS -->` and `<!-- END NEXTSEEK-DOCS -->` markers in `container/CLAUDE.md`.
  - `update_claude_md(path, block_content) -> None` — atomically replaces the markered block in the file at `path`.

**Key invariants:**
- `BEGIN_MARKER` and `END_MARKER` in `constants.py` are byte-identical to the strings in `container/CLAUDE.md`.
- `update_claude_md` writes atomically via `os.replace` (write to `<path>.tmp` first).
- Missing or duplicated markers raise `ValueError`; the file is not modified.
- Calling `update_claude_md` twice with the same block produces byte-identical output.

## 2. Dependencies

- **Predecessor tasks**: T2 (package), T4 (imports `Section`).
- **Artifacts consumed**: `build_tools/ingest_nextseek_docs/split.Section`.
- **External packages**: none.

## 3. Key Design Decisions

- **D6**: Summary prose = first-H1 paragraph; section list = H1 titles — *Constraint*: `render_claude_md_block` takes `overview_paragraph` from the caller (T7 will pass the first Section's description or body excerpt).
- **D7**: Two CLAUDE.md files — *Constraint*: `DEFAULT_CLAUDE_MD_PATH = Path("container/CLAUDE.md")`, NOT repo-root.
- **R2/R8 resolution**: marker strings centralized — *Constraint*: nothing else in the codebase hard-codes the marker literals; downstream tests import from `constants`.
- **R6 resolution**: atomic write — *Constraint*: `update_claude_md` uses `os.replace` on a sibling tmpfile. No in-place write.
- **Coverage floor**: 95% for both `constants.py` and `toc.py`.

## 4. TDD Implementation Order

**Coverage target**: 95% for `toc.py`. `constants.py` is compile-time-only; its test is import-and-compare.

**Step 1 — RED**: `test_constants_markers_exist` — import fails.
**Step 2 — GREEN**: create `constants.py` per Section 6.

**Step 3 — RED**: `test_constants_markers_match_container_claude_md` — asserts the strings in `constants.BEGIN_MARKER/END_MARKER` appear verbatim in `container/CLAUDE.md`.
**Step 4 — GREEN**: already green after Step 2.

**Step 5 — RED**: `test_render_readme_golden` (fail: function absent).
**Step 6 — GREEN**: implement `render_readme`.

**Step 7 — RED**: `test_render_claude_md_block_golden` (fail: function absent).
**Step 8 — GREEN**: implement `render_claude_md_block`.

**Step 9 — RED**: `test_update_claude_md_happy_path`.
**Step 10 — GREEN**: implement `update_claude_md` with atomic write.

**Step 11 — RED**: `test_update_claude_md_missing_markers` — raises `ValueError`, file unchanged.
**Step 12 — GREEN**: add validation.

**Step 13 — RED**: `test_update_claude_md_duplicate_markers` — raises.
**Step 14 — GREEN**: add duplicate check.

**Step 15 — RED**: `test_update_claude_md_is_atomic` — monkeypatch `os.replace` to raise; assert file byte-unchanged.
**Step 16 — GREEN**: confirm tmpfile write happens before replace.

**Step 17 — RED**: `test_update_claude_md_idempotent` — call twice, assert byte-identical.
**Step 18 — GREEN**: confirmed by reference impl.

**Step 19 — VERIFY**:
  ```bash
  uv run pytest tests/unit/test_toc.py tests/unit/test_constants.py -q
  uv run pytest --cov=build_tools.ingest_nextseek_docs.toc \
      --cov=build_tools.ingest_nextseek_docs.constants \
      --cov-report=term-missing --cov-fail-under=95 tests/unit/
  ```

## 5. Behavioral Contract (Tests)

### `tests/unit/test_constants.py`

```python
"""Unit tests for build_tools.ingest_nextseek_docs.constants."""
from __future__ import annotations

from pathlib import Path

from build_tools.ingest_nextseek_docs import constants as C

REPO_ROOT = Path(__file__).resolve().parents[2]


def test_begin_marker_exact_string() -> None:
    assert C.BEGIN_MARKER == "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->"


def test_end_marker_exact_string() -> None:
    assert C.END_MARKER == "<!-- END NEXTSEEK-DOCS (auto-generated) -->"


def test_default_doc_url_is_gitbook_pdf_endpoint() -> None:
    assert C.DEFAULT_DOC_URL == (
        "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/"
        "~gitbook/pdf?limit=100"
    )


def test_default_docs_dir_is_pathlib_path() -> None:
    assert isinstance(C.DEFAULT_DOCS_DIR, Path)
    assert str(C.DEFAULT_DOCS_DIR) == "docs/nextseek"


def test_default_claude_md_path_is_container_file() -> None:
    assert isinstance(C.DEFAULT_CLAUDE_MD_PATH, Path)
    assert str(C.DEFAULT_CLAUDE_MD_PATH) == "container/CLAUDE.md"


def test_markers_match_container_claude_md_file() -> None:
    """Constants must match the strings baked into container/CLAUDE.md exactly."""
    md = (REPO_ROOT / "container" / "CLAUDE.md").read_text()
    assert C.BEGIN_MARKER in md
    assert C.END_MARKER in md
```

### `tests/unit/test_toc.py`

```python
"""Unit tests for build_tools.ingest_nextseek_docs.toc."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from build_tools.ingest_nextseek_docs import toc
from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER
from build_tools.ingest_nextseek_docs.split import Section


def _make_section(ordinal: int, title: str, slug: str, description: str) -> Section:
    return Section(
        ordinal=ordinal,
        title=title,
        slug=slug,
        body=f"# {title}\n\n{description}\n",
        description=description,
    )


SOURCE_URL = "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/"
SAMPLE_SECTIONS = [
    _make_section(1, "Welcome", "welcome", "Intro paragraph for welcome."),
    _make_section(2, "Getting Started", "getting-started", "Short intro."),
]


def test_render_readme_golden_output() -> None:
    content_hash = "abc123def4567890deadbeefcafe0000abc123def4567890deadbeefcafe0000"
    result = toc.render_readme(SAMPLE_SECTIONS, SOURCE_URL, content_hash)
    expected = (
        "# NExtSEEK Documentation — Table of Contents\n"
        "\n"
        "_Generated by build_tools/ingest_nextseek_docs. Do not edit by hand._\n"
        "\n"
        f"Source: {SOURCE_URL}\n"
        f"Content hash: {content_hash[:12]}\n"
        "\n"
        "## Sections\n"
        "\n"
        "- **[Welcome](01-welcome.md)** — Intro paragraph for welcome.\n"
        "- **[Getting Started](02-getting-started.md)** — Short intro.\n"
    )
    assert result == expected, (
        f"render_readme output mismatch.\n"
        f"--- expected ---\n{expected!r}\n"
        f"--- actual ---\n{result!r}"
    )


def test_render_claude_md_block_golden_output() -> None:
    sections = [
        _make_section(1, "Welcome", "welcome", "w"),
        _make_section(2, "Getting Started", "getting-started", "g"),
        _make_section(3, "Sample Registration", "sample-registration", "s"),
    ]
    overview = "NExtSEEK is the BMC sample tracking system."
    result = toc.render_claude_md_block(sections, overview)
    expected = (
        "\n"
        "## NExtSEEK Documentation\n"
        "\n"
        f"{overview}\n"
        "\n"
        "Top-level sections: Welcome, Getting Started, Sample Registration.\n"
        "\n"
        "For detail, read `/app/docs/nextseek/README.md` first.\n"
        "\n"
    )
    assert result == expected, (
        f"render_claude_md_block output mismatch.\n"
        f"--- expected ---\n{expected!r}\n"
        f"--- actual ---\n{result!r}"
    )


def test_update_claude_md_replaces_block_between_markers(tmp_path: Path) -> None:
    seeded = (
        "# Header\n"
        f"{BEGIN_MARKER}\n"
        "OLD CONTENT\n"
        f"{END_MARKER}\n"
        "# Footer\n"
    )
    path = tmp_path / "CLAUDE.md"
    path.write_text(seeded)

    toc.update_claude_md(path, "NEW CONTENT\n")

    result = path.read_text()
    expected = (
        "# Header\n"
        f"{BEGIN_MARKER}\n"
        "NEW CONTENT\n"
        f"{END_MARKER}\n"
        "# Footer\n"
    )
    assert result == expected


def test_update_claude_md_missing_markers_raises_and_file_unchanged(
    tmp_path: Path,
) -> None:
    original = "# No markers here\nJust content.\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(original)
    with pytest.raises(ValueError, match="marker"):
        toc.update_claude_md(path, "anything")
    assert path.read_text() == original


def test_update_claude_md_duplicate_markers_raises(tmp_path: Path) -> None:
    doubled = f"{BEGIN_MARKER}\n1\n{END_MARKER}\n{BEGIN_MARKER}\n2\n{END_MARKER}\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(doubled)
    with pytest.raises(ValueError, match="marker"):
        toc.update_claude_md(path, "anything")
    assert path.read_text() == doubled


def test_update_claude_md_is_atomic_on_replace_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If os.replace raises, the original file is byte-unchanged."""
    original = f"{BEGIN_MARKER}\nold\n{END_MARKER}\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(original)

    monkeypatch.setattr(
        toc.os,
        "replace",
        lambda src, dst: (_ for _ in ()).throw(OSError("disk full")),
    )
    with pytest.raises(OSError, match="disk full"):
        toc.update_claude_md(path, "new\n")

    assert path.read_text() == original
    # No orphaned .tmp file either
    assert not (tmp_path / "CLAUDE.md.tmp").exists()


def test_update_claude_md_idempotent(tmp_path: Path) -> None:
    seeded = f"{BEGIN_MARKER}\n\n{END_MARKER}\n"
    path = tmp_path / "CLAUDE.md"
    path.write_text(seeded)

    block = "SAME CONTENT\n"
    toc.update_claude_md(path, block)
    first = path.read_bytes()
    toc.update_claude_md(path, block)
    second = path.read_bytes()
    assert first == second


def test_update_claude_md_uses_os_replace(tmp_path: Path) -> None:
    """Sanity check: implementation uses os.replace, not shutil.move or rename."""
    import inspect
    src = inspect.getsource(toc.update_claude_md)
    assert "os.replace" in src, "update_claude_md must use os.replace for atomicity"
```

## 6. Reference Implementation

### `build_tools/ingest_nextseek_docs/constants.py` (new)

```python
"""Central constants for the NExtSEEK ingestion tool."""
from __future__ import annotations

from pathlib import Path

BEGIN_MARKER = "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->"
END_MARKER = "<!-- END NEXTSEEK-DOCS (auto-generated) -->"

DEFAULT_DOC_URL = (
    "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/"
    "~gitbook/pdf?limit=100"
)

DEFAULT_DOCS_DIR = Path("docs/nextseek")
DEFAULT_CLAUDE_MD_PATH = Path("container/CLAUDE.md")
```

### `build_tools/ingest_nextseek_docs/toc.py` (new)

```python
"""Render README.md and container/CLAUDE.md block for NExtSEEK ingestion."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Iterable

from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER
from build_tools.ingest_nextseek_docs.split import Section


def render_readme(
    sections: Iterable[Section],
    source_url: str,
    content_hash: str,
) -> str:
    """Render the full text of `docs/nextseek/README.md`."""
    lines = [
        "# NExtSEEK Documentation — Table of Contents",
        "",
        "_Generated by build_tools/ingest_nextseek_docs. Do not edit by hand._",
        "",
        f"Source: {source_url}",
        f"Content hash: {content_hash[:12]}",
        "",
        "## Sections",
        "",
    ]
    for s in sections:
        filename = f"{s.ordinal:02d}-{s.slug}.md"
        lines.append(f"- **[{s.title}]({filename})** — {s.description}")
    lines.append("")  # trailing newline
    return "\n".join(lines)


def render_claude_md_block(
    sections: Iterable[Section],
    overview_paragraph: str,
) -> str:
    """Render the content that goes between BEGIN and END markers.

    Leading and trailing newlines are included so the block sits cleanly
    between the markers in the final file.
    """
    titles = ", ".join(s.title for s in sections)
    lines = [
        "",  # blank line after BEGIN_MARKER
        "## NExtSEEK Documentation",
        "",
        overview_paragraph,
        "",
        f"Top-level sections: {titles}.",
        "",
        "For detail, read `/app/docs/nextseek/README.md` first.",
        "",  # trailing blank line before END_MARKER
    ]
    return "\n".join(lines)


def update_claude_md(path: Path, block_content: str) -> None:
    """Atomically replace the markered block in `path` with `block_content`.

    Uses write-to-sibling-tmpfile + `os.replace` for atomicity. If either
    marker is missing, duplicated, or out-of-order, raises `ValueError` and
    leaves the file unchanged.

    Args:
        path: Path to a file containing exactly one BEGIN and one END marker.
        block_content: New content to place between the markers. Line
            endings are preserved verbatim — callers typically produce this
            via `render_claude_md_block`.

    Raises:
        ValueError: marker missing, duplicated, or out of order.
        OSError: filesystem failure (atomicity preserved — original unchanged).
    """
    original = path.read_text()

    begin_count = original.count(BEGIN_MARKER)
    end_count = original.count(END_MARKER)
    if begin_count == 0 or end_count == 0:
        raise ValueError(
            f"missing marker in {path}: "
            f"BEGIN count={begin_count}, END count={end_count}. "
            f"Expected exactly 1 of each."
        )
    if begin_count > 1 or end_count > 1:
        raise ValueError(
            f"duplicate marker in {path}: "
            f"BEGIN count={begin_count}, END count={end_count}. "
            f"Expected exactly 1 of each."
        )

    begin_idx = original.index(BEGIN_MARKER)
    end_idx = original.index(END_MARKER)
    if begin_idx >= end_idx:
        raise ValueError(
            f"marker order inverted in {path}: "
            f"BEGIN at {begin_idx}, END at {end_idx}"
        )

    prefix = original[: begin_idx + len(BEGIN_MARKER)]
    suffix = original[end_idx:]
    new_content = prefix + block_content + suffix

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_content)
    try:
        os.replace(tmp, path)
    except OSError:
        # Atomicity: tmp written but replace failed — clean up, leave original alone.
        if tmp.exists():
            tmp.unlink()
        raise
```

## 7. Modified Files (exact diffs)

None — new files only.

## 8. Verification

```bash
uv run pytest tests/unit/test_toc.py tests/unit/test_constants.py -q

# Coverage for toc + constants
uv run pytest \
    --cov=build_tools.ingest_nextseek_docs.toc \
    --cov=build_tools.ingest_nextseek_docs.constants \
    --cov-report=term-missing --cov-fail-under=95 \
    tests/unit/test_toc.py tests/unit/test_constants.py

# Marker roundtrip: the string in constants.py matches the one in container/CLAUDE.md
uv run python -c "
from pathlib import Path
from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER
md = Path('container/CLAUDE.md').read_text()
assert BEGIN_MARKER in md and END_MARKER in md
print('marker consistency ok')
"

# Full suite
uv run pytest -q
```

**Expected test count**: 6 in `test_constants.py` + 8 in `test_toc.py` = 14 new.

**Expected coverage**: ≥ 95% for both modules.

## 9. Implementation Notes

- `render_claude_md_block` returns a string that begins with a `\n` and ends with a `\n` so, when placed immediately after the BEGIN marker line and before the END marker, the result has blank lines around the content block — matching `test_update_claude_md_replaces_block_between_markers`'s expected output.
- `update_claude_md` uses `path.read_text()` / `tmp.write_text()` — default UTF-8 encoding. All DMAC docs are ASCII/UTF-8; no encoding-detection needed.
- `path.with_suffix(path.suffix + ".tmp")` produces `CLAUDE.md.tmp` from `CLAUDE.md`. This is the sibling-tmpfile idiom (same filesystem → `os.replace` is atomic on POSIX).
- Activation order for `os.replace` failure: we clean up the tmp, then re-raise. The original file is untouched because we never opened it for writing.
- `render_claude_md_block` expects `overview_paragraph` to NOT already contain the surrounding blank lines — it adds them. Caller (T7) passes a single-paragraph string.

## 10. Worktree & Branch

- **Branch**: `task/05-toc`
- **Worktree**: `.claude/worktrees/task-05-toc/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass; coverage ≥ 95% for both new modules.
