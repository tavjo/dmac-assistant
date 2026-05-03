# task-B08-generate-submission — `nextseek-generate-submission` shim

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3. Predecessors: B1, B2.
> **Status**: **UNVETTED** — awaiting Phase 4.

## 1. Overview

Author the `nextseek-generate-submission` shim — generates submission packages (GEO / SRA / nf-core RNAseq / nf-core scRNAseq / PRIDE) for a comma-separated list of UIDs via the runner's `_dispatch_generate_submission` (`_nextseek_runner.py:238`).

After this task: shim + test exist; suite green; coverage ≥95%.

**Key invariants**:
- Two REQUIRED args: `--type <enum>` and `--uids <csv>`.
- `--type` is one of: `GEO`, `SRA`, `NFCORE_RNASEQ`, `NFCORE_SCRNASEQ`, `PRIDE`. Shim does NOT enumerate-validate (the runner does at `_nextseek_runner.py:239-240`); shim only checks non-empty.
- `--uids` is a CSV; shim does not parse — runner splits on `,`.

## 2. Dependencies

- **Predecessors**: B1, B2.
- **Artifacts consumed**: `_nextseek_common.sh`, `_nextseek_runner.py` (`_dispatch_generate_submission`).
- **External packages**: none new.

## 3. Key Design Decisions

Inherits B3 §3 (D8, D14, D20, D29, NEW-7, build_context git-add `-f`, Wave-3 inheritance rule 1).

- **Plan body line 1587-1588**: `--type` (required) + `--uids` (required); exec: `--agent generate-submission --type "$TYPE" --uids "$UIDS"`. — *Constraint*: shim only checks non-empty for both. Runner does enum + CSV-parse validation.
- **No shim-side enum validation**: keeps the shim minimal; the runner is the authority. If a future amendment wants shim-side validation for faster failure, it must be raised via `/ultraplan amend` and propagated to ALL Wave-3 shims (consistency).

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `_nextseek_runner.py` (FILE-PATH form). No new Python.

All commands from repo root; anchor with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED**: create `tests/unit/test_shim_generate_submission.py` per §5.1. Pre-clean any stale shim:
```bash
cd "$(git rev-parse --show-toplevel)"
rm -f build_context/plugins/nextseek/bin/nextseek-generate-submission
uv run pytest tests/unit/test_shim_generate_submission.py -v
```
Expected: 4 red (mix of FAIL and ERROR is acceptable — `subprocess.run` raises `FileNotFoundError` when the shim is absent, which pytest reports as ERROR; tests reading `SHIM.read_text()` likewise error).

**Step 2 — GREEN**: create `build_context/plugins/nextseek/bin/nextseek-generate-submission` per §6.1; `chmod +x`.

**Step 3 — Verify GREEN**: re-run §4 Step 1 command. Expected: 4 passed.

**Step 4 — Full host suite + coverage floor**:
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest \
  tests/unit/test_nextseek_runner.py \
  tests/unit/test_nextseek_runner_dispatch.py \
  tests/unit/test_shim_*.py \
  --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
  -v
# AMENDMENT 1 (2026-05-02 evening): `--cov-fail-under=95` REMOVED from host invocations.
# Reason: pytest.importorskip("chat_nextseek") (Wave-3 inheritance rule 1) causes module-level
# skip on host (Python 3.12; chat_nextseek requires >=3.14, image-only). _nextseek_runner.py is
# never imported on host => host coverage = 0% structurally. Host `--cov=` report is informational
# only. Binding >=95% gate is enforced on image in Wave 5 B17 image-e2e.
```

**Step 5 — Commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git add -f build_context/plugins/nextseek/bin/nextseek-generate-submission
git add tests/unit/test_shim_generate_submission.py
git commit -m $'nextseek-plugin: nextseek-generate-submission shim\n\nPlan B \xc2\xb7 T8. --type GEO|SRA|NFCORE_RNASEQ|NFCORE_SCRNASEQ|PRIDE\nplus --uids CSV. Runner enforces enum + CSV parsing.'
```

**Step 6 — Verify commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-generate-submission shim$'
```

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_generate_submission.py`

```python
"""Plan B · T8 — nextseek-generate-submission shim. Image-only per Wave-3 rule 1."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-generate-submission"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-generate-submission" in r.stdout
    assert "--type" in r.stdout
    assert "--uids" in r.stdout


def test_missing_type_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--uids", "UID-1,UID-2"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --type" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_missing_uids_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--type", "GEO"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --uids" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_runner_dispatched_with_correct_args(tmp_path):
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-generate-submission"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    r = subprocess.run(
        [str(fake_shim), "--type", "GEO", "--uids", "UID-1,UID-2,UID-3"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "generate-submission"
    assert "--type" in argv
    assert "GEO" in argv
    assert "--uids" in argv
    assert "UID-1,UID-2,UID-3" in argv
```

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-generate-submission`

```bash
#!/bin/sh
# nextseek-generate-submission — emit a submission package for a UID set.
# --type GEO|SRA|NFCORE_RNASEQ|NFCORE_SCRNASEQ|PRIDE
# --uids comma-separated UIDs
# Runner enforces enum + CSV parsing.
# Plan B · T8.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

