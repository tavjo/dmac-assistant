# task-B03-entity-extract — `nextseek-entity-extract` shim (canonical Wave-3 template)

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3 — APPROVED 2026-05-01) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3 (LLM/dispatch shims). Predecessors: B1 (scaffold), B2 (shared runner). No predecessor inside Wave 3.
> **Status**: **UNVETTED** — awaiting Phase 4 combined adversarial+checklist review.

## 1. Overview

Author the canonical user-facing shim that the SKILL.md preamble (B10) invokes for every `/nextseek` query. After this task:

- `build_context/plugins/nextseek/bin/nextseek-entity-extract` exists, executable, source-tracked (force-added).
- A pytest unit suite at `tests/unit/test_shim_entity_extract.py` exercises help / missing-arg / runner-dispatch behavior via subprocess.
- All B2 tests still green on image; runner coverage ≥95% on `_nextseek_runner.py` (FILE-PATH form) **on image only** per Amendment 1 (2026-05-02 evening). On host, B2 + B3 modules SKIP at module level via `pytest.importorskip("chat_nextseek")` → host coverage = 0% structurally; the binding ≥95% gate is enforced on image in Wave 5 B17 image-e2e.

This is the **template task** for Wave 3 — B4, B5, B7, B8 mirror its structure with only the `--agent` value and arg parsing changing. B6a/B6b/B9 carry additional security or dispatcher concerns and have their own specs but reuse this task's shim/test scaffolding.

**Key invariants:**
- Shim is `/bin/sh` (POSIX), not bash. The runner is invoked via `exec python "$SCRIPT_DIR/_nextseek_runner.py" ...`.
- The shim sources `_nextseek_common.sh` so it inherits the `nextseek_die` helper and the cred-translation defaults (`API_USER`, `API_PASS`, `NEXTSEEK_BASE_URL`, etc.).
- `--help` exits 0 BEFORE reaching `exec`. Missing `--query` exits 3 via `nextseek_die`.
- The shim accepts both `--query <text>` and `--query=<text>` forms.
- No new Python files; no change to the runner. The runner already dispatches `--agent entity` via `_dispatch_entity` (B2).
- Host-side test file gated by `pytest.importorskip("chat_nextseek")` per Wave-3 inheritance rule 1, even though the tests stub the runner — the rule is unconditional and matches the plan body's `## Host vs Image Python Environment` Rule 1.

## 2. Dependencies

- **Predecessor tasks**: B1 (scaffold — `plugin.json` + repo path), B2 (`_nextseek_common.sh` + `_nextseek_runner.py` with `--agent entity` dispatch). Both merged to `ultraplan/nextseek-plugin-2026-04-27` at HEAD `7a31286`.
- **Plan A prerequisites** (already on `main` at `33e21f6`, inherited): Python 3.14 image-only, `chat_nextseek` image-only.
- **Artifacts consumed**:
  - `build_context/plugins/nextseek/bin/_nextseek_common.sh` (sourced by the shim)
  - `build_context/plugins/nextseek/bin/_nextseek_runner.py` (executed via `exec python`)
- **External packages**: none new. `pytest`, `pytest-cov` already present.
- **Tooling required**: `git`, `chmod`, `uv`, `pytest`. No Docker, no Make.

## 3. Key Design Decisions

