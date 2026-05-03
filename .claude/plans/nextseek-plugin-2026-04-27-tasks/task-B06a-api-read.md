# task-B06a-api-read — `nextseek-api-read` shim (read-only API dispatch + Layer-1 boundary)

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3. Predecessors: B1, B2.
> **Status**: **UNVETTED** — awaiting Phase 4.

## 1. Overview

Author the **read-only API** shim. This is the single shim that Container-Claude's L1 permission allowlist (B12) permits via the catch-all `Bash(nextseek-api-read:*)` permission. Layer 2 (the runner's `_dispatch_api_read` allowlist check against `read_safe_endpoints.json`) is the load-bearing security boundary; this shim's job is to close the residual CRITICAL-3 vector — preventing an LLM from smuggling `--confirmed-write` through the L1-allowed read shim by rejecting that flag at the shim level before reaching the runner.

After this task:
- `build_context/plugins/nextseek/bin/nextseek-api-read` exists, executable, source-tracked.
- `tests/unit/test_shim_api_read.py` exercises help / missing-`--parser-plan` / runner-dispatch / **`--confirmed-write` rejection** (the boundary test).
- B2 + earlier-Wave-3 + B6a host-runnable suite green; runner coverage ≥95% on `_nextseek_runner.py`.

**Key invariants:**
- Layer-1 (the L1 allowlist in `.claude/settings.local.json` from B12) ONLY allows `nextseek-api-read`. `nextseek-api-write` is NOT in L1; Container-Claude must trip a permission prompt and the user must `AskUserQuestion`-confirm before B6b runs.
- Layer-2 (the runner) refuses non-allowlisted (endpoint, method) pairs (`_nextseek_runner.py:151-157`). This shim does not duplicate that logic.
- This shim's CONTRIBUTION is the **Layer-1 boundary test**: rejecting `--confirmed-write` at the shim level so an LLM-authored argv cannot route a write through the L1-allowed read pathway.

## 2. Dependencies

- **Predecessors**: B1, B2.
- **Artifacts consumed**: `_nextseek_common.sh`, `_nextseek_runner.py` (`_dispatch_api_read` at `_nextseek_runner.py:130`).
- **External packages**: none new.

## 3. Key Design Decisions

Inherits B3 §3 (D8, D14, D20, D29, NEW-7, build_context git-add `-f`, Wave-3 inheritance rule 1).

Additional B6a-specific decisions:
- **Plan body line 1551-1554**: `--parser-plan <json>` required; `--confirmed-write` MUST be rejected at the shim with the exact message `--confirmed-write is not valid on nextseek-api-read; use nextseek-api-write`. — *Constraint*: rejection happens in the case loop BEFORE any other validation, so the message is deterministic regardless of other arg ordering.
- **Plan body line 1577**: the `test_read_shim_rejects_confirmed_write` boundary test "must be added to the B4-B8 commit batch." — *Constraint*: §5.1 below includes this exact test verbatim from plan body line 1564-1574 (with the `pytest.importorskip` rule applied).
- **`--query` is optional, forwarded to runner**: the runner's argparse accepts `--query` (`_nextseek_runner.py:273`); `_dispatch_api_read` does not consume it but argparse won't error. Forwarding it lets a future logging hook attribute the read-call to its originating user query.
- **Layer-1/2 split (Plan body §"Write safety — 3 layers")**: this shim closes Layer 1 ONLY. Layer 2 is the runner. Layer 3 is the SKILL.md behavioral gate (B10). Do not duplicate Layer 2's allowlist check here.

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `_nextseek_runner.py` (FILE-PATH form). No new Python code in the shim itself; the runner's branches are already covered by B2.

All commands from repo root; anchor with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED**: create `tests/unit/test_shim_api_read.py` per §5.1.
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_api_read.py -v
```
Expected: 4 failures (shim missing).

**Step 2 — GREEN**: create `build_context/plugins/nextseek/bin/nextseek-api-read` per §6.1; `chmod +x`.

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
git add -f build_context/plugins/nextseek/bin/nextseek-api-read
git add tests/unit/test_shim_api_read.py
git commit -m $'nextseek-plugin: nextseek-api-read shim (Layer-1 boundary)\n\nPlan B \xc2\xb7 T6a. Read-only API dispatch. Closes the residual\nCRITICAL-3 vector by rejecting --confirmed-write at the shim level.\nLayer 2 (runner allowlist against read_safe_endpoints.json) is the\nload-bearing security boundary; this shim is defense in depth.'
```

