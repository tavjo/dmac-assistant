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

import secrets
import time
from dataclasses import dataclass
from pathlib import Path

import docker
import pytest

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


def _run_claude_print(
    client: "docker.DockerClient",
    env: dict[str, str],
    mounts: dict[str, dict[str, str]],
    prompt: str,
    timeout: int = LIVE_TIMEOUT_SECONDS,
) -> ClaudeRunResult:
    """Start a Claude container, stream stdin in, and collect all outputs."""
    _allow_docker_unix_socket_only()
    container = client.containers.create(
        IMAGE,
        command=[
            "claude",
            "--print",
            "--output-format",
            "stream-json",
            "--input-format",
            "text",
            "--verbose",
            "--dangerously-skip-permissions",
        ],
        environment=env,
        volumes=mounts,
        stdin_open=True,
        tty=False,
        detach=True,
    )
    try:
        container.start()
        sock = client.api.attach_socket(
            container.id,
            params={"stdin": 1, "stream": 1},
        )
        sock._sock.sendall(prompt.encode("utf-8") + b"\n")
        sock._sock.shutdown(1)
        sock.close()

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            container.reload()
            if container.status == "exited":
                break
            time.sleep(0.5)
        else:
            partial_logs = container.logs(stdout=True, stderr=True)
            container.kill()
            partial_text = partial_logs.decode("utf-8", errors="replace")
            auth_markers = [
                "ExpiredTokenException",
                "UnauthorizedException",
                "403",
                "AccessDenied",
            ]
            if any(marker in partial_text for marker in auth_markers):
                pytest.skip(
                    "Bedrock auth failure (likely ADR-004 hourly token expiry): "
                    f"{partial_text[:500]}"
                )
            raise TimeoutError(
                f"Claude Code did not exit within {timeout}s; "
                f"partial logs={partial_text[:1000]!r}"
            )

        stdout_bytes = container.logs(stdout=True, stderr=False)
        stderr_bytes = container.logs(stdout=False, stderr=True)
        container_logs_bytes = container.logs(stdout=True, stderr=True)
        exit_code = container.wait(timeout=5)["StatusCode"]
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass

    stderr_text = stderr_bytes.decode("utf-8", errors="replace")
    auth_markers = [
        "ExpiredTokenException",
        "UnauthorizedException",
        "403",
        "AccessDenied",
    ]
    if any(marker in stderr_text for marker in auth_markers):
        pytest.skip(
            "Bedrock auth failure (likely ADR-004 hourly token expiry): "
            f"{stderr_text[:500]}"
        )

    assert exit_code == 0, (
        f"claude --print failed: exit={exit_code}, stderr={stderr_text!r}"
    )
    return ClaudeRunResult(
        stdout_bytes=stdout_bytes,
        stderr_bytes=stderr_bytes,
        container_logs_bytes=container_logs_bytes,
        exit_code=exit_code,
    )


def test_bedrock_inference_works(
    live_env: dict[str, str],
    live_socket: None,
    docker_client: "docker.DockerClient",
    container_mounts: dict[str, dict[str, str]],
) -> None:
    """Verify a real Bedrock round-trip with fresh nonce and reasoning output."""
    del live_socket
    nonce = secrets.token_hex(4)
    prompt = f"In {nonce}, what is 17+28? Reply with just the number and nothing else."

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

    assert parser.contains_text("45"), (
        f"Expected '45' in assistant output; "
        f"got: {parser.assistant_texts!r}; usage: {parser.final_usage!r}"
    )
    assert parser.contains_text(nonce), (
        "Nonce missing from assistant output - cache hit or stub response"
    )
    if not parser.final_usage:
        pytest.fail(
            "No `usage` field found in result event; "
            f"raw stream head: {result.stdout_bytes[:2000]!r}"
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
