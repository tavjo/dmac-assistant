# task-B07-graph — `nextseek-graph` shim

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3. Predecessors: B1, B2.
> **Status**: **UNVETTED** — awaiting Phase 4.

## 1. Overview

Author the `nextseek-graph` shim — Cypher-graph lineage queries via the runner's `_dispatch_graph` (`_nextseek_runner.py:209`). Mirror of B3 with `--agent graph`.

After this task: shim + test exist; full host-runnable suite green; coverage ≥95% on `_nextseek_runner.py`.

**Key invariants**: identical structure to B3 / B4 / B5 (POSIX sh, `_nextseek_common.sh`, `exec python`, `pytest.importorskip("chat_nextseek")`).

## 2. Dependencies

- **Predecessors**: B1, B2.
- **Artifacts consumed**: `_nextseek_common.sh`, `_nextseek_runner.py` (`_dispatch_graph`).
- **External packages**: none new.

## 3. Key Design Decisions

Inherits B3 §3 (D8, D14, D20, D29, NEW-7, build_context git-add `-f`, Wave-3 inheritance rule 1).

- **Plan body line 1584-1585**: `--query <text>`. Exec: `--agent graph --query "$QUERY"`. — *Constraint*: same surface as B3/B4/B5; runner handles entity_agent + graph_agent internally.

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `_nextseek_runner.py` (FILE-PATH form). No new Python.

All commands from repo root; anchor with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED**: create `tests/unit/test_shim_graph.py` per §5.1.
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_graph.py -v
```
Expected: 3 failures.

**Step 2 — GREEN**: create `build_context/plugins/nextseek/bin/nextseek-graph` per §6.1; `chmod +x`.

**Step 3 — Verify GREEN**: re-run §4 Step 1 command. Expected: 3 passed.

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
git add -f build_context/plugins/nextseek/bin/nextseek-graph
git add tests/unit/test_shim_graph.py
git commit -m $'nextseek-plugin: nextseek-graph shim\n\nPlan B \xc2\xb7 T7. Mirror of T3 with --agent graph. Cypher lineage queries.'
```

**Step 6 — Verify commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-graph shim$'
git diff --stat HEAD~1 HEAD | grep -q 'nextseek-graph'
```

The second guard catches the empty-commit failure mode.

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_graph.py`

```python
"""Plan B · T7 — nextseek-graph shim. Image-only per Wave-3 inheritance rule 1."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "nextseek-graph"
COMMON = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin" / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-graph" in r.stdout


def test_missing_query_errors_with_code_3():
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --query" in r.stderr
    assert "nextseek-error" in r.stderr


def test_runner_dispatched_with_correct_args(tmp_path):
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-graph"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    r = subprocess.run(
        [str(fake_shim), "--query", "trace lineage of UID-12345"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    assert payload["called_with"][0] == "--agent"
    assert payload["called_with"][1] == "graph"
    assert payload["called_with"][2] == "--query"
    assert payload["called_with"][3] == "trace lineage of UID-12345"
```

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-graph`

```bash
#!/bin/sh
# nextseek-graph — graph/Cypher lineage queries.
# Plan B · T7.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

QUERY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    --query=*) QUERY="${1#--query=}"; shift ;;
    --help)
      echo "Usage: nextseek-graph --query \"<text>\""
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$QUERY" ] || nextseek_die 3 "missing --query"

exec python "$SCRIPT_DIR/_nextseek_runner.py" --agent graph --query "$QUERY"
```

**Mode**: `0755`.

## 7. Modified Files (exact diffs)

None.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

uv run pytest tests/unit/test_shim_graph.py -v
# Expected: 3 passed (image) or 3 skipped (host).

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

python -c "import py_compile; py_compile.compile('tests/unit/test_shim_graph.py', doraise=True)"
test -x build_context/plugins/nextseek/bin/nextseek-graph && echo "executable OK"
```

**Expected test count**: 3 new.
**Expected coverage**: ≥95% on `_nextseek_runner.py`.

## 9. Implementation Notes

### 9.1 Plan-line citations
- Plan body line 1584-1585: B7 task definition.
- Plan body lines 51-56: Wave-3 inheritance rules.

### 9.2 Gotchas

Same as B3 §9.3.

### 9.3 Coverage status — no exception

Default 95% on `_nextseek_runner.py`, held by B2.

### 9.4 Self-review checklist

- [x] Tests fail before; pass after; no regressions; coverage ≥95%.
- [x] `importorskip` at top; FILE-PATH `--cov=` preserved; `git add -f`. (`--cov-fail-under=95` REMOVED per Amendment 1 (2026-05-02 evening) — host informational only, binding gate on image in Wave 5 B17.)
- [x] No `make install-chat-nextseek`; no empty subdirs.

## 10. Worktree & Branch

- **Branch**: `task/B07-graph`
- **Worktree**: `.claude/worktrees/task-B07-graph/`
- **Init**:
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B07-graph
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 all green.
  2. Shim mode `0755` and tracked.
  3. Commit subject `^nextseek-plugin: nextseek-graph shim$`.
  4. Post-merge `feature-dev:code-reviewer` APPROVE.


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
