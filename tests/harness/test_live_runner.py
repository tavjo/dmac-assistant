"""Unit tests for the shared live-runner harness (M-2 refactor)."""
from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from tests.harness.live_runner import (
    AUTH_ERROR_MARKERS,
    DEFAULT_IMAGE,
    ClaudeRunResult,
    allow_docker_unix_socket_only,
    maybe_skip_on_auth,
    run_claude_print,
)


# ---------- maybe_skip_on_auth ----------

def test_maybe_skip_on_auth_skips_on_expired_token() -> None:
    with pytest.raises(pytest.skip.Exception):
        maybe_skip_on_auth(b"ExpiredTokenException: token expired")


def test_maybe_skip_on_auth_skips_on_unauthorized() -> None:
    with pytest.raises(pytest.skip.Exception):
        maybe_skip_on_auth(b"UnauthorizedException")


def test_maybe_skip_on_auth_skips_on_access_denied() -> None:
    with pytest.raises(pytest.skip.Exception):
        maybe_skip_on_auth(b"AccessDenied")


def test_maybe_skip_on_auth_skips_on_invalid_key_format() -> None:
    with pytest.raises(pytest.skip.Exception):
        maybe_skip_on_auth(b'{"Message":"Invalid API Key format: Must start with pre-defined prefix"}')


def test_maybe_skip_on_auth_silent_when_no_marker() -> None:
    maybe_skip_on_auth(b"normal stream-json output", b"stderr noise")


def test_maybe_skip_on_auth_silent_on_empty() -> None:
    maybe_skip_on_auth()
    maybe_skip_on_auth(b"")
    maybe_skip_on_auth(b"", b"")


def test_maybe_skip_on_auth_skips_when_marker_in_second_blob() -> None:
    with pytest.raises(pytest.skip.Exception):
        maybe_skip_on_auth(b"clean stdout", b"AccessDenied on stderr")


def test_maybe_skip_on_auth_handles_invalid_utf8() -> None:
    maybe_skip_on_auth(b"\xff\xfe invalid utf-8 but no marker")


def test_auth_error_markers_are_tuple_of_strings() -> None:
    assert isinstance(AUTH_ERROR_MARKERS, tuple)
    assert len(AUTH_ERROR_MARKERS) >= 4
    assert all(isinstance(m, str) for m in AUTH_ERROR_MARKERS)


# ---------- allow_docker_unix_socket_only ----------

def test_allow_docker_unix_socket_only_calls_pytest_socket() -> None:
    with patch("pytest_socket.enable_socket") as enable, \
         patch("pytest_socket.disable_socket") as disable:
        allow_docker_unix_socket_only()
    enable.assert_called_once_with()
    disable.assert_called_once_with(allow_unix_socket=True)


def test_allow_docker_unix_socket_only_silent_if_lib_missing() -> None:
    import builtins

    real_import = builtins.__import__

    def fake_import(name: str, *args, **kwargs):
        if name == "pytest_socket":
            raise ImportError("fake: pytest_socket missing")
        return real_import(name, *args, **kwargs)

    with patch.object(builtins, "__import__", side_effect=fake_import):
        allow_docker_unix_socket_only()


# ---------- run_claude_print ----------

def _ok_completed(stdout: bytes = b"OK\n", stderr: bytes = b"") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(
        args=["docker"], returncode=0, stdout=stdout, stderr=stderr,
    )


def test_run_claude_print_builds_expected_cmd_and_returns_result() -> None:
    captured: dict = {}

    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        captured["cmd"] = cmd
        captured["input"] = input
        captured["timeout"] = timeout
        return _ok_completed(stdout=b'{"type":"result"}\n', stderr=b"")

    # OI-3 (T4): the de-credentialed agent launch no longer carries the bearer
    # token — it reaches Bedrock through the proxy sidecar. This harness only
    # forwards whatever env pairs it is given as `-e KEY=VALUE`; exercise that
    # pass-through with the two env vars the agent DOES still receive.
    env = {"AWS_REGION": "us-east-1", "ANTHROPIC_BEDROCK_BASE_URL": "http://bedrock-proxy:8080"}
    mounts = {
        "/tmp/fake-claude": {"bind": "/home/user/.claude", "mode": "rw"},
        "/tmp/fake-scratch": {"bind": "/data/scratch", "mode": "rw"},
    }

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        result = run_claude_print(env, mounts, "hi", timeout=60)

    assert isinstance(result, ClaudeRunResult)
    assert result.exit_code == 0
    assert result.stdout_bytes == b'{"type":"result"}\n'
    assert result.container_logs_bytes == b'{"type":"result"}\n' + b"\n" + b""
    cmd = captured["cmd"]
    assert cmd[:4] == ["docker", "run", "--rm", "-i"]
    assert "-e" in cmd and f"AWS_REGION=us-east-1" in cmd
    assert "-e" in cmd and "ANTHROPIC_BEDROCK_BASE_URL=http://bedrock-proxy:8080" in cmd
    # OI-3 (T4): no bearer token in the de-credentialed launch cmd.
    assert not any("AWS_BEARER_TOKEN_BEDROCK" in part for part in cmd)
    assert "-v" in cmd and "/tmp/fake-claude:/home/user/.claude:rw" in cmd
    assert "-v" in cmd and "/tmp/fake-scratch:/data/scratch:rw" in cmd
    assert DEFAULT_IMAGE in cmd
    assert cmd[-8:] == [
        "claude", "--print", "--output-format", "stream-json",
        "--input-format", "text", "--verbose", "--dangerously-skip-permissions",
    ]
    assert captured["input"] == b"hi\n"
    assert captured["timeout"] == 60