TYPE=""
UIDS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --type) TYPE="$2"; shift 2 ;;
    --type=*) TYPE="${1#--type=}"; shift ;;
    --uids) UIDS="$2"; shift 2 ;;
    --uids=*) UIDS="${1#--uids=}"; shift ;;
    --help)
      echo "Usage: nextseek-generate-submission --type <GEO|SRA|NFCORE_RNASEQ|NFCORE_SCRNASEQ|PRIDE> --uids <UID1,UID2,...>"
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$TYPE" ] || nextseek_die 3 "missing --type"
[ -n "$UIDS" ] || nextseek_die 3 "missing --uids"

exec python "$SCRIPT_DIR/_nextseek_runner.py" \
  --agent generate-submission --type "$TYPE" --uids "$UIDS"
```

**Mode**: `0755`.

## 7. Modified Files (exact diffs)

None.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

uv run pytest tests/unit/test_shim_generate_submission.py -v
# Expected: 4 passed (image) or 4 skipped (host).

uv run pytest \
  tests/unit/test_nextseek_runner.py \
  tests/unit/test_nextseek_runner_dispatch.py \
  tests/unit/test_shim_*.py \
  --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
  -v
# AMENDMENT 1 (2026-05-02 evening): `--cov-fail-under=95` REMOVED from host invocations.
# Reason: pytest.importorskip("chat_nextseek") (Wave-3 inheritance rule 1) causes module-level
# skip on host (Python 3.12; chat_nextseek requires >=3.14, image-only). _nextseek_runner.py is
# never imported on host => host coverage = 0% structurally. Host `--cov=` report is informational
# only. Binding >=95% gate is enforced on image in Wave 5 B17 image-e2e.

python -c "import py_compile; py_compile.compile('tests/unit/test_shim_generate_submission.py', doraise=True)"
test -x build_context/plugins/nextseek/bin/nextseek-generate-submission && echo "executable OK"
```

**Expected test count**: 4 new.
**Expected coverage**: ≥95% on `_nextseek_runner.py`.

## 9. Implementation Notes

### 9.1 Plan-line citations
- Plan body line 1587-1588: B8 task definition.
- `_nextseek_runner.py:238-255`: `_dispatch_generate_submission` (enum + CSV parsing).
- Plan body lines 51-56: Wave-3 inheritance rules.

### 9.2 Why the shim does not enum-validate `--type`

The runner's `_dispatch_generate_submission` raises `_err("VALIDATION", ...)` (`_nextseek_runner.py:239-240`) for non-enum values, with exit code 3. Adding the same validation in the shim would be:
- Code duplication (the enum list would have to be kept in sync between the shim and the runner).
- A potential drift point if a future chat_nextseek release adds a new submission type.
- A coverage problem: the shim's enum validation would not be reachable through any pytest-cov instrumentation (bash).

The runner is the single source of truth for enum membership. The shim's `[ -n "$TYPE" ]` non-empty check is enough.

### 9.3 Why the shim does not pre-parse `--uids`

Same rationale: the runner does `args.uids.split(",")` on `_nextseek_runner.py:249`. Pre-parsing in the shim would force CSV semantics into bash (subtle: leading/trailing whitespace, escaped commas) — better to let Python handle it once.

### 9.4 Coverage status — no exception

Default 95% on `_nextseek_runner.py`, held by B2.

### 9.5 Self-review checklist

- [x] Tests fail before; pass after; no regressions; coverage ≥95%.
- [x] `importorskip` at top; FILE-PATH `--cov=` preserved; `git add -f`. (`--cov-fail-under=95` REMOVED per Amendment 1 (2026-05-02 evening) — host informational only, binding gate on image in Wave 5 B17.)
- [x] BOTH `--type` and `--uids` required at the shim.
- [x] No enum validation in the shim (deliberate — see §9.2).
- [x] No `make install-chat-nextseek`; no empty subdirs.

## 10. Worktree & Branch

- **Branch**: `task/B08-generate-submission`
- **Worktree**: `.claude/worktrees/task-B08-generate-submission/`
- **Init**:
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B08-generate-submission
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 all green.
  2. Shim mode `0755` and tracked.
  3. Commit subject `^nextseek-plugin: nextseek-generate-submission shim$`.
  4. Post-merge `feature-dev:code-reviewer` APPROVE.


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
