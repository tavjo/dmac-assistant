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
    """Plan A T8 AMD3-C2: ensure_image() now raises RuntimeError instead of
    auto-building. Convert that to a session skip so the smoke suite
    reports "image not built" cleanly rather than producing N errors.
    """
    try:
        return ensure_image()
    except RuntimeError as exc:
        pytest.skip(str(exc))


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
    "/app/plugins/nextseek",
    "/app/plugins/nextseek/skills/nextseek/SKILL.md",
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
            "test -L /home/user/.claude/plugins/local/nextseek "
            "&& test -f /home/user/.claude/plugins/local/nextseek/.claude-plugin/plugin.json "
            "&& printf 'PLUGIN_TARGET=%s\\n' "
            "\"$(readlink /home/user/.claude/plugins/local/nextseek)\" "
            "&& test -L /home/user/CLAUDE.md "
            "&& printf 'CLAUDEMD_TARGET=%s\\n' \"$(readlink /home/user/CLAUDE.md)\"",
        ],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, (
        f"plugin-discovery structure absent after entrypoint; logs={logs!r}"
    )
    assert "PLUGIN_TARGET=/app/plugins/nextseek" in logs, (
        f"nextseek symlink did not resolve to the baked tree; logs={logs!r}"
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
            "/home/user/.claude/plugins/local/nextseek",
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


def test_python_resolves_to_314(dummy_env: dict[str, str]) -> None:
    """Plan A · T0: bare `python` MUST resolve to 3.14 inside the image."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=["-c", "python -c 'import sys; print(sys.version_info[:2])'"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, f"`python` invocation failed: {logs!r}"
    assert "(3, 14)" in logs, (
        f"`python` did not resolve to 3.14; got logs={logs!r}. "
        "Plan A T0 R4 PATH-first symlink invariant violated."
    )


def test_python314_alias_resolves_to_314(dummy_env: dict[str, str]) -> None:
    """Plan A · T0: explicit `python3.14` alias MUST also resolve to 3.14."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=["-c", "python3.14 -c 'import sys; print(sys.version_info[:2])'"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, f"`python3.14` invocation failed: {logs!r}"
    assert "(3, 14)" in logs, f"`python3.14` did not resolve to 3.14; logs={logs!r}"


def test_dmac_python_env_resolves_to_314(dummy_env: dict[str, str]) -> None:
    """Plan A · T0: `$DMAC_PYTHON` MUST be a usable interpreter path."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=[
            "-c",
            '"$DMAC_PYTHON" -c '
            "'import sys; assert sys.version_info >= (3, 14); print(\"DMAC_PYTHON_OK\")'",
        ],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code == 0, f"$DMAC_PYTHON invocation failed: {logs!r}"
    assert "DMAC_PYTHON_OK" in logs, f"$DMAC_PYTHON path not 3.14; logs={logs!r}"


def test_chat_nextseek_absent_from_agent_image(dummy_env: dict[str, str]) -> None:
    """T11 (U-11, gate 9): `python -c "import chat_nextseek"` MUST FAIL inside
    the agent image. chat_nextseek (and its ~2 GB torch dependency chain) is
    sidecar-only; the agent image ships only the thin WS/viewset client.
    Inverts the old Plan A T8 persistent-install gate.
    """
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=[
            "-c",
            "python -c 'import chat_nextseek'",
        ],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")

    assert exit_code != 0, (
        f"`python -c 'import chat_nextseek'` SUCCEEDED (exit={exit_code}) — "
        "chat_nextseek must NOT be installed in the agent image (T11/U-11); "
        f"logs={logs!r}"
    )
    assert "ModuleNotFoundError" in logs or "ImportError" in logs, (
        f"expected an import failure for chat_nextseek; logs={logs!r}"
    )


def test_old_plugin_path_absent():
    """D25 amended: nextseek-api is removed from the image. Plan-body B14.2
    test #1, adapted to use the IMAGE_TAG constant per the existing fixture
    convention in tests/test_image_smoke.py (line 14).
    """
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG,
         "test", "-d", "/app/plugins/nextseek-api"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (
        f"D25 BREACH: /app/plugins/nextseek-api still exists in image "
        f"{IMAGE_TAG}. The Dockerfile's COPY must be plugin-specific "
        f"(COPY build_context/plugins/nextseek/ /app/plugins/nextseek/), "
        f"NOT the broad COPY build_context/plugins/ /app/plugins/ form. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )


def test_new_plugin_path_present():
    """The new plugin tree is present at /app/plugins/nextseek/ - including
    the four required subdirs: bin/ (shims), scripts/ (setup.sh), skills/
    (SKILL.md), commands/ (nextseek.md), context/ (catalog snapshots).
    """
    import subprocess
    for subdir in ("bin", "scripts", "skills", "commands", "context"):
        r = subprocess.run(
            ["docker", "run", "--rm", IMAGE_TAG,
             "test", "-d", f"/app/plugins/nextseek/{subdir}"],
            capture_output=True, text=True,
        )
        assert r.returncode == 0, (
            f"/app/plugins/nextseek/{subdir} missing from image {IMAGE_TAG}; "
            f"stdout={r.stdout!r} stderr={r.stderr!r}"
        )
    r = subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG,
         "test", "-x", "/app/plugins/nextseek/scripts/setup.sh"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"/app/plugins/nextseek/scripts/setup.sh missing or non-executable; "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )


def test_new_plugin_bin_on_path():
    """Plan-body B14.2 test #3: command -v nextseek-entity-extract resolves
    to the plugin bin path. Closes Wave-4 carryover risk #3 (the wiring
    gap). The expected resolution path is /app/plugins/nextseek/bin/...,
    not /app/plugins/nextseek-api/bin/...
    """
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG,
         "/bin/sh", "-c", "command -v nextseek-entity-extract"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"command -v nextseek-entity-extract failed in image {IMAGE_TAG}; "
        f"PATH likely missing /app/plugins/nextseek/bin. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    assert "/app/plugins/nextseek/bin/nextseek-entity-extract" in r.stdout, (
        f"command -v resolved to wrong path: {r.stdout!r} (expected "
        f"/app/plugins/nextseek/bin/nextseek-entity-extract). If this "
        f"resolves to /app/plugins/nextseek-api/bin/..., the legacy PATH "
        f"is still in the Dockerfile - Wave-4 carryover #3 NOT closed."
    )


def test_usr_bin_python_resolves_for_stripped_path_dispatch():
    """Wave-3 carryover risk #2 image-side defence (load-bearing)."""
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", IMAGE_TAG,
         "/bin/sh", "-c", "PATH=/usr/bin:/bin python --version"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, (
        f"/usr/bin/python or /bin/python does not resolve in image {IMAGE_TAG} "
        f"under stripped PATH=/usr/bin:/bin. This blocks Wave-3 stripped-PATH "
        f"dispatch tests at B17 image-e2e. Fix per §9.6 ladder. "
        f"stdout={r.stdout!r} stderr={r.stderr!r}"
    )
    combined = r.stdout + r.stderr
    assert "Python 3.14" in combined, (
        f"stripped PATH found a Python interpreter, but it is not Python 3.14: "
        f"{combined!r}. Wave-3 dispatch tests assume 3.14 features (typing.Any "
        f"+ dataclass slots + match-case). Update the image's /usr/bin/python "
        f"symlink to point at the 3.14 install."
    )