def test_run_claude_print_uses_default_ro_when_mode_missing() -> None:
    captured: dict = {}

    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        captured["cmd"] = cmd
        return _ok_completed()

    mounts = {"/tmp/projects": {"bind": "/data/projects/fake"}}

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        run_claude_print({}, mounts, "prompt", timeout=30)

    assert "/tmp/projects:/data/projects/fake:rw" in captured["cmd"]


def test_run_claude_print_honors_ro_mount_mode() -> None:
    captured: dict = {}

    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        captured["cmd"] = cmd
        return _ok_completed()

    mounts = {"/tmp/projects": {"bind": "/data/projects/fake", "mode": "ro"}}

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        run_claude_print({}, mounts, "prompt", timeout=30)

    assert "/tmp/projects:/data/projects/fake:ro" in captured["cmd"]


def test_run_claude_print_merges_extra_env_over_env() -> None:
    captured: dict = {}

    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        captured["cmd"] = cmd
        return _ok_completed()

    env = {"A": "1", "B": "2"}
    extra = {"B": "override", "C": "3"}

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        run_claude_print(env, {}, "prompt", timeout=10, extra_env=extra)

    cmd = captured["cmd"]
    assert "A=1" in cmd
    assert "B=override" in cmd
    assert "B=2" not in cmd
    assert "C=3" in cmd


def test_run_claude_print_extra_env_none_leaves_env_unchanged() -> None:
    captured: dict = {}

    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        captured["cmd"] = cmd
        return _ok_completed()

    env = {"A": "1"}

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        run_claude_print(env, {}, "p", timeout=10)

    assert "A=1" in captured["cmd"]


def test_run_claude_print_uses_custom_image() -> None:
    captured: dict = {}

    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        captured["cmd"] = cmd
        return _ok_completed()

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        run_claude_print({}, {}, "p", timeout=10, image="other:tag")

    assert "other:tag" in captured["cmd"]
    assert DEFAULT_IMAGE not in captured["cmd"]


def test_run_claude_print_propagates_nonzero_exit_code() -> None:
    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        return subprocess.CompletedProcess(
            args=cmd, returncode=42, stdout=b"", stderr=b"plugin error",
        )

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        result = run_claude_print({}, {}, "p", timeout=10)

    assert result.exit_code == 42
    assert result.stderr_bytes == b"plugin error"


def test_run_claude_print_skips_on_timeout_with_auth_marker_in_partial() -> None:
    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        raise subprocess.TimeoutExpired(
            cmd=cmd, timeout=timeout, output=b"AccessDenied partial", stderr=b""
        )

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        with pytest.raises(pytest.skip.Exception):
            run_claude_print({}, {}, "p", timeout=5)


def test_run_claude_print_raises_timeout_when_no_auth_marker() -> None:
    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        raise subprocess.TimeoutExpired(
            cmd=cmd, timeout=timeout, output=b"no markers here", stderr=b"also clean"
        )

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        with pytest.raises(TimeoutError, match="did not exit within 5s"):
            run_claude_print({}, {}, "p", timeout=5)


def test_run_claude_print_timeout_with_none_partials() -> None:
    """exc.stdout/exc.stderr can be None if nothing was captured."""
    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        raise subprocess.TimeoutExpired(cmd=cmd, timeout=timeout)

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        with pytest.raises(TimeoutError):
            run_claude_print({}, {}, "p", timeout=5)


def test_run_claude_print_skips_on_auth_marker_in_completed_stderr() -> None:
    def fake_run(cmd, *, input=None, capture_output, timeout, check):
        return subprocess.CompletedProcess(
            args=cmd, returncode=1, stdout=b"", stderr=b"ExpiredTokenException"
        )

    with patch("tests.harness.live_runner.subprocess.run", side_effect=fake_run):
        with pytest.raises(pytest.skip.Exception):
            run_claude_print({}, {}, "p", timeout=10)
