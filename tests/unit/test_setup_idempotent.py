"""Plan B · T12 — Layer-1 permission allowlist installer.

Tests cover:
  - Plan body line 2013-2040 baseline: idempotency + existing-entry preservation.
  - CRITICAL-3 boundary: nextseek-api-write MUST NOT appear in produced allowlist.
  - CRITICAL-4 boundary: --confirmed-write MUST NOT appear in produced allowlist.
  - Coverage of all 10 plan-body allowlist strings (9 logical groups).
  - Missing-settings.json bootstrap (script creates it from scratch).
  - File mode preservation (0755).

The test invokes setup.sh via subprocess and inspects the JSON it produces.
No chat_nextseek import; no importorskip needed.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SETUP = (
    REPO_ROOT
    / "build_context" / "plugins" / "nextseek"
    / "scripts" / "setup.sh"
).resolve()

# The 10 individual nextseek-* allowlist strings that setup.sh must install.
# Sourced verbatim from plan body line 1989-2000. Distinct shim names = 7
# (entity-extract, parse, plan, api-read, graph, report, generate-submission);
# `nextseek-report` contributes 4 strings (one per --mode value: samples,
# protocols, published, rppr) while the other 6 shims contribute 1 each,
# giving 6 + 4 = 10 individual strings. Test asserts each individual string
# is present below; do NOT consolidate the 4 report-mode entries into one
# wildcard — the explicit per-mode entries are part of the plan-body L1
# contract and gate exactly the four reporter sub-modes.
EXPECTED_ALLOW_ENTRIES = (
    "Bash(nextseek-entity-extract:*)",
    "Bash(nextseek-parse:*)",
    "Bash(nextseek-plan:*)",
    "Bash(nextseek-api-read --parser-plan*)",
    "Bash(nextseek-graph:*)",
    "Bash(nextseek-report --mode samples*)",
    "Bash(nextseek-report --mode protocols*)",
    "Bash(nextseek-report --mode published*)",
    "Bash(nextseek-report --mode rppr*)",
    "Bash(nextseek-generate-submission --type*)",
)


def _has_jq() -> bool:
    return shutil.which("jq") is not None


def _run_setup(env: dict, *, expect_returncode: int = 0):
    r = subprocess.run(
        ["sh", str(SETUP)], capture_output=True, text=True, env=env
    )
    assert r.returncode == expect_returncode, (
        f"setup.sh exit={r.returncode} stderr={r.stderr!r} stdout={r.stdout!r}"
    )
    return r


def _make_env(tmp_path: Path, settings_path: Path) -> dict:
    return {**os.environ, "SETTINGS_FILE": str(settings_path), "HOME": str(tmp_path)}


@pytest.fixture(autouse=True)
def _require_jq():
    if not _has_jq():
        pytest.skip(
            "jq is required for setup.sh; install jq on the host or run these "
            "tests inside the image (Dockerfile line 9 installs jq)"
        )


def test_setup_idempotent_preserves_existing_and_dedupes(tmp_path):
    """Plan body line 2021-2040 baseline: existing entry preserved across runs;
    no duplicates after second run; new nextseek entry present."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "permissions": {"allow": ["Bash(echo:*)"]}
    }))
    env = _make_env(tmp_path, settings)
    for _ in range(2):
        _run_setup(env)
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]
    # Existing entry preserved.
    assert "Bash(echo:*)" in allow
    # No duplicates after second run.
    assert len(allow) == len(set(allow)), f"duplicates present: {allow}"
    # New nextseek entries present (at least entity-extract).
    assert any("nextseek-entity-extract" in a for a in allow)


def test_setup_creates_settings_file_if_missing(tmp_path):
    """If settings.json does not exist, setup.sh creates it from {}."""
    settings = tmp_path / "settings.json"
    assert not settings.exists()
    env = _make_env(tmp_path, settings)
    _run_setup(env)
    assert settings.exists()
    data = json.loads(settings.read_text())
    assert "permissions" in data
    assert "allow" in data["permissions"]
    assert isinstance(data["permissions"]["allow"], list)
    assert len(data["permissions"]["allow"]) >= len(EXPECTED_ALLOW_ENTRIES)


def test_setup_installs_all_expected_entries(tmp_path):
    """Every plan-body line 1989-2000 entry must be present after a run.

    There are 10 individual allowlist strings (see EXPECTED_ALLOW_ENTRIES
    docstring above). Earlier drafts of this spec used the test name
    `test_setup_installs_all_nine_expected_entries` matching the plan-body
    "9 patterns" prose framing; the count was clarified to 10 individual
    strings during Phase 4 review (2026-05-03)."""
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    env = _make_env(tmp_path, settings)
    _run_setup(env)
    allow = set(json.loads(settings.read_text())["permissions"]["allow"])
    missing = [e for e in EXPECTED_ALLOW_ENTRIES if e not in allow]
    assert not missing, f"missing allowlist entries: {missing}"


