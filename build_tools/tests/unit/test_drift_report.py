"""Unit tests for build_tools.drift_report."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from build_tools import drift_report


def test_format_drift_summary_returns_stdout_when_git_succeeds(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
        captured["cmd"] = cmd
        captured["capture_output"] = capture_output
        captured["text"] = text
        captured["check"] = check
        return subprocess.CompletedProcess(cmd, returncode=0, stdout=" 1 file changed\n", stderr="")

    monkeypatch.setattr(drift_report.subprocess, "run", fake_run)
    out = drift_report.format_drift_summary(tmp_path)
    assert out == " 1 file changed\n"
    assert captured["cmd"][0] == "git"
    assert "-C" in captured["cmd"]
    assert str(tmp_path) in captured["cmd"]
    assert "diff" in captured["cmd"]
    assert "--stat" in captured["cmd"]
    assert "container/CLAUDE.md" in captured["cmd"]
    assert "docs/nextseek/" in captured["cmd"]
    assert captured["capture_output"] is True
    assert captured["text"] is True
    assert captured["check"] is False


def test_format_drift_summary_returns_unavailable_when_git_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*a, **kw):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("git not found")

    monkeypatch.setattr(drift_report.subprocess, "run", boom)
    assert drift_report.format_drift_summary(tmp_path) == drift_report._UNAVAILABLE


def test_format_drift_summary_returns_unavailable_on_oserror(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def boom(*a, **kw):  # type: ignore[no-untyped-def]
        raise OSError("permission denied")

    monkeypatch.setattr(drift_report.subprocess, "run", boom)
    assert drift_report.format_drift_summary(tmp_path) == drift_report._UNAVAILABLE


def test_format_drift_summary_returns_unavailable_on_nonzero_rc(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    def fake_run(cmd, capture_output, text, check):  # type: ignore[no-untyped-def]
        return subprocess.CompletedProcess(cmd, returncode=128, stdout="", stderr="not a git repo")

    monkeypatch.setattr(drift_report.subprocess, "run", fake_run)
    assert drift_report.format_drift_summary(tmp_path) == drift_report._UNAVAILABLE
