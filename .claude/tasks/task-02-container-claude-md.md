# task-02-container-claude-md

## 1. Overview

Create two things:
1. **`container/CLAUDE.md`** — the baseline in-container agent instructions, baked into the Docker image as `/app/CLAUDE.md` in a later POC milestone. Contains a human-authored header plus the empty `<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->` / `<!-- END NEXTSEEK-DOCS (auto-generated) -->` marker block that the ingestion tool will later populate.
2. **`build_tools/ingest_nextseek_docs/` package scaffolding** — empty `__init__.py` files so T3–T6 can import from the package without racing on directory creation. No module content yet.

Also adds a pointer line to repo-root `CLAUDE.md` so future development sessions know about `container/CLAUDE.md`.

**Key invariants:**
- `container/CLAUDE.md` marker strings are byte-identical to what T5 will put in `constants.py`.
- `build_tools/` and `build_tools/ingest_nextseek_docs/` are importable Python packages.
- Repo-root `CLAUDE.md` mentions `container/CLAUDE.md`.
- This task creates no runtime code. Any assertion about modules under `build_tools/ingest_nextseek_docs/` is tested in T3–T7.

## 2. Dependencies

- **Predecessor tasks**: T1 (for pytest infra — verification below uses pytest).
- **Artifacts consumed**: `tests/conftest.py` (the autouse guard must remain dormant because `constants.py` is still not created here either; T5 creates it).
- **External packages**: none (no `uv add`).

## 3. Key Design Decisions

- **D7**: Injection target is `container/CLAUDE.md` (new), not repo-root — *Constraint*: this task writes `container/CLAUDE.md`, not `CLAUDE.md`. The repo-root file gets only a one-line pointer.
- **R2 resolution**: marker strings — *Constraint*: the marker strings in `container/CLAUDE.md` MUST be exactly `<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->` and `<!-- END NEXTSEEK-DOCS (auto-generated) -->` (with trailing `(auto-generated)`). T5's `constants.BEGIN_MARKER` / `END_MARKER` will equal these strings byte-for-byte; T7 and T9 assert round-trip consistency.
- **D14**: The block between markers is empty at end of T2 — *Constraint*: do not pre-populate with placeholder text; the ingestion tool expects to fill an empty block.

## 4. TDD Implementation Order

**Coverage target**: N/A for this task — it creates no application code. Only file existence is verified.

**Step 1 — RED: assertion test** for file existence and marker presence:
  File: `tests/unit/test_t02_artifacts.py` (renamed at end of task to `test_container_md_skeleton.py`)
  ```bash
  uv run pytest tests/unit/test_t02_artifacts.py --no-cov -q
  ```
  Expected: fails — `container/CLAUDE.md` does not exist.

**Step 2 — GREEN: create `container/CLAUDE.md`** per Section 6.

**Step 3 — RED: import test** for package scaffolding:
  Same test file, second test function asserts `importlib.import_module("build_tools.ingest_nextseek_docs")` succeeds.
  Expected: fails — package not created yet.

**Step 4 — GREEN: create `build_tools/__init__.py` and `build_tools/ingest_nextseek_docs/__init__.py`**:
  ```bash
  mkdir -p build_tools/ingest_nextseek_docs
  touch build_tools/__init__.py build_tools/ingest_nextseek_docs/__init__.py
  ```

**Step 5 — RED: repo-root pointer**:
  Third test asserts `"container/CLAUDE.md"` appears in the repo-root `CLAUDE.md`.
  Expected: fails.

**Step 6 — GREEN: edit repo-root `CLAUDE.md`** per Section 7 Edit 1.

**Step 7 — REFACTOR & rename test file** to `tests/unit/test_container_md_skeleton.py` (final name).

