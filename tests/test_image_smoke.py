"""Hermetic smoke tests for the dmac-assistant:poc image."""
from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from build_tools.verify_env import REQUIRED_VARS
from tests.harness.canaries import CANARY_SECRET
from tests.harness.containers import (
    IMAGE_TAG,
    docker_available,
    ensure_image,
    make_container,
    seeded_settings_file,
)


pytestmark = pytest.mark.skipif(
    not docker_available(),
    reason="docker daemon not available",
)


@pytest.fixture(scope="session", autouse=True)
def _session_image() -> str:
    """Ensure the expected local image exists once for the smoke session."""
    return ensure_image()


@pytest.fixture
def dummy_env() -> dict[str, str]:
    """Provide a complete synthetic env block derived from T01's contract."""
    return {key: f"stub-{key}" for key in REQUIRED_VARS}


def test_entrypoint_scrubs_env_selectively(
    tmp_path: Path,
    dummy_env: dict[str, str],
) -> None:
    """Entrypoint should delete only the ``env`` key and leak no secrets."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    settings_path = claude_dir / "settings.local.json"
    seeded = {
        "env": {"SECRET": "CANARY-789"},
        "model": "claude-xyz",
        "permissions": {"allow": []},
        "hooks": {},
    }
    seeded_settings_file(settings_path, seeded)
    pre_mode = stat.S_IMODE(settings_path.stat().st_mode)

    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir): ("/home/user/.claude", "rw")},
        env=dummy_env,
        command=["true"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, f"entrypoint failed: {logs!r}"

    parsed = json.loads(settings_path.read_text(encoding="utf-8"))
    assert "env" not in parsed
    assert parsed["model"] == "claude-xyz"
    assert parsed["permissions"] == {"allow": []}
    assert parsed["hooks"] == {}

    post_mode = stat.S_IMODE(settings_path.stat().st_mode)
    assert post_mode == pre_mode
    assert "CANARY-789" not in logs


def test_ro_mount_rejects_writes(tmp_path: Path, dummy_env: dict[str, str]) -> None:
    """A ``:ro`` mount should reject writes at the kernel boundary."""
    fake_project = tmp_path / "fake_project"
    fake_project.mkdir()
    (fake_project / "already-there.txt").write_text("ok\n", encoding="utf-8")

    with make_container(
        image=IMAGE_TAG,
        mounts={str(fake_project): ("/data/projects/fake", "ro")},
        env=dummy_env,
        command=["-c", "echo leak > /data/projects/fake/canary"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code != 0, f"ro mount accepted a write (exit 0); logs={logs!r}"
    assert ("Read-only file system" in logs) or ("Permission denied" in logs), logs
    assert not (fake_project / "canary").exists()


def test_rw_mount_accepts_writes(tmp_path: Path, dummy_env: dict[str, str]) -> None:
    """A ``:rw`` mount should write through to the host filesystem."""
    scratch = tmp_path / "scratch"
    scratch.mkdir()

    with make_container(
        image=IMAGE_TAG,
        mounts={str(scratch): ("/data/scratch", "rw")},
        env=dummy_env,
        command=["-c", "echo hello > /data/scratch/out.txt"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, f"rw mount write failed: {logs!r}"
    out_path = scratch / "out.txt"
    assert out_path.is_file()
    assert out_path.read_text(encoding="utf-8") == "hello\n"


LAYOUT_PATHS = [
    "/app/CLAUDE.md",
    "/app/docs/nextseek-api/README.md",
    "/app/plugins/nextseek-api",
    "/app/plugins/nextseek-api/skills/nextseek-api/SKILL.md",
    "/usr/local/bin/entrypoint.sh",
    "/home/user",
]


@pytest.mark.parametrize("path", LAYOUT_PATHS)
def test_layout_contract_paths(path: str, dummy_env: dict[str, str]) -> None:
    """Every DD-10 layout path should exist in the built image."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=["-c", f"test -e {path} && echo PRESENT:{path}"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, f"path {path} missing; logs={logs!r}"
    assert f"PRESENT:{path}" in logs


@pytest.fixture
def claude_dir_with_empty_settings(tmp_path: Path) -> Path:
    """Seed a valid file so exit-code propagation exercises the scrub path."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()
    seeded = {
        "env": {},
        "model": "claude-xyz",
        "permissions": {"allow": []},
        "hooks": {},
    }
    seeded_settings_file(claude_dir / "settings.local.json", seeded)
    return claude_dir


def test_exec_passes_exit_code(
    claude_dir_with_empty_settings: Path,
    dummy_env: dict[str, str],
) -> None:
    """Entrypoint ``exec`` should preserve the child's exit status."""
    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir_with_empty_settings): ("/home/user/.claude", "rw")},
        env=dummy_env,
        command=["sh", "-c", "exit 42"],
    ) as container:
        exit_code = container.wait()["StatusCode"]

    assert exit_code == 42, f"expected 42, got {exit_code}"


def test_no_seeded_secret_in_logs(tmp_path: Path, dummy_env: dict[str, str]) -> None:
    """Seed the canary into every required env var and assert it never leaks."""
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    env_with_canary = dict(dummy_env)
    for key in REQUIRED_VARS:
        env_with_canary[key] = CANARY_SECRET

    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir): ("/home/user/.claude", "rw")},
        env=env_with_canary,
        command=["claude", "--version"],
    ) as container:
        container.wait()
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert CANARY_SECRET not in logs, f"canary leaked into container logs: {logs!r}"
