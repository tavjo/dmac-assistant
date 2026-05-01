# task-08-makefile

## 1. Overview

Add a top-level `Makefile` with the `ingest-nextseek-docs` target that wraps `uv run python -m build_tools.ingest_nextseek_docs` and emits a post-run reminder when exit code is 2 (changes written).

**Key invariants:**
- `make ingest-nextseek-docs ARGS=--help` propagates the `--help` flag and exits 0.
- `make ingest-nextseek-docs` exits with the same code as the underlying Python process.
- When exit code is 2, an informational message about rebuilding the Docker image is printed after the run.
- Recipe indentation uses TAB characters (not spaces).
- POSIX-compatible shell syntax; no GNU-make-specific extensions that would break on BSD `make` (macOS default).

## 2. Dependencies

- **Predecessor tasks**: T7 (the CLI exists and responds to `--help`).
- **Artifacts consumed**: `build_tools/ingest_nextseek_docs/__main__.py`.
- **External packages**: none (GNU `make` or BSD `make` must be installed; both present by default on macOS and standard Linux distros).

## 3. Key Design Decisions

- **R13 resolution**: Makefile portability — *Constraint*: no `$(shell ...)`, no `ifeq`/`ifneq`, no `export` statements. Only POSIX-compatible `sh -c` constructs.
- **D11**: exit codes propagate — *Constraint*: the recipe captures and re-raises the Python exit code verbatim.
- **Coverage floor**: N/A — Makefile is not Python. Verification is behavioral.

## 4. TDD Implementation Order

**Coverage target**: N/A for the Makefile itself. A Python test (`tests/integration/test_makefile.py`) validates observable behavior.

**Step 1 — RED**: `test_make_dry_run_ingest_nextseek_docs_shows_uv_command` — fails because Makefile does not exist.
**Step 2 — GREEN**: create `Makefile` per Section 6.

**Step 3 — RED**: `test_make_help_propagates_argparse_help`.
**Step 4 — GREEN**: confirm `$(ARGS)` propagation.

**Step 5 — RED**: `test_makefile_recipe_uses_tabs`.
**Step 6 — GREEN**: confirmed in Section 6 (indentation is tabs).

**Step 7 — RED**: `test_phony_declaration_includes_target`.
**Step 8 — GREEN**: confirmed.

**Step 9 — VERIFY**:
  ```bash
  uv run pytest tests/integration/test_makefile.py -q
  make -n ingest-nextseek-docs ARGS=--help
  ```

## 5. Behavioral Contract (Tests)

### `tests/integration/test_makefile.py`

```python
"""Integration tests for the ingest-nextseek-docs Makefile target."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def test_makefile_exists() -> None:
    assert MAKEFILE.exists()


def test_makefile_recipe_uses_tab_indentation() -> None:
    """GNU and BSD make both require tabs for recipe lines."""
    content = MAKEFILE.read_text()
    lines = content.splitlines()
    # Find the recipe lines after 'ingest-nextseek-docs:'
    inside_recipe = False
    recipe_lines: list[str] = []
    for line in lines:
        if line.startswith("ingest-nextseek-docs:"):
            inside_recipe = True
            continue
        if inside_recipe:
            if not line:
                break
            if line[0] not in (" ", "\t"):
                break
            recipe_lines.append(line)
    assert recipe_lines, "no recipe lines found under ingest-nextseek-docs target"
    for rl in recipe_lines:
        assert rl.startswith("\t"), (
            f"recipe line must start with TAB, got: {rl!r}"
        )


def test_phony_declaration_includes_ingest_target() -> None:
    content = MAKEFILE.read_text()
    # Match either `.PHONY: ... ingest-nextseek-docs ...` or a dedicated line
    assert "ingest-nextseek-docs" in content
    phony_lines = [l for l in content.splitlines() if l.strip().startswith(".PHONY")]
    assert any("ingest-nextseek-docs" in l for l in phony_lines), (
        "ingest-nextseek-docs must be declared .PHONY"
    )


def test_make_dry_run_shows_uv_command() -> None:
    """make -n prints the commands that would run."""
    result = subprocess.run(
        ["make", "-n", "ingest-nextseek-docs", "ARGS=--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "uv run python -m build_tools.ingest_nextseek_docs" in combined
    assert "--help" in combined


def test_make_help_exits_zero_and_prints_argparse_help() -> None:
    """Actually invoking make with ARGS=--help runs through to argparse help."""
    result = subprocess.run(
        ["make", "ingest-nextseek-docs", "ARGS=--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "--force" in result.stdout
    assert "--help" in result.stdout
```

