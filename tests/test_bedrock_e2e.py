"""Live Bedrock round-trip E2E for the dmac-assistant image."""
from __future__ import annotations

try:
    from build_tools.verify_env import REQUIRED_VARS
except ImportError:
    import pytest

    pytest.skip(
        "T01 not yet merged (build_tools.verify_env missing)",
        allow_module_level=True,
    )

import re
import secrets
import subprocess
from dataclasses import dataclass
from pathlib import Path

import docker
import pytest

_UUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$"
)

pytest.importorskip("xdist", reason="pytest-xdist required for live-serial tests")

from tests.harness.canaries import scan_dir_for_secret
from tests.harness.stream_json import StreamJSONParser, parse_stream


pytestmark = [
    pytest.mark.live,
    pytest.mark.xdist_group("live-serial"),
]

IMAGE = "dmac-assistant:poc"
LIVE_TIMEOUT_SECONDS = 60


def _allow_docker_unix_socket_only() -> None:
    """Keep host networking gated while allowing docker-py's Unix socket."""
    try:
        import pytest_socket
    except ImportError:
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)


@pytest.fixture(scope="module")
def docker_client():
    _allow_docker_unix_socket_only()
    client = docker.from_env()
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"Docker daemon unavailable: {exc}")
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.fail(f"{IMAGE} missing; run `make image-build` first")
    yield client
    client.close()


@pytest.fixture
def claude_dir_tmp(tmp_path: Path) -> Path:
    """Per-test .claude mount dir, also scanned for token leakage."""
    user_id = f"t07-{secrets.token_hex(4)}"
    claude_dir = tmp_path / "claude-users" / user_id / ".claude"
    claude_dir.mkdir(parents=True, exist_ok=True)
    return claude_dir


@pytest.fixture
def container_mounts(tmp_path: Path, claude_dir_tmp: Path) -> dict[str, dict[str, str]]:
    """Compose the canonical DD-10 mount contract for live tests."""
    scratch_dir = tmp_path / "scratch" / claude_dir_tmp.parent.name
    projects_dir = tmp_path / "projects" / "fake"
    for directory in (scratch_dir, projects_dir):
        directory.mkdir(parents=True, exist_ok=True)
    return {
        str(claude_dir_tmp): {"bind": "/home/user/.claude", "mode": "rw"},
        str(scratch_dir): {"bind": "/data/scratch", "mode": "rw"},
        str(projects_dir): {"bind": "/data/projects/fake", "mode": "ro"},
    }


@dataclass
class ClaudeRunResult:
    stdout_bytes: bytes
    stderr_bytes: bytes
    container_logs_bytes: bytes
    exit_code: int


_AUTH_ERROR_MARKERS = (
    "ExpiredTokenException",
    "UnauthorizedException",
    "AccessDenied",
    "Invalid API Key format",
)


def _maybe_skip_on_auth(*blobs: bytes) -> None:
    """Skip (per ADR-004) when output shows a recognized Bedrock auth failure."""
    joined = b"\n".join(b for b in blobs if b).decode("utf-8", errors="replace")
    if any(marker in joined for marker in _AUTH_ERROR_MARKERS):
        pytest.skip(
            "Bedrock auth failure (likely ADR-004 hourly token expiry or "
            f"malformed credential in --env-file): {joined[:500]}"
        )


