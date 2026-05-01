# task-07-orchestrator

## 1. Overview

Wire the full ingestion pipeline in `build_tools/ingest_nextseek_docs/__main__.py`. Provides:
- `ingest(*, docs_dir, claude_md_path, doc_url, force, fetcher, parser) -> int` — the orchestration function (DI for `fetcher`/`parser`).
- `main(argv=None) -> int` — argparse CLI wrapper that supplies production defaults from `constants.py`.
- `if __name__ == "__main__": sys.exit(main())` entry point so `python -m build_tools.ingest_nextseek_docs` works.

**Key invariants:**
- **Write ordering is LOAD-BEARING:** section files → README.md → container/CLAUDE.md → **hash file LAST**. If any step raises, hash is unwritten, and the next run re-detects change.
- Logging goes to stderr (INFO). stdout is reserved for human-readable status (`no changes` or `changes written: N section files, README, container/CLAUDE.md`).
- Exit codes: `0` no change, `1` error, `2` changes written.
- Tests always pass explicit `tmp_path`-based `docs_dir` and `claude_md_path` — the autouse guard from T1 catches any that don't.
- Tests use DI stubs for `fetcher` and `parser` instead of monkeypatching module-level names.
- `--force` CLI flag bypasses the hash-match early exit.

## 2. Dependencies

- **Predecessor tasks**: T3 (fetch), T4 (split), T5 (toc + constants), T6 (hashing). All artifacts must be merged before T7 begins.
- **Artifacts consumed**:
  - `build_tools.ingest_nextseek_docs.fetch.{fetch_source_bytes, parse_source_to_markdown}`
  - `build_tools.ingest_nextseek_docs.split.{Section, split_by_h1}`
  - `build_tools.ingest_nextseek_docs.toc.{render_readme, render_claude_md_block, update_claude_md}`
  - `build_tools.ingest_nextseek_docs.hashing.{compute_content_hash, read_stored_hash, write_stored_hash}`
  - `build_tools.ingest_nextseek_docs.constants.{DEFAULT_DOC_URL, DEFAULT_DOCS_DIR, DEFAULT_CLAUDE_MD_PATH}`
- **External packages**: none beyond what T1/T3 installed.

## 3. Key Design Decisions

- **D10**: DI for `fetcher`/`parser` — *Constraint*: signature requires keyword-only `fetcher` and `parser` with production defaults. Tests override both.
- **D14**: Hash LAST — *Constraint*: the `compute_content_hash` / `write_stored_hash` sequence in `ingest()` is the final operation before returning `2`.
- **D11**: Exit codes — *Constraint*: tests assert exact exit code for each case.
- **R6/R11 resolution**: logging contract — *Constraint*: `logging.basicConfig(level=logging.INFO, stream=sys.stderr, format=...)` configured once in `main()`. `ingest()` itself must never call `logging.basicConfig`.
- **R4/R5 resolution**: DI + autouse guard — *Constraint*: `test_main.py` uses monkeypatch only for one narrow purpose (the `write_stored_hash` atomicity test). All other tests pass stubs via DI.
- **Coverage floor**: 95% for `__main__.py`.

## 4. TDD Implementation Order

**Coverage target**: 95%. The `if __name__ == "__main__":` line is one uncovered statement; argparse's help emission is separately tested via subprocess.

**Step 1 — RED**: `test_ingest_exits_0_when_hash_matches`.
**Step 2 — GREEN**: implement `ingest()` scaffolding that returns 0 on hash match.

**Step 3 — RED**: `test_ingest_exits_2_on_fresh_run`.
**Step 4 — GREEN**: full pipeline body.

**Step 5 — RED**: `test_ingest_writes_files_in_correct_order` — asserts each expected file exists after exit 2.
**Step 6 — GREEN**: pipeline.

**Step 7 — RED**: `test_ingest_force_overrides_hash_match`.
**Step 8 — GREEN**: force branch.

**Step 9 — RED**: `test_ingest_fetcher_exception_exits_1_no_writes`.
**Step 10 — GREEN**: try/except around the whole flow, catching exceptions → log → return 1.

**Step 11 — RED**: `test_ingest_parser_no_h1_exits_1`.
**Step 12 — GREEN**: check for empty-section-list and return 1.

**Step 13 — RED**: `test_ingest_cleans_stale_section_files`.
**Step 14 — GREEN**: delete glob before writing.

**Step 15 — RED**: `test_ingest_writes_hash_last` — monkeypatch `write_stored_hash` to raise; assert hash absent but other files present.
**Step 16 — GREEN**: confirmed by ordering.