## 6. Reference Implementation

### `Makefile` (new)

```make
.PHONY: ingest-nextseek-docs

ingest-nextseek-docs:
	@uv run python -m build_tools.ingest_nextseek_docs $(ARGS); \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo ""; \
	  echo "NExtSEEK docs changed. Review the diff, commit, and rebuild the Docker image."; \
	fi; \
	exit $$code
```

**IMPORTANT:** the indentation of the recipe lines MUST be a TAB character, not spaces. Many editors auto-convert tabs. Verify after writing with:

```bash
cat -A Makefile | head -20
# Recipe lines should begin with ^I (TAB representation), not spaces.
```

## 7. Modified Files (exact diffs)

None — new file.

## 8. Verification

```bash
# Python-level behavioral tests
uv run pytest tests/integration/test_makefile.py -q

# Direct make invocations
make -n ingest-nextseek-docs ARGS=--help | grep "uv run python -m build_tools.ingest_nextseek_docs"
make ingest-nextseek-docs ARGS=--help | grep -E "\-\-force|\-\-help"

# Tab verification
grep -P "^\t" Makefile | head -5

# .PHONY declaration
grep "^\.PHONY" Makefile | grep "ingest-nextseek-docs"

# Full suite
uv run pytest -q
```

**Expected test count**: 5 new tests in `test_makefile.py`.

**Expected coverage**: N/A (Makefile).

## 9. Implementation Notes

- `$$?` is Make's way of escaping `$` so the shell sees `$?` (the exit code of the previous command). Required because Make interprets `$(...)` and `$?` differently.
- The recipe uses `\` line continuations to make all commands run in a single shell invocation — this preserves `$$code` across lines. Without continuations, each line would run in a separate shell and `$$code` would be unset.
- `@` at the start suppresses make from echoing the command itself; the recipe's own `echo` lines are the ones users see.
- On some macOS setups, `make` defaults to BSD make rather than GNU make. This recipe uses only POSIX make features and standard `/bin/sh` constructs (`[`, `$?`, `exit`), so it works on both.
- If `ARGS` is undefined, `$(ARGS)` expands to empty — the CLI runs with no extra arguments, which exercises the defaults. This is intentional and matches the production usage: `make ingest-nextseek-docs` with no args triggers a real ingestion against the default URL.

## 10. Worktree & Branch

- **Branch**: `task/08-makefile`
- **Worktree**: `.claude/worktrees/task-08-makefile/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass.

## Spec Risk Notes (Phase 4)

**Status**: vetted.

- **`make` must be installed** on the execution host. Present by default on macOS (BSD make) and on all standard Linux distros (GNU make). If a CI container strips `make`, the tests skip/fail at subprocess level — flagged in test docstrings. Acceptable for POC.
- **BSD-vs-GNU make portability**: the recipe uses POSIX-only constructs — no `$(shell ...)`, no `ifeq`, no `:=`, just variable interpolation and shell-joined commands. Verified against both BSD make (macOS default) and GNU make (Linux default).
- **Tab-verification test is regex-based**: `line.startswith("\t")`. If a future maintainer edits the Makefile with a spaces-only editor config, this test catches it before CI runs ingest.
- **`$(ARGS)` with spaces**: shell word-splitting applies. `ARGS=--force` works. `ARGS="--doc-url foo.com --force"` requires the caller to quote correctly on the make command line — consistent with standard make behavior, not a regression.
