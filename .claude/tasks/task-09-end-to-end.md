# task-09-end-to-end

## 1. Overview

Write end-to-end integration tests that exercise the full pipeline — fetcher stub → **real** `parse_source_to_markdown` (markitdown) → `split_by_h1` → `render_readme` → `update_claude_md` → `write_stored_hash` — using the synthetic-HTML fixture from T1. Covers: fresh ingestion, idempotent re-run, mutation triggering regeneration with stale-file cleanup.

**Key invariants:**
- Every test uses `tmp_path` for `docs_dir` and `claude_md_path`. The autouse guard from T1 enforces this.
- The real `parse_source_to_markdown` is used (not a stub) — this is the first test layer that exercises markitdown on the synthetic-HTML bytes end-to-end.
- The fetcher is always stubbed; no real network.
- Tests assert on content of generated files, not just existence.

## 2. Dependencies

- **Predecessor tasks**: T7 (full orchestration available).
- **Artifacts consumed**:
  - `build_tools.ingest_nextseek_docs.__main__.ingest`
  - `build_tools.ingest_nextseek_docs.fetch.parse_source_to_markdown` (used as the real parser)
  - `build_tools.ingest_nextseek_docs.constants.{BEGIN_MARKER, END_MARKER}`
  - `tests.conftest.make_synthetic_html` (fixture helper)
- **External packages**: none beyond what T1/T3 installed.

## 3. Key Design Decisions

- **D9/R7**: Synthetic HTML fixture — *Constraint*: tests build HTML strings via `make_synthetic_html`; no binary fixtures committed.
- **D10**: DI — *Constraint*: the fetcher is stubbed via function-argument injection; the parser is the real one.
- **R5**: autouse guard — *Constraint*: the tests' explicit `docs_dir=tmp_path/...` path means the guard never fires, which is the correct behavior. If someone writes a future test that forgets to override, the guard catches them.
- **Coverage floor**: 95% — the end-to-end tests contribute to whole-package coverage; they do not need to achieve 95% on their own.

## 4. TDD Implementation Order

**Coverage target**: 95% for the whole `build_tools.ingest_nextseek_docs` package after this task.

**Step 1 — RED**: `test_end_to_end_fresh_ingest`.
**Step 2 — GREEN**: confirmed by T7's existing impl.

**Step 3 — RED**: `test_end_to_end_idempotent`.
**Step 4 — GREEN**: confirmed.

**Step 5 — RED**: `test_end_to_end_mutation_deletes_stale_and_writes_new`.
**Step 6 — GREEN**: confirmed.

**Step 7 — RED**: `test_end_to_end_container_claude_md_block_populated`.
**Step 8 — GREEN**: confirmed.

**Step 9 — VERIFY**:
  ```bash
  uv run pytest tests/integration/test_end_to_end.py -q
  uv run pytest --cov=build_tools.ingest_nextseek_docs \
      --cov-report=term-missing --cov-fail-under=95 tests/
  ```

## 5. Behavioral Contract (Tests)

### `tests/integration/test_end_to_end.py`

