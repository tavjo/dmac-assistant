# task-B04-parse — `nextseek-parse` shim

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3. Predecessors: B1, B2. **Independent of B3** at the code level (separate shim file, separate test file). Wave-3 tasks may run in parallel.
> **Status**: **UNVETTED** — awaiting Phase 4 combined adversarial+checklist review.

## 1. Overview

Author the `nextseek-parse` shim — a `--query`-driven LLM dispatcher that returns the parser_agent's plan (mode/target_endpoint/etc.) for an input query. Mirror of B3 with `--agent parse` instead of `--agent entity`.

After this task:
- `build_context/plugins/nextseek/bin/nextseek-parse` exists, executable, source-tracked.
- `tests/unit/test_shim_parse.py` exercises help / missing-arg / runner-dispatch.
- B2 + B3 + B4 host-runnable suite green; runner coverage ≥95% on `_nextseek_runner.py`.

**Key invariants:** identical to B3 §1 (POSIX sh, sourcing `_nextseek_common.sh`, `exec python` to runner, `pytest.importorskip("chat_nextseek")` at test-file top). Only the `--agent` value and the test's expected argv differ.

## 2. Dependencies

- **Predecessors**: B1, B2. (B3 not strictly required — B4 reuses no B3 artifact, only the same patterns.)
- **Artifacts consumed**: `_nextseek_common.sh`, `_nextseek_runner.py` (`_dispatch_parse` already implemented in B2).
- **External packages**: none new.
- **Tooling**: `git`, `chmod`, `uv`, `pytest`.

## 3. Key Design Decisions

Inherits B3 §3 verbatim: D8, D14, D20, D29, NEW-7, build_context git-add `-f`, Wave-3 inheritance rule 1.

Additional B4-specific decision:
- **Plan body line 1545**: `--query <text>`. Validates non-empty. Exec: `--agent parse --query "$QUERY"`. — *Constraint*: B4's CLI surface is identical to B3's (same arg, same validation). The runner's `_dispatch_parse` (`_nextseek_runner.py:101`) calls `entity_agent` then `parser_agent`; the shim does NOT need to know that — it just forwards `--query`.

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `build_context/plugins/nextseek/bin/_nextseek_runner.py` (FILE-PATH form). Same rationale as B3 — no new Python code.

All commands run from repo root; anchor with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED**: create `tests/unit/test_shim_parse.py` per §5.1. Run:
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_parse.py -v
```
Expected: 3 failures (shim missing).

**Step 2 — GREEN**: create `build_context/plugins/nextseek/bin/nextseek-parse` per §6.1. Then:
```bash
cd "$(git rev-parse --show-toplevel)"
chmod +x build_context/plugins/nextseek/bin/nextseek-parse
```

**Step 3 — Verify GREEN**:
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_parse.py -v
```
Expected: 3 passed.

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
Expected: B2 (17) + however many shim tests are in `tests/unit/test_shim_*.py` at execution time + 3 (B4) all pass; coverage ≥95%.

**Step 5 — Commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git add -f build_context/plugins/nextseek/bin/nextseek-parse
git add tests/unit/test_shim_parse.py
git commit -m $'nextseek-plugin: nextseek-parse shim\n\nPlan B \xc2\xb7 T4. Mirror of T3 with --agent parse.'
```

**Step 6 — Verify commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-parse shim$'
git diff --stat HEAD~1 HEAD | grep -q 'nextseek-parse'
```

