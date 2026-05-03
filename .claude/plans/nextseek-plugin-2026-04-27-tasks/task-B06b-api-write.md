# task-B06b-api-write — `nextseek-api-write` shim (write-class API dispatch)

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3) — Wave 3 inheritance rules per plan compact handoff (2026-05-02).
> **Wave**: 3. Predecessors: B1, B2.
> **Status**: **UNVETTED** — awaiting Phase 4.

## 1. Overview

Author the **write-class API** shim. Layer 1 (the L1 allowlist in `.claude/settings.local.json` from B12) **does NOT include `nextseek-api-write`** — every invocation of this shim by Container-Claude trips a permission prompt the user must approve. Layer 2 (the runner) requires `--confirmed-write` and refuses without it. Layer 3 (the SKILL.md behavioral gate from B10) requires Container-Claude to first ask the user via `AskUserQuestion` and obtain an affirmative answer before invoking `nextseek-api-write`.

After this task:
- `build_context/plugins/nextseek/bin/nextseek-api-write` exists, executable, source-tracked.
- `tests/unit/test_shim_api_write.py` exercises help / missing-`--parser-plan` / missing-`--confirmed-write` / runner-dispatch.
- Suite still green; runner coverage ≥95%.

**Key invariants:**
- Shim REQUIRES both `--parser-plan <json>` and `--confirmed-write`. Either missing → `nextseek_die 3`.
- Shim is intentionally NOT in B12's L1 allowlist. This task does NOT modify `.claude/settings.local.json`. (B12 will explicitly NOT add this shim.)
- The shim forwards `--confirmed-write` verbatim to the runner — Layer 2 (`_nextseek_runner.py:179-181`) re-checks it. Defense in depth.

## 2. Dependencies

- **Predecessors**: B1, B2.
- **Artifacts consumed**: `_nextseek_common.sh`, `_nextseek_runner.py` (`_dispatch_api_write` at `_nextseek_runner.py:175`).
- **External packages**: none new.

## 3. Key Design Decisions

Inherits B3 §3 (D8, D14, D20, D29, NEW-7, build_context git-add `-f`, Wave-3 inheritance rule 1).

Additional B6b-specific decisions:
- **Plan body line 1579-1582**: `--parser-plan <json>` (required) + `--confirmed-write` (required). — *Constraint*: BOTH are required. Missing either → `nextseek_die 3`. The runner's L2 only re-checks `--confirmed-write`; missing `--parser-plan` would surface as a runner-side argparse error (less helpful UX than the shim's `nextseek_die`).
- **Layer-1 omission (Plan body §"Write safety — 3 layers")**: B12 must NOT add `Bash(nextseek-api-write:*)` to `.claude/settings.local.json`. — *Constraint*: this spec explicitly forbids modifying `.claude/settings.local.json` from B6b; the omission is B12's responsibility but is observable via `grep -F "nextseek-api-write" .claude/settings.local.json` returning empty. (B12 spec must keep that grep negative.)
- **`--query` forwarded for log context**: same rationale as B6a §3.

## 4. TDD Implementation Order

**Coverage target**: ≥95% on `_nextseek_runner.py` (FILE-PATH form). No new Python.

All commands from repo root; anchor with `cd "$(git rev-parse --show-toplevel)"`.

**Step 1 — RED**: create `tests/unit/test_shim_api_write.py` per §5.1.
```bash
cd "$(git rev-parse --show-toplevel)"
uv run pytest tests/unit/test_shim_api_write.py -v
```
Expected: 4 failures.