def test_critical_3_api_write_excluded(tmp_path):
    """CRITICAL-3 boundary (load-bearing). The produced allowlist MUST NOT
    contain any pattern that can match nextseek-api-write. If this test fails,
    the L1 boundary is broken — an LLM could invoke nextseek-api-write
    without a permission prompt and bypass L2 if the runner gate is ever
    weakened."""
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    env = _make_env(tmp_path, settings)
    _run_setup(env)
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    offenders = [a for a in allow if "nextseek-api-write" in a]
    assert not offenders, (
        f"CRITICAL-3 BOUNDARY BREACH: setup.sh produced allowlist entries "
        f"matching nextseek-api-write: {offenders}. Layer 1 must not include "
        f"any pattern that can match nextseek-api-write (plan body line 619). "
        f"The api-write shim is gated by L2 (runner --confirmed-write check) "
        f"and L3 (SKILL.md plain-text prompt) only — L1 must refuse it."
    )


def test_critical_4_confirmed_write_excluded(tmp_path):
    """CRITICAL-4 boundary (load-bearing). The produced allowlist MUST NOT
    contain any pattern containing --confirmed-write. If this test fails, an
    LLM could pre-bake --confirmed-write into a Bash invocation and bypass L2
    via L1."""
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    env = _make_env(tmp_path, settings)
    _run_setup(env)
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    offenders = [a for a in allow if "--confirmed-write" in a]
    assert not offenders, (
        f"CRITICAL-4 BOUNDARY BREACH: setup.sh produced allowlist entries "
        f"containing --confirmed-write: {offenders}. Layer 1 must not include "
        f"any command containing --confirmed-write (plan body line 619)."
    )


def test_setup_preserves_unrelated_existing_permission_keys(tmp_path):
    """If settings.json has non-allow keys (e.g., 'env', 'hooks', 'deny'),
    setup.sh must preserve them. The plan-body jq filter only mutates
    .permissions.allow; this test asserts that surface is correctly bounded."""
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "permissions": {
            "allow": ["Bash(ls:*)"],
            "deny": ["Bash(rm:*)"],
        },
        "env": {"FOO": "bar"},
    }))
    env = _make_env(tmp_path, settings)
    _run_setup(env)
    data = json.loads(settings.read_text())
    assert data["env"] == {"FOO": "bar"}, "top-level env must be preserved"
    assert "deny" in data["permissions"]
    assert "Bash(rm:*)" in data["permissions"]["deny"], (
        "permissions.deny entries must be preserved"
    )


def test_setup_first_run_returncode_zero_on_empty_settings(tmp_path):
    """A first run on {} settings must succeed cleanly (no jq error, exit 0)."""
    settings = tmp_path / "settings.json"
    settings.write_text("{}")
    env = _make_env(tmp_path, settings)
    r = _run_setup(env)
    assert "nextseek allowlist installed at" in r.stdout, (
        f"expected confirmation message in stdout; got {r.stdout!r}"
    )


def test_setup_script_is_executable():
    """0755 mode preserved. Mirrors the Wave-3 shim test convention."""
    assert SETUP.exists(), f"setup.sh missing at {SETUP}"
    mode = SETUP.stat().st_mode
    assert mode & stat.S_IXUSR, "setup.sh must be executable by owner"
    assert mode & stat.S_IXGRP, "setup.sh must be executable by group"
    assert mode & stat.S_IXOTH, "setup.sh must be executable by other"


def test_setup_handles_nested_missing_dir(tmp_path):
    """If $HOME/.claude does not exist, setup.sh creates it (mkdir -p).
    The default SETTINGS path is $HOME/.claude/settings.json."""
    nested_home = tmp_path / "fakehome"
    nested_home.mkdir()
    # Leave SETTINGS_FILE unset so setup.sh uses $HOME/.claude/settings.json.
    env = {k: v for k, v in os.environ.items() if k != "SETTINGS_FILE"}
    env["HOME"] = str(nested_home)
    r = subprocess.run(
        ["sh", str(SETUP)], capture_output=True, text=True, env=env
    )
    assert r.returncode == 0, (
        f"setup.sh failed on nested-missing-dir: stderr={r.stderr!r}"
    )
    settings = nested_home / ".claude" / "settings.json"
    assert settings.exists(), "setup.sh must create $HOME/.claude/settings.json"
    data = json.loads(settings.read_text())
    assert any("nextseek-entity-extract" in a for a in data["permissions"]["allow"])
