"""T09 — cross-cutting secret-leak canary suite.

Exercises every surface of the dmac-assistant:poc image that handles
credentials with fresh, randomly-generated sentinel values. Confirms
those sentinels never appear in stdout, stderr, container logs, or any
file written under the mounted scratch/.claude/ trees. A negative
control deliberately plants a sentinel and asserts the scanner flags
it — proving the detector works.

Per DD-27 the scanner also runs over `docker inspect <container>.Config.Env`
as an expected-visible surface (operators with docker-sock access are
trusted, but the scan guards against accidental re-export via entrypoint
`export`). Per DD-28 the attack-surface tests are container-based runs
via docker-py; earlier `@respx.mock` + `subprocess.run(python, ...)`
tests are deleted because respx only patches the current process.
"""
from __future__ import annotations

import json
import secrets
import time
from pathlib import Path

import docker
import pytest

from tests.harness.canaries import (
    ALL_CANARIES,
    CANARY_AWS,
    CANARY_NX_PASS,
    CANARY_NX_URL,
    CANARY_NX_USER,
    scan_dir_for_secret,
    scan_for_canaries,
)
from tests.harness.live_runner import allow_docker_unix_socket_only

IMAGE = "dmac-assistant:poc"


# ============================================================
# Unit tests for the scanner (covers tests/harness/canaries.py)
# ============================================================