# ============================================================================
# T4.1 — Image-rebuild verification tests
# ============================================================================


def test_runner_ns_present_in_image() -> None:
    """The rebuilt image contains the T1.3 NExtSEEK runner script."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env={},
        command=["-c", "ls -la /opt/dmac/runner_ns.py"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode(
            "utf-8", errors="replace"
        )

    assert exit_code == 0, (
        "runner_ns.py missing from /opt/dmac in rebuilt image; "
        f"logs={logs!r}"
    )
    assert "runner_ns.py" in logs


def test_runner_ns_mode_world_executable() -> None:
    """The runner is mode 0755 so uid 1001 can execute the root-owned file."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env={},
        command=["-c", "stat -c '%a %u %g' /opt/dmac/runner_ns.py"],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode(
            "utf-8", errors="replace"
        )

    assert exit_code == 0, f"stat runner_ns.py failed; logs={logs!r}"
    stat_lines = [
        line.strip()
        for line in logs.splitlines()
        if line.strip() and line.strip()[0].isdigit()
    ]
    assert stat_lines, f"stat output missing mode/uid/gid line; logs={logs!r}"
    mode, uid, gid = stat_lines[-1].split()
    assert mode == "755", (
        f"runner_ns.py mode should be 755, got mode={mode!r} "
        f"uid={uid!r} gid={gid!r}; logs={logs!r}"
    )


def test_thin_client_modules_importable_at_opt_dmac() -> None:
    """T11: runner_ns.py's sibling helper modules (_ws_contract,
    _assistant_models, _assistant_client, _sidecar_client) must import from
    /opt/dmac/ WITHOUT chat_nextseek — proving the new Dockerfile COPYs landed
    and the thin client's deps (websockets, httpx) come from `uv sync`.
    Replaces the old chat_nextseek.orchestrator import gate (inverted by
    test_chat_nextseek_absent_from_agent_image above).
    """
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env={},
        command=[
            "-c",
            "cd /opt/dmac && python -c '"
            "import _ws_contract, _assistant_models, _assistant_client, "
            "_sidecar_client; print(\"THIN_CLIENT_OK\")'",
        ],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode(
            "utf-8", errors="replace"
        )

    assert exit_code == 0, (
        f"thin-client helper modules failed to import at /opt/dmac; logs={logs!r}"
    )
    assert "THIN_CLIENT_OK" in logs


