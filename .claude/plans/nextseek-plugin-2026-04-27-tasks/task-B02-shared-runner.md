# task-B02-shared-runner — Shared shim helpers (`_nextseek_common.sh` + `_nextseek_runner.py`)

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3 — APPROVED 2026-05-01)
> **Wave**: 2 (sole task; depends on B1; blocks B3-B9 in Wave 3)
> **Status**: **LOCKED 2026-05-01** (Phase 4 REVISE → 9 fixes applied → focused re-review APPROVE-with-micro-fixes → JSONDecodeError test added → Phase 5 user-confirmed). See `## LOCKED` section at end of file.
> **Coverage target**: **95%** on `_nextseek_runner.py` (ultraplan default; no exception). *Amended 2026-05-01 from plan-locked 90% — see plan `## Amendment Log`.*

## 1. Overview

Author the two shared helpers that every Wave 3 shim (B3 entity-extract, B4 parse, B5 plan, B6a api-read, B6b api-write, B7 graph, B8 generate-submission) and Wave 4 reporter dispatcher (B9 report) reuse:

1. **`build_context/plugins/nextseek/bin/_nextseek_common.sh`** — POSIX shell snippet sourced by every `nextseek-*` shim. Translates Plan-A-supplied env vars into the names `chat_nextseek.config.ChatConfig` reads (D20), forces the GCP profile (D23), defaults the outputs directory under `/data/scratch/${API_USER:-anon}` so the Plan A T5/T6 post-turn copier can publish to `/data/output/`, and exports a structured `nextseek_die` error helper.
2. **`build_context/plugins/nextseek/bin/_nextseek_runner.py`** — Python script that loads `ChatConfig` once, dispatches to one of 8 typed dispatchers (`entity`, `parse`, `plan`, `api-read`, `api-write`, `graph`, `report`, `generate-submission`), enforces Layer-2 write-safety on `api-write` (`--confirmed-write` required → exit 5 if missing), enforces the read-safe endpoint allowlist on `api-read` (`read_safe_endpoints.json` lookup → exit 5 if not allowlisted), and emits one-line stdout JSON or one-line structured stderr JSON with deterministic exit codes (`0`, `2`, `3`, `4`, `5`, `6`).

Plus the test contract:

3. **`tests/unit/test_nextseek_runner.py`** — baseline cred-missing failure test (exit code != 0 + structured `CONFIG_MISSING` payload on stderr).
4. **`tests/unit/test_nextseek_runner_dispatch.py`** — eight per-dispatcher monkeypatched tests (NEW-2 from Rev 2 review) that pin the exact positional-argument order of every `chat_nextseek` agent / helper call. Plus one extra `api-write`-without-`--confirmed-write` test that asserts `SystemExit(code=5)` (NEW-5 / NEW-1 reinforcement).

**Key invariants:**

- Dispatchers call `chat_nextseek` public functions with the **exact real signatures** from the Rev 2 Mandatory Amendments (plan lines 181-198). Do NOT use the older v1 `run_api_request` / duck-typed `ReporterPlan` shape.
- The runner imports `ReporterPlan` and `ReportWriterPlan` from `chat_nextseek.schemas.chat`; it does not fabricate duck-typed reporter objects.
- `api-read` consults `read_safe_endpoints.json` only — there is no inline allowlist constant. Path resolution: `NEXTSEEK_READ_SAFE_ENDPOINTS_PATH` env override (test mode) → `/app/plugins/nextseek/context/read_safe_endpoints.json` (image default). Missing file → exit 6 (`CONFIG_ERROR`), not silent allow.
- `api-write` does NOT consult any allowlist. It is gated by Layer 1 (Claude Code asks the user because the shim is not in the L1 allowlist) + Layer 2 (`--confirmed-write` flag, enforced here) + Layer 3 (SKILL.md plain-text confirmation, B10).
- `NEXTSEEK_DRY_RUN=1` short-circuits every dispatcher to a minimal valid typed JSON response without calling any LLM, REST, or Neo4j path. This is what B17.1's image dry-run e2e test exercises.
- Coverage scope (B2.4) is intentionally narrowed to `_nextseek_runner.py` only. The shell shims under `bin/` are measured by their own bats / subprocess tests in B3-B9. This is a declared exception (§4, §9.4) — Phase 4 vetting must approve.

## 2. Dependencies

- **Predecessor tasks**: **B1 (scaffold)** — `build_context/plugins/nextseek/` and its `.claude-plugin/plugin.json` must exist on the integration branch before B2 starts. The runner lives at `build_context/plugins/nextseek/bin/_nextseek_runner.py`; the bin directory is created by B2 inside the B1-established plugin root.
- **Plan A prerequisites** (already merged to `main` at `33e21f6`):
  - Python 3.14 pinned **inside the image** (Plan A T0); `chat_nextseek` importable as `import chat_nextseek` **only inside the `dmac-assistant:poc` image** — the host venv pins Python 3.12 and chat_nextseek (which requires 3.14) is intentionally NOT installed there per Plan A T7's PATH_B image-only decision (`pyproject.toml` closing comment: `# T7 path-decision: PATH_B image-only — chat_nextseek install deferred to T8 (R4-NEW-5)`). B0 pre-flight verifies importability inside the image only — see plan `## Host vs Image Python Environment` for the full split + test-discipline rules. **Consequence for this task**: every host-side test that imports chat_nextseek (directly or transitively via subprocess) MUST guard with `pytest.importorskip("chat_nextseek")`.
  - `chat_nextseek.config.ChatConfig`, `chat_nextseek.session.SQLiteSessionState`, `chat_nextseek.schemas.chat.ReporterPlan`, `chat_nextseek.schemas.chat.ReportWriterPlan` resolvable.
  - `chat_nextseek.agents.entity_agent / parser_agent / multi_parser_agent / planner_agent / api_agent_build_request / graph_agent / report_writer_agent` present (verified by onboard re-grep on 2026-05-01).
  - `chat_nextseek.helpers.tool_nextseek_api_request` and `chat_nextseek.helpers.run_reporter_summary` present (verified).
- **Artifacts consumed**:
  - `build_context/plugins/nextseek/.claude-plugin/plugin.json` (from B1) — only as a presence check; the runner does not read it.
  - **Pre-flight presence gate** (Phase 4 cross-task review HIGH-1): before the B2 executor writes any files, run:
    ```bash
    git ls-files build_context/plugins/nextseek/.claude-plugin/plugin.json | grep -q . \
      || { echo 'ERROR: B1 not merged to integration branch — abort B2'; exit 1; }
    ```
    This fails fast if the B2 worktree was cut from a state where B1 was committed locally but not yet merged to `ultraplan/nextseek-plugin-2026-04-27`.