**Step 6 — Verify commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-api-read shim'
```

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_api_read.py`

```python
"""Plan B · T6a — nextseek-api-read shim.

Image-only per Wave-3 inheritance rule 1. Includes the CRITICAL-3 boundary
test mandated by plan body line 1564-1574: a read shim must NOT accept
--confirmed-write. The runner's L2 allowlist would catch a write attempt
on the read endpoint, but this shim-level rejection means an LLM cannot
silently smuggle --confirmed-write through the L1-allowed read pathway.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-api-read"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-api-read" in r.stdout
    assert "--parser-plan" in r.stdout


def test_missing_parser_plan_errors_with_code_3():
    r = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --parser-plan" in r.stderr
    assert "nextseek-error" in r.stderr


def test_read_shim_rejects_confirmed_write():
    """CRITICAL-3 boundary: read shim must exit non-zero with the specific
    message naming nextseek-api-write as the correct route."""
    r = subprocess.run(
        [str(SHIM),
         "--query", "x",
         "--parser-plan", "{}",
         "--confirmed-write"],
        capture_output=True,
        text=True,
    )
    assert r.returncode != 0, (
        f"read shim accepted --confirmed-write: stdout={r.stdout!r} "
        f"stderr={r.stderr!r}"
    )
    assert "--confirmed-write is not valid on nextseek-api-read" in r.stderr
    assert "nextseek-api-write" in r.stderr


def test_runner_dispatched_with_correct_args(tmp_path):
    """Stub runner — confirm shim invokes it with --agent api-read --parser-plan
    <json> (and --query if supplied)."""
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-api-read"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    plan_json = '{"target_endpoint":"/sample/","method":"GET"}'
    r = subprocess.run(
        [str(fake_shim),
         "--query", "list LinVo samples",
         "--parser-plan", plan_json],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "api-read"
    # --parser-plan must be present, with the exact JSON string preserved.
    assert "--parser-plan" in argv
    assert plan_json in argv
    # --query forwarded as well (optional but supported).
    assert "--query" in argv
    assert "list LinVo samples" in argv
    # --confirmed-write MUST NOT be in the forwarded argv.
    assert "--confirmed-write" not in argv
```

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-api-read`

```bash
#!/bin/sh
# nextseek-api-read — read-only API dispatch (Layer-1 allowed, Layer-2 enforced).
# CRITICAL-3 boundary: rejects --confirmed-write at the shim before exec'ing
# the runner. The runner's L2 allowlist against read_safe_endpoints.json is the
# load-bearing security check; this rejection is defense in depth.
# Plan B · T6a.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

QUERY=""
PARSER_PLAN=""
while [ $# -gt 0 ]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    --query=*) QUERY="${1#--query=}"; shift ;;
    --parser-plan) PARSER_PLAN="$2"; shift 2 ;;
    --parser-plan=*) PARSER_PLAN="${1#--parser-plan=}"; shift ;;
    --confirmed-write|--confirmed-write=*)
      nextseek_die 3 "--confirmed-write is not valid on nextseek-api-read; use nextseek-api-write"
      ;;
    --help)
      echo "Usage: nextseek-api-read --parser-plan '<json>' [--query \"<text>\"]"
      echo ""
      echo "Read-only API dispatch. Refuses --confirmed-write (use nextseek-api-write"
      echo "for write-class operations). The runner additionally enforces an allowlist"
      echo "of (endpoint, method) pairs from read_safe_endpoints.json."
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$PARSER_PLAN" ] || nextseek_die 3 "missing --parser-plan"

if [ -n "$QUERY" ]; then
  exec python "$SCRIPT_DIR/_nextseek_runner.py" \
    --agent api-read --parser-plan "$PARSER_PLAN" --query "$QUERY"
else
  exec python "$SCRIPT_DIR/_nextseek_runner.py" \
    --agent api-read --parser-plan "$PARSER_PLAN"
fi
```

**Mode**: `0755`.

## 7. Modified Files (exact diffs)

None.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

uv run pytest tests/unit/test_shim_api_read.py -v
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
# Expected: ≥95% on _nextseek_runner.py.

python -c "import py_compile; py_compile.compile('tests/unit/test_shim_api_read.py', doraise=True)"
test -x build_context/plugins/nextseek/bin/nextseek-api-read && echo "executable OK"
```