**Step 8 — VERIFY**:
  ```bash
  uv run pytest tests/unit/test_container_md_skeleton.py --no-cov -q
  uv run pytest --no-cov -q
  ```
  Expected: new tests pass; no regressions; autouse self-test from T1 still skips (constants.py still absent — T5's job).

## 5. Behavioral Contract (Tests)

### `tests/unit/test_container_md_skeleton.py`

```python
"""Verify container/CLAUDE.md skeleton and build_tools package scaffolding."""
from __future__ import annotations

from importlib import import_module
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTAINER_CLAUDE_MD = REPO_ROOT / "container" / "CLAUDE.md"
ROOT_CLAUDE_MD = REPO_ROOT / "CLAUDE.md"

BEGIN_MARKER = "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->"
END_MARKER = "<!-- END NEXTSEEK-DOCS (auto-generated) -->"


def test_container_claude_md_exists() -> None:
    assert CONTAINER_CLAUDE_MD.exists(), f"missing: {CONTAINER_CLAUDE_MD}"


def test_container_claude_md_has_markers_exactly_once_each() -> None:
    content = CONTAINER_CLAUDE_MD.read_text()
    assert content.count(BEGIN_MARKER) == 1
    assert content.count(END_MARKER) == 1


def test_container_claude_md_markers_are_in_correct_order() -> None:
    content = CONTAINER_CLAUDE_MD.read_text()
    begin_idx = content.index(BEGIN_MARKER)
    end_idx = content.index(END_MARKER)
    assert begin_idx < end_idx, "BEGIN marker must precede END marker"


def test_container_claude_md_block_is_empty() -> None:
    """Between the markers, only whitespace should exist. Ingestion fills it."""
    content = CONTAINER_CLAUDE_MD.read_text()
    begin_idx = content.index(BEGIN_MARKER) + len(BEGIN_MARKER)
    end_idx = content.index(END_MARKER)
    between = content[begin_idx:end_idx]
    assert between.strip() == "", (
        f"block between markers must be empty before ingestion; got: {between!r}"
    )


def test_container_claude_md_mentions_credentials_warning() -> None:
    """The skeleton must instruct the agent never to write credentials."""
    content = CONTAINER_CLAUDE_MD.read_text()
    assert "Never log, print, or write credentials" in content


def test_build_tools_package_is_importable() -> None:
    pkg = import_module("build_tools")
    assert pkg is not None


def test_ingest_nextseek_docs_package_is_importable() -> None:
    pkg = import_module("build_tools.ingest_nextseek_docs")
    assert pkg is not None


def test_repo_root_claude_md_points_at_container_claude_md() -> None:
    content = ROOT_CLAUDE_MD.read_text()
    assert "container/CLAUDE.md" in content, (
        "repo-root CLAUDE.md must mention container/CLAUDE.md as the in-container "
        "agent instruction file"
    )
```

## 6. Reference Implementation

### `container/CLAUDE.md` (new file)

```markdown
# In-Container Agent Instructions

You are the DMAC assistant running inside a Docker container for an MIT BMC lab member. Project data is mounted read-only at `/data/projects/`. Write output files to `/data/scratch/`. NExtSEEK credentials are available via `NEXTSEEK_USERNAME` and `NEXTSEEK_PASSWORD` environment variables. **Never log, print, or write credentials to any file.** Confirm destructive NExtSEEK operations (POST/PUT/DELETE) with the user conversationally before executing them.

<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->
<!-- END NEXTSEEK-DOCS (auto-generated) -->
```

### `build_tools/__init__.py` (new, empty)

```python
```

### `build_tools/ingest_nextseek_docs/__init__.py` (new, empty)

```python
```

## 7. Modified Files (exact diffs)

### Edit 1: `CLAUDE.md` (repo root)

**OLD:**
```markdown
- `dmac-assistant-sds.md` — Software Design Specification (components, data flow, mounts, env vars, milestones)
- `dmac-assistant-adrs.md` — Architecture Decision Records (the *why* behind each choice)

Read both before implementing. When a decision is unclear, the ADRs record the reasoning and the rejected alternatives — do not re-litigate them without cause.
```

**NEW:**
```markdown
- `dmac-assistant-sds.md` — Software Design Specification (components, data flow, mounts, env vars, milestones)
- `dmac-assistant-adrs.md` — Architecture Decision Records (the *why* behind each choice)

In-container agent instructions live in `container/CLAUDE.md` (baked into the image as `/app/CLAUDE.md` in a later milestone). That file's NExtSEEK block is auto-generated by `make ingest-nextseek-docs`; the rest is human-authored.

Read both design docs before implementing. When a decision is unclear, the ADRs record the reasoning and the rejected alternatives — do not re-litigate them without cause.
```

(The edit preserves the original description of the two design docs and inserts a new paragraph about `container/CLAUDE.md` between the bullet list and the existing "Read both before implementing..." sentence. The insertion point is verified against the committed file before writing.)

## 8. Verification

```bash
# New tests pass
uv run pytest tests/unit/test_container_md_skeleton.py --no-cov -q

# Autouse guard still skips cleanly (constants module still not created)
uv run pytest tests/unit/test_autouse_guard.py --no-cov -q

# Full suite
uv run pytest --no-cov -q

# Package importable from CLI
uv run python -c "import build_tools.ingest_nextseek_docs; print('ok')"

# Markers literal match
grep -Fc "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->" container/CLAUDE.md
grep -Fc "<!-- END NEXTSEEK-DOCS (auto-generated) -->" container/CLAUDE.md
# Both greps must output "1"
```

**Expected test count**: 8 new tests, all passing.

**Expected coverage**: N/A (no application code).

## 9. Implementation Notes

- The marker strings in `container/CLAUDE.md` must be **byte-identical** to what T5 puts in `constants.py`. Copy-paste from this spec's Section 6 directly; do not retype.
- The repo-root `CLAUDE.md` edit is additive. Keep the entire existing file intact except for the specific `OLD`/`NEW` block. The existing `## What This System Is`, `## Load-Bearing Invariants`, etc. must remain.
- Empty `__init__.py` files are intentional. Do not add imports at package level.

## 10. Worktree & Branch

- **Branch**: `task/02-container-claude-md`
- **Worktree**: `.claude/worktrees/task-02-container-claude-md/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 verification commands pass.

## Spec Risk Notes (Phase 4)

**Status**: vetted.

- **Verified**: Edit 1's OLD block matches the committed `CLAUDE.md` byte-for-byte (confirmed 2026-04-13).
- **Low-risk**: the `CLAUDE.md` Edit is sandwiched between stable markers ("Architecture Decision Records..." line and "Read both design docs..." line). If a future edit moves these lines, Edit 1 must be re-checked before T2 runs.
- **Mitigation**: the executing agent should Read `CLAUDE.md` first, find the anchor lines, and confirm the OLD block is present before attempting Edit. If absent, escalate via `AskUserQuestion` rather than create a new block elsewhere.