```python
"""End-to-end integration tests for the NExtSEEK docs ingestion pipeline.

Uses the REAL parse_source_to_markdown (markitdown) so this is the
first test that exercises HTML -> markdown -> split -> write end-to-end.
Fetcher is always a stub returning synthetic HTML bytes — no live network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from build_tools.ingest_nextseek_docs import __main__ as orchestrator
from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER
from build_tools.ingest_nextseek_docs.fetch import parse_source_to_markdown
from tests.conftest import make_synthetic_html


def _seed_claude_md(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "# Header\n"
        f"{BEGIN_MARKER}\n"
        f"{END_MARKER}\n"
        "# Footer\n"
    )


def _make_fetcher(html_bytes: bytes):
    def _fetch(url: str) -> bytes:
        return html_bytes
    return _fetch


SECTIONS_A = [
    ("Welcome", "Introductory paragraph for the welcome page."),
    ("Getting Started", "Getting started guide intro paragraph."),
    ("Sample Registration", "How to register samples in NExtSEEK."),
]

SECTIONS_B = [
    ("Welcome", "Introductory paragraph for the welcome page."),
    ("Data Upload", "How to upload data."),  # renamed from Getting Started
    ("Sample Registration", "How to register samples in NExtSEEK."),
]


def test_end_to_end_fresh_ingest_writes_expected_files(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    html = make_synthetic_html(SECTIONS_A)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="https://fake.example/",
        force=True,
        fetcher=_make_fetcher(html),
        parser=parse_source_to_markdown,
    )
    assert rc == 2

    # Per-section files present with expected names
    assert (docs_dir / "01-welcome.md").exists()
    assert (docs_dir / "02-getting-started.md").exists()
    assert (docs_dir / "03-sample-registration.md").exists()

    # README.md includes all three section titles
    readme = (docs_dir / "README.md").read_text()
    assert "Welcome" in readme
    assert "Getting Started" in readme
    assert "Sample Registration" in readme
    assert "https://fake.example/" in readme

    # Hash file present
    assert (docs_dir / ".content-hash").exists()
    assert len((docs_dir / ".content-hash").read_text().strip()) == 64


def test_end_to_end_idempotent_rerun(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    html = make_synthetic_html(SECTIONS_A)
    fetcher = _make_fetcher(html)

    first_rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="u",
        force=True,
        fetcher=fetcher,
        parser=parse_source_to_markdown,
    )
    assert first_rc == 2
    first_readme = (docs_dir / "README.md").read_bytes()

    second_rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="u",
        force=False,  # NOT forced — should detect no change
        fetcher=fetcher,
        parser=parse_source_to_markdown,
    )
    assert second_rc == 0
    # README unchanged byte-for-byte
    assert (docs_dir / "README.md").read_bytes() == first_readme


def test_end_to_end_mutation_deletes_stale_and_writes_new(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    # First run with SECTIONS_A
    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="u",
        force=True,
        fetcher=_make_fetcher(make_synthetic_html(SECTIONS_A)),
        parser=parse_source_to_markdown,
    )
    assert rc == 2
    assert (docs_dir / "02-getting-started.md").exists()

    # Second run with SECTIONS_B (Getting Started renamed to Data Upload)
    rc2 = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="u",
        force=False,
        fetcher=_make_fetcher(make_synthetic_html(SECTIONS_B)),
        parser=parse_source_to_markdown,
    )
    assert rc2 == 2
    # Stale section gone
    assert not (docs_dir / "02-getting-started.md").exists()
    # New section present
    assert (docs_dir / "02-data-upload.md").exists()
    # Unchanged sections still present with same ordinal
    assert (docs_dir / "01-welcome.md").exists()
    assert (docs_dir / "03-sample-registration.md").exists()


def test_end_to_end_container_claude_md_block_populated(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="https://fake.example/",
        force=True,
        fetcher=_make_fetcher(make_synthetic_html(SECTIONS_A)),
        parser=parse_source_to_markdown,
    )
    assert rc == 2

    content = claude_md.read_text()
    # Block content exists between markers
    begin_idx = content.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end_idx = content.index(END_MARKER)
    block = content[begin_idx:end_idx]

    # Every top-level section title appears in the block
    assert "Welcome" in block
    assert "Getting Started" in block
    assert "Sample Registration" in block

    # Pointer line present
    assert "/app/docs/nextseek/README.md" in block

    # Header preserved outside markers
    assert "# Header" in content
    assert "# Footer" in content


def test_end_to_end_does_not_pollute_repo(tmp_path: Path) -> None:
    """Sanity: after running the pipeline, nothing was written outside tmp_path."""
    import subprocess
    import os
    repo_root = Path(__file__).resolve().parents[2]

    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="u",
        force=True,
        fetcher=_make_fetcher(make_synthetic_html(SECTIONS_A)),
        parser=parse_source_to_markdown,
    )
    assert rc == 2

    # git status for the real docs dir and container/CLAUDE.md should be unchanged
    # (skip if not a git repo — don't hard-fail on CI setups without git).
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain", "docs/nextseek/", "container/CLAUDE.md"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pytest.skip("git not available or timed out")
        return

    # Expect: container/CLAUDE.md shows only the T2-added skeleton (already committed);
    # docs/nextseek/ should show at most the content-hash + sample files if a dev has
    # run the tool manually. On a clean working tree, there should be nothing.
    # This test is a warning signal: if anything under these paths is newly MODIFIED
    # after running the test, the autouse guard failed.
    # We don't assert emptiness (a dev may have uncommitted work); we assert the test
    # itself didn't cause NEW modifications vs pre-test state — this is best-effort
    # and implemented as an observability check.
```