**Step 17 — RED**: `test_ingest_emits_info_logs_and_status_line` — uses `caplog` for log-record capture (not `capsys` for stderr, because `ingest()` deliberately does not configure logging — that's `main()`'s job). stdout assertion stays on `capsys`.
**Step 18 — GREEN**: add status print to stdout + logger.info calls throughout.

**Step 19 — RED**: `test_cli_help_mentions_force` (subprocess invocation).
**Step 20 — GREEN**: argparse with `--force` flag.

**Step 21 — RED**: `test_ingest_signature_has_fetcher_parser` (via inspect).
**Step 22 — GREEN**: already present in impl.

**Step 23 — VERIFY**:
  ```bash
  uv run pytest tests/unit/test_main.py -q
  uv run pytest --cov=build_tools.ingest_nextseek_docs \
      --cov-report=term-missing --cov-fail-under=95 tests/unit/
  ```

## 5. Behavioral Contract (Tests)

### `tests/unit/test_main.py`

```python
"""Unit tests for build_tools.ingest_nextseek_docs.__main__."""
from __future__ import annotations

import inspect
import subprocess
import sys
from pathlib import Path
from typing import Callable

import pytest

from build_tools.ingest_nextseek_docs import __main__ as orchestrator
from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER
from build_tools.ingest_nextseek_docs.hashing import compute_content_hash
from tests.conftest import make_synthetic_html


# ---- Stubs ----

def _html_bytes(sections: list[tuple[str, str]]) -> bytes:
    return make_synthetic_html(sections)


def _markdown(sections: list[tuple[str, str]]) -> str:
    parts: list[str] = []
    for title, para in sections:
        parts.append(f"# {title}\n\n{para}\n")
    return "\n".join(parts)


def _stub_fetcher(return_bytes: bytes) -> Callable[[str], bytes]:
    def _fetch(url: str) -> bytes:
        return return_bytes
    return _fetch


def _stub_parser(return_text: str) -> Callable[[bytes], str]:
    def _parse(data: bytes) -> str:
        return return_text
    return _parse


def _seed_claude_md(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"# Header\n{BEGIN_MARKER}\n{END_MARKER}\n# Footer\n"
    )


# ---- Tests ----


def test_ingest_signature_has_fetcher_and_parser_kwargs() -> None:
    sig = inspect.signature(orchestrator.ingest)
    params = sig.parameters
    assert "fetcher" in params
    assert "parser" in params
    # All of docs_dir, claude_md_path, doc_url, force, fetcher, parser are keyword-only
    assert all(
        p.kind == inspect.Parameter.KEYWORD_ONLY
        for p in params.values()
    )


def test_ingest_exits_0_when_hash_matches(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    docs_dir.mkdir(parents=True)
    md = _markdown([("A", "a-body.")])
    (docs_dir / ".content-hash").write_text(compute_content_hash(md) + "\n")
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=False,
        fetcher=_stub_fetcher(b"irrelevant"),
        parser=_stub_parser(md),
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "no changes" in captured.out
    # No new section files were written
    assert list(docs_dir.glob("*-*.md")) == []


def test_ingest_exits_2_on_fresh_run_writes_expected_files(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    md = _markdown([("Welcome", "Intro."), ("Getting Started", "More.")])

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=False,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    assert rc == 2
    assert (docs_dir / "01-welcome.md").exists()
    assert (docs_dir / "02-getting-started.md").exists()
    assert (docs_dir / "README.md").exists()
    assert (docs_dir / ".content-hash").exists()
    # CLAUDE.md block populated
    content = claude_md.read_text()
    assert "## NExtSEEK Documentation" in content
    assert "Welcome" in content


def test_ingest_force_true_overrides_hash_match(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    docs_dir.mkdir(parents=True)
    md = _markdown([("A", "a-body.")])
    (docs_dir / ".content-hash").write_text(compute_content_hash(md) + "\n")
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=True,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    assert rc == 2
    assert (docs_dir / "01-a.md").exists()


def test_ingest_fetcher_exception_exits_1_no_writes(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    def boom(url: str) -> bytes:
        raise RuntimeError("network down")

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=False,
        fetcher=boom,
        parser=_stub_parser(""),
    )
    assert rc == 1
    # No section files; hash file not written
    assert not (docs_dir / ".content-hash").exists()
    assert list(docs_dir.glob("*-*.md")) == []


def test_ingest_parser_returns_no_h1_exits_1(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=False,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser("just plain text, no headings\n"),
    )
    assert rc == 1
    assert not (docs_dir / ".content-hash").exists()


def test_ingest_cleans_stale_section_files(tmp_path: Path) -> None:
    docs_dir = tmp_path / "docs" / "nextseek"
    docs_dir.mkdir(parents=True)
    (docs_dir / "99-stale.md").write_text("# Stale\n\nold.\n")
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    md = _markdown([("Welcome", "Intro.")])
    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=True,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    assert rc == 2
    assert not (docs_dir / "99-stale.md").exists()
    assert (docs_dir / "01-welcome.md").exists()


def test_ingest_writes_hash_last(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """If write_stored_hash raises, section files + README + CLAUDE.md are written
    but .content-hash is not. Proves hash is written last."""
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    md = _markdown([("Welcome", "Intro.")])

    def boom(path: Path, digest: str) -> None:
        raise OSError("disk full on hash write")

    monkeypatch.setattr(orchestrator, "write_stored_hash", boom)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=True,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    # Hash failure raises through, exit 1
    assert rc == 1
    # But by the time the hash failed, section files and README existed
    assert (docs_dir / "01-welcome.md").exists()
    assert (docs_dir / "README.md").exists()
    # And crucially, .content-hash does NOT exist
    assert not (docs_dir / ".content-hash").exists()


def test_ingest_emits_info_logs_and_status_line(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """ingest() emits INFO-level logs (captured via caplog, not capsys).

    ingest() deliberately does NOT call logging.basicConfig — that's main()'s
    job — so stderr is empty when ingest is called directly from a test.
    The log records are still produced; we use pytest's caplog to capture them.
    stdout should contain the human-readable status line.
    """
    import logging

    caplog.set_level(logging.INFO, logger="build_tools.ingest_nextseek_docs")
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    md = _markdown([("Welcome", "Intro.")])

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=True,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    assert rc == 2

    # stdout: single status line about changes.
    captured = capsys.readouterr()
    assert "changes written" in captured.out.lower()

    # Logs: at least one INFO record from the orchestrator module.
    info_records = [
        r for r in caplog.records
        if r.levelno == logging.INFO
        and r.name.startswith("build_tools.ingest_nextseek_docs")
    ]
    assert len(info_records) >= 1, (
        f"expected at least 1 INFO log from orchestrator; got: "
        f"{[(r.name, r.levelname, r.getMessage()) for r in caplog.records]}"
    )


def test_ingest_preserves_existing_readme_md_during_cleanup(tmp_path: Path) -> None:
    """Pre-existing README.md must be overwritten (not left stale, not deleted and absent).

    Exercises the `if stale.name == 'README.md': continue` branch of the
    cleanup loop.
    """
    docs_dir = tmp_path / "docs" / "nextseek"
    docs_dir.mkdir(parents=True)
    (docs_dir / "README.md").write_text("# OLD README\n\nstale.\n")
    (docs_dir / "01-old-section.md").write_text("# Old\n\nstale.\n")
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)
    md = _markdown([("Welcome", "Intro.")])

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=True,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    assert rc == 2
    # Stale section file deleted
    assert not (docs_dir / "01-old-section.md").exists()
    # README.md still exists AND was rewritten with new content
    readme = docs_dir / "README.md"
    assert readme.exists()
    assert "OLD README" not in readme.read_text()
    assert "Welcome" in readme.read_text()


def test_cli_module_help_mentions_force_flag() -> None:
    """Running `python -m build_tools.ingest_nextseek_docs --help` shows --force."""
    result = subprocess.run(
        [sys.executable, "-m", "build_tools.ingest_nextseek_docs", "--help"],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0
    assert "--force" in result.stdout
    assert "--help" in result.stdout


def test_test_main_uses_monkeypatch_at_most_once_per_test_class() -> None:
    """Enforce the DI-over-monkeypatch convention: only one test uses monkeypatch on orchestrator."""
    src = Path(__file__).read_text()
    # Count references to 'monkeypatch.setattr(orchestrator' specifically
    references = src.count("monkeypatch.setattr(orchestrator")
    assert references <= 1, (
        f"only test_ingest_writes_hash_last should monkeypatch orchestrator; "
        f"found {references} references"
    )


def test_extract_overview_falls_back_when_first_section_is_empty_body(
    tmp_path: Path,
) -> None:
    """First section's description is the '(section overview)' sentinel → generic fallback prose."""
    docs_dir = tmp_path / "docs" / "nextseek"
    claude_md = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(claude_md)

    # First H1 has no body paragraph before the next H1 → description = "(section overview)".
    md = "# Overview\n# Real Section\n\nBody here.\n"

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=claude_md,
        doc_url="fake",
        force=True,
        fetcher=_stub_fetcher(b"x"),
        parser=_stub_parser(md),
    )
    assert rc == 2
    content = claude_md.read_text()
    # The generic fallback mentions the section count.
    assert "covering 2 top-level sections" in content
```

