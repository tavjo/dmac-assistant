# task-B09-report — `nextseek-report` deterministic dispatcher shim

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3. Predecessors: B1, B2.
> **Status**: **UNVETTED** — awaiting Phase 4.

## 1. Overview

Author the `nextseek-report` shim — deterministic dispatcher for project summaries (samples / protocols / published / RPPR) per D8. Single shim with a `--mode` switch over the four chat_nextseek reporter sub-modes; the runner's `_dispatch_report` (`_nextseek_runner.py:217`) builds a `ReporterPlan` and invokes `helpers.run_reporter_summary`.

After this task: shim + test exist; suite green; coverage ≥95% on `_nextseek_runner.py`.

**Key invariants:**
- Two REQUIRED args: `--mode <enum>` and `--project <name>`.
- `--mode` is one of: `samples`, `protocols`, `published`, `rppr` (lowercase). Shim only checks non-empty; runner's `_dispatch_report` enum-validates at `_nextseek_runner.py:218`.
- Different from B3-B8: this is a deterministic dispatcher (D8), not an LLM agent invocation. Output is structured, not prose.

## 2. Dependencies

- **Predecessors**: B1, B2.
- **Artifacts consumed**: `_nextseek_common.sh`, `_nextseek_runner.py` (`_dispatch_report`).
- **External packages**: none new.

## 3. Key Design Decisions

Inherits B3 §3 (D8, D14, D20, D29, NEW-7, build_context git-add `-f`, Wave-3 inheritance rule 1).

- **D8 (deterministic dispatchers)**: report sub-modes are an enum, not free-text. — *Constraint*: shim REQUIRES `--mode`, no fallback to "infer mode from query."
- **Plan body line 1608-1690**: B9 task definition. Note: the plan body's B9.3 verification block carries stale `--cov-fail-under=90` AND dotted-module `--cov=build_context.plugins.nextseek.bin._nextseek_runner` form (lines 1679-1680). Per Wave-3 inheritance rules (plan compact handoff lines 51-56), §4 below corrects to `--cov-fail-under=95` and FILE-PATH `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py`. This spec is the corrected authority; plan body B9.3 is superseded.
- **Plan body line 1665-1669** (test for invalid mode at runner): kept as a documentation pointer; the actual enum-rejection coverage lives in B2's `test_nextseek_runner_dispatch.py` already (the dispatch table covers `_dispatch_report` enum branches). B9 does not add a redundant runner-level test.

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `_nextseek_runner.py` (FILE-PATH form). No new Python.

All commands from repo root; anchor with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED**: create `tests/unit/test_shim_report.py` per §5.1.
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_report.py -v
```
Expected: 4 failures.

**Step 2 — GREEN**: create `build_context/plugins/nextseek/bin/nextseek-report` per §6.1; `chmod +x`.

**Step 3 — Verify GREEN**: re-run §4 Step 1 command. Expected: 4 passed.

**Step 4 — Full host suite + coverage floor (CORRECTED FORM — supersedes plan body B9.3)**:
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
**Note for executor**: plan body line 1679 reads `--cov=build_context.plugins.nextseek.bin._nextseek_runner` (DOTTED-MODULE form, fails — `bin/` has no `__init__.py`). Plan body line 1680 reads `--cov-fail-under=90`. BOTH ARE STALE and explicitly superseded by the FILE-PATH form + 95 floor above. The 2026-05-02 chat_nextseek host-import audit Amendment Log entry items 7-10 mandate this correction; this spec applies it. The plan body is a known-stale reference whose correction is part of B9 explosion.

**Step 5 — Commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git add -f build_context/plugins/nextseek/bin/nextseek-report
git add tests/unit/test_shim_report.py
git commit -m $'nextseek-plugin: nextseek-report deterministic dispatcher\n\nPlan B \xc2\xb7 T9. Single shim with --mode samples|protocols|published|rppr.\nRunner enforces enum + project non-empty.'
```

**Step 6 — Verify commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-report'
```

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_report.py`

```python
"""Plan B · T9 — nextseek-report deterministic dispatcher.

Image-only per Wave-3 inheritance rule 1. Single shim with --mode switch over
{samples, protocols, published, rppr}. Runner enforces enum + project
non-empty at _nextseek_runner.py:218-223.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-report"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-report" in r.stdout
    assert "--mode" in r.stdout
    assert "--project" in r.stdout


def test_missing_mode_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--project", "LinVo"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --mode" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_missing_project_errors_with_code_3():
    r = subprocess.run(
        [str(SHIM), "--mode", "samples"],
        capture_output=True, text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --project" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_runner_dispatched_with_correct_args(tmp_path):
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-report"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    # Preserve PATH so `exec python` in the shim resolves the same interpreter
    # as the test runner. macOS 12+ has no /usr/bin/python — a stripped PATH
    # would break this test before the fake runner runs.
    import os
    env = {**os.environ, "API_USER": "x", "API_PASS": "y"}
    r = subprocess.run(
        [str(fake_shim), "--mode", "samples", "--project", "LinVo"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "report"
    assert "--mode" in argv
    assert "samples" in argv
    assert "--project" in argv
    assert "LinVo" in argv
```

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-report`

```bash
#!/bin/sh
# nextseek-report — deterministic project-summary dispatcher (D8).
# --mode samples|protocols|published|rppr (per chat_nextseek reporter sub-modes)
# --project <NAME>
# Runner enforces enum at _nextseek_runner.py:218.
# Plan B · T9.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

