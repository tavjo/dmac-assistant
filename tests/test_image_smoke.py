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
    "/app/docs/nextseek/README.md",
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


def test_entrypoint_plugin_discovery_symlinks_present(
    tmp_path: Path,
    dummy_env: dict[str, str],
) -> None:
    """H-2: DD-37 plugin-discovery regression lock.

    claude-code 2.1.92 auto-discovers plugins only under
    ``~/.claude/plugins/local/``. The image bakes the plugin tree at
    ``/app/plugins/`` and the entrypoint is responsible for symlinking
    each ``/app/plugins/<name>`` into ``~/.claude/plugins/local/<name>``
    on every container start. Without those links the in-container
    claude-code silently refuses to register the plugin — the T08
    live happy-path test with a directive prompt can't distinguish
    "plugin loaded and invoked" from "bash scripts found on PATH and
    run directly", so the discovery signal needs its own hermetic cover.

    This test uses an empty ``.claude`` mount (mirroring a fresh
    per-user dir), runs the real entrypoint, then inspects the symlink
    structure. Asserts:
      * ``plugin.json`` resolves through the link to the baked tree.
      * ``CLAUDE.md`` cwd-symlink is re-created if absent.
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir): ("/home/user/.claude", "rw")},
        env=dummy_env,
        command=[
            "sh",
            "-c",
            "set -e; "
            "test -L /home/user/.claude/plugins/local/nextseek-api "
            "&& test -f /home/user/.claude/plugins/local/nextseek-api/.claude-plugin/plugin.json "
            "&& printf 'PLUGIN_TARGET=%s\\n' "
            "\"$(readlink /home/user/.claude/plugins/local/nextseek-api)\" "
            "&& test -L /home/user/CLAUDE.md "
            "&& printf 'CLAUDEMD_TARGET=%s\\n' \"$(readlink /home/user/CLAUDE.md)\"",
        ],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, (
        f"plugin-discovery structure absent after entrypoint; logs={logs!r}"
    )
    assert "PLUGIN_TARGET=/app/plugins/nextseek-api" in logs, (
        f"nextseek-api symlink did not resolve to the baked tree; logs={logs!r}"
    )
    assert "CLAUDEMD_TARGET=/app/CLAUDE.md" in logs, (
        f"CLAUDE.md cwd-symlink missing or wrong target; logs={logs!r}"
    )


def test_plugin_manifest_validates_through_entrypoint_symlink(
    tmp_path: Path,
    dummy_env: dict[str, str],
) -> None:
    """R-04: DD-37 plugin-discovery stronger signal.

    The sibling `test_entrypoint_plugin_discovery_symlinks_present` asserts
    the symlink structure exists. This test additionally exercises
    claude-code's OWN manifest reader via `claude plugin validate <path>`
    against the symlinked path — proving:
      * the symlink resolves to a readable plugin.json,
      * the manifest satisfies claude-code's plugin schema (name, version,
        etc.), and
      * a future claude-code version that tightens the schema surfaces as a
        test failure rather than silently-broken discovery.

    This is hermetic (no Bedrock, no network) because `claude plugin
    validate` is a pure file-read + schema check — exit 0 iff manifest
    parses.
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir): ("/home/user/.claude", "rw")},
        env=dummy_env,
        command=[
            "claude",
            "plugin",
            "validate",
            "/home/user/.claude/plugins/local/nextseek-api",
        ],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, (
        f"claude plugin validate failed through symlink path; logs={logs!r}"
    )
    assert "Validation passed" in logs, (
        f"plugin manifest read through entrypoint symlink but did not validate; "
        f"logs={logs!r}"
    )


def test_dockerfile_cmd_has_verbose_flag() -> None:
    """DD-31 regression lock: stream-json in --print mode requires --verbose.

    claude-code 2.1.92 rejects `--print --output-format stream-json` without
    `--verbose` at arg-validation time. A future CMD revert would only
    surface during live runs (which CI may skip) — this hermetic file-read
    catches it at every suite run. Hermetic by design (no docker daemon
    call required), complementing the image-level smoke tests.
    """
    import re

    repo_root = Path(__file__).resolve().parents[1]
    dockerfile = repo_root / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")
    match = re.search(r'^CMD\s+\[(.*)\]\s*$', text, flags=re.MULTILINE)
    assert match, f"Dockerfile at {dockerfile} has no CMD line"
    cmd_args = match.group(1)
    assert '"--verbose"' in cmd_args, (
        f"Dockerfile CMD is missing --verbose (DD-31): {cmd_args!r}"
    )
    assert '"stream-json"' in cmd_args, (
        f"Dockerfile CMD is missing stream-json output format: {cmd_args!r}"
    )
    assert '"--print"' in cmd_args, (
        f"Dockerfile CMD is missing --print mode: {cmd_args!r}"
    )