class TestScan:
    def test_scan_empty_inputs_returns_empty(self) -> None:
        assert scan_for_canaries([], [], ALL_CANARIES) == []

    def test_scan_canary_in_single_stream(self) -> None:
        streams = [b"hello " + CANARY_AWS.encode() + b" world"]
        hits = scan_for_canaries(streams, [], ALL_CANARIES)
        assert len(hits) == 1
        assert hits[0][0] == CANARY_AWS
        assert hits[0][1].startswith("stream[0]")

    def test_scan_canary_in_single_file(self, tmp_path: Path) -> None:
        f = tmp_path / "out.txt"
        f.write_text(f"prefix {CANARY_NX_PASS} suffix")
        hits = scan_for_canaries([], [f], ALL_CANARIES)
        assert len(hits) == 1
        assert hits[0][0] == CANARY_NX_PASS
        assert str(f) in hits[0][1]

    def test_scan_multiple_canaries_across_streams_and_files(
        self, tmp_path: Path
    ) -> None:
        streams = [CANARY_AWS.encode(), b"nothing"]
        f1 = tmp_path / "a"
        f2 = tmp_path / "b"
        f1.write_text(CANARY_NX_USER)
        f2.write_text("clean")
        hits = scan_for_canaries(streams, [f1, f2], ALL_CANARIES)
        assert {(h[0]) for h in hits} == {CANARY_AWS, CANARY_NX_USER}

    def test_scan_ignores_missing_paths(self, tmp_path: Path) -> None:
        ghost = tmp_path / "does-not-exist"
        streams = [CANARY_AWS.encode()]
        hits = scan_for_canaries(streams, [ghost], ALL_CANARIES)
        assert len(hits) == 1
        assert hits[0][0] == CANARY_AWS

    def test_scan_walks_directory_tree(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        (deep / "leaf.txt").write_text(CANARY_NX_PASS)
        hits = scan_for_canaries([], [tmp_path], ALL_CANARIES)
        assert len(hits) == 1
        assert hits[0][0] == CANARY_NX_PASS
        assert "leaf.txt" in hits[0][1]

    def test_scan_handles_binary_files(self, tmp_path: Path) -> None:
        bin_file = tmp_path / "blob.bin"
        bin_file.write_bytes(bytes(range(256)))
        hits = scan_for_canaries([], [bin_file], ALL_CANARIES)
        assert hits == []

    def test_scan_detects_canary_in_binary_file(self, tmp_path: Path) -> None:
        bin_file = tmp_path / "blob.bin"
        bin_file.write_bytes(b"\x00\x01" + CANARY_AWS.encode() + b"\xff")
        hits = scan_for_canaries([], [bin_file], ALL_CANARIES)
        assert len(hits) == 1
        assert hits[0][0] == CANARY_AWS

    def test_scan_accepts_str_streams(self) -> None:
        hits = scan_for_canaries([f"foo {CANARY_AWS} bar"], [], ALL_CANARIES)
        assert hits and hits[0][0] == CANARY_AWS

    def test_canaries_are_distinct_per_session(self) -> None:
        assert CANARY_AWS.startswith("CANARY-AWS-")
        assert len(CANARY_AWS) == len("CANARY-AWS-") + 12
        assert "dev" in CANARY_NX_URL  # DD-21 shape
        assert len(set(ALL_CANARIES)) == len(ALL_CANARIES)

    def test_scan_does_not_follow_symlink_loops(self, tmp_path: Path) -> None:
        """F7: the scanner must not infinite-loop on self-referential symlinks."""
        loop_dir = tmp_path / "loop"
        loop_dir.mkdir()
        (loop_dir / "self").symlink_to(loop_dir, target_is_directory=True)
        (loop_dir / "real.txt").write_text("clean")
        start = time.monotonic()
        hits = scan_for_canaries([], [loop_dir], ALL_CANARIES)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"symlink walk took {elapsed:.2f}s; likely looping"
        assert hits == []


# ============================================================
# Unit tests for scan_dir_for_secret (T06 cross-spec helper)
# ============================================================

class TestScanDirForSecret:
    def test_returns_empty_for_missing_root(self, tmp_path: Path) -> None:
        ghost = tmp_path / "does-not-exist"
        assert scan_dir_for_secret(ghost, b"anything") == []

    def test_returns_empty_when_needle_absent(self, tmp_path: Path) -> None:
        (tmp_path / "clean.txt").write_text("nothing to see")
        assert scan_dir_for_secret(tmp_path, b"missing-needle") == []

    def test_finds_needle_in_single_file(self, tmp_path: Path) -> None:
        f = tmp_path / "leak.txt"
        f.write_bytes(b"prefix SECRET-123 suffix")
        hits = scan_dir_for_secret(tmp_path, b"SECRET-123")
        assert hits == [f]

    def test_walks_nested_dirs(self, tmp_path: Path) -> None:
        deep = tmp_path / "a" / "b" / "c"
        deep.mkdir(parents=True)
        target = deep / "leaf.bin"
        target.write_bytes(b"\x00\x01NEEDLE\xff")
        hits = scan_dir_for_secret(tmp_path, b"NEEDLE")
        assert hits == [target]

    def test_accepts_file_path_as_root(self, tmp_path: Path) -> None:
        f = tmp_path / "x.txt"
        f.write_bytes(b"has SECRET here")
        assert scan_dir_for_secret(f, b"SECRET") == [f]

    def test_skips_unreadable_file_without_raising(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """read_bytes OSError is caught silently — the scanner must not raise."""
        blocked = tmp_path / "blocked.txt"
        blocked.write_text("content with NEEDLE")

        real_read_bytes = Path.read_bytes

        def fake_read_bytes(self: Path) -> bytes:
            if self == blocked:
                raise PermissionError("simulated EACCES")
            return real_read_bytes(self)

        monkeypatch.setattr(Path, "read_bytes", fake_read_bytes)
        assert scan_dir_for_secret(tmp_path, b"NEEDLE") == []


# ============================================================
# Per-capture-mechanism negative control (F4)
# ============================================================

def test_negative_control_catches_stream_canary() -> None:
    """F4 — prove the scanner detects a byte-stream canary, not just a file canary.

    Complements test_negative_control_scanner_catches_planted_canary which
    exercises the file-walking code path only. If the file walker and the
    stream scanner diverge (e.g. a refactor that breaks byte-stream handling),
    this negative control fails loudly.
    """
    hits = scan_for_canaries(
        [CANARY_AWS.encode() + b" planted in stream"],
        [],
        ALL_CANARIES,
    )
    assert len(hits) == 1
    assert hits[0][0] == CANARY_AWS
    assert hits[0][1].startswith("stream[0]")


# ============================================================
# Shared fixtures for attack-surface tests
# ============================================================

@pytest.fixture
def canary_env(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Poison the live env vars with canary sentinels (no .env file touched)."""
    env = {
        "AWS_BEARER_TOKEN_BEDROCK": CANARY_AWS,
        "AWS_REGION": "us-east-1",
        "NEXTSEEK_USERNAME": CANARY_NX_USER,
        "NEXTSEEK_PASSWORD": CANARY_NX_PASS,
        "NEXTSEEK_URL": CANARY_NX_URL,
        "CLAUDE_CODE_USE_BEDROCK": "1",
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    return env


@pytest.fixture
def docker_client():
    # T01's pyproject.toml sets --disable-socket globally; docker-py talks
    # over AF_UNIX which is blocked unless pytest-socket is told to let it
    # through. Mirror T07/T08's pattern (shared helper in live_runner).
    allow_docker_unix_socket_only()
    client = docker.from_env()
    try:
        client.ping()
    except Exception as exc:  # pragma: no cover — environmental
        pytest.skip(f"Docker daemon unavailable: {exc}")
    try:
        client.images.get(IMAGE)
    except docker.errors.ImageNotFound:
        pytest.fail(f"{IMAGE} missing; run `make image-build` first")
    yield client
    client.close()


@pytest.fixture
def container_tree(tmp_path: Path) -> dict[str, Path]:
    user_id = f"t09-{secrets.token_hex(4)}"
    claude_dir = tmp_path / "claude-users" / user_id / ".claude"
    scratch_dir = tmp_path / "scratch" / user_id
    projects_dir = tmp_path / "projects" / "fake"
    for d in (claude_dir, scratch_dir, projects_dir):
        d.mkdir(parents=True, exist_ok=True)
    return {
        "claude": claude_dir,
        "scratch": scratch_dir,
        "projects": projects_dir,
    }


def _mounts(tree: dict[str, Path]) -> dict[str, dict[str, str]]:
    return {
        str(tree["claude"]): {"bind": "/home/user/.claude", "mode": "rw"},
        str(tree["scratch"]): {"bind": "/data/scratch", "mode": "rw"},
        str(tree["projects"]): {"bind": "/data/projects/fake", "mode": "ro"},
    }


def _run_container_capture_all(
    client: "docker.DockerClient",
    command: list[str],
    env: dict[str, str],
    mounts: dict[str, dict[str, str]],
    timeout: int = 60,
) -> dict[str, bytes | int]:
    """Run a container, capture every credential-bearing surface.

    DD-27: in addition to stdout/stderr, capture
    `docker inspect <id>.Config.Env` as `inspect_env` — a host process
    with Docker-socket access reads this verbatim. Callers MUST include
    `inspect_env` in the scanner's streams list.
    """
    container = client.containers.create(
        IMAGE, command=command, environment=env,
        volumes=mounts, stdin_open=False, tty=False, detach=True,
    )
    try:
        container.start()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            container.reload()
            if container.status == "exited":
                break
            time.sleep(0.3)
        else:
            container.kill()
        stdout = container.logs(stdout=True, stderr=False)
        stderr = container.logs(stdout=False, stderr=True)
        try:
            exit_code = container.wait(timeout=5)["StatusCode"]
        except Exception:
            exit_code = -1
        inspect = client.api.inspect_container(container.id)
        env_list = inspect.get("Config", {}).get("Env") or []
        inspect_env = ("\n".join(env_list)).encode("utf-8")
        return {
            "stdout": stdout,
            "stderr": stderr,
            "combined": stdout + b"\n" + stderr,
            "inspect_env": inspect_env,
            "exit_code": exit_code,
        }
    finally:
        try:
            container.remove(force=True)
        except Exception:
            pass


def _all_files_under(*roots: Path) -> list[Path]:
    return [p for root in roots for p in root.rglob("*") if p.is_file()]


# ============================================================
# Attack-surface tests (5 total incl. negative control)
# DD-28: all attack-surface tests are container-based runs; no respx.
# ============================================================

def test_entrypoint_scrub_no_canary_leak(
    canary_env: dict[str, str],
    docker_client: "docker.DockerClient",
    container_tree: dict[str, Path],
) -> None:
    """Seed settings.local.json with a canary under `env`; run the entrypoint;
    assert (1) scrub landed (no `env` key, other keys preserved);
    (2) no canary in stdout/stderr or any file under the .claude/scratch mounts;
    (3) no pre-scrub residue files (F3) left behind by atomic jq-move.
    """
    seeded = {"env": {"SECRET": CANARY_AWS}, "model": "claude-xyz"}
    settings_path = container_tree["claude"] / "settings.local.json"
    settings_path.write_text(json.dumps(seeded))

    streams = _run_container_capture_all(
        docker_client,
        command=["sh", "-c", "echo entrypoint-ran"],
        env=canary_env,
        mounts=_mounts(container_tree),
        timeout=30,
    )
    scrubbed = json.loads(settings_path.read_text())
    assert "env" not in scrubbed
    assert scrubbed.get("model") == "claude-xyz"

    residue = (
        list(container_tree["claude"].rglob("*.tmp"))
        + list(container_tree["claude"].rglob("*~"))
        + list(container_tree["claude"].rglob("*.bak"))
        + list(container_tree["claude"].rglob("settings.local.json.swp"))
    )
    assert residue == [], f"entrypoint left pre-scrub residue: {residue!r}"

    hits = scan_for_canaries(
        [streams["stdout"], streams["stderr"], streams["inspect_env"]],
        [container_tree["claude"], container_tree["scratch"]],
        ALL_CANARIES,
    )
    leaks = [h for h in hits if not h[1].startswith("stream[2]")]
    assert leaks == [], f"canary leaked to unexpected surface: {leaks!r}"


def test_smoke_run_no_canary_leak(
    canary_env: dict[str, str],
    docker_client: "docker.DockerClient",
    container_tree: dict[str, Path],
) -> None:
    """Run a safe no-auth command in the container with canary env; verify
    no canary escapes to stdout/stderr or host-mounted trees.
    """
    streams = _run_container_capture_all(
        docker_client,
        command=["claude", "--version"],
        env=canary_env,
        mounts=_mounts(container_tree),
        timeout=30,
    )
    hits = scan_for_canaries(
        [streams["stdout"], streams["stderr"], streams["inspect_env"]],
        [container_tree["claude"], container_tree["scratch"]],
        ALL_CANARIES,
    )
    leaks = [h for h in hits if not h[1].startswith("stream[2]")]
    assert leaks == [], f"canary leaked from smoke run: {leaks!r}"


def test_container_startup_no_canary_leak(
    canary_env: dict[str, str],
    docker_client: "docker.DockerClient",
    container_tree: dict[str, Path],
) -> None:
    """DD-28: seed the full set of canary creds; run `claude --version` in the
    real image; scan every surface. Proves canaries DO land in the inspect-Env
    (expected) but do NOT leak to stdout/stderr or any mounted file.
    """
    streams = _run_container_capture_all(
        docker_client,
        command=["claude", "--version"],
        env=canary_env,
        mounts=_mounts(container_tree),
        timeout=30,
    )
    hits = scan_for_canaries(
        [streams["stdout"], streams["stderr"], streams["inspect_env"]],
        [container_tree["claude"], container_tree["scratch"]],
        ALL_CANARIES,
    )
    inspect_hits = [h for h in hits if h[1].startswith("stream[2]")]
    assert inspect_hits, (
        "inspect_env scan returned no canaries — either docker.api.inspect_container "
        "is broken or canaries were dropped from Config.Env"
    )
    leaks = [h for h in hits if not h[1].startswith("stream[2]")]
    assert leaks == [], f"canary leaked to non-inspect surface: {leaks!r}"


def test_inspect_env_is_scanned_as_expected_surface(
    canary_env: dict[str, str],
    docker_client: "docker.DockerClient",
    container_tree: dict[str, Path],
) -> None:
    """DD-27 positive control: confirm the scanner sees canaries in
    inspect_env (expected-visible), and does NOT see them in stdout/stderr
    when the container just runs a trivial command that doesn't print env.
    """
    streams = _run_container_capture_all(
        docker_client,
        command=["sh", "-c", "true"],
        env=canary_env,
        mounts=_mounts(container_tree),
        timeout=30,
    )
    inspect_hits = scan_for_canaries(
        [streams["inspect_env"]], [], ALL_CANARIES
    )
    assert inspect_hits, "scanner failed to find canary in inspect_env"

    stdio_hits = scan_for_canaries(
        [streams["stdout"], streams["stderr"]], [], ALL_CANARIES
    )
    assert stdio_hits == [], f"canary appeared in stdio: {stdio_hits!r}"


def test_negative_control_scanner_catches_planted_canary(
    tmp_path: Path,
) -> None:
    """Meta-test: plant CANARY_AWS into a file; assert the scanner finds it.

    If this test ever fails, the scanner is broken and the other four tests
    are passing silently. This is the single invariant that guarantees the
    suite is doing real work.
    """
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    planted = scratch / "leaked_secret.txt"
    planted.write_text(f"accidentally wrote {CANARY_AWS} to a file")

    hits = scan_for_canaries([b""], [scratch], ALL_CANARIES)
    assert len(hits) == 1
    assert hits[0][0] == CANARY_AWS
    assert str(planted) in hits[0][1]


# ============================================================
# T5 — G1: hermetic zero-creds containment gate
# Proves that the REAL bridge path (start_container → _build_environment)
# strips AWS_BEARER_TOKEN_BEDROCK from the launched agent container, while
# a bare containers.create() path (bypassing _build_environment) DOES
# propagate it — making the negative control meaningful.
# ============================================================

def _make_bridge_config(tmp_path: Path) -> "BridgeConfig":
    """Build a minimal BridgeConfig with all required host paths present."""
    from pydantic import SecretStr

    from dmac_assistant.config import BridgeConfig, UserRecord

    # _build_volumes needs these dirs to exist for Docker bind mounts.
    claude_users_root = tmp_path / "claude-users"
    scratch_root = tmp_path / "scratch"
    dropbox_root = tmp_path / "dropbox"
    output_root = tmp_path / "output"
    user_id = "t5testuser"
    (claude_users_root / user_id / ".claude").mkdir(parents=True)
    (scratch_root / user_id).mkdir(parents=True)
    (dropbox_root / "fake-project").mkdir(parents=True)
    (output_root / user_id).mkdir(parents=True)

    # catalog_file must exist and contain valid JSON.
    catalog = tmp_path / "catalog.json"
    catalog.write_text('{"default": {}}', encoding="utf-8")

    return BridgeConfig(
        users={"t5testuser": UserRecord(password=SecretStr("pw"), projects=["fake-project"])},
        claude_users_root=claude_users_root,
        scratch_root=scratch_root,
        dropbox_root=dropbox_root,
        output_root=output_root,
        catalog_file=catalog,
        # sidecar_network=None: skip the network fail-fast check (no sidecar
        # stack is required for this gate).
        sidecar_network=None,
        bedrock_proxy_url="http://bedrock-proxy:8080",
    )


def _make_identity() -> "AuthenticatedIdentity":
    from pydantic import SecretStr

    from dmac_assistant.auth import AuthenticatedIdentity

    return AuthenticatedIdentity(
        user_id="t5testuser",
        password=SecretStr("pw"),
        projects=["fake-project"],
    )


def _container_env_streams(
    client: "docker.DockerClient", container_id: str
) -> tuple[bytes, bytes]:
    """Return (inspect_env_bytes, exec_env_bytes) for a running container."""
    inspect = client.api.inspect_container(container_id)
    env_list = inspect.get("Config", {}).get("Env") or []
    inspect_env = ("\n".join(env_list)).encode("utf-8")

    exec_info = client.api.exec_create(
        container_id, cmd=["env"], stdin=False, stdout=True, stderr=False, tty=False
    )
    exec_id = exec_info["Id"] if isinstance(exec_info, dict) else exec_info
    exec_out = client.api.exec_start(exec_id, detach=False, stream=False)
    exec_env = exec_out if isinstance(exec_out, bytes) else b""
    return inspect_env, exec_env


@pytest.mark.live_docker
def test_bedrock_proxy_containment(
    docker_client: "docker.DockerClient",
    tmp_path: Path,
) -> None:
    """G1: after T4's de-cred edit, the real bridge path (start_container →
    _build_environment) must produce an agent container that holds ZERO
    AWS_BEARER_TOKEN_BEDROCK / CANARY_AWS bytes.

    The negative control uses bare containers.create() — which bypasses
    _build_environment and passes env verbatim — to prove the DETECTOR is live.
    Without the negative control, a passing real-path scan could be a silent
    scanner failure rather than a genuine containment proof.
    """
    from dmac_assistant.containers import start_container

    identity = _make_identity()
    config = _make_bridge_config(tmp_path)

    bridge_env = {
        "AWS_BEARER_TOKEN_BEDROCK": CANARY_AWS,
        "AWS_REGION": "us-east-1",
    }

    real_container = None
    neg_container = None
    try:
        # ---- Real bridge path -----------------------------------------------
        # start_container → build_container_spec → _build_environment filters
        # AWS_BEARER_TOKEN_BEDROCK.  command_override=["sleep","30"] keeps the
        # container alive long enough for inspect/exec; it exits immediately
        # otherwise (claude needs stdin).
        real_container = start_container(
            identity,
            image=IMAGE,
            session_id=None,
            bridge_env=bridge_env,
            config=config,
            client=docker_client,
            command_override=["sleep", "30"],
        )
        real_container.reload()
        real_inspect_env, real_exec_env = _container_env_streams(
            docker_client, real_container.id
        )

        agent_env_scan_hits = scan_for_canaries(
            [real_inspect_env, real_exec_env],
            [],
            [CANARY_AWS, "AWS_BEARER_TOKEN_BEDROCK"],
        )
        print(f"\nagent-env scan: {len(agent_env_scan_hits)} hits")
        assert agent_env_scan_hits == [], (
            f"CONTAINMENT FAILURE: AWS bearer token found in agent container env "
            f"via the real bridge path: {agent_env_scan_hits!r}"
        )

        # ---- Negative control -----------------------------------------------
        # bare containers.create() passes env verbatim, bypassing
        # _build_environment.  The scanner MUST flag the sentinel here —
        # proving the detector is live so a "0 hits on real path" is meaningful.
        neg_container = docker_client.containers.create(
            IMAGE,
            command=["sleep", "30"],
            environment={"AWS_BEARER_TOKEN_BEDROCK": CANARY_AWS},
            detach=True,
        )
        neg_container.start()
        neg_inspect_env, neg_exec_env = _container_env_streams(
            docker_client, neg_container.id
        )

        neg_hits = scan_for_canaries(
            [neg_inspect_env, neg_exec_env],
            [],
            [CANARY_AWS, "AWS_BEARER_TOKEN_BEDROCK"],
        )
        print(f"negative control: flagged ({len(neg_hits)} hit(s))")
        assert neg_hits, (
            "NEGATIVE CONTROL FAILED: scanner did not detect the sentinel "
            "in the verbatim-env container — the detector is broken; "
            "'0 hits on real path' would be meaningless"
        )

    finally:
        for c in (real_container, neg_container):
            if c is not None:
                try:
                    c.remove(force=True)
                except Exception:
                    pass
