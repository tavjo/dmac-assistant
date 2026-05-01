"""Contract tests for build_tools.drift_report and make image-preflight."""
from __future__ import annotations

import os
import shutil
import stat
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from build_tools import drift_report


REPO_ROOT = Path(__file__).resolve().parents[1]


def _git_init_repo(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "core.autocrlf", "false"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.email", "t@example.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(tmp_path), "config", "user.name", "Tester"],
        check=True,
    )


def _make_fake_uv(bin_dir: Path, ingest_exit_code: int) -> Path:
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / "uv"
    script.write_text(
        textwrap.dedent(
            f"""\
            #!/bin/sh
            # Strip leading `run [--project <dir>]` to find the python invocation.
            if [ "$1" = "run" ]; then
              shift
              while [ "$1" = "--project" ] || [ "$1" = "--directory" ]; do
                shift; shift
              done
              if [ "$1" = "python" ] && [ "$2" = "-m" ] && [ "$3" = "build_tools.ingest_nextseek_docs" ]; then
                exit {ingest_exit_code}
              fi
              if [ "$1" = "python" ]; then
                # Re-exec the real python with the rest of the args (e.g. -c '...').
                exec "$@"
              fi
            fi
            echo "fake uv received unexpected args: $*" >&2
            exit 99
            """
        ),
        encoding="utf-8",
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return script


def _run_preflight(cwd: Path, ingest_exit_code: int, extra_env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    fake_bin = cwd / ".fake-bin"
    _make_fake_uv(fake_bin, ingest_exit_code)
    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}:{env.get('PATH', '')}"
    env["PYTHONPATH"] = f"{REPO_ROOT}:{env.get('PYTHONPATH', '')}"
    if extra_env:
        env.update(extra_env)
    return subprocess.run(
        ["make", "image-preflight"],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_format_drift_summary_returns_stat_output(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    (tmp_path / "container").mkdir()
    claude_md = tmp_path / "container" / "CLAUDE.md"
    claude_md.write_text("original\n", encoding="utf-8")
    (tmp_path / "docs" / "nextseek").mkdir(parents=True)
    (tmp_path / "docs" / "nextseek" / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "baseline"], check=True)
    claude_md.write_text("original\nchanged\n", encoding="utf-8")

    summary = drift_report.format_drift_summary(tmp_path)

    assert summary.strip()
    assert "container/CLAUDE.md" in summary
    assert "1 file changed" in summary


def test_format_drift_summary_returns_empty_string_when_clean(tmp_path: Path) -> None:
    _git_init_repo(tmp_path)
    (tmp_path / "container").mkdir()
    (tmp_path / "container" / "CLAUDE.md").write_text("stable\n", encoding="utf-8")
    (tmp_path / "docs" / "nextseek").mkdir(parents=True)
    (tmp_path / "docs" / "nextseek" / "README.md").write_text("stable\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "baseline"], check=True)

    assert drift_report.format_drift_summary(tmp_path).strip() == ""


def test_format_drift_summary_returns_benign_marker_when_git_unavailable(tmp_path: Path) -> None:
    assert "(git diff unavailable" in drift_report.format_drift_summary(tmp_path)


def test_format_drift_summary_handles_nonzero_git_exit(tmp_path: Path) -> None:
    class _FakeResult:
        returncode = 128
        stdout = ""
        stderr = "fatal: not a git repository"

    with patch("build_tools.drift_report.subprocess.run", return_value=_FakeResult()):
        summary = drift_report.format_drift_summary(tmp_path)

    assert "(git diff unavailable" in summary


def test_format_drift_summary_handles_missing_git_binary(monkeypatch: pytest.MonkeyPatch) -> None:
    def _raise(*args, **kwargs):
        raise FileNotFoundError("git not found")

    monkeypatch.setattr("build_tools.drift_report.subprocess.run", _raise)

    summary = drift_report.format_drift_summary(Path("/tmp"))

    assert "(git diff unavailable" in summary


@pytest.mark.skipif(shutil.which("make") is None, reason="make not on PATH")
def test_preflight_target_exit_0_is_silent_and_returns_0(tmp_path: Path) -> None:
    shutil.copy(REPO_ROOT / "Makefile", tmp_path / "Makefile")
    result = _run_preflight(tmp_path, ingest_exit_code=0)

    assert result.returncode == 0
    assert result.stderr.strip() == ""


@pytest.mark.skipif(shutil.which("make") is None, reason="make not on PATH")
def test_preflight_target_emits_warning_on_exit_2(tmp_path: Path) -> None:
    shutil.copy(REPO_ROOT / "Makefile", tmp_path / "Makefile")
    _git_init_repo(tmp_path)
    (tmp_path / "container").mkdir()
    claude_md = tmp_path / "container" / "CLAUDE.md"
    claude_md.write_text("baseline\n", encoding="utf-8")
    (tmp_path / "docs" / "nextseek").mkdir(parents=True)
    (tmp_path / "docs" / "nextseek" / "README.md").write_text("baseline\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "-A"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "commit", "-qm", "baseline"], check=True)
    claude_md.write_text("baseline\nchanged\n", encoding="utf-8")

    result = _run_preflight(tmp_path, ingest_exit_code=2)

    assert result.returncode == 0
    assert "DRIFT DETECTED" in result.stderr
    assert "container/CLAUDE.md" in result.stderr
    assert "1 file changed" in result.stderr


@pytest.mark.skipif(shutil.which("make") is None, reason="make not on PATH")
def test_preflight_target_warn_only_on_unexpected_exit_code(tmp_path: Path) -> None:
    shutil.copy(REPO_ROOT / "Makefile", tmp_path / "Makefile")
    result = _run_preflight(tmp_path, ingest_exit_code=1)

    assert result.returncode == 0
    assert "unexpected code" in result.stderr.lower()
