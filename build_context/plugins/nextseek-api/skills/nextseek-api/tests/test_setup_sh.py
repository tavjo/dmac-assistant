"""
Subprocess tests for scripts/setup.sh.

Each test builds a fake HOME directory with a fixture ~/.claude/settings.json,
runs setup.sh under that HOME, and asserts the expected behavior (merge, idempotence,
backup, abort-on-no, jq-missing).
"""
from __future__ import annotations

import glob
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest


# skills/nextseek-api/tests/test_setup_sh.py — 4 parents up = plugin root
PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SETUP_SH = PLUGIN_ROOT / "skills" / "nextseek-api" / "scripts" / "setup.sh"

EXPECTED_PATTERNS = [
    "Bash(nextseek-init:*)",
    "Bash(nextseek-spec:*)",
    "Bash(nextseek-validate:*)",
    "Bash(nextseek-exec --method GET*)",
    "Bash(nextseek-exec --endpoint schema_rag/*)",
]


@pytest.fixture
def fake_home(tmp_path: Path) -> Path:
    """Create an isolated HOME with a .claude directory but NO settings.json yet."""
    home = tmp_path / "home"
    (home / ".claude").mkdir(parents=True)
    return home


def _write_settings(fake_home: Path, settings: dict) -> Path:
    """Write a settings.json fixture into fake_home/.claude/."""
    path = fake_home / ".claude" / "settings.json"
    path.write_text(json.dumps(settings, indent=2) + "\n")
    return path


def _run_setup(
    fake_home: Path,
    stdin_input: str = "y\n",
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    """Invoke setup.sh with HOME overridden to fake_home."""
    env = os.environ.copy()
    env["HOME"] = str(fake_home)
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["bash", str(SETUP_SH)],
        input=stdin_input,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _read_allow(fake_home: Path) -> list[str]:
    """Read permissions.allow from the fake HOME's settings.json."""
    data = json.loads((fake_home / ".claude" / "settings.json").read_text())
    return data.get("permissions", {}).get("allow", [])


# ----- Test 1 -----
def test_fresh_settings_gets_all_patterns(fake_home: Path) -> None:
    """Starting from {permissions: {allow: []}}, all 5 patterns are added."""
    _write_settings(fake_home, {"permissions": {"allow": []}})
    result = _run_setup(fake_home, stdin_input="y\n")
    assert result.returncode == 0, f"stderr={result.stderr}"
    allow = _read_allow(fake_home)
    for pattern in EXPECTED_PATTERNS:
        assert pattern in allow, f"Missing pattern: {pattern}\nGot: {allow}"


# ----- Test 2 -----
def test_existing_patterns_preserved(fake_home: Path) -> None:
    """Unrelated existing allow entries remain after merge."""
    _write_settings(
        fake_home,
        {
            "permissions": {
                "allow": [
                    "Bash(npm install:*)",
                    "Bash(git status:*)",
                    "Read(/home/user/**)",
                ]
            }
        },
    )
    result = _run_setup(fake_home, stdin_input="y\n")
    assert result.returncode == 0, f"stderr={result.stderr}"
    allow = _read_allow(fake_home)
    for original in ["Bash(npm install:*)", "Bash(git status:*)", "Read(/home/user/**)"]:
        assert original in allow, f"Original pattern lost: {original}"
    for new in EXPECTED_PATTERNS:
        assert new in allow, f"New pattern not added: {new}"


# ----- Test 3 -----
def test_idempotent_re_run(fake_home: Path) -> None:
    """Running setup.sh twice does not duplicate patterns."""
    _write_settings(fake_home, {"permissions": {"allow": []}})

    result1 = _run_setup(fake_home, stdin_input="y\n")
    assert result1.returncode == 0
    allow_after_first = _read_allow(fake_home)

    result2 = _run_setup(fake_home, stdin_input="y\n")
    assert result2.returncode == 0
    allow_after_second = _read_allow(fake_home)

    assert sorted(allow_after_first) == sorted(allow_after_second), (
        "Second run changed the allow list"
    )
    # No pattern appears more than once
    for pattern in EXPECTED_PATTERNS:
        assert allow_after_second.count(pattern) == 1


# ----- Test 4 -----
def test_backup_created(fake_home: Path) -> None:
    """A .bak.<timestamp> file is created before modification."""
    settings_path = _write_settings(
        fake_home, {"permissions": {"allow": ["Bash(original:*)"]}}
    )
    original_content = settings_path.read_text()

    result = _run_setup(fake_home, stdin_input="y\n")
    assert result.returncode == 0

    backups = sorted(glob.glob(str(fake_home / ".claude" / "settings.json.bak.*")))
    assert len(backups) >= 1, "No backup file created"
    # Backup contains the original, pre-merge content
    assert Path(backups[0]).read_text() == original_content


# ----- Test 5 -----
def test_abort_on_user_no(fake_home: Path) -> None:
    """If the user types 'n', no changes are made to settings.json."""
    original = {"permissions": {"allow": ["Bash(untouched:*)"]}}
    settings_path = _write_settings(fake_home, original)
    original_content = settings_path.read_text()

    result = _run_setup(fake_home, stdin_input="n\n")
    assert result.returncode == 0, f"stderr={result.stderr}"

    # Settings unchanged
    assert settings_path.read_text() == original_content
    # No backup created (nothing was modified)
    backups = glob.glob(str(fake_home / ".claude" / "settings.json.bak.*"))
    assert backups == [], f"Backup created despite user declining: {backups}"
    # Abort message on stdout
    assert "abort" in result.stdout.lower() or "cancel" in result.stdout.lower()


# ----- Test 6 -----
def test_jq_missing_errors_cleanly(fake_home: Path, tmp_path: Path) -> None:
    """If jq is not on PATH, script prints brew instructions and exits 1."""
    _write_settings(fake_home, {"permissions": {"allow": []}})

    # Create a PATH that contains only a stub dir (no jq)
    stub_path_dir = tmp_path / "stubpath"
    stub_path_dir.mkdir()
    # Provide a minimal set of core utils so bash itself still runs
    for util in ["bash", "cp", "mv", "cat", "echo", "date", "mkdir", "rm", "printf"]:
        real = shutil.which(util)
        if real:
            (stub_path_dir / util).symlink_to(real)

    result = _run_setup(
        fake_home,
        stdin_input="y\n",
        extra_env={"PATH": str(stub_path_dir)},
    )
    assert result.returncode == 1, (
        f"Expected exit 1 when jq missing, got {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    combined = (result.stdout + result.stderr).lower()
    assert "jq" in combined
    assert "brew install jq" in combined