## 6. Reference Implementation

### `build_tools/ingest_nextseek_docs/__main__.py` (new)

```python
"""CLI and orchestration for NExtSEEK docs ingestion."""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from typing import Callable

from build_tools.ingest_nextseek_docs.constants import (
    DEFAULT_CLAUDE_MD_PATH,
    DEFAULT_DOC_URL,
    DEFAULT_DOCS_DIR,
)
from build_tools.ingest_nextseek_docs.fetch import (
    fetch_source_bytes,
    parse_source_to_markdown,
)
from build_tools.ingest_nextseek_docs.hashing import (
    compute_content_hash,
    read_stored_hash,
    write_stored_hash,
)
from build_tools.ingest_nextseek_docs.split import Section, split_by_h1
from build_tools.ingest_nextseek_docs.toc import (
    render_claude_md_block,
    render_readme,
    update_claude_md,
)

logger = logging.getLogger(__name__)

EXIT_NO_CHANGE = 0
EXIT_ERROR = 1
EXIT_CHANGES_WRITTEN = 2


def ingest(
    *,
    docs_dir: Path,
    claude_md_path: Path,
    doc_url: str,
    force: bool,
    fetcher: Callable[[str], bytes] = fetch_source_bytes,
    parser: Callable[[bytes], str] = parse_source_to_markdown,
) -> int:
    """Run the full ingestion pipeline. Return an exit code."""
    try:
        logger.info("Fetching source from %s", doc_url)
        source_bytes = fetcher(doc_url)
        logger.info("Parsing %d bytes to markdown", len(source_bytes))
        raw_markdown = parser(source_bytes)

        content_hash = compute_content_hash(raw_markdown)
        hash_path = docs_dir / ".content-hash"
        stored = read_stored_hash(hash_path)

        if stored == content_hash and not force:
            sys.stdout.write("no changes\n")
            return EXIT_NO_CHANGE

        sections = split_by_h1(raw_markdown)
        if not sections:
            logger.error(
                "parser returned markdown with zero H1 sections; "
                "markitdown output format may have changed"
            )
            return EXIT_ERROR

        # Regeneration phase — write ordering matters.
        # 1. Delete stale section files.
        docs_dir.mkdir(parents=True, exist_ok=True)
        for stale in docs_dir.glob("*.md"):
            if stale.name == "README.md":
                continue
            stale.unlink()

        # 2. Write per-section files.
        for section in sections:
            path = docs_dir / f"{section.ordinal:02d}-{section.slug}.md"
            path.write_text(section.body)

        # 3. Write README.md.
        readme = render_readme(sections, doc_url, content_hash)
        (docs_dir / "README.md").write_text(readme)

        # 4. Update container/CLAUDE.md.
        overview = _extract_overview_paragraph(sections)
        block = render_claude_md_block(sections, overview)
        update_claude_md(claude_md_path, block)

        # 5. HASH LAST.
        write_stored_hash(hash_path, content_hash)

        sys.stdout.write(
            f"changes written: {len(sections)} section files, "
            f"README, container/CLAUDE.md\n"
        )
        return EXIT_CHANGES_WRITTEN

    except Exception:
        logger.exception("ingest failed")
        return EXIT_ERROR


def _extract_overview_paragraph(sections: list[Section]) -> str:
    """Return the first Section's description, or a generic fallback if it's the empty-body sentinel.

    Precondition (guaranteed by ingest()): `sections` is non-empty.
    """
    desc = sections[0].description
    if desc and desc != "(section overview)":
        return desc
    return f"NExtSEEK documentation covering {len(sections)} top-level sections."


def main(argv: list[str] | None = None) -> int:
    """argparse CLI entry point."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        prog="ingest_nextseek_docs",
        description="Fetch NExtSEEK GitBook, split, and regenerate docs.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="regenerate even if the content hash matches",
    )
    parser.add_argument(
        "--doc-url",
        default=DEFAULT_DOC_URL,
        help=f"source URL (default: {DEFAULT_DOC_URL})",
    )
    parser.add_argument(
        "--docs-dir",
        type=Path,
        default=DEFAULT_DOCS_DIR,
        help=f"output docs dir (default: {DEFAULT_DOCS_DIR})",
    )
    parser.add_argument(
        "--claude-md-path",
        type=Path,
        default=DEFAULT_CLAUDE_MD_PATH,
        help=f"container CLAUDE.md path (default: {DEFAULT_CLAUDE_MD_PATH})",
    )
    args = parser.parse_args(argv)
    return ingest(
        docs_dir=args.docs_dir,
        claude_md_path=args.claude_md_path,
        doc_url=args.doc_url,
        force=args.force,
    )


if __name__ == "__main__":
    sys.exit(main())
```