**Expected test count**: 4 new (one more than B3/B4/B5 — the boundary test).
**Expected coverage**: ≥95% on `_nextseek_runner.py`.

## 9. Implementation Notes

### 9.1 Plan-line citations
- Plan body line 1551-1577: B6a task definition, including the CRITICAL-3 boundary test (extended from plan body lines 1564-1574 with the specific message assertions required by the contractual rejection message — see §3) (lines 1564-1574).
- Plan body line 1781-1789 (Write safety — 3 layers): the L1/L2/L3 doctrine this shim partially implements.
- Plan body lines 51-56: Wave-3 inheritance rules.
- `_nextseek_runner.py:130-172`: the L2 enforcement this shim's L1 work complements.

### 9.2a Shim and runner rejection messages diverge intentionally

The shim (§6.1) emits `"--confirmed-write is not valid on nextseek-api-read; use nextseek-api-write"` (full tool names). The runner's L2 (`_nextseek_runner.py:136`) emits `"--confirmed-write is not valid on api-read; use api-write"` (short names). This divergence is intentional: the shim is the user-facing L1 perimeter and is referenced by SKILL.md (B10) using its full file name; the runner is reachable only by direct `python _nextseek_runner.py` calls (bypassing the shim) where the short names match the runner's `--agent` enum. Future maintainers MUST NOT "fix" one to match the other without updating SKILL.md's contractual quotation.

### 9.2 Why reject `--confirmed-write` at the shim, not just at the runner

The runner's `_dispatch_api_read` (`_nextseek_runner.py:134-136`) DOES reject `args.confirmed_write`. So why duplicate it at the shim?

Answer: because `nextseek-api-read` is L1-allowlisted but `nextseek-api-write` is not. An LLM that learns it can't call `nextseek-api-write` (permission prompt) might attempt `nextseek-api-read --confirmed-write '{"endpoint": "/sample/", "method": "POST"}'`. The runner would reject that — but only AFTER the L1-allowlisted shim already accepted the invocation. Some auditors will read the L1 allowlist + shim combination as the security perimeter and miss the runner's L2 check. Rejecting at the shim makes the L1 perimeter sufficient on its own; L2 is then defense in depth, not the only line.

This is not theoretical. CRITICAL-3 was the residual finding from Phase 4 review on B6a's earlier draft. The verbatim rejection message is contractual — the SKILL.md (B10) and L1 allowlist commentary reference it.

### 9.3 Why `--confirmed-write=*` is rejected too

The case branch matches both `--confirmed-write` (boolean) and `--confirmed-write=*` (e.g. `--confirmed-write=yes`). A naive case loop that only matched the bare flag would let `--confirmed-write=yes` fall through to `*) nextseek_die 3 "unknown arg"` — same exit code, but a different message that doesn't name the alternative `nextseek-api-write`. The contractual message is preserved in both cases.

### 9.4 The exec-with-or-without-query branch

Forwarding `--query` to the runner is conditional. If the user did NOT pass `--query`, the shim must NOT pass an empty `--query ""` to the runner — the runner's `_dispatch_api_read` ignores `args.query`, but argparse's `--query ""` would set `args.query = ""` (a falsy string), which any future hook checking `if args.query` would mishandle. Branch `if [ -n "$QUERY" ]` keeps the surface clean.

### 9.5 Coverage status — no exception

Default 95% on `_nextseek_runner.py`, held by B2.

### 9.6 Self-review checklist

- [x] Tests fail before implementation; pass after; no regressions; coverage ≥95%.
- [x] `pytest.importorskip("chat_nextseek")` at top.
- [x] FILE-PATH `--cov=` preserved; `--cov-fail-under=95` REMOVED per Amendment 1 (2026-05-02 evening) — host informational only, binding gate on image (Wave 5 B17).
- [x] `git add -f` for `build_context/...`.
- [x] CRITICAL-3 boundary test included verbatim per plan line 1564-1574.
- [x] `--confirmed-write=*` (with-value form) also rejected.
- [x] No `make install-chat-nextseek`; no empty subdirs.

## 10. Worktree & Branch

- **Branch**: `task/B06a-api-read`
- **Worktree**: `.claude/worktrees/task-B06a-api-read/`
- **Init**:
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B06a-api-read
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 all green; the CRITICAL-3 boundary test passes.
  2. Shim mode `0755` and tracked.
  3. Commit subject starts with `nextseek-plugin: nextseek-api-read shim`.
  4. Post-merge `feature-dev:code-reviewer` returns APPROVE.


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