- **External packages** (test side):
  - `pytest` (already in `pyproject.toml`'s test deps).
  - `pytest-cov` (already configured in `[tool.pytest.ini_options]` with repo-wide `--cov-fail-under=95`; B2.4 invokes pytest-cov with a per-task `--cov` override scoped to `_nextseek_runner.py` and the same `--cov-fail-under=95`).
  - `unittest.mock` (stdlib).
- **Tooling**: `python` (3.14), `uv`, `git`, `chmod`. No Docker for this task — the runner is exercised on the host against the host's `chat_nextseek` install.

## 3. Key Design Decisions

- **D20 (cred env var translation)**: Bridge ships `NEXTSEEK_USERNAME` / `NEXTSEEK_PASSWORD`; chat_nextseek's `ChatConfig` reads `API_USER` / `API_PASS` / `NEXTSEEK_BASE_URL`. — *Constraint*: `_nextseek_common.sh` re-exports the bridge names under the chat_nextseek names with `: "${API_USER:=${NEXTSEEK_USERNAME:-}}"` style indirection. The shim must NOT clobber `API_USER` if it is already set (test scenarios may set it directly).
- **D22 (3-layer write safety)**: Writes require all three layers: (L1) no allowlist entry → Claude Code asks the user; (L2) `--confirmed-write` flag on the binary; (L3) plain-text "yes/no" confirmation in SKILL.md. — *Constraint*: `_dispatch_api_write` enforces L2 and emits exit code 5 with `WRITE_BLOCKED` payload when `--confirmed-write` is absent. `_dispatch_api_read` rejects `--confirmed-write` if passed (validation error, exit 3). The L2 enforcement must be unconditional — there is no escape hatch env var.
- **D23 (force GCP profile)**: chat_nextseek supports both bedrock and GCP modes; in DMAC-assistant the entrypoint always wants `NEXTSEEK_MODE=gcp`. — *Constraint*: `_nextseek_common.sh` defaults `NEXTSEEK_MODE` to `gcp` if unset, and exports it. The runner does not re-read `NEXTSEEK_MODE` — the source-of-truth is `ChatConfig`'s own resolution.
- **D27 (chat_nextseek importable)**: chat_nextseek is installed once at image build (Plan A T7+T8), not per-invocation. — *Constraint*: imports inside dispatchers (`from chat_nextseek.agents import entity_agent`, etc.) are deferred to call time, not module-load time. This serves two purposes: (a) `_load_config` can emit a clean `IMPORT_FAILED` exit 2 if chat_nextseek vanishes; (b) tests can monkeypatch `chat_nextseek.agents.entity_agent` BEFORE the dispatcher imports it (the dispatcher does `from chat_nextseek.agents import entity_agent` after monkeypatching, so the import resolves the patched object — see §9.2 for the import-mechanics nuance).
- **D29 (no `uv run --with` in shims)**: All shims invoke plain `python` (system / image Python). — *Constraint*: shebang on `_nextseek_runner.py` is `#!/usr/bin/env python` (no `uv run --with chat_nextseek`). Shims that source `_nextseek_common.sh` then call `python /app/plugins/nextseek/bin/_nextseek_runner.py …` directly.
- **NEW-1 (Rev 2 finding closed by Rev 3)**: `_dispatch_api_read` and `_dispatch_api_write` are SEPARATE dispatchers, not a unified `_dispatch_api_call`. — *Constraint*: there is no `--write` boolean toggle on a single dispatcher. The `--agent` arg routes between two distinct functions.
- **NEW-2 (Rev 2 finding closed by Rev 3)**: Per-dispatcher monkeypatch tests are required, one per `_DISPATCH` key. — *Constraint*: B2.2b authors all 8 (entity, parse, plan, api-read, api-write, graph, report, generate-submission) plus the api-write-exit-5 test. No "just spot-check one of them".
- **NEW-5 (Rev 2 finding closed by Rev 3)**: `read_safe_endpoints.json` is the only source of truth for read-safe pairs. — *Constraint*: `_load_read_safe_endpoints()` reads from disk; missing file → exit 6. Tests override the path via `NEXTSEEK_READ_SAFE_ENDPOINTS_PATH` or via `monkeypatch.setattr(runner, "_load_read_safe_endpoints", lambda: …)`.
- **NEW-7 (Rev 2 finding closed by Rev 3, then amended 2026-05-01)**: B2.4 must specify a concrete coverage floor. — *Constraint*: `--cov-fail-under=95` (ultraplan default; raised from the original 90% via the 2026-05-01 amendment), scoped to `_nextseek_runner.py` only.

## 4. TDD Implementation Order

**Coverage target**: **95% on `build_context/plugins/nextseek/bin/_nextseek_runner.py`** — ultraplan default. **No exception.** *Amended 2026-05-01 from plan-locked 90%; see plan `## Amendment Log` entry "Coverage bump B2 90% → 95%".*

The shell layer (`_nextseek_common.sh`) is still out of pytest-cov scope (it is sourced shell, not Python; tests for it live in B3-B9 as bats / subprocess invocations, not pytest-cov-instrumented unit tests). That is **scope** not **exception** — pytest-cov simply does not instrument sourced shell. The 95% applies to `_nextseek_runner.py` only because that is the only Python under cov scope for this task.

The three error branches that the prior 90% target carved out as "uncoverable" — `_load_config` ImportError, `_load_read_safe_endpoints` OSError, and the broad-except in `main()` — are all reachable via standard `monkeypatch` and are now covered by the additional tests in §5.2 (tests #10-#12).

---

**Step 1 — RED (B2.2 baseline test)**: Write `tests/unit/test_nextseek_runner.py` with the failing-by-design `test_runner_emits_structured_error_on_missing_creds`. The runner does not yet exist, so the subprocess `python <runner-path>` will fail at file-not-found — the assertion `result.returncode != 0` is true but the `json.loads(...)` will raise. That's still a RED outcome (test errors, not passes). Confirm:
  ```bash
  uv run pytest tests/unit/test_nextseek_runner.py -v
  # Expected: ERRORED (file-not-found on RUNNER) or FAILED.
  ```

**Step 2 — RED (B2.2b dispatcher tests)**: Write `tests/unit/test_nextseek_runner_dispatch.py` with all 9 tests (8 per-dispatcher + 1 api-write-exit-5). Confirm:
  ```bash
  uv run pytest tests/unit/test_nextseek_runner_dispatch.py -v
  # Expected: ERRORED on _load_runner() because RUNNER_PATH does not exist.
  ```

**Step 3 — GREEN (B2.1 shell helper)**: First create the bin directory (Phase 4 cross-task review MEDIUM-1 — B1 does NOT create this), then write `build_context/plugins/nextseek/bin/_nextseek_common.sh` per §6.1. Make it executable: `chmod +x` is not strictly required for sourced files but is harmless. Sanity check:
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  mkdir -p build_context/plugins/nextseek/bin/
  # ... write _nextseek_common.sh per §6.1 ...
  sh -n build_context/plugins/nextseek/bin/_nextseek_common.sh   # syntax-check
  ```

**Step 4 — GREEN (B2.3 runner)**: Write `build_context/plugins/nextseek/bin/_nextseek_runner.py` per §6.2. Make it executable:
  ```bash
  chmod +x build_context/plugins/nextseek/bin/_nextseek_runner.py
  ```

**Step 5 — VERIFY (B2.4 tests + coverage floor)**: Run the runner tests and the dispatcher tests with the coverage floor:
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  uv run pytest tests/unit/test_nextseek_runner.py tests/unit/test_nextseek_runner_dispatch.py \
    --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
    --cov-fail-under=95 -v
  ```
  Expected: 1 (B2.2) + 8 dispatcher + 1 api-write-exit-5 + 3 amendment-2026-05-01 + 4 Phase-4-review-CRITICAL-1+HIGH-1 (incl. malformed-JSON re-review residual) = **17 tests pass**, coverage ≥ 95% on `_nextseek_runner`.

  **Note on `--disable-socket`** (Phase 4 review MEDIUM-2): the repo `pyproject.toml` `[tool.pytest.ini_options].addopts` includes `--disable-socket` and applies to this per-task invocation too. `subprocess.run` is unaffected (no socket). If a future `chat_nextseek` version opens a socket at module-import time (e.g., a connection-pool init), the dispatcher tests would fail under `--disable-socket`. Mitigations if that happens: (a) decorate affected tests with `@pytest.mark.enable_socket`, or (b) defer the offending `chat_nextseek` import even further. Verify against the pinned `chat_nextseek` rev before assuming this is moot.

  Note on `--cov` arg form: pytest-cov accepts EITHER a Python module dotted path OR a file path. Because `build_context/plugins/nextseek/bin/` has no `__init__.py` (it is not an installable package), use the file-path form `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py`. Plan B2.4 lines 1114-1119 prescribe both forms; the file-path form is the safer default.

**Step 6 — VERIFY (full suite, no regression)**:
  ```bash
  uv run pytest -q
  ```
  The repo-wide `--cov-fail-under=95` from `pyproject.toml` is computed against `tests.harness` and `src/dmac_assistant`. B2 adds zero lines to those packages, so the repo-wide gate must continue to pass at the existing baseline.

**Step 7 — Commit (B2.5)**:
  ```bash
  chmod +x build_context/plugins/nextseek/bin/_nextseek_runner.py
  git add -f build_context/plugins/nextseek/bin/_nextseek_common.sh \
             build_context/plugins/nextseek/bin/_nextseek_runner.py
  git add tests/unit/test_nextseek_runner.py \
          tests/unit/test_nextseek_runner_dispatch.py
  git commit -m "$(cat <<'EOF'
  nextseek-plugin: shared runner + cred-translation helper

  Plan B · T2. Includes per-dispatcher monkeypatch tests (B2.2b)
  that pin chat_nextseek call signatures.
  EOF
  )"
  ```

## 5. Behavioral Contract (Tests)

The tests below are **the contract**. Every assertion is intentional. No `TODO`, no placeholder. The runner implementation in §6 must satisfy these tests; if the implementation deviates, adjust the implementation, not the tests.

### 5.1 New file: `tests/unit/test_nextseek_runner.py`

```python
"""Plan B · T2: shared runner produces structured JSON output."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

# Skip cleanly on hosts without chat_nextseek installed. The subprocess we
# spawn loads `_nextseek_runner.py`, which does
# `from chat_nextseek.config import ChatConfig` first; on a host without
# chat_nextseek that exits 2 with IMPORT_FAILED before reaching the
# cred-missing branch this test asserts. chat_nextseek is image-only by
# Plan A T7's PATH_B decision (host Python 3.12 vs chat_nextseek's
# `requires-python >=3.14`) — see plan `## Host vs Image Python Environment`
# and `## Amendment Log` entry "chat_nextseek host-import audit (2026-05-02)".
pytest.importorskip("chat_nextseek")

RUNNER = Path(
    "build_context/plugins/nextseek/bin/_nextseek_runner.py"
).resolve()


def test_runner_emits_structured_error_on_missing_creds(tmp_path, monkeypatch):
    monkeypatch.delenv("API_USER", raising=False)
    monkeypatch.delenv("API_PASS", raising=False)
    # Use sys.executable (not bare "python") because macOS dev environments
    # frequently lack a `python` symlink on the minimal /usr/bin:/bin PATH —
    # cross-task review MEDIUM-2.
    result = subprocess.run(
        [sys.executable, str(RUNNER), "--agent", "entity", "--query", "x"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["error"]["code"] == "CONFIG_MISSING"
```

### 5.2 New file: `tests/unit/test_nextseek_runner_dispatch.py`

Top-of-file note: prepend `pytest.importorskip("chat_nextseek")` immediately after the stdlib imports. **This is unconditional, not conditional on a "test environment without chat_nextseek".** chat_nextseek is never installed on the host venv (Plan A T7 PATH_B image-only — see plan `## Host vs Image Python Environment` and `pyproject.toml` closing comment). The pre-flight at the top of the plan only verifies image-side importability via `docker run`; it does NOT install or verify chat_nextseek on the host. Tests that need real chat_nextseek behavior live in the image surface (B17 dry-run, B18 manual smoke). The 9 tests below are taken from the plan's Rev 3 spec at lines 491-783 verbatim — they ARE the contract; they only execute on hosts where chat_nextseek happens to be installed (typically: never), and on CI/dev hosts they skip cleanly.

```python
"""Plan B · T2 · B2.2b: per-dispatcher monkeypatch tests for _nextseek_runner."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# Skip cleanly if chat_nextseek is not installed in the test env (instead of
# failing with cryptic ModuleNotFoundError inside test bodies). Phase 4 review
# CRITICAL-2.
pytest.importorskip("chat_nextseek")

RUNNER_PATH = Path(
    "build_context/plugins/nextseek/bin/_nextseek_runner.py"
).resolve()


def _load_runner():
    """Load _nextseek_runner.py as a module (it's a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_nextseek_runner", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_nextseek_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner():
    return _load_runner()


def test_dispatch_entity_calls_entity_agent_with_config_and_query(runner, monkeypatch):
    """entity_agent must be called with (config, query) in that order."""
    fake_entity_agent = MagicMock(return_value=MagicMock(model_dump=lambda: {"sampletypes": []}))
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)

    args = argparse.Namespace(query="find samples")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_entity(args, config, session)

    fake_entity_agent.assert_called_once()
    call_args, call_kwargs = fake_entity_agent.call_args
    assert call_args[0] is config, f"first positional arg should be config, got {call_args[0]!r}"
    assert call_args[1] == "find samples", f"second positional arg should be query, got {call_args[1]!r}"
    assert result == {"sampletypes": []}


def test_dispatch_parse_calls_parser_agent_with_session_config_query_entity(runner, monkeypatch):
    """parser_agent must be called with (session, config, query, entity_out)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_parser_agent = MagicMock(
        return_value=MagicMock(model_dump=lambda: {"mode": "new_search"})
    )
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "parser_agent", fake_parser_agent)

    args = argparse.Namespace(query="find samples")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_parse(args, config, session)

    fake_entity_agent.assert_called_once()
    ent_args, _ = fake_entity_agent.call_args
    assert ent_args[0] is config
    assert ent_args[1] == "find samples"

    fake_parser_agent.assert_called_once()
    p_args, _ = fake_parser_agent.call_args
    assert p_args[0] is session, f"parser_agent arg0 should be session, got {p_args[0]!r}"
    assert p_args[1] is config, f"parser_agent arg1 should be config, got {p_args[1]!r}"
    assert p_args[2] == "find samples", f"parser_agent arg2 should be query, got {p_args[2]!r}"
    assert p_args[3] is fake_entity_out, f"parser_agent arg3 should be entity_out, got {p_args[3]!r}"
    assert result == {"mode": "new_search"}


def test_dispatch_plan_calls_planner_agent_with_full_positional_chain(runner, monkeypatch):
    """planner_agent must be called with (session, config, query, entity_out, multi)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_multi = MagicMock(name="multi_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_multi_parser_agent = MagicMock(return_value=fake_multi)
    fake_planner_agent = MagicMock(
        return_value=MagicMock(model_dump=lambda: {"plan": []})
    )
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "multi_parser_agent", fake_multi_parser_agent)
    monkeypatch.setattr(agents_mod, "planner_agent", fake_planner_agent)

    args = argparse.Namespace(query="find samples then lineage")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_plan(args, config, session)

    fake_multi_parser_agent.assert_called_once()
    mp_args, _ = fake_multi_parser_agent.call_args
    assert mp_args[0] is session
    assert mp_args[1] is config
    assert mp_args[2] == "find samples then lineage"
    assert mp_args[3] is fake_entity_out

    fake_planner_agent.assert_called_once()
    pl_args, _ = fake_planner_agent.call_args
    assert pl_args[0] is session, f"planner_agent arg0 should be session, got {pl_args[0]!r}"
    assert pl_args[1] is config, f"planner_agent arg1 should be config, got {pl_args[1]!r}"
    assert pl_args[2] == "find samples then lineage"
    assert pl_args[3] is fake_entity_out, f"planner_agent arg3 should be entity_out"
    assert pl_args[4] is fake_multi, f"planner_agent arg4 should be multi, got {pl_args[4]!r}"
    assert result == {"plan": []}


def test_dispatch_api_read_calls_helpers_tool_nextseek_api_request(runner, monkeypatch, tmp_path):
    """api-read: build_request → allowlist check → helpers.tool_nextseek_api_request."""
    fake_api_plan = MagicMock(name="api_plan")
    fake_api_plan.endpoint = "/samples/"
    fake_api_plan.method = "GET"
    fake_api_plan.requestBody = None
    fake_api_plan.queryParameters = {"project": "X"}
    fake_api_plan.model_dump = lambda: {"endpoint": "/samples/", "method": "GET"}

    fake_build_request = MagicMock(return_value=fake_api_plan)
    fake_tool_request = MagicMock(return_value={"results": []})

    import chat_nextseek.agents as agents_mod
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(agents_mod, "api_agent_build_request", fake_build_request)
    monkeypatch.setattr(helpers_mod, "tool_nextseek_api_request", fake_tool_request)
    monkeypatch.setattr(
        runner, "_load_read_safe_endpoints",
        lambda: {("/samples/", "GET")},
    )

    args = argparse.Namespace(
        parser_plan='{"mode": "new_search"}',
        confirmed_write=False,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_api_read(args, config, session)

    fake_build_request.assert_called_once()
    br_args, _ = fake_build_request.call_args
    assert br_args[0] is config, f"api_agent_build_request arg0 should be config"
    assert br_args[1] == {"mode": "new_search"}, f"arg1 should be parsed plan dict"

    fake_tool_request.assert_called_once()
    tr_args, tr_kwargs = fake_tool_request.call_args
    assert tr_args[0] is config, f"tool_nextseek_api_request arg0 should be config"
    assert tr_args[1] == "/samples/", f"arg1 should be endpoint"
    assert tr_args[2] == "GET", f"arg2 should be method"
    assert tr_kwargs.get("requestBody") is None
    assert tr_kwargs.get("queryParameters") == {"project": "X"}
    assert result["endpoint"] == "/samples/"
    assert result["method"] == "GET"
    assert result["response"] == {"results": []}


def test_dispatch_api_write_with_confirmed_write_calls_helpers_tool_nextseek_api_request(
    runner, monkeypatch
):
    """api-write with --confirmed-write: passes through to helpers.tool_nextseek_api_request."""
    fake_api_plan = MagicMock(name="api_plan")
    fake_api_plan.endpoint = "/samples/"
    fake_api_plan.method = "POST"
    fake_api_plan.requestBody = {"name": "S1"}
    fake_api_plan.queryParameters = None
    fake_api_plan.model_dump = lambda: {"endpoint": "/samples/", "method": "POST"}

    fake_build_request = MagicMock(return_value=fake_api_plan)
    fake_tool_request = MagicMock(return_value={"created": True})

    import chat_nextseek.agents as agents_mod
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(agents_mod, "api_agent_build_request", fake_build_request)
    monkeypatch.setattr(helpers_mod, "tool_nextseek_api_request", fake_tool_request)

    args = argparse.Namespace(
        parser_plan='{"mode": "create"}',
        confirmed_write=True,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_api_write(args, config, session)

    fake_tool_request.assert_called_once()
    tr_args, tr_kwargs = fake_tool_request.call_args
    assert tr_args[0] is config
    assert tr_args[1] == "/samples/"
    assert tr_args[2] == "POST"
    assert tr_kwargs.get("requestBody") == {"name": "S1"}
    assert tr_kwargs.get("queryParameters") is None
    assert result["endpoint"] == "/samples/"
    assert result["method"] == "POST"


def test_dispatch_api_write_without_confirmed_write_exits_5(runner, monkeypatch):
    """api-write without --confirmed-write must SystemExit with code 5 (Layer-2 block)."""
    args = argparse.Namespace(
        parser_plan='{"mode": "create"}',
        confirmed_write=False,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    with pytest.raises(SystemExit) as exc_info:
        runner._dispatch_api_write(args, config, session)
    assert exc_info.value.code == 5, f"expected exit 5 (WRITE_BLOCKED), got {exc_info.value.code}"


def test_dispatch_graph_calls_graph_agent_with_config_query_entity(runner, monkeypatch):
    """graph_agent must be called with (config, query, entity_out)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_graph_agent = MagicMock(return_value={"cypher": "MATCH (n) RETURN n", "result": []})
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "graph_agent", fake_graph_agent)

    args = argparse.Namespace(query="lineage of S1")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_graph(args, config, session)

    fake_graph_agent.assert_called_once()
    g_args, _ = fake_graph_agent.call_args
    assert g_args[0] is config, f"graph_agent arg0 should be config"
    assert g_args[1] == "lineage of S1", f"graph_agent arg1 should be query"
    assert g_args[2] is fake_entity_out, f"graph_agent arg2 should be entity_out"
    assert result == {"cypher": "MATCH (n) RETURN n", "result": []}


def test_dispatch_report_calls_run_reporter_summary_with_reporter_plan(runner, monkeypatch):
    """run_reporter_summary must be called with (config, ReporterPlan, log_dir)."""
    fake_run_reporter = MagicMock(return_value=([{"row": 1}], ["/tmp/out.csv"], "summary text"))
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "run_reporter_summary", fake_run_reporter)
    monkeypatch.setenv("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")

    args = argparse.Namespace(mode="samples", project="ProjectA", query=None)
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_report(args, config, session)

    fake_run_reporter.assert_called_once()
    r_args, _ = fake_run_reporter.call_args
    assert r_args[0] is config, f"run_reporter_summary arg0 should be config"
    rp = r_args[1]
    assert rp.project == "ProjectA"
    assert rp.summary_mode == "samples", f"summary_mode should be 'samples', got {rp.summary_mode!r}"
    assert r_args[2] == "/tmp/nextseek", f"arg2 should be log_dir"
    assert result["summary"] == "summary text"
    assert result["saved_files"] == ["/tmp/out.csv"]


def test_dispatch_generate_submission_calls_report_writer_agent_with_plan(runner, monkeypatch):
    """report_writer_agent must be called with (config, query_str, ReportWriterPlan)."""
    fake_report = MagicMock()
    fake_report.model_dump = lambda: {"report": "text", "type": "GEO"}
    fake_writer = MagicMock(return_value=fake_report)
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "report_writer_agent", fake_writer)

    args = argparse.Namespace(type="GEO", uids="S1,S2", query="generate GEO")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_generate_submission(args, config, session)

    fake_writer.assert_called_once()
    w_args, _ = fake_writer.call_args
    assert w_args[0] is config, f"report_writer_agent arg0 should be config"
    assert w_args[1] == "generate GEO", f"arg1 should be query string"
    plan = w_args[2]
    assert plan.report_type == "GEO", f"report_type should be 'GEO', got {plan.report_type!r}"
    assert plan.reporter_context == {"uids": ["S1", "S2"]}
    assert result == {"report": "text", "type": "GEO"}


# ---------- amendment 2026-05-01: cover the previously-excepted branches ----

def test_load_config_emits_import_failed_when_chat_nextseek_unimportable(
    runner, monkeypatch, capsys
):
    """_load_config must exit 2 with IMPORT_FAILED when chat_nextseek.config is unimportable.

    Strategy: inject `None` into sys.modules['chat_nextseek.config'] — Python's
    import machinery treats that as a previously-failed import and raises a
    plain `ImportError` ("import of chat_nextseek.config halted; use of None
    is not allowed"), NOT a `ModuleNotFoundError`. The runner's
    `except ImportError as exc:` catches it because ImportError is the parent
    class either way.
    """
    import json as _json
    monkeypatch.setitem(sys.modules, "chat_nextseek.config", None)

    with pytest.raises(SystemExit) as exc_info:
        runner._load_config()

    assert exc_info.value.code == 2, f"expected exit 2 (CONFIG_MISSING/IMPORT_FAILED), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "IMPORT_FAILED"
    assert "chat_nextseek not importable" in payload["error"]["message"]


def test_load_read_safe_endpoints_emits_config_error_on_open_oserror(
    runner, monkeypatch, tmp_path, capsys
):
    """_load_read_safe_endpoints must exit 6 (CONFIG_ERROR) when open() raises OSError.

    Strategy: point the path env var at an existing file (so the os.path.exists
    pre-check passes), then monkeypatch builtins.open to raise OSError when
    invoked on that path — this exercises the OSError branch of the try/except
    around `open(path)`/`json.load(fh)`.
    """
    import builtins
    import json as _json

    fake_path = tmp_path / "read_safe_endpoints.json"
    fake_path.write_text("[]")  # exists, but we'll force open to fail
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(fake_path))

    real_open = builtins.open

    def _raising_open(file, *args, **kwargs):
        if str(file) == str(fake_path):
            raise OSError(13, "Permission denied")
        return real_open(file, *args, **kwargs)

    monkeypatch.setattr(builtins, "open", _raising_open)

    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()

    assert exc_info.value.code == 6, f"expected exit 6 (CONFIG_ERROR), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "CONFIG_ERROR"
    assert "OSError" in payload["error"]["message"] or "Permission denied" in payload["error"]["message"]


def test_main_wraps_unexpected_dispatcher_exception_as_agent_failed(
    runner, monkeypatch, capsys
):
    """main()'s broad except clause must convert non-SystemExit dispatcher errors
    to exit code 4 with an AGENT_FAILED payload.

    Strategy: enable NEXTSEEK_DRY_RUN so main() skips _load_config/_make_session,
    then monkeypatch the entity dispatcher in _DISPATCH to raise RuntimeError.
    Set sys.argv so argparse parses cleanly.
    """
    import json as _json

    monkeypatch.setenv("NEXTSEEK_DRY_RUN", "1")

    def _boom(args, config, session):
        raise RuntimeError("kaboom")

    # Replace the entity dispatcher in the module-level dispatch table.
    monkeypatch.setitem(runner._DISPATCH, "entity", _boom)
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner.py", "--agent", "entity", "--query", "x"])

    with pytest.raises(SystemExit) as exc_info:
        runner.main()

    assert exc_info.value.code == 4, f"expected exit 4 (AGENT_FAILED), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "AGENT_FAILED"
    assert "RuntimeError" in payload["error"]["message"]
    assert "kaboom" in payload["error"]["message"]


# ----- Phase 4 review CRITICAL-1 + HIGH-1: cover the real _load_read_safe_endpoints
# implementation and the _dispatch_report RPPR remap branch.

def test_load_read_safe_endpoints_happy_path_returns_endpoint_method_set(
    runner, monkeypatch, tmp_path
):
    """_load_read_safe_endpoints must parse a populated JSON file into a set of
    (endpoint, METHOD) tuples, exercising the json.load call, the for-loop
    body, and the allowlist.add line — all uncovered without this test.
    """
    fake_path = tmp_path / "read_safe_endpoints.json"
    fake_path.write_text(
        '[{"endpoint": "/samples/", "methods": ["GET", "post"]},'
        ' {"endpoint": "/projects/", "methods": ["GET"]}]'
    )
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(fake_path))

    allowlist = runner._load_read_safe_endpoints()

    assert allowlist == {
        ("/samples/", "GET"),
        ("/samples/", "POST"),  # method must be upper-cased
        ("/projects/", "GET"),
    }


def test_load_read_safe_endpoints_emits_config_error_when_file_missing(
    runner, monkeypatch, tmp_path, capsys
):
    """_load_read_safe_endpoints must exit 6 (CONFIG_ERROR) when the path does
    not exist, exercising the os.path.exists → _err missing-file branch.
    """
    import json as _json

    missing_path = tmp_path / "does-not-exist.json"
    assert not missing_path.exists()  # sanity
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(missing_path))

    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()

    assert exc_info.value.code == 6, f"expected exit 6 (CONFIG_ERROR), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "CONFIG_ERROR"
    assert "missing" in payload["error"]["message"].lower()
    assert str(missing_path) in payload["error"]["message"]


def test_load_read_safe_endpoints_emits_config_error_on_malformed_json(
    runner, monkeypatch, tmp_path, capsys
):
    """_load_read_safe_endpoints must exit 6 (CONFIG_ERROR) when the file is
    present but contains malformed JSON, exercising the json.JSONDecodeError
    arm of the `except (OSError, json.JSONDecodeError)` clause that the OSError
    test at line 493 leaves uncovered. Phase 4 re-review residual from
    CRITICAL-1.
    """
    import json as _json

    bad_path = tmp_path / "read_safe_endpoints.json"
    bad_path.write_text("{this is not valid json")  # malformed
    monkeypatch.setenv("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH", str(bad_path))

    with pytest.raises(SystemExit) as exc_info:
        runner._load_read_safe_endpoints()

    assert exc_info.value.code == 6, f"expected exit 6 (CONFIG_ERROR), got {exc_info.value.code}"
    err = capsys.readouterr().err.strip().splitlines()[-1]
    payload = _json.loads(err)
    assert payload["error"]["code"] == "CONFIG_ERROR"
    assert "JSONDecodeError" in payload["error"]["message"]


def test_dispatch_report_with_rppr_mode_remaps_summary_mode_to_uppercase(
    runner, monkeypatch
):
    """_dispatch_report must remap args.mode='rppr' → ReporterPlan.summary_mode='RPPR'.

    The base report test only exercises args.mode='samples' (else-branch of the
    ternary at runner line 806). This test covers the true-branch of that
    ternary — Phase 4 review HIGH-1.
    """
    fake_run_reporter = MagicMock(return_value=([{"row": 1}], ["/tmp/out.csv"], "summary"))
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "run_reporter_summary", fake_run_reporter)
    monkeypatch.setenv("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")

    args = argparse.Namespace(mode="rppr", project="ProjectA", query=None)
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    runner._dispatch_report(args, config, session)

    fake_run_reporter.assert_called_once()
    r_args, _ = fake_run_reporter.call_args
    rp = r_args[1]
    assert rp.summary_mode == "RPPR", f"summary_mode should remap 'rppr' → 'RPPR', got {rp.summary_mode!r}"
    assert rp.project == "ProjectA"
```

**Total tests added by B2**: 1 (B2.2 baseline) + 9 (B2.2b — eight per-dispatcher + one api-write-exit-5) + 3 (amendment 2026-05-01 — coverage-bump tests) + 4 (Phase 4 review CRITICAL-1 + HIGH-1 — real-impl coverage tests, incl. malformed-JSON branch added in re-review) = **17 new tests**.

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/bin/_nextseek_common.sh`

```sh
#!/bin/sh
# Sourced by every nextseek-* shim. Translates env vars chat_nextseek expects.

# D20: re-export env names chat_nextseek's ChatConfig reads.
: "${API_USER:=${NEXTSEEK_USERNAME:-}}"
: "${API_PASS:=${NEXTSEEK_PASSWORD:-}}"
: "${NEXTSEEK_BASE_URL:=${NEXTSEEK_URL:-}}"
export API_USER API_PASS NEXTSEEK_BASE_URL

# D23: force GCP profile.
: "${NEXTSEEK_MODE:=gcp}"
export NEXTSEEK_MODE

# Default outputs land under /data/scratch/<user>/<run-id>/ (chat_nextseek
# orchestrator creates per-run subdirs). The bridge-side copier (Plan A T5)
# discovers them by scratch-listing diff and publishes to /data/output/.
: "${NEXTSEEK_OUTPUTS_DIR:=/data/scratch/${API_USER:-anon}}"
export NEXTSEEK_OUTPUTS_DIR

# Quiet config-load logs by default.
: "${CHAT_NEXTSEEK_CONFIG_VERBOSE:=false}"
export CHAT_NEXTSEEK_CONFIG_VERBOSE

# nextseek_die <code> <message>: structured error -> stderr + exit
nextseek_die() {
  printf 'nextseek-error: %s\n' "$2" >&2
  exit "$1"
}
```

### 6.2 New file: `build_context/plugins/nextseek/bin/_nextseek_runner.py`

```python
#!/usr/bin/env python
"""Shared entry point for nextseek-* shims.

Loads chat_nextseek's ChatConfig once, dispatches to the requested agent,
emits one of:
  - stdout: result JSON (one line)
  - stderr (last line): structured error JSON, exit code != 0

Exit codes:
  0  ok
  2  config / env missing
  3  validation (bad args)
  4  agent failure (LLM error, network, etc.)
  5  write blocked (Layer-2 --confirmed-write missing OR endpoint not in
     read_safe_endpoints.json on api-read path)
  6  config error (read_safe_endpoints.json missing in production)

Dry-run mode: when NEXTSEEK_DRY_RUN=1, each dispatcher returns a minimal
valid typed JSON response without invoking any LLM, REST, or Neo4j call.
This is what B17.1's image dry-run test exercises to prove wiring without
needing live GCP/NExtSEEK credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


READ_SAFE_ENDPOINTS_DEFAULT = "/app/plugins/nextseek/context/read_safe_endpoints.json"


def _err(code: str, message: str, exit_code: int) -> None:
    payload = {"error": {"code": code, "message": message}}
    sys.stderr.write(json.dumps(payload) + "\n")
    sys.exit(exit_code)


def _dry_run() -> bool:
    return os.environ.get("NEXTSEEK_DRY_RUN") == "1"


def _load_config():
    try:
        from chat_nextseek.config import ChatConfig
    except ImportError as exc:
        _err("IMPORT_FAILED", f"chat_nextseek not importable: {exc}", 2)
    if not os.environ.get("API_USER") or not os.environ.get("API_PASS"):
        _err("CONFIG_MISSING", "API_USER / API_PASS not set", 2)
    return ChatConfig({})


def _make_session(config):
    from chat_nextseek.session import SQLiteSessionState
    user = os.environ.get("API_USER", "anon")
    return SQLiteSessionState(config.SESSION_DB_PATH, user)


def _load_read_safe_endpoints():
    """Return set of (endpoint, METHOD) tuples from read_safe_endpoints.json.

    Path resolution:
      - If NEXTSEEK_READ_SAFE_ENDPOINTS_PATH is set, use that (test override).
      - Else default to /app/plugins/nextseek/context/read_safe_endpoints.json.

    If the file is missing, exit with code 6 (CONFIG_ERROR) naming the path.
    """
    path = os.environ.get("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH",
                          READ_SAFE_ENDPOINTS_DEFAULT)
    if not os.path.exists(path):
        _err("CONFIG_ERROR",
             f"read_safe_endpoints.json missing at {path}; set "
             "NEXTSEEK_READ_SAFE_ENDPOINTS_PATH or rebuild the image",
             6)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _err("CONFIG_ERROR",
             f"failed to load {path}: {type(exc).__name__}: {exc}",
             6)
    allowlist = set()
    for entry in data:
        ep = entry.get("endpoint")
        for m in entry.get("methods", []):
            allowlist.add((ep, m.upper()))
    return allowlist


# ---------------------------------------------------------------- dispatchers

def _dispatch_entity(args, config, session):
    if _dry_run():
        return {"sampletypes": [], "assays": [], "keywords": [], "projects": []}
    from chat_nextseek.agents import entity_agent
    out = entity_agent(config, args.query)
    return out.model_dump() if hasattr(out, "model_dump") else out


def _dispatch_parse(args, config, session):
    if _dry_run():
        return {"mode": "new_search", "target_endpoint": None}
    from chat_nextseek.agents import parser_agent, entity_agent
    entity_out = entity_agent(config, args.query)
    plan = parser_agent(session, config, args.query, entity_out)
    return plan.model_dump() if hasattr(plan, "model_dump") else plan


def _dispatch_plan(args, config, session):
    """multi_parser + planner advisor. Read-only execution per Rev 2 D2."""
    if _dry_run():
        return {
            "plan": [],
            "executed_read_steps": [],
            "context_engineer_outputs": [],
            "evaluator": None,
            "skipped_steps": [],
            "recommended_next_actions": [],
        }
    from chat_nextseek.agents import (
        entity_agent, multi_parser_agent, planner_agent,
    )
    entity_out = entity_agent(config, args.query)
    multi = multi_parser_agent(session, config, args.query, entity_out)
    plan = planner_agent(session, config, args.query, entity_out, multi)
    return plan.model_dump() if hasattr(plan, "model_dump") else plan


def _dispatch_api_read(args, config, session):
    """Read-only API dispatch. Refuses non-allowlisted (endpoint, method) pairs."""
    if not args.parser_plan:
        _err("VALIDATION", "--parser-plan required", 3)
    if args.confirmed_write:
        _err("VALIDATION",
             "--confirmed-write is not valid on api-read; use api-write", 3)

    if _dry_run():
        return {"endpoint": "/dry-run/", "method": "GET", "response": {}}

    try:
        plan_dict = json.loads(args.parser_plan)
    except json.JSONDecodeError as exc:
        _err("VALIDATION", f"--parser-plan is not valid JSON: {exc}", 3)

    from chat_nextseek.agents import api_agent_build_request
    api_plan = api_agent_build_request(config, plan_dict)
    endpoint = api_plan.endpoint
    method = api_plan.method.upper()

    allowlist = _load_read_safe_endpoints()
    if (endpoint, method) not in allowlist:
        _err("WRITE_BLOCKED",
             f"endpoint {endpoint!r} method {method!r} not in "
             "read_safe_endpoints.json; route via nextseek-api-write if "
             "this is an intentional write",
             5)

    from chat_nextseek import helpers
    result = helpers.tool_nextseek_api_request(
        config,
        endpoint,
        method,
        requestBody=api_plan.requestBody,
        queryParameters=api_plan.queryParameters,
    )
    return {
        "endpoint": endpoint,
        "method": method,
        "api_plan": api_plan.model_dump() if hasattr(api_plan, "model_dump") else api_plan,
        "response": result,
    }


def _dispatch_api_write(args, config, session):
    """Write-class API dispatch. Layer 2: refuses without --confirmed-write."""
    if not args.parser_plan:
        _err("VALIDATION", "--parser-plan required", 3)
    if not args.confirmed_write:
        _err("WRITE_BLOCKED",
             "nextseek-api-write requires --confirmed-write (Layer 2)", 5)

    if _dry_run():
        return {"endpoint": "/dry-run/", "method": "POST", "response": {}}

    try:
        plan_dict = json.loads(args.parser_plan)
    except json.JSONDecodeError as exc:
        _err("VALIDATION", f"--parser-plan is not valid JSON: {exc}", 3)

    from chat_nextseek.agents import api_agent_build_request
    api_plan = api_agent_build_request(config, plan_dict)
    from chat_nextseek import helpers
    result = helpers.tool_nextseek_api_request(
        config,
        api_plan.endpoint,
        api_plan.method,
        requestBody=api_plan.requestBody,
        queryParameters=api_plan.queryParameters,
    )
    return {
        "endpoint": api_plan.endpoint,
        "method": api_plan.method.upper(),
        "api_plan": api_plan.model_dump() if hasattr(api_plan, "model_dump") else api_plan,
        "response": result,
    }


def _dispatch_graph(args, config, session):
    if _dry_run():
        return {"cypher": "", "result": []}
    from chat_nextseek.agents import graph_agent, entity_agent
    entity_out = entity_agent(config, args.query)
    return graph_agent(config, args.query, entity_out)


def _dispatch_report(args, config, session):
    if args.mode not in ("samples", "protocols", "published", "rppr"):
        _err("VALIDATION",
             f"--mode must be samples|protocols|published|rppr, got {args.mode!r}",
             3)
    if not args.project:
        _err("VALIDATION", "--project required", 3)

    if _dry_run():
        return {"summary": "", "saved_files": [], "rows": []}

    from chat_nextseek import helpers
    from chat_nextseek.schemas.chat import ReporterPlan
    summary_mode = "RPPR" if args.mode == "rppr" else args.mode
    rp = ReporterPlan(project=args.project, reporter_mode="summary",
                      summary_mode=summary_mode)
    log_dir = os.environ.get("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")
    result, saved, summary = helpers.run_reporter_summary(config, rp, log_dir)
    return {"summary": summary, "saved_files": saved, "rows": result}


def _dispatch_generate_submission(args, config, session):
    if args.type not in ("GEO", "SRA", "NFCORE_RNASEQ", "NFCORE_SCRNASEQ", "PRIDE"):
        _err("VALIDATION", f"--type unsupported: {args.type!r}", 3)
    if not args.uids:
        _err("VALIDATION", "--uids required (comma-separated)", 3)

    if _dry_run():
        return {"report": "", "type": args.type}

    from chat_nextseek.agents import report_writer_agent
    from chat_nextseek.schemas.chat import ReportWriterPlan
    uids = [u.strip() for u in args.uids.split(",") if u.strip()]
    plan = ReportWriterPlan(report_type=args.type, reporter_context={"uids": uids})
    out = report_writer_agent(config, args.query or "", plan)
    # Match the hasattr-guard pattern used by every other dispatcher; report_writer_agent
    # may return a Pydantic model OR a plain dict depending on the chat_nextseek version
    # (Phase 4 review HIGH-2 — consistency with _dispatch_entity / _dispatch_parse / etc).
    return out.model_dump() if hasattr(out, "model_dump") else out


_DISPATCH = {
    "entity": _dispatch_entity,
    "parse": _dispatch_parse,
    "plan": _dispatch_plan,
    "api-read": _dispatch_api_read,
    "api-write": _dispatch_api_write,
    "graph": _dispatch_graph,
    "report": _dispatch_report,
    "generate-submission": _dispatch_generate_submission,
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True, choices=sorted(_DISPATCH))
    p.add_argument("--query")
    p.add_argument("--parser-plan")  # for api-read / api-write
    p.add_argument("--confirmed-write", action="store_true")
    p.add_argument("--mode")  # for report
    p.add_argument("--project")  # for report
    p.add_argument("--type")  # for generate-submission
    p.add_argument("--uids")  # for generate-submission
    args = p.parse_args()

    if _dry_run():
        config = None
        session = None
    else:
        config = _load_config()
        session = _make_session(config)

    try:
        result = _DISPATCH[args.agent](args, config, session)
    except SystemExit:
        raise
    except Exception as exc:
        _err("AGENT_FAILED",
             f"{type(exc).__name__}: {exc}",
             4)
    sys.stdout.write(json.dumps(result, default=str) + "\n")


if __name__ == "__main__":
    main()
```

## 7. Modified Files (exact diffs)

**None.** B2 only creates new files. No edits to `pyproject.toml`, no edits to `Dockerfile`, no edits to `Makefile`. (B14 / B13 / B16 own those.)

If the executing agent finds itself wanting to edit `pyproject.toml` (e.g. to add a `[tool.coverage.run] source` entry for the new runner), STOP and escalate via `AskUserQuestion`. The plan-locked decision is to use a per-invocation `--cov=<file>` argument in B2.4 to avoid mixing the runner into the repo-wide coverage gate. Modifying `pyproject.toml` is out-of-spec and would change repo-wide coverage semantics.

## 8. Verification

```bash
# Run new tests only — all 17 must pass
uv run pytest tests/unit/test_nextseek_runner.py tests/unit/test_nextseek_runner_dispatch.py -v

# Run new tests with the coverage floor (95% on _nextseek_runner — ultraplan default)
uv run pytest tests/unit/test_nextseek_runner.py tests/unit/test_nextseek_runner_dispatch.py \
  --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
  --cov-fail-under=95 -v

# Run full suite — no regressions; the repo-wide --cov-fail-under=95 (against
# tests.harness + src/dmac_assistant) must continue to pass.
uv run pytest -q

# Shell helper syntax check (no shellcheck required for this minimal sourced file)
sh -n build_context/plugins/nextseek/bin/_nextseek_common.sh

# Linter / type checker — none required for the new code:
#   - _nextseek_runner.py is a script, not a package, and the repo does not
#     run mypy on bin/ scripts.
#   - _nextseek_common.sh is sourced; bats coverage lives in B3-B9.
```

**Expected test count**: **17 new** (1 baseline + 9 dispatcher + 3 amendment-2026-05-01 coverage-bump tests + 4 Phase-4-review-CRITICAL-1+HIGH-1 real-impl tests, incl. malformed-JSON branch added in re-review).
**Expected coverage**: **≥ 95%** on `_nextseek_runner.py`. Repo-wide coverage gate unchanged.

## 9. Implementation Notes

### 9.1 Plan-line citations

- Plan content: `nextseek-plugin-2026-04-27.md` lines 401-1133 (Task B2 block, all sub-steps).
- Mandatory Amendments — runner contract: lines 181-198.
- Read-safe endpoint allowlist contract: lines 199 onward (read_safe_endpoints.json schema).
- File Structure references: lines 126-129.

### 9.2 Import-mechanics nuance for monkeypatch tests

The dispatcher tests in `test_nextseek_runner_dispatch.py` rely on a subtle import ordering:

1. The test fixture loads `_nextseek_runner.py` as a module (`runner`).
2. The test imports `chat_nextseek.agents` and monkeypatches an attribute on it (e.g. `agents_mod.entity_agent`).
3. The test calls `runner._dispatch_entity(...)`.
4. Inside `_dispatch_entity`, the line `from chat_nextseek.agents import entity_agent` runs at call time.
5. Python's import machinery returns the already-imported `chat_nextseek.agents` module, which now has `entity_agent` rebound to the MagicMock. The dispatcher then binds the local name `entity_agent` to the MagicMock and calls it.

This works only because the runner uses **deferred imports** inside dispatchers. If a future refactor hoists `from chat_nextseek.agents import entity_agent` to module-top-level, the local name `entity_agent` in `_dispatch_entity` would point to the original function, not the patched one, and monkeypatch tests would silently break. **Do not refactor imports out of the dispatcher bodies.** Any such refactor must trigger a `/ultraplan amend`.

### 9.3 Gotchas

- **`pytest.importorskip("chat_nextseek")`** at the top of `test_nextseek_runner.py` AND `test_nextseek_runner_dispatch.py` is mandatory and unconditional — not "defensive". chat_nextseek is **never** in `pyproject.toml`'s dependencies by deliberate design (`pyproject.toml` closing comment: `# T7 path-decision: PATH_B image-only — chat_nextseek install deferred to T8 (R4-NEW-5)`). The host can't install it (host Python 3.12 vs chat_nextseek's `requires-python >=3.14`). On host these tests skip; in the built image they would run, but Plan A's chat_nextseek test surface is `tests/test_image_smoke.py::test_chat_nextseek_importable_no_with` (image-side via `docker run`), not host pytest. See plan `## Host vs Image Python Environment` for the authoritative reference.
- **Subprocess test in B2.2** runs `python` (not `uv run python`) and passes `env={"PATH": "/usr/bin:/bin"}`. This is intentional — it isolates the subprocess from the parent's env so `API_USER` truly is unset. If `python` is not on the minimal PATH for the CI runner, fall back to `sys.executable` and add a comment. Do not change the env-stripping behavior.
- **`pytest-cov` source resolution**: pytest-cov accepts a file path OR a dotted module path. Because `build_context/plugins/nextseek/bin/` is not a Python package (no `__init__.py`), the dotted form fails. Use `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py` (file path). The plan's B2.4 (line 1119) acknowledges both forms; the file-path form is the safer default.
- **`SystemExit` propagation**: `main()`'s `try/except` deliberately re-raises `SystemExit` so dispatcher `_err(...)` calls produce the intended exit codes. Do not add `SystemExit` to the broad `except Exception` clause — that would convert every WRITE_BLOCKED into AGENT_FAILED (exit 4 instead of exit 5) and break the api-write Layer-2 contract.
- **`_load_config()` does NOT return on the import failure path** — `_err` calls `sys.exit`, which raises `SystemExit`. Pyright/mypy may complain about the function appearing to return implicitly; add `# type: ignore[return]` if the type checker is invoked, but the repo does not run mypy on this directory.
- **Shell shim shebang**: `#!/bin/sh` is intentional — POSIX sh, not bash. The constructs used (`: "${VAR:=default}"`, `export VAR1 VAR2`, `printf`, `exit`) are all POSIX. Do not switch to `#!/bin/bash` without amending Plan B.
- **`NEXTSEEK_OUTPUTS_DIR` default**: `/data/scratch/${API_USER:-anon}` is the in-container path. On host-side tests, this directory may not exist; tests use `monkeypatch.setenv("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")` to override. The runner must trust the env value, not validate it (validation belongs in Plan A's copier).
- **`build_context/` is gitignored — `git add -f` is mandatory for the build_context paths in Step 7.** `.gitignore` line 13 reads `build_context/`. Plain `git add build_context/...` silently no-ops. The `tests/unit/...` paths in the same step are NOT gitignored and use plain `git add`, kept on a separate `git add` line in Step 7. The single existing tracked file under that tree (`build_context/plugins/nextseek-api/skills/nextseek-api/SKILL.md`) was also force-added historically. Do not amend `.gitignore` to whitelist the subtree — the `-f` flag at commit time is the agreed resolution (see plan `## Amendment Log` entry "build_context git-add -f").

### 9.4 Coverage status — no exception (amended 2026-05-01)

B2's coverage target is the ultraplan default 95% on `_nextseek_runner.py`. The previously-locked 90% target was amended to 95% on 2026-05-01 after recognizing the three "uncoverable" branches (`_load_config` ImportError, `_load_read_safe_endpoints` OSError, `main()` broad-except) are reachable via standard `monkeypatch` and do not qualify as architectural uncoverability. The three additional tests at the end of §5.2 cover those branches. See plan `## Amendment Log` entry for the full record.

The shell shim layer (`_nextseek_common.sh`) is OUT of pytest-cov scope — that's a *scope* statement, not an *exception*. pytest-cov instruments only Python; sourced shell is exercised by bats / subprocess tests in B3-B9.

### 9.5 Self-review checklist (per Phase 3 spec)

- [ ] Tests fail before implementation? **Yes** — Step 1 + Step 2 of §4 RED states confirm both test files error out (file-not-found on RUNNER_PATH) before §6 implementation lands.
- [ ] Tests pass after? **Yes** — all 17 tests pass once `_nextseek_runner.py` and `_nextseek_common.sh` are written per §6.
- [ ] No regressions? **Yes** — the repo-wide `--cov-fail-under=95` against `tests.harness + src/dmac_assistant` is unaffected; B2 adds zero lines to those packages.
- [ ] Coverage meets declared target? **Yes** — 95% on `_nextseek_runner.py`. The 17 tests cover every dispatcher's happy path, api-write WRITE_BLOCKED, all validation paths, dry-run short-circuits, the `IMPORT_FAILED` exit-2 path in `_load_config`, every branch of `_load_read_safe_endpoints` (happy path, missing-file, OSError, JSONDecodeError), the `_dispatch_report` `rppr` → `RPPR` remap, and the `AGENT_FAILED` exit-4 path in `main()`'s broad-except.
- [ ] Exception justified if below 95%? **N/A — no exception (target is the default 95%).**

## 10. Worktree & Branch

- **Branch**: `task/B02-shared-runner` (cut from integration branch `ultraplan/nextseek-plugin-2026-04-27` AFTER B1 merges)
- **Worktree**: `.claude/worktrees/task-B02-shared-runner/` (created via `scripts/init_worktrees.sh nextseek-plugin-2026-04-27 B02-shared-runner`)
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**: All of the following pass in the worktree:
  1. `uv run pytest tests/unit/test_nextseek_runner.py tests/unit/test_nextseek_runner_dispatch.py --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py --cov-fail-under=95 -v` exits 0 with 17 tests passed.
  2. `uv run pytest -q` (full suite) exits 0; repo-wide cov gate at 95% holds.
  3. `sh -n build_context/plugins/nextseek/bin/_nextseek_common.sh` exits 0.
  4. `git log -1 --pretty=format:'%s'` returns `nextseek-plugin: shared runner + cred-translation helper`.
  5. `_nextseek_runner.py` has the executable bit set (`test -x build_context/plugins/nextseek/bin/_nextseek_runner.py`).
- **Wave dependency**: B2 must complete and merge before any of B3-B9 (Wave 3 — 8 shims + reporter dispatcher) can start. They all source `_nextseek_common.sh` and exec `_nextseek_runner.py`.
- **Re-grep gate before Wave 3 dispatch**: Per the compact handoff §"Pre-execution sanity checks" point 2, after B2.5 commits, re-grep `chat_nextseek` agent/helper signatures (the same grep run at onboard time) to confirm no upstream refactoring between 2026-05-01 and the moment B3-B9 dispatch. If any signature has shifted, escalate via `AskUserQuestion` before continuing.

## LOCKED 2026-05-01

This spec is immutable as of 2026-05-01 after Phase 5 user confirmation.

- **Phase 4 verdict (round 1)**: REVISE → all blockers + non-blockers applied (see `.claude/reviews/plan-B-spec-B02-phase4-review-2026-05-01.md`). 2 CRITICAL + 1 HIGH + 2 MEDIUM all closed.
- **Cross-task verdict**: APPROVE-with-micro-fixes — all 4 fixes applied (`git ls-files` presence gate, `mkdir -p bin/`, `sys.executable`, manifest cross-reference).
- **Phase 4 verdict (round 2 — focused re-review)**: APPROVE-with-micro-fixes (residual `json.JSONDecodeError` test added, total 16 → 17 — see `.claude/reviews/plan-B-spec-B02-phase4-rereview-2026-05-01.md`).
- **Coverage**: 95% on `_nextseek_runner.py` (ultraplan default; no exception). 17 tests cover every dispatcher happy path, validation paths, dry-run short-circuits, the L2 WRITE_BLOCKED path, the IMPORT_FAILED / CONFIG_ERROR / AGENT_FAILED error paths, every branch of `_load_read_safe_endpoints` (happy/missing-file/OSError/JSONDecodeError), and the RPPR remap.
- **Amendment in scope**: 2026-05-01 amendment (90% → 95%) fully propagated within B2. B3.3 / B9.3 stale 90% values in plan body are flagged in plan `## Amendment Log` for Wave 3 explosion to handle.
- **Lock effect**: any deviation requires `/ultraplan amend`. Behavioral tests in §5.2 are authoritative over §6 reference implementation.