MODE=""
PROJECT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --mode=*) MODE="${1#--mode=}"; shift ;;
    --project) PROJECT="$2"; shift 2 ;;
    --project=*) PROJECT="${1#--project=}"; shift ;;
    --help)
      echo "Usage: nextseek-report --mode <samples|protocols|published|rppr> --project <NAME>"
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$MODE" ] || nextseek_die 3 "missing --mode"
[ -n "$PROJECT" ] || nextseek_die 3 "missing --project"

exec python "$SCRIPT_DIR/_nextseek_runner.py" \
  --agent report --mode "$MODE" --project "$PROJECT"
```

**Mode**: `0755`.

## 7. Modified Files (exact diffs)

None.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

uv run pytest tests/unit/test_shim_report.py -v
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
# CORRECTED FORM — supersedes plan body B9.3 lines 1679-1680.

python -c "import py_compile; py_compile.compile('tests/unit/test_shim_report.py', doraise=True)"
test -x build_context/plugins/nextseek/bin/nextseek-report && echo "executable OK"
```

**Expected test count**: 4 new.
**Expected coverage**: ≥95% on `_nextseek_runner.py`.

## 9. Implementation Notes

### 9.1 Plan-line citations
- Plan body line 1608-1690: B9 task definition.
- Plan body line 1679-1680: STALE — dotted-module `--cov=` + `--cov-fail-under=90`. SUPERSEDED here.
- `_nextseek_runner.py:217-235`: `_dispatch_report` (enum + project + ReporterPlan + run_reporter_summary).
- Plan body lines 51-56: Wave-3 inheritance rules.
- 2026-05-02 chat_nextseek host-import audit Amendment Log items 7-10: forward-propagation rule + correction authorization.

### 9.2 Why deterministic dispatcher, not LLM

D8: this is a structured project summary, not a free-text query. The four reporter sub-modes correspond to fixed chat_nextseek workflows:
- `samples` → tabular sample listing.
- `protocols` → protocol-doc roll-up.
- `published` → published-paper roll-up.
- `rppr` → RPPR-formatted summary (research progress report).

Routing by `--mode` instead of by LLM-inferred intent removes a class of misclassification errors. The shim is therefore an exact mapping; the runner constructs the `ReporterPlan` deterministically.

### 9.3 Why `rppr` is lowercase here but `RPPR` inside the runner

Plan body line 1633 specifies the `--mode` enum as `samples|protocols|published|rppr` (all lowercase). The runner translates `rppr` → `RPPR` for `summary_mode` (`_nextseek_runner.py:230`: `summary_mode = "RPPR" if args.mode == "rppr" else args.mode`). This keeps the user-facing CLI consistent (all-lowercase enum) while matching chat_nextseek's expected `summary_mode` value. Do NOT make the shim accept `RPPR` directly — the runner's translation is the contract.

### 9.4 Plan body B9.3 corrections (CRITICAL — Wave-3 inheritance rules in action)

Plan body line 1679: `--cov=build_context.plugins.nextseek.bin._nextseek_runner` (DOTTED-MODULE) — would fail under pytest-cov because `build_context/plugins/nextseek/bin/` has no `__init__.py`. Corrected here to FILE-PATH form `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py`.

Plan body line 1680: `--cov-fail-under=90`. Corrected to `95` per the 2026-05-01 Coverage Bump amendment that already raised B2's floor. Both corrections are mandatory by the Wave-3 inheritance rules (plan compact handoff lines 51-56).

When B9 is implemented, the executor follows §4 above (CORRECTED), NOT plan body B9.3 (STALE). Phase 4 reviewers must confirm this spec carries the corrected forms, not the stale ones.

### 9.5 Coverage status — no exception

Default 95% on `_nextseek_runner.py`, held by B2.

### 9.6 Self-review checklist

- [x] Tests fail before; pass after; no regressions; coverage ≥95%.
- [x] `importorskip` at top.
- [x] FILE-PATH `--cov=` form (NOT dotted-module).
- [x] `--cov-fail-under=95` REMOVED from host invocations per Amendment 1 (2026-05-02 evening) — host informational only. Image-side binding gate enforces 95 (NOT 90 — per 2026-05-01 Coverage Bump amendment); enforcement in Wave 5 B17.
- [x] `git add -f` for `build_context/...`.
- [x] BOTH `--mode` and `--project` required at the shim.
- [x] No enum validation in the shim (deliberate — runner is the authority).
- [x] No `make install-chat-nextseek`; no empty subdirs.

## 10. Worktree & Branch

- **Branch**: `task/B09-report`
- **Worktree**: `.claude/worktrees/task-B09-report/`
- **Init**:
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B09-report
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 all green on host. FILE-PATH `--cov=` form preserved for diagnostic; **host coverage is informational only** per Amendment 1 (2026-05-02 evening) — expected 0% structurally. **Binding ≥95% coverage on `_nextseek_runner.py` is enforced on image in Wave 5 B17 image-e2e.**
  2. Shim mode `0755` and tracked.
  3. Commit subject starts with `nextseek-plugin: nextseek-report`.
  4. Post-merge `feature-dev:code-reviewer` APPROVE.


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