The second guard catches the empty-commit failure mode (subject lands but `git add -f` was forgotten). Required because `build_context/` is gitignored — see B1 Phase 4 review HIGH-1.

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_parse.py`

```python
"""Plan B · T4 — nextseek-parse shim.

Image-only by Plan A T7's PATH_B decision. Per Wave-3 inheritance rule 1
(2026-05-02 chat_nextseek host-import audit item 7), gate the whole file
with importorskip — the rule is unconditional.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "nextseek-parse"
COMMON = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-parse" in r.stdout


def test_missing_query_errors_with_code_3():
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --query" in r.stderr
    assert "nextseek-error" in r.stderr


def test_runner_dispatched_with_correct_args(tmp_path):
    """Stub runner — confirm shim invokes it with --agent parse --query <text>."""
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)

    fake_common = tmp_path / "_nextseek_common.sh"
    fake_common.write_text(COMMON.read_text())

    fake_shim = tmp_path / "nextseek-parse"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    r = subprocess.run(
        [str(fake_shim), "--query", "list samples for project X"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert payload["called_with"][0] == "--agent"
    assert payload["called_with"][1] == "parse"
    assert payload["called_with"][2] == "--query"
    assert payload["called_with"][3] == "list samples for project X"
```

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-parse`

```bash
#!/bin/sh
# nextseek-parse — derive a parser plan from a free-text query.
# Plan B · T4.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

QUERY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    --query=*) QUERY="${1#--query=}"; shift ;;
    --help)
      echo "Usage: nextseek-parse --query \"<text>\""
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$QUERY" ] || nextseek_die 3 "missing --query"

exec python "$SCRIPT_DIR/_nextseek_runner.py" --agent parse --query "$QUERY"
```

**Mode**: `0755`.

## 7. Modified Files (exact diffs)

None. Two new files only.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

uv run pytest tests/unit/test_shim_parse.py -v
# Expected: 3 passed (image) or 3 skipped (host without chat_nextseek)

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
# Expected: full B2+B3+B4 (and any later-merged Wave-3 shim tests) green; coverage ≥95%.

python -c "import py_compile; py_compile.compile('tests/unit/test_shim_parse.py', doraise=True)"
test -x build_context/plugins/nextseek/bin/nextseek-parse && echo "executable OK"
```

**Expected test count**: 3 new.
**Expected coverage**: ≥95% on `_nextseek_runner.py` (held by B2).

## 9. Implementation Notes

### 9.1 Plan-line citations

- Plan body line 1544-1545: B4 task definition.
- Plan body lines 51-56: Wave-3 inheritance rules.

### 9.2 Why not factor B3 + B4 into a shared script

B3's shim, B4's shim, B5's shim, B7's shim are ~90% identical. A reasonable refactor would extract them into a single parameterized template generator. **Plan B intentionally does not do that** because:
- Each shim is the L1 allowlist target (B12). Layer 1 enforcement reads the shim names verbatim.
- The SKILL.md tool catalog (B10) names each shim by file. A generated wrapper would force the catalog to know about the parameterization.
- Cold-start agents (and human reviewers) can audit `nextseek-parse` independently. A factored template hides the dispatch-target name behind another file.

This is design decision D8 ("deterministic dispatchers — flat, named") applied to the shim layer. Do not refactor without raising via `/ultraplan amend`.

### 9.3 Gotchas

Same as B3 §9.3:
- Quoting on `"$QUERY"` is load-bearing (security + arg integrity).
- `[ -n "$QUERY" ] || nextseek_die 3` MUST follow the case loop, before `exec`.
- `git add -f` for `build_context/...`.
- `pytest.importorskip("chat_nextseek")` at module top.

### 9.4 Coverage status — no exception

Same as B3 §9.4. Default 95% on `_nextseek_runner.py`, FILE-PATH form, held by B2.

### 9.5 Self-review checklist

- [x] Tests fail before implementation? Yes — §4 Step 1.
- [x] Tests pass after? Yes — §4 Step 3.
- [x] No regressions? Yes — §4 Step 4.
- [x] Coverage meets target? Yes — held at 100% by B2.
- [x] `importorskip` at top? Yes — §5.1 line 11.
- [x] FILE-PATH `--cov=` form? Yes.
- [x] `--cov-fail-under=95` REMOVED per Amendment 1 (2026-05-02 evening); host invocations informational only, binding gate enforced on image in Wave 5 B17.
- [x] `git add -f` for `build_context/...`? Yes — §4 Step 5.
- [x] No `make install-chat-nextseek`? Confirmed absent.
- [x] No empty subdirs? Confirmed.

## 10. Worktree & Branch

- **Branch**: `task/B04-parse`
- **Worktree**: `.claude/worktrees/task-B04-parse/`
- **Init**:
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B04-parse
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 all green.
  2. Shim is mode `0755` and tracked.
  3. Commit subject matches `^nextseek-plugin: nextseek-parse shim$`.
  4. Post-merge `feature-dev:code-reviewer` returns APPROVE.


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
