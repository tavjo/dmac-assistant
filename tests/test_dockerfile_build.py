"""Build-and-introspect tests for the dmac-assistant Docker image."""
from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER
from build_tools.ingest_nextseek_docs.toc import update_claude_md

IMAGE_TAG = "dmac-assistant:test"
REPO_ROOT = Path(__file__).resolve().parent.parent


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        subprocess.run(
            ["docker", "info"],
            check=True,
            capture_output=True,
            timeout=5,
        )
        return True
    except Exception:
        return False


@pytest.fixture(scope="module")
def built_image() -> str:
    build_context = REPO_ROOT / "build_context"
    if not (build_context / "plugins" / "nextseek-api").is_dir():
        subprocess.run(["make", "image-stage"], cwd=REPO_ROOT, check=True)

    result = subprocess.run(
        [
            "docker",
            "buildx",
            "build",
            "--platform=linux/amd64",
            "--load",
            "-t",
            IMAGE_TAG,
            ".",
        ],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"docker build failed (rc={result.returncode})\n"
        f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    )
    return IMAGE_TAG


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_image_architecture_amd64(built_image: str) -> None:
    result = subprocess.run(
        ["docker", "image", "inspect", built_image, "--format", "{{.Architecture}} {{.Os}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "amd64 linux"


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_layout_contract_paths_present(built_image: str) -> None:
    script = (
        "set -e; "
        "for p in /app/CLAUDE.md /app/docs/nextseek-api/README.md "
        "/app/docs/nextseek/README.md /app/plugins/nextseek-api "
        "/usr/local/bin/entrypoint.sh; do "
        'test -e "$p" || { echo MISSING:$p >&2; exit 2; }; '
        "done; "
        "echo OK"
    )
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", built_image, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, (
        f"path check failed rc={result.returncode}\n"
        f"STDOUT:{result.stdout}\nSTDERR:{result.stderr}"
    )
    assert "OK" in result.stdout


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_claude_version_pinned(built_image: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "claude", built_image, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "2.1.92" in result.stdout


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_claude_is_real_npm_binary(built_image: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "which", built_image, "claude"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "/usr/local/bin/claude"

    result2 = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", built_image, "-c", "head -1 /usr/local/bin/claude"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result2.returncode == 0, result2.stderr
    assert "node" in result2.stdout.lower() or "#!" in result2.stdout


@pytest.mark.slow
@pytest.mark.skipif(not _docker_available(), reason="docker daemon not running")
def test_entrypoint_mode_0755(built_image: str) -> None:
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "stat", built_image, "-c", "%a", "/usr/local/bin/entrypoint.sh"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "755"


def test_plugin_discovery_survives_ingestion(tmp_path: Path) -> None:
    claude_md = tmp_path / "CLAUDE.md"
    plugin_discovery = textwrap.dedent(
        """\
        # In-Container Agent Instructions

        (preamble...)

        ## Plugins available in this image

        - **`nextseek-api`** — interactive NExtSEEK query plugin.
          - Documentation: `/app/docs/nextseek-api/README.md`

        """
    )
    initial = plugin_discovery + BEGIN_MARKER + "\n" + END_MARKER + "\n"
    claude_md.write_text(initial, encoding="utf-8")

    update_claude_md(claude_md, "\n## NExtSEEK Documentation\n\n(auto)\n")

    final = claude_md.read_text(encoding="utf-8")
    assert plugin_discovery in final
    assert "## NExtSEEK Documentation" in final
    assert final.count(BEGIN_MARKER) == 1
    assert final.count(END_MARKER) == 1
    assert final.index(plugin_discovery) < final.index(BEGIN_MARKER)


def test_python_314_install_precedes_uv_sync() -> None:
    """Plan A · T0 R4 ordering: `uv python install 3.14` MUST appear before
    any `uv sync` or `uv pip install` line in the Dockerfile.

    R4-NEW-4 directive: compare CHARACTER OFFSETS, not line indices, so a
    future maintainer who chains `uv python install 3.14 && uv sync` onto
    the same logical RUN line still passes. The assertion is "first
    occurrence of `uv python install 3.14` precedes first occurrence of
    `uv sync` or `uv pip install` in the file as a whole."
    """
    import re

    dockerfile = REPO_ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    install_match = re.search(r"uv python install 3\.14", text)
    assert install_match is not None, (
        "Dockerfile is missing `uv python install 3.14`. Plan A T0 R4 "
        "requires this line before any uv sync / uv pip install."
    )

    consumer_match = re.search(r"uv (sync|pip install)", text)
    if consumer_match is not None:
        assert install_match.start() < consumer_match.start(), (
            f"`uv python install 3.14` (offset {install_match.start()}) "
            f"appears AFTER first `uv {consumer_match.group(1)}` "
            f"(offset {consumer_match.start()}). Plan A T0 R4 ordering "
            "invariant violated."
        )


def test_python_314_symlink_uses_uv_python_find_not_glob() -> None:
    """Plan A · T0 R4 (resolves R3-2): the symlink target MUST come from
    `uv python find 3.14`, not a glob like `/opt/uv/python/cpython-3.14*`.
    """
    import re

    dockerfile = REPO_ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    assert "uv python find 3.14" in text, (
        "Dockerfile must invoke `uv python find 3.14` to resolve the "
        "interpreter path deterministically. R3-2: glob-based ENV is "
        "non-deterministic and forbidden."
    )
    assert re.search(r"cpython-3\.14\*", text) is None, (
        "Dockerfile contains a glob over `cpython-3.14*`. R3-2 forbids "
        "glob expansion in ENV/RUN — use `$(uv python find 3.14)` instead."
    )


def test_dmac_python_env_set_to_well_known_path() -> None:
    """Plan A · T0 R4: `ENV DMAC_PYTHON` MUST point at the well-known
    symlink path `/usr/local/bin/python3.14`, not at an opaque uv path.
    """
    import re

    dockerfile = REPO_ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    match = re.search(r"^ENV\s+DMAC_PYTHON=(\S+)", text, flags=re.MULTILINE)
    assert match is not None, "Dockerfile missing `ENV DMAC_PYTHON=...`."
    assert match.group(1) == "/usr/local/bin/python3.14", (
        f"DMAC_PYTHON points at {match.group(1)!r}; T0 R4 requires "
        "`/usr/local/bin/python3.14` so callers don't depend on uv internals."
    )


def test_dockerfile_uses_uv_sync_locked() -> None:
    """Plan A · T8 Amendment 5 v3: Dockerfile must install bridge deps via
    `uv sync --locked` into the project venv at /opt/dmac-venv, with the
    venv prepended to PATH so plain `python` resolves to the venv
    interpreter. Replaces Amendment 4's `--system` install model (uv has
    never accepted `--system` on `sync`). Amendment 4 vendored-source
    drift guards (COPY vendor, no SSH, no git+ URLs) preserved.
    """
    import re

    dockerfile = REPO_ROOT / "Dockerfile"
    text = dockerfile.read_text(encoding="utf-8")

    # Amendment 5 v3: assert canonical uv-in-Docker pattern (uv sync --locked +
    # venv-on-PATH; no --system anywhere). Replaces the AMD4 literal-string check
    # whose pattern was rejected by uv at runtime.
    assert "uv sync --locked" in text, (
        "Dockerfile must invoke `uv sync --locked` to install bridge deps from "
        "pyproject.toml + uv.lock into the project venv. C2 fix: replaces the "
        "ephemeral `uv run --with` pre-warm with a persistent venv-backed install."
    )
    assert "UV_PROJECT_ENVIRONMENT=/opt/dmac-venv" in text, (
        "Dockerfile must set UV_PROJECT_ENVIRONMENT=/opt/dmac-venv so uv sync "
        "materializes the venv at the production-style path."
    )
    assert '"/opt/dmac-venv/bin:$PATH"' in text or "/opt/dmac-venv/bin:${PATH}" in text, (
        "Dockerfile must prepend /opt/dmac-venv/bin to PATH so plain `python` and "
        "plugin-shim invocations resolve to the venv interpreter without `uv run`."
    )

    # Amendment 5 drift guard: --system MUST NOT appear ANYWHERE in the Dockerfile.
    # Both `uv sync --system` (invalid since uv 0.0.x) and `uv pip install --system`
    # (the Amendment 4 chat_nextseek line, now superseded) are forbidden. Use a plain
    # substring check rather than a regex so multi-line `RUN ... \` continuations
    # with `--system` on a continuation line are also caught (per AMD5v3-M1).
    assert "--system" not in text, (
        "Amendment 5 forbids --system anywhere in the Dockerfile. "
        "The canonical uv-in-Docker pattern uses venv-on-PATH "
        "(UV_PROJECT_ENVIRONMENT + VIRTUAL_ENV + PATH) instead of --system."
    )

    # W3-H3: --no-install-project is mandatory.
    assert "--no-install-project" in text, (
        "Dockerfile must pass --no-install-project to uv sync."
    )

    # Anti-regression: chat_nextseek must not appear in any `uv run --with` line.
    for line in text.splitlines():
        if "uv run --with" in line:
            assert "chat_nextseek" not in line, (
                f"chat_nextseek slipped back into a `uv run --with` line: {line!r}"
            )

    # Amendment 4 drift guards: vendored-source build, no SSH or git+ URL.
    assert "--mount=type=ssh" not in text, (
        "Amendment 4 forbids `--mount=type=ssh` (vendored-source build needs no "
        "SSH forwarding)."
    )
    for line in text.splitlines():
        if "chat_nextseek" in line:
            assert "git+ssh://" not in line, (
                f"Amendment 4 forbids git+ssh:// for chat_nextseek: {line!r}"
            )
            assert "git+https://" not in line, (
                f"Amendment 4 forbids git+https:// for chat_nextseek: {line!r}"
            )

    # Amendment 4: vendored COPY + local install pair.
    assert "COPY vendor/chat_nextseek /tmp/chat_nextseek" in text, (
        "Amendment 4 requires `COPY vendor/chat_nextseek /tmp/chat_nextseek` in "
        "the Dockerfile (vendored-source install)."
    )
    assert re.search(r"uv pip install\b.*/tmp/chat_nextseek", text), (
        "Amendment 5 v3 requires a `uv pip install ... /tmp/chat_nextseek` "
        "line consuming the COPY destination (no --system; venv-on-PATH "
        "provides interpreter resolution)."
    )

    # R4-NEW-5 ordering: chat_nextseek install line follows uv sync line.
    sync_match = re.search(r"uv sync --locked", text)
    pip_match = re.search(r"uv pip install\b.*/tmp/chat_nextseek", text)
    assert sync_match is not None and pip_match is not None
    assert sync_match.start() < pip_match.start(), (
        "chat_nextseek install must follow `uv sync --locked`."
    )

    # AMD3-M2 leftover guard: no placeholder.
    assert "<CHAT_NEXTSEEK_REV>" not in text, (
        "Dockerfile contains the literal placeholder `<CHAT_NEXTSEEK_REV>`."
    )

    # Amendment 7 v2 (2026-04-30): markitdown was REMOVED from the image
    # entirely. It lives in the sibling build_tools/ uv project (host-only).
    # The image runtime never imports markitdown. Drift guards below assert
    # that markitdown stays out of both the Dockerfile and the bridge
    # pyproject.toml.
    assert "markitdown" not in text, (
        "Amendment 7 v2 forbids any markitdown reference in the Dockerfile. "
        "markitdown is host-only (lives under build_tools/); the image needs "
        "the COPYd doc artifacts, not the library that generates them."
    )

    pyproject = REPO_ROOT / "pyproject.toml"
    pyproject_text = pyproject.read_text(encoding="utf-8")
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "markitdown" not in stripped, (
            f"Amendment 7 v2 forbids an active markitdown dep in bridge "
            f"pyproject.toml (it lives under build_tools/); found: {line!r}"
        )

    # Amendment 7 v2: the build_tools sibling project must declare its own
    # pyproject.toml and own lockfile so the bridge lockfile stays portable.
    build_tools_pyproject = REPO_ROOT / "build_tools" / "pyproject.toml"
    assert build_tools_pyproject.is_file(), (
        "Amendment 7 v2 requires build_tools/pyproject.toml (sibling uv "
        "project for host-only markitdown-based doc ingestion)."
    )
    build_tools_lock = REPO_ROOT / "build_tools" / "uv.lock"
    assert build_tools_lock.is_file(), (
        "Amendment 7 v2 requires build_tools/uv.lock (run `cd build_tools "
        "&& uv lock` if absent)."
    )