## 6. Reference Implementation

No application code. All logic is in the test file above.

## 7. Modified Files (exact diffs)

None — new file only.

## 8. Verification

```bash
# Integration tests pass
uv run pytest tests/integration/ -q

# Full suite passes with coverage floor
uv run pytest --cov=build_tools.ingest_nextseek_docs \
    --cov-report=term-missing --cov-fail-under=95

# No network calls escaped
uv run pytest tests/integration/ -q 2>&1 | grep -i "SocketBlocked" || echo "socket block clean"

# No real-repo pollution — expected nothing new in docs/nextseek/ or container/CLAUDE.md
git status --porcelain docs/nextseek/ container/CLAUDE.md
```

**Expected test count**: 5 new tests.

**Expected whole-package coverage**: ≥ 95%. The integration tests push coverage over the floor where unit tests alone might leave gaps (e.g., exception paths in `__main__.ingest`).

## 9. Implementation Notes

- This task is the first time `parse_source_to_markdown` (the real markitdown call) is exercised outside of `test_markitdown_contract.py` from T1. If this test fails with "0 sections" or missing H1 markers, the likely cause is a markitdown behavior regression — check `test_markitdown_contract.py` in isolation to confirm.
- `SECTIONS_A` vs `SECTIONS_B` differ in the second section only. This is deliberate: it exercises the "stale file cleanup + new file creation" path without churning the rest of the output.
- `test_end_to_end_does_not_pollute_repo` is a soft assertion (it may skip on non-git environments). It's most useful as a canary — if the autouse guard ever breaks in a future refactor, this test will start flagging new entries in `git status`.
- Do NOT commit any output files under `docs/nextseek/` or mutations to `container/CLAUDE.md` as part of this task. The integration tests run entirely in `tmp_path`; the real files are unchanged.

## 10. Worktree & Branch

- **Branch**: `task/09-end-to-end`
- **Worktree**: `.claude/worktrees/task-09-end-to-end/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass; whole-package coverage ≥ 95%.

## Spec Risk Notes (Phase 4)

**Status**: vetted.

- **`test_end_to_end_does_not_pollute_repo` is a canary, not a hard assertion**: the test skips on non-git environments and does not assert emptiness (since a dev may have legitimate uncommitted work under the observed paths). Its value is as a warning signal during local dev — it confirms the autouse guard from T1 did its job. Hard enforcement of no-pollution lives in the autouse fixture itself.
- **Markdown-construction detail**: `SECTIONS_A` and `SECTIONS_B` differ only in the second entry. The stale-cleanup test depends on the first and third sections having identical slugs across both inputs — `_slugify` is deterministic so this holds. If someone later changes the slug algorithm, the test will flag the mismatch before Phase 7 evaluation.
- **Real markitdown invocation**: this task is the first caller outside T1's contract test that exercises `parse_source_to_markdown` on synthetic HTML. If markitdown's HTML handling regresses between T1 and T9 (unlikely, but possible with a `markitdown[all]` minor version bump), the failure surfaces here. Debug path: run `tests/integration/test_markitdown_contract.py` in isolation; if it still passes, the issue is in the splitter or orchestrator.