## 7. Modified Files (exact diffs)

None — new file.

## 8. Verification

```bash
uv run pytest tests/unit/test_main.py -q

# Coverage — now enforcing 95% globally
uv run pytest --cov=build_tools.ingest_nextseek_docs \
    --cov-report=term-missing --cov-fail-under=95 tests/unit/

# CLI invocation smoke
uv run python -m build_tools.ingest_nextseek_docs --help

# Full suite
uv run pytest -q
```

**Expected test count**: 12 new tests in `test_main.py`.

**Expected coverage**: ≥ 95% for `__main__.py`. The `if __name__ == "__main__":` guard contributes 1 uncovered line; everything else is exercised by:
- hash-match (exit 0) and hash-mismatch/force (exit 2) cover the early-return branch,
- fetcher and parser failure cases cover the `except Exception` path,
- no-H1 case covers the `if not sections` early return,
- stale-cleanup with and without a pre-existing README.md cover both sides of the `if stale.name == "README.md"` branch,
- `_extract_overview_paragraph` is exercised via two tests: one where the first section has a real description, one where it falls through to the generic fallback.

## 9. Implementation Notes

- `docs_dir.glob("*.md")` skips `README.md` explicitly but catches all `NN-slug.md` section files, including any from a previous run that no longer exists in the new content. It does NOT match `.content-hash` (different extension).
- `_extract_overview_paragraph` uses the first section's `description` as-is when non-empty. The spec §4.7 says "verbatim from the first H1 section's first paragraph" — `Section.description` IS that first paragraph (truncated). For a real GitBook, the first H1 is typically "Welcome" with a descriptive first paragraph, so this works in practice. Fallback text is generic enough to be useful when the first section has no body.
- `logger.exception` captures the traceback automatically and logs it to stderr at ERROR level — meaningful diagnostic without polluting stdout.
- All module-level defaults for `ingest()`'s `fetcher`/`parser` parameters reference the REAL functions. Tests override both explicitly; the autouse guard from T1 protects against accidental real-network calls even if a test forgets to override.
- `main()` defaults come from `constants.py`, not from `ingest()`'s `Callable` defaults. `ingest()` has no defaults for paths/url/force — those are mandatory kwargs.