def _run_claude_print(
    client: "docker.DockerClient",
    env: dict[str, str],
    mounts: dict[str, dict[str, str]],
    prompt: str,
    timeout: int = LIVE_TIMEOUT_SECONDS,
) -> ClaudeRunResult:
    """Run `claude --print` inside the image via `docker run -i`.

    Uses the docker CLI rather than docker-py's `attach_socket` because the
    library's hijacked-socket pattern does not reliably propagate stdin EOF
    for the `claude --print --input-format text` workload: the claude process
    blocks waiting for input that never arrives. ADR-006's docker-py
    convention applies to the production bridge, not to test harnesses.
    """
    del client  # presence of `docker_client` fixture asserts image exists
    cmd: list[str] = ["docker", "run", "--rm", "-i"]
    for key, value in env.items():
        cmd.extend(["-e", f"{key}={value}"])
    for host_path, spec in mounts.items():
        bind = spec["bind"]
        mode = spec.get("mode", "rw")
        cmd.extend(["-v", f"{host_path}:{bind}:{mode}"])
    cmd.extend([
        IMAGE,
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
        _maybe_skip_on_auth(partial_stderr, partial_stdout)
        raise TimeoutError(
            f"claude --print did not exit within {timeout}s; "
            f"stdout={partial_stdout[:500]!r} stderr={partial_stderr[:500]!r}"
        ) from exc

    _maybe_skip_on_auth(completed.stderr, completed.stdout)

    assert completed.returncode == 0, (
        f"claude --print failed: exit={completed.returncode}, "
        f"stderr={completed.stderr.decode('utf-8', errors='replace')[:500]!r}"
    )
    return ClaudeRunResult(
        stdout_bytes=completed.stdout,
        stderr_bytes=completed.stderr,
        container_logs_bytes=completed.stdout + b"\n" + completed.stderr,
        exit_code=completed.returncode,
    )


def test_bedrock_inference_works(
    live_env: dict[str, str],
    live_socket: None,
    docker_client: "docker.DockerClient",
    container_mounts: dict[str, dict[str, str]],
) -> None:
    """Verify a real Bedrock round-trip with a fresh nonce.

    Uses a literal-echo prompt per T07 spec. A prior math-question variant
    with an 8-hex nonce triggered claude-code's tool-use heuristics — the
    hex token pattern-matched as a git short-SHA and Claude went searching
    instead of answering. The echo form is stable and proves "Bedrock was
    actually hit" via both (a) fresh nonce in the response and (b) populated
    usage.input_tokens in the final result event.
    """
    del live_socket
    nonce = secrets.token_hex(6)
    marker = f"BEDROCK-PING-{nonce}"
    prompt = (
        f"Reply with exactly this single line and nothing else: {marker}"
    )

    env = {var: live_env[var] for var in REQUIRED_VARS if var in live_env}
    env["CLAUDE_CODE_USE_BEDROCK"] = "1"

    result = _run_claude_print(
        docker_client,
        env,
        container_mounts,
        prompt,
        timeout=LIVE_TIMEOUT_SECONDS,
    )

    parser = StreamJSONParser()
    for event in parse_stream(result.stdout_bytes, strict=False):
        parser.feed(event)

    assert parser.contains_text(marker), (
        f"Expected {marker!r} in assistant output - cache hit, stub, or "
        f"Claude went off-script; got: {parser.assistant_texts!r}; "
        f"usage: {parser.final_usage!r}"
    )
    if not parser.final_usage:
        pytest.fail(
            "No `usage` field found in result event; "
            f"raw stream head: {result.stdout_bytes[:2000]!r}"
        )
    if parser.final_usage.get("input_tokens", 0) == 0:
        pytest.fail(
            f"usage.input_tokens is zero - Bedrock was not actually hit: "
            f"{parser.final_usage!r}"
        )

    # DD-34 stub-defeat signals: a minimal hand-crafted stub can fake echo +
    # one usage field; faking this combined Bedrock result shape requires
    # knowing the schema of a real response, which is a materially higher
    # bar than the prior (4-line stub) exposure.
    result_event = parser.final_result
    assert result_event is not None, (
        f"Stream has no `result` event - malformed run; "
        f"raw stream head: {result.stdout_bytes[:2000]!r}"
    )
    assert result_event.get("is_error") is False, (
        f"Result event marked as error: {result_event!r}"
    )
    assert result_event.get("stop_reason") == "end_turn", (
        f"Expected stop_reason='end_turn'; got: "
        f"{result_event.get('stop_reason')!r}"
    )
    session_id = result_event.get("session_id", "")
    assert _UUID_RE.match(session_id), (
        f"session_id does not match UUID shape (stub-defeat): {session_id!r}"
    )
    usage_keys = set(parser.final_usage.keys())
    required_usage_keys = {
        "input_tokens",
        "output_tokens",
        "cache_read_input_tokens",
    }
    missing = required_usage_keys - usage_keys
    assert not missing, (
        f"usage missing Bedrock-shape keys (stub-defeat): missing={missing}; "
        f"got keys={sorted(usage_keys)}"
    )


def test_bedrock_token_never_logged(
    live_env: dict[str, str],
    live_socket: None,
    docker_client: "docker.DockerClient",
    container_mounts: dict[str, dict[str, str]],
    claude_dir_tmp: Path,
) -> None:
    """The real bearer token must never appear in streams or .claude files."""
    del live_socket
    token = live_env["AWS_BEARER_TOKEN_BEDROCK"]
    assert token
    assert len(token) >= 20

    env = {var: live_env[var] for var in REQUIRED_VARS if var in live_env}
    env["CLAUDE_CODE_USE_BEDROCK"] = "1"

    result = _run_claude_print(
        docker_client,
        env,
        container_mounts,
        "Say 'hello'.",
        timeout=LIVE_TIMEOUT_SECONDS,
    )
    combined = (
        result.stdout_bytes
        + b"\n"
        + result.stderr_bytes
        + b"\n"
        + result.container_logs_bytes
    )
    token_bytes = token.encode("utf-8")
    assert token_bytes not in combined

    hits = scan_dir_for_secret(claude_dir_tmp, token_bytes)
    assert hits == [], f"Token leaked into .claude/ mount files: {hits!r}"