**Step 2 — GREEN**: create `build_context/plugins/nextseek/bin/nextseek-api-write` per §6.1; `chmod +x`.

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
git add -f build_context/plugins/nextseek/bin/nextseek-api-write
git add tests/unit/test_shim_api_write.py
git commit -m $'nextseek-plugin: nextseek-api-write shim (Layer-2 gate)\n\nPlan B \xc2\xb7 T6b. Write-class API dispatch. Requires --confirmed-write.\nIntentionally NOT in the L1 allowlist (B12) \xe2\x80\x94 every invocation must\ntrip a permission prompt. Runner re-validates --confirmed-write.'
```

**Step 6 — Verify commit**:
```bash
cd "$(git rev-parse --show-toplevel)"
git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: nextseek-api-write shim'
```

## 5. Behavioral Contract (Tests)

### 5.1 New file: `tests/unit/test_shim_api_write.py`

```python
"""Plan B · T6b — nextseek-api-write shim. Write-class. Image-only per Wave-3
inheritance rule 1. Layer 1 NOT allowlisted (B12). Layer 2 (runner) re-checks
--confirmed-write. Layer 3 is the SKILL.md AskUserQuestion gate (B10)."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

pytest.importorskip("chat_nextseek")

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIM_DIR = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "bin"
SHIM = SHIM_DIR / "nextseek-api-write"
COMMON = SHIM_DIR / "_nextseek_common.sh"


def test_help_exits_zero_and_prints_usage():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "Usage" in r.stdout
    assert "nextseek-api-write" in r.stdout
    assert "--parser-plan" in r.stdout
    assert "--confirmed-write" in r.stdout


def test_missing_parser_plan_errors_with_code_3():
    r = subprocess.run([str(SHIM), "--confirmed-write"], capture_output=True, text=True)
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --parser-plan" in r.stderr


def test_missing_confirmed_write_errors_with_code_3():
    """Without --confirmed-write the shim must reject. The runner has its
    own re-check (L2), but the shim's rejection means we never spawn the
    runner subprocess for an unconfirmed write attempt."""
    r = subprocess.run(
        [str(SHIM), "--parser-plan", "{}"],
        capture_output=True,
        text=True,
    )
    assert r.returncode == 3, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    assert "missing --confirmed-write" in r.stderr


def test_runner_dispatched_with_confirmed_write_forwarded(tmp_path):
    """Stub runner — confirm shim invokes it with --agent api-write,
    --parser-plan <json>, AND --confirmed-write all forwarded."""
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text(
        "import sys, json\n"
        "print(json.dumps({'called_with': sys.argv[1:]}))\n"
    )
    fake_runner.chmod(0o755)
    (tmp_path / "_nextseek_common.sh").write_text(COMMON.read_text())
    fake_shim = tmp_path / "nextseek-api-write"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)

    plan_json = '{"target_endpoint":"/sample/","method":"POST","requestBody":{}}'
    r = subprocess.run(
        [str(fake_shim),
         "--parser-plan", plan_json,
         "--confirmed-write"],
        capture_output=True,
        text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert r.returncode == 0, f"stdout={r.stdout!r} stderr={r.stderr!r}"
    payload = json.loads(r.stdout.strip())
    argv = payload["called_with"]
    assert argv[0] == "--agent"
    assert argv[1] == "api-write"
    assert "--parser-plan" in argv
    assert plan_json in argv
    assert "--confirmed-write" in argv
```

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/nextseek-api-write`

```bash
#!/bin/sh
# nextseek-api-write — write-class API dispatch.
# Layer 1: NOT in the L1 allowlist (B12) — every call trips a permission prompt.
# Layer 2: this shim requires both --parser-plan and --confirmed-write.
#          The runner re-checks --confirmed-write at _nextseek_runner.py:179-181.
# Layer 3: the SKILL.md (B10) requires Container-Claude to AskUserQuestion-confirm
#          before invoking this shim.
# Plan B · T6b.
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

QUERY=""
PARSER_PLAN=""
CONFIRMED_WRITE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    --query=*) QUERY="${1#--query=}"; shift ;;
    --parser-plan) PARSER_PLAN="$2"; shift 2 ;;
    --parser-plan=*) PARSER_PLAN="${1#--parser-plan=}"; shift ;;
    --confirmed-write) CONFIRMED_WRITE=1; shift ;;
    --confirmed-write=*)
      nextseek_die 3 "--confirmed-write requires no value; pass bare --confirmed-write"
      ;;
    --help)
      echo "Usage: nextseek-api-write --parser-plan '<json>' --confirmed-write [--query \"<text>\"]"
      echo ""
      echo "Write-class API dispatch. BOTH --parser-plan and --confirmed-write are"
      echo "required. The runner re-validates --confirmed-write before issuing the"
      echo "request. This shim is intentionally NOT in the L1 permission allowlist;"
      echo "every invocation prompts the user."
      exit 0
      ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$PARSER_PLAN" ] || nextseek_die 3 "missing --parser-plan"
[ "$CONFIRMED_WRITE" = "1" ] || nextseek_die 3 "missing --confirmed-write"

if [ -n "$QUERY" ]; then
  exec python "$SCRIPT_DIR/_nextseek_runner.py" \
    --agent api-write --parser-plan "$PARSER_PLAN" --confirmed-write --query "$QUERY"
else
  exec python "$SCRIPT_DIR/_nextseek_runner.py" \
    --agent api-write --parser-plan "$PARSER_PLAN" --confirmed-write
fi
```

**Mode**: `0755`.

## 7. Modified Files (exact diffs)

None.

## 8. Verification

```bash
cd "$(git rev-parse --show-toplevel)"

uv run pytest tests/unit/test_shim_api_write.py -v
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

python -c "import py_compile; py_compile.compile('tests/unit/test_shim_api_write.py', doraise=True)"
test -x build_context/plugins/nextseek/bin/nextseek-api-write && echo "executable OK"

# B12-precondition assertion (informational, not a hard fail at this stage):
# .claude/settings.local.json must NOT contain 'nextseek-api-write' in any
# Bash(...) allow rule. B12 is responsible for keeping this true; B6b just
# documents the expectation.
if grep -qF "nextseek-api-write" .claude/settings.local.json 2>/dev/null; then
  echo "WARN: api-write found in settings.local.json — must NOT be present post-B12"
else
  echo "OK: api-write absent from settings.local.json (expected)"
fi
```

**Expected test count**: 4 new.
**Expected coverage**: ≥95% on `_nextseek_runner.py` (held by B2).

## 9. Implementation Notes

### 9.1 Plan-line citations
- Plan body line 1579-1582: B6b task definition.
- Plan body §"Write safety — 3 layers": L1/L2/L3 doctrine.
- `_nextseek_runner.py:175-206`: L2 enforcement.
- Plan body lines 51-56: Wave-3 inheritance rules.

### 9.2 Why both shim and runner check `--confirmed-write`

Same logic as B6a §9.2, mirrored: the runner is authoritative, but auditors reading just the shim should see a complete enforcement. The shim rejects fast (no python startup, no chat_nextseek import) for unconfirmed writes, which improves UX and slightly reduces blast surface. The runner's L2 catches programmatic callers that bypass the shim.

### 9.2a Why `--confirmed-write=<value>` is rejected explicitly

The case loop has a dedicated `--confirmed-write=*)` arm that calls `nextseek_die 3 "--confirmed-write requires no value; pass bare --confirmed-write"`. Without this arm, `--confirmed-write=yes` would fall to the `*) nextseek_die 3 "unknown arg"` catch-all — same exit code, but a generic error message that doesn't tell the caller how to fix the invocation. Symmetric with B6a's case-loop treatment (B6a §9.3) where the same explicit rejection is used to preserve a contractual error message.

### 9.3 Why `CONFIRMED_WRITE` is an integer flag, not a string

Boolean POSIX-sh idiom: `=1` and `=0`. Using `CONFIRMED_WRITE=true`/`false` would force a string compare with `[ "$CONFIRMED_WRITE" = "true" ]` which is fine but more brittle (easy to typo). Using `=1`/`=0` matches the pattern in `_nextseek_common.sh` (`CHAT_NEXTSEEK_CONFIG_VERBOSE` defaults to `false`, but no test checks it; for our flag, `=1` parsed via `[ "$CONFIRMED_WRITE" = "1" ]` is unambiguous).

### 9.4 The exec-with-or-without-query branch

Same rationale as B6a §9.4. Don't pass `--query ""` to the runner.

### 9.5 Shim NOT added to L1 allowlist by this task

This task creates ONLY two new files: the shim and its test. It does NOT touch `.claude/settings.local.json`. B12 is responsible for the L1 allowlist. The grep assertion in §8 is informational.

If a reviewer pushes back ("how do you know B12 will keep `nextseek-api-write` out?"), the answer is: B12's spec must explicitly forbid adding it. That is B12's contract, vetted in Wave 5. If B12 spec author errs and adds it, B17 (image dry-run e2e) and the post-merge code-reviewer will catch it.

### 9.6 Coverage status — no exception

Default 95% on `_nextseek_runner.py`, held by B2.

### 9.7 Self-review checklist

- [x] Tests fail before implementation; pass after; no regressions; coverage ≥95%.
- [x] `pytest.importorskip("chat_nextseek")` at top.
- [x] FILE-PATH `--cov=` preserved; `--cov-fail-under=95` REMOVED per Amendment 1 (2026-05-02 evening) — host informational only, binding gate on image (Wave 5 B17).
- [x] `git add -f` for `build_context/...`.
- [x] BOTH `--parser-plan` and `--confirmed-write` required at the shim.
- [x] No modification to `.claude/settings.local.json` from this task.
- [x] No `make install-chat-nextseek`; no empty subdirs.

## 10. Worktree & Branch

- **Branch**: `task/B06b-api-write`
- **Worktree**: `.claude/worktrees/task-B06b-api-write/`
- **Init**:
  ```bash
  bash ${CLAUDE_PLUGIN_ROOT}/skills/ultraplan/scripts/init_worktrees.sh nextseek-plugin-2026-04-27 task-B06b-api-write
  ```
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**:
  1. §8 all green.
  2. Shim mode `0755` and tracked.
  3. Commit subject starts with `nextseek-plugin: nextseek-api-write shim`.
  4. `.claude/settings.local.json` unchanged by this commit (`git diff HEAD~1 HEAD -- .claude/settings.local.json` is empty).
  5. Post-merge `feature-dev:code-reviewer` returns APPROVE.


---

## LOCKED 2026-05-02

Phase 4 combined review: APPROVE-with-micro-fixes (per-spec + cross-task reviewers in parallel).
All required fixes applied 2026-05-02 (see plan `## Task Specs Manifest` for the per-spec review pointer).
User-confirmed via `/ultraplan` Phase 5 prompt 2026-05-02.

This spec is now immutable. Any deviation requires `/ultraplan amend`.