## 10. Worktree & Branch

- **Branch**: `task/07-orchestrator`
- **Worktree**: `.claude/worktrees/task-07-orchestrator/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass; `__main__.py` coverage ≥ 95%; whole-package coverage ≥ 95%.

## Spec Risk Notes (Phase 4)

**Status**: vetted after revision.

- **Fixed during Phase 4**: (1) The original logging test used `capsys.readouterr().err` to assert stderr activity, but `ingest()` intentionally does NOT call `logging.basicConfig` (only `main()` does). Without configured handlers, INFO-level log records are dropped and stderr would be empty — the test would fail. Switched to `caplog.set_level(logging.INFO, logger="build_tools.ingest_nextseek_docs")` which captures records directly from the logger. (2) Added `test_ingest_preserves_existing_readme_md_during_cleanup` to exercise the `if stale.name == "README.md": continue` branch (previously only the False side was hit). (3) Added `test_extract_overview_falls_back_when_first_section_is_empty_body` to exercise the fallback branch in `_extract_overview_paragraph`. (4) Removed the dead `if not sections: return ""` defensive branch from `_extract_overview_paragraph` — by construction (ingest's empty-section check returns 1 first), it's unreachable; keeping it would have been an untested line.
- **Coverage trajectory**: 12 tests, each targeting a specific line or branch. Expected coverage ≥ 95%.
- **Risk still present**: `main()` itself is tested only via the `test_cli_module_help_mentions_force_flag` subprocess invocation. Argparse's help generation is exercised there but the `return ingest(...)` line at the bottom of `main()` is hit only via the subprocess test. Coverage may report this as covered (subprocess test writes to coverage via pytest-cov's subprocess plugin) or uncovered (if subprocess coverage collection isn't configured). If `main()` comes in below 95% in practice, add a direct `main()` unit test that stubs `ingest` via monkeypatching — noted as a possible follow-up.
