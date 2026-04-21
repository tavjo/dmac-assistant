"""Shared live-runner helpers for T07/T08/T09 live E2E tests (M-2 refactor).

Extracts the previously-duplicated ``_run_claude_print``,
``_maybe_skip_on_auth``, ``_AUTH_ERROR_MARKERS``, ``ClaudeRunResult``, and
``_allow_docker_unix_socket_only`` blocks from ``tests/test_bedrock_e2e.py``
and ``tests/test_plugin_e2e.py`` into a single module. Behavior is preserved
exactly; callers that previously asserted ``returncode == 0`` inside the
helper now assert on the returned ``ClaudeRunResult.exit_code`` at the
callsite (T07 happy path), which matches T08's pre-existing permissive
pattern for probing expected failures.

DD-31: ``--verbose`` is required alongside ``--output-format stream-json``
in claude-code 2.1.92.

DD-33: uses ``subprocess.run(["docker", "run", "-i", ...])`` rather than
docker-py's ``attach_socket`` because the library's hijacked-socket pattern
does not reliably propagate stdin EOF for ``claude --print --input-format
text``. ADR-006's docker-py convention applies to the production bridge,
not test harnesses.
"""
from __future__ import annotations

import subprocess
from dataclasses import dataclass

import pytest

AUTH_ERROR_MARKERS: tuple[str, ...] = (
    "ExpiredTokenException",
    "UnauthorizedException",
    "AccessDenied",
    "Invalid API Key format",
)

DEFAULT_IMAGE = "dmac-assistant:poc"


@dataclass
class ClaudeRunResult:
    stdout_bytes: bytes
    stderr_bytes: bytes
    container_logs_bytes: bytes
    exit_code: int


def allow_docker_unix_socket_only() -> None:
    """Keep host networking gated while allowing docker-py's Unix socket."""
    try:
        import pytest_socket
    except ImportError:
        return
    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)


def maybe_skip_on_auth(*blobs: bytes) -> None:
    """Skip (per ADR-004) when output shows a recognized Bedrock auth failure."""
    joined = b"\n".join(b for b in blobs if b).decode("utf-8", errors="replace")
    if any(marker in joined for marker in AUTH_ERROR_MARKERS):
        pytest.skip(
            "Bedrock auth failure (likely ADR-004 hourly token expiry or "
            f"malformed credential in --env-file): {joined[:500]}"
        )


def run_claude_print(
    env: dict[str, str],
    mounts: dict[str, dict[str, str]],
    prompt: str,
    *,
    timeout: int,
    image: str = DEFAULT_IMAGE,
    extra_env: dict[str, str] | None = None,
) -> ClaudeRunResult:
    """Run ``claude --print`` inside the image via ``docker run -i``.

    ``extra_env`` is merged over ``env`` (e.g., ``USE_DEV_API=1`` for T08
    DD-21 layer 2). Does NOT assert exit_code — callers that require success
    should assert on the returned ``ClaudeRunResult.exit_code``; callers
    probing expected failures (unauth-negative) read the code directly.

    On timeout, scans partial output for auth markers and ``pytest.skip``s
    if present; otherwise re-raises as ``TimeoutError`` with truncated
    stdout/stderr for diagnosis.
    """
    effective_env = dict(env)
    if extra_env:
        effective_env.update(extra_env)

    cmd: list[str] = ["docker", "run", "--rm", "-i"]
    for key, value in effective_env.items():
        cmd.extend(["-e", f"{key}={value}"])
    for host_path, spec in mounts.items():
        bind = spec["bind"]
        mode = spec.get("mode", "rw")
        cmd.extend(["-v", f"{host_path}:{bind}:{mode}"])
    cmd.extend([
        image,
        "claude",
        "--print",
        "--output-format",
        "stream-json",
        "--input-format",
        "text",
        "--verbose",
        "--dangerously-skip-permissions",
    ])

    try:
        completed = subprocess.run(
            cmd,
            input=prompt.encode("utf-8") + b"\n",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        partial_stdout = exc.stdout or b""
        partial_stderr = exc.stderr or b""
        maybe_skip_on_auth(partial_stderr, partial_stdout)
        raise TimeoutError(
            f"claude --print did not exit within {timeout}s; "
            f"stdout={partial_stdout[:500]!r} stderr={partial_stderr[:500]!r}"
        ) from exc

    maybe_skip_on_auth(completed.stderr, completed.stdout)

    return ClaudeRunResult(
        stdout_bytes=completed.stdout,
        stderr_bytes=completed.stderr,
        container_logs_bytes=completed.stdout + b"\n" + completed.stderr,
        exit_code=completed.returncode,
    )