- **D8 (deterministic dispatchers)**: nextseek shims are flat `--agent X` invocations — no per-shim Python wrapping. — *Constraint*: the shim is bash + `exec python runner.py`; never `uv run --with`, never inline Python.
- **D14 (preamble)**: SKILL.md authored in B10 will mandate `nextseek-entity-extract --query "<full question>"` as the always-first step. — *Constraint*: this shim's stdout/stderr contract is load-bearing for every other shim; missing-arg/help behavior must be stable.
- **D20 (env translation)**: `_nextseek_common.sh` translates `NEXTSEEK_USERNAME`/`NEXTSEEK_PASSWORD` → `API_USER`/`API_PASS`. — *Constraint*: shim MUST source the common helper before exec'ing the runner; the runner's `_load_config` reads the translated names.
- **D29 (no `uv run --with` in shims)**: Plan B uses plain `python` and `/bin/sh` for shims. — *Constraint*: shebang is `#!/bin/sh`; runner invocation is `exec python ...`, not `exec uv run ...`.
- **NEW-7 (coverage floor)**: every Wave-3 shim test invocation adds `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py --cov-fail-under=95` (FILE-PATH form, 95% — per 2026-05-01 Coverage Bump amendment + 2026-05-02 chat_nextseek host-import audit item 7). — *Constraint*: NOT the dotted-module form `build_context.plugins.nextseek.bin._nextseek_runner` (fails because `bin/` lacks `__init__.py`). Plan body B3.3 line ~1514 carries the stale dotted-module form and `--cov-fail-under=90` — both are corrected in §4 below.
- **build_context git-add `-f`** (2026-05-01 Amendment): every commit step targeting `build_context/plugins/nextseek/...` paths uses `git add -f`. Plain `git add` silently no-ops on the gitignored tree.
- **Wave-3 inheritance rule 1 (2026-05-02 chat_nextseek host-import audit item 7)**: every host-side test file that imports `chat_nextseek` directly OR transitively MUST start with `pytest.importorskip("chat_nextseek")`. UNCONDITIONAL.

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `build_context/plugins/nextseek/bin/_nextseek_runner.py` (FILE-PATH form). No new Python code is added by this task; the floor is held entirely by the B2 test suite. New shim tests do not exercise runner branches but must not cause a regression. **No coverage exception declared.**

All commands run from the repo root. Anchor explicitly with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED: write the failing test file**

Create `tests/unit/test_shim_entity_extract.py` with the exact content in §5.1 below. Pre-clean any stale shim from a prior aborted attempt (the path is gitignored so a stale file can silently defeat RED):

```bash
cd "$(git rev-parse --show-toplevel)"
rm -f build_context/plugins/nextseek/bin/nextseek-entity-extract
uv run pytest tests/unit/test_shim_entity_extract.py -v
```