def test_entrypoint_dmac_runtime_mode_idle_keeps_container_alive(
    dummy_env: dict[str, str],
) -> None:
    """DMAC_RUNTIME_MODE=idle runs the entrypoint sleep loop."""
    import time

    idle_env = dict(dummy_env)
    idle_env["DMAC_RUNTIME_MODE"] = "idle"
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=idle_env,
        command=["sh", "-c", "exit 7"],
    ) as container:
        time.sleep(2)
        container.reload()
        status = container.status
        logs = container.logs(stdout=True, stderr=True).decode(
            "utf-8", errors="replace"
        )
        container.stop(timeout=5)

    assert status == "running", (
        "idle-mode container exited instead of staying alive; "
        f"status={status!r} logs={logs!r}"
    )


def test_entrypoint_dmac_runtime_mode_default_runs_command(
    dummy_env: dict[str, str],
) -> None:
    """Without DMAC_RUNTIME_MODE, the entrypoint still execs the command."""
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=["sh", "-c", "printf DEFAULT_PATH_OK"],
    ) as container:
        result = container.wait()
        logs = container.logs(stdout=True, stderr=True).decode(
            "utf-8", errors="replace"
        )

    assert result["StatusCode"] == 0, (
        f"default entrypoint path failed; result={result!r} logs={logs!r}"
    )
    assert "DEFAULT_PATH_OK" in logs


# ============================================================================
# Task 8 — nextseek-batch-upload skill baked into image
# ============================================================================


def test_batch_upload_skill_symlink_and_plugin_validates(
    tmp_path: Path,
    dummy_env: dict[str, str],
) -> None:
    """Task 8 smoke: the nextseek-batch-upload SKILL.md symlink resolves through the
    entrypoint-created plugin symlink, and `claude plugin validate` passes.

    (a) Mirror test_entrypoint_plugin_discovery_symlinks_present (line 206):
    mount an empty .claude so the real entrypoint creates
    ~/.claude/plugins/local/nextseek -> /app/plugins/nextseek, then resolve
    the new skill symlink through that link.

    (b) Mirror test_plugin_manifest_validates_through_entrypoint_symlink (line 261):
    `claude plugin validate` must exit 0 and print "Validation passed".
    """
    claude_dir = tmp_path / ".claude"
    claude_dir.mkdir()

    # (a) Skill symlink resolves through the entrypoint-created plugin link.
    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir): ("/home/user/.claude", "rw")},
        env=dummy_env,
        command=[
            "sh", "-c",
            "set -e; printf 'SKILL_TARGET=%s\\n' "
            "\"$(readlink -f /home/user/.claude/plugins/local/nextseek/skills/nextseek-batch-upload/SKILL.md)\"",
        ],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
    assert exit_code == 0, f"batch-upload skill symlink did not resolve; logs={logs!r}"
    assert "SKILL_TARGET=/app/plugins/nextseek/skills/nextseek-batch-upload/SKILL.md" in logs, logs

    # (b) claude plugin validate passes through the symlinked plugin path.
    with make_container(
        image=IMAGE_TAG,
        mounts={str(claude_dir): ("/home/user/.claude", "rw")},
        env=dummy_env,
        command=["claude", "plugin", "validate", "/home/user/.claude/plugins/local/nextseek"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
    assert exit_code == 0, f"claude plugin validate failed; logs={logs!r}"
    assert "Validation passed" in logs, logs


def test_batch_upload_tools_on_path_and_deps_import(dummy_env: dict[str, str]) -> None:
    """Task 8 smoke: all five batch-upload bin tools are on PATH and the four
    Python deps (polars, fastexcel, xlsxwriter, markitdown) import cleanly.

    Mirror test_new_plugin_bin_on_path (line 466) / test_python_resolves_to_314
    (line 335): exec under `sh` (no entrypoint symlinks needed for PATH/import
    checks — PATH is baked into the image via Dockerfile ENV).
    """
    tools = (
        "nextseek-sampletype-attrs nextseek-sample-read nextseek-extract-text "
        "nextseek-build-payload nextseek-validate-upload"
    )
    with make_container(
        image=IMAGE_TAG,
        mounts={},
        env=dummy_env,
        command=[
            "-c",
            f"set -e; for t in {tools}; do command -v \"$t\" >/dev/null || {{ echo MISSING:$t; exit 1; }}; done; "
            "python -c 'import polars, fastexcel, xlsxwriter, markitdown; print(\"DEPS_OK\")'",
        ],
        entrypoint_override=["sh"],
    ) as container:
        exit_code = container.wait()["StatusCode"]
        logs = container.logs(stdout=True, stderr=True).decode("utf-8", errors="replace")
    assert exit_code == 0, f"tool-on-PATH or dep-import check failed; logs={logs!r}"
    assert "DEPS_OK" in logs, logs