Expected: 3 red (some FAIL, some ERROR is acceptable — when the shim is absent, `subprocess.run([str(SHIM), ...])` raises `FileNotFoundError` which pytest reports as ERROR; tests that don't reach `subprocess.run` may report FAIL). The signal is "not all green," not a specific FAIL count.

**Step 2 — GREEN: write the shim**

Create `build_context/plugins/nextseek/bin/nextseek-entity-extract` with the exact content in §6.1 below. Then mark it executable:

```bash
cd "$(git rev-parse --show-toplevel)"
chmod +x build_context/plugins/nextseek/bin/nextseek-entity-extract
```

**Step 3 — Verify GREEN**

```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_entity_extract.py -v
```

Expected: 3 passed.

**Step 4 — Verify no regression on the B2 suite + apply runner coverage floor (FILE-PATH form, 95%)**

```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest \
  tests/unit/test_nextseek_runner.py \
  tests/unit/test_nextseek_runner_dispatch.py \
  tests/unit/test_shim_entity_extract.py \
  --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
  -v
# AMENDMENT 1 (2026-05-02 evening): `--cov-fail-under=95` REMOVED from host invocations.
# Reason: pytest.importorskip("chat_nextseek") (Wave-3 inheritance rule 1) causes module-level
# skip on host (Python 3.12; chat_nextseek requires >=3.14, image-only). _nextseek_runner.py is
# never imported on host => host coverage = 0% structurally. Host `--cov=` report is informational
# only. Binding >=95% gate is enforced on image in Wave 5 B17 image-e2e.
```

Expected: 17 (B2) + 3 (B3) = 20 tests pass; coverage on `_nextseek_runner.py` ≥ 95% (B2 reported 100%; this task adds zero new runner code, so unchanged).

**Step 5 — Commit**

Use ANSI-C `$'...'` quoting for the multi-line message body to avoid the leading-whitespace HEREDOC pitfall flagged in B1 Phase 4 review HIGH-1.

```bash
cd "$(git rev-parse --show-toplevel)"
git add -f build_context/plugins/nextseek/bin/nextseek-entity-extract
git add tests/unit/test_shim_entity_extract.py
git commit -m $'nextseek-plugin: nextseek-entity-extract shim\n\nPlan B \xc2\xb7 T3. Template for Wave-3 LLM shims (B4, B5, B7, B8).\nCoverage floor held on _nextseek_runner.py (95%, FILE-PATH form).'
```

Note: `\xc2\xb7` is UTF-8 `·` (middle dot) used to match the Plan B convention from B1/B2 commits ("Plan B · T1.", "Plan B · T2."). If the executor's shell does not interpret `\x` escapes inside `$'...'`, fall back to a plain ASCII period after `Plan B`.

**Step 6 — Verify commit landed on the task branch**

```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-entity-extract shim$'
git diff --stat HEAD~1 HEAD | grep -q 'nextseek-entity-extract'
```

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_entity_extract.py`

```python
"""Plan B · T3 — nextseek-entity-extract shim.

Image-only by Plan A T7's PATH_B decision: chat_nextseek requires Python ≥3.14
and is never installed on host. The runner is invoked transitively from these
tests' subprocess calls only when the test stubs the runner; the real shim's
--help and missing-arg paths exit before reaching the runner. Per Wave-3
inheritance rule 1 (2026-05-02 chat_nextseek host-import audit item 7),
gate the whole file with importorskip — the rule is unconditional.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "nextseek-entity-extract"
COMMON = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    """--help short-circuits before exec'ing the runner. Exit 0, stdout 'Usage'."""
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-entity-extract" in r.stdout


def test_missing_query_errors_with_code_3():
    """Missing --query → nextseek_die 3 'missing --query' on stderr."""
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --query" in r.stderr
    assert "nextseek-error" in r.stderr  # nextseek_die format


def test_runner_dispatched_with_correct_args(tmp_path):
    """Stub the runner — confirm shim invokes it with --agent entity --query <text>.

    The real shim execs `python "$SCRIPT_DIR/_nextseek_runner.py" --agent entity
    --query "$QUERY"`. We copy the shim and the common helper into a tmp dir, and
    plant a fake _nextseek_runner.py that echoes argv as JSON. This isolates the
    test from chat_nextseek and from the runner's real dispatch table.
    """
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)

    fake_common = tmp_path / "_nextseek_common.sh"
    fake_common.write_text(COMMON.read_text())

    fake_shim = tmp_path / "nextseek-entity-extract"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    # Preserve PATH so `exec python` in the shim resolves the same interpreter
    # as the test runner. macOS 12+ has no /usr/bin/python (only /usr/bin/python3),
    # so a stripped PATH like {"PATH": "/usr/bin:/bin"} would fail before the fake
    # runner runs. See §9.3 for the full rationale.
    import os
    env = {**os.environ, "API_USER": "x", "API_PASS": "y"}
    r = subprocess.run(
        [str(fake_shim), "--query", "find LinVo samples"],
        capture_output=True,
        text=True,
        env=env,
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert payload["called_with"][0] == "--agent"
    assert payload["called_with"][1] == "entity"
    assert payload["called_with"][2] == "--query"
    assert payload["called_with"][3] == "find LinVo samples"
```

**Notes for the executor:**
- `REPO_ROOT = Path(__file__).resolve().parents[2]` walks `tests/unit/test_shim_entity_extract.py` → `tests/unit` → `tests` → repo root. Verified against B2's `test_nextseek_runner.py` parents-walk pattern.
- The fake runner's shebang relies on a `python` on PATH inside `tmp_path`'s subprocess env. The shim's `exec python "$SCRIPT_DIR/_nextseek_runner.py"` invokes `python` via PATH lookup; we set `PATH=/usr/bin:/bin` and the test environment must have a `python` at one of those locations. Image and host both satisfy this. If the executor environment lacks `python` on the minimal PATH, fall back to `env={"PATH": os.environ["PATH"], ...}` — but the minimal-PATH form is preferred to keep the test deterministic.
- `pytest.importorskip("chat_nextseek")` at module top means the entire file is skipped on host. That is the intended behavior — the host pytest run reports `s s s` for these three tests, the image pytest run reports `. . .`. Phase 4 review must confirm this is acceptable; B2's Wave-1 fixup applied the identical pattern (3765ed3) and was approved.

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-entity-extract`

```bash
#!/bin/sh
# nextseek-entity-extract — extract sampletypes/assays/keywords/projects.
# Always invoked first by the SKILL.md preamble (D14).
# Plan B · T3.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

QUERY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    --query=*) QUERY="${1#--query=}"; shift ;;
    --help)
      echo "Usage: nextseek-entity-extract --query \"<text>\""
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$QUERY" ] || nextseek_die 3 "missing --query"

exec python "$SCRIPT_DIR/_nextseek_runner.py" --agent entity --query "$QUERY"
```

**Mode**: `0755` (executable). Set via `chmod +x` in §4 Step 2.

## 7. Modified Files (exact diffs)

None. This task creates two new files only; no existing file is modified.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

# 1. New tests pass
uv run pytest tests/unit/test_shim_entity_extract.py -v
# Expected: 3 passed (or 3 skipped on host without chat_nextseek)

# 2. Full B2+B3 host-runnable suite, no regression, coverage floor enforced
uv run pytest \
  tests/unit/test_nextseek_runner.py \
  tests/unit/test_nextseek_runner_dispatch.py \
  tests/unit/test_shim_entity_extract.py \
  --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
  -v
# AMENDMENT 1 (2026-05-02 evening): `--cov-fail-under=95` REMOVED from host invocations.
# Reason: pytest.importorskip("chat_nextseek") (Wave-3 inheritance rule 1) causes module-level
# skip on host (Python 3.12; chat_nextseek requires >=3.14, image-only). _nextseek_runner.py is
# never imported on host => host coverage = 0% structurally. Host `--cov=` report is informational
# only. Binding >=95% gate is enforced on image in Wave 5 B17 image-e2e.
# Expected on image: 20 passed, coverage ≥95% on _nextseek_runner.py (binding gate; enforced in Wave 5 B17).
# Expected on host: ALL of test_nextseek_runner.py, test_nextseek_runner_dispatch.py, and
#                   test_shim_entity_extract.py SKIP at module level via pytest.importorskip
#                   ("chat_nextseek" not importable on Python 3.12 — B2's fixup commit 3765ed3 made
#                   the importorskip unconditional). _nextseek_runner.py is therefore never imported
#                   on host → host coverage = 0% structurally per Amendment 1 (2026-05-02 evening).
#                   The host pytest exits 0 (no --cov-fail-under flag); host coverage report is
#                   informational only.

# 3. Linter — no new lint targets for shell; pyflakes via pytest collection covers Python
python -c "import py_compile; py_compile.compile('tests/unit/test_shim_entity_extract.py', doraise=True)"
# Expected: silent success.

# 4. Shim is executable
test -x build_context/plugins/nextseek/bin/nextseek-entity-extract && echo "executable OK"
# Expected: "executable OK"
```

**Expected test count**: 3 new (`test_shim_entity_extract.py`).
**Expected coverage**: ≥95% on `_nextseek_runner.py` (B2 reported 100%; this task adds 0 runner code).

If projected coverage is below 95%, this spec is incomplete — but B3 cannot reduce coverage because it adds no Python code. Investigate any coverage drop as a pytest config or import-graph issue, not as missing tests.

## 9. Implementation Notes

### 9.1 Plan-line citations

- Plan body line 1420-1531: B3 task definition. The shim block at lines 1428-1448 and the test block at lines 1454-1505 are the source for §5.1 and §6.1 above.
- Plan body line 1514: stale `--cov=build_context.plugins.nextseek.bin._nextseek_runner` (DOTTED-MODULE form, fails — `bin/` has no `__init__.py`). §4 Step 4 above corrects to FILE-PATH form.
- Plan body line 1515: stale `--cov-fail-under=90`. §4 Step 4 above corrects to `95` per 2026-05-01 Coverage Bump amendment.
- Plan body line 1523: plain `git add` for `build_context/...` path. §4 Step 5 above corrects to `git add -f` per 2026-05-01 build_context amendment.
- Plan body lines 51-56 (Wave-3 inheritance rules): full enumeration of the four corrections applied above.

### 9.2 Why this shim is sh, not bash

POSIX `/bin/sh` is guaranteed on every Linux base image (and on Alpine, where the Plan B runtime ultimately lives via the dmac-assistant image). bash is not. The shim uses only POSIX features: `case`/`esac`, `[ ... ]` test, `$#`, `$@`, parameter expansion `${1#--query=}`. No arrays, no `[[`, no `local`, no PIPESTATUS — all bash-isms are absent. The B2 `_nextseek_common.sh` follows the same convention (verified 2026-05-02).

### 9.3 Gotchas

- **Do not call `exec` until after both arg-parse exit paths**. The current order — case loop → `[ -n "$QUERY" ] || nextseek_die 3` → `exec python ...` — is load-bearing for the `test_missing_query_errors_with_code_3` test. Moving `exec` earlier (e.g. into the case statement) would short-circuit the `--query` presence check.
- **Quoting matters**. `exec python "$SCRIPT_DIR/_nextseek_runner.py" --agent entity --query "$QUERY"` — `$QUERY` MUST be double-quoted so a query like `"find samples; rm -rf /"` is passed as a single argv element, not split on whitespace and re-interpreted. This was the entire reason `nextseek_die 3 "unknown arg: $1"` triggers on stray positionals.
- **Test 3's PATH-restriction**. `env={"PATH": "/usr/bin:/bin"}` is intentional — it isolates the subprocess from any user-side `PATH` mods (e.g. pyenv shims) that could change which `python` runs. If the test fails with `python: command not found`, the executor's host environment lacks `/usr/bin/python` or `/bin/python`; switch to `env={"PATH": os.environ["PATH"], ...}` and document why.
- **`importorskip` placement matters**. It must be at module top, BEFORE any `from chat_nextseek import ...`. We don't import chat_nextseek directly here, but the inheritance rule is unconditional. Phase 4 reviewers must confirm placement matches B2's `test_nextseek_runner.py` (line 1, before `from __future__`).
- **`build_context/` is gitignored** (`.gitignore` line 13). `git add` without `-f` silently no-ops on the new shim; the subsequent `git commit` then either fails ("nothing to commit") or commits empty. Use `git add -f` per §4 Step 5. The test file under `tests/unit/` is NOT under `build_context/` — plain `git add` is correct for it.

### 9.4 Coverage status — no exception

Default 95% target on `_nextseek_runner.py` (FILE-PATH form). B2's suite already reports 100% on that file; B3 adds zero runner code. No exception declared. If Phase 4 review surfaces a coverage drop, treat it as a defect — do NOT amend the target.

### 9.5 Self-review checklist (per Phase 3 spec)

- [x] Tests fail before implementation? Yes — §4 Step 1 RED.
- [x] Tests pass after? Yes — §4 Step 3.
- [x] No regressions? Yes — §4 Step 4 runs full B2+B3 host-runnable suite.
- [x] Coverage meets declared target? Yes — held at ≥95% by B2.
- [x] No coverage exception. N/A.
- [x] `pytest.importorskip("chat_nextseek")` at top of host test file? Yes — §5.1 line 11.
- [x] FILE-PATH `--cov=` form? Yes — §4 Step 4 + §8.
- [x] `--cov-fail-under=95` REMOVED per Amendment 1 (2026-05-02 evening) — host invocations are informational only (host coverage = 0% structurally); binding ≥95% gate enforced on image in Wave 5 B17.
- [x] `git add -f` for `build_context/...` path? Yes — §4 Step 5.
- [x] No `make install-chat-nextseek` reference? Confirmed absent.
- [x] No empty subdirs created? Confirmed — only one shim file under existing `bin/`.

## 10. Worktree & Branch

- **Branch**: `task/B03-entity-extract`
- **Worktree**: `.claude/worktrees/task-B03-entity-extract/`
- **Init command** (executor runs from main worktree):
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B03-entity-extract
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 Verification block all green on host: 3 new tests pass (or skip via importorskip), full B2+B3 suite has no regression. Coverage on `_nextseek_runner.py` (FILE-PATH form) is **informational only on host** per Amendment 1 (2026-05-02 evening) — expected 0% structurally because `pytest.importorskip("chat_nextseek")` skips B2/B3 modules at module-level on host. **Binding ≥95% coverage gate is enforced on image in Wave 5 B17 image-e2e.**
  2. Shim is mode `0755` and tracked (`git ls-files build_context/plugins/nextseek/bin/nextseek-entity-extract` returns the path).
  3. Commit subject matches `^nextseek-plugin: nextseek-entity-extract shim$`.
  4. Post-merge `feature-dev:code-reviewer` adversarial pass returns APPROVE (per `feedback_post_merge_review.md`).


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
