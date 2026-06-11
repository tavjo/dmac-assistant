"""Build-and-introspect tests for the dmac-assistant Docker image."""
from __future__ import annotations

import re
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
    # T11 (U-11): the agent image no longer COPYs vendor/chat_nextseek, so the
    # vendor-presence prereq moved to the SIDECAR image pin
    # (test_sidecar_dockerfile_keeps_vendored_chat_nextseek below). The agent
    # build needs only the committed build_context tree.
    build_context = REPO_ROOT / "build_context"
    assert (build_context / "plugins" / "nextseek").is_dir(), (
        "build_context/plugins/nextseek must be populated by the B13 snapshot "
        "and plugin staging commits before image builds; `make image-build` "
        "must not restage the legacy nextseek-api plugin."
    )

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
        "/app/docs/nextseek/README.md /app/plugins/nextseek "
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
    # Derive the pinned version from the Dockerfile so this tracks the pin
    # automatically across bumps (no hardcoded literal to drift). The
    # streamjson fixture test independently forces a per-version fixture.
    dockerfile = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    match = re.search(r"claude-code@([0-9.]+)", dockerfile)
    assert match, "could not find claude-code@<version> pin in Dockerfile"
    pinned = match.group(1)
    result = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "claude", built_image, "--version"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert pinned in result.stdout, f"expected pinned {pinned}, got {result.stdout!r}"


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

    # Claude Code 2.1.158+ ships `claude` as a native compiled binary (ELF),
    # not a node-shebang script as older npm builds did. Either is a "real"
    # binary; the guard is against a hand-rolled stub/shim. Read raw bytes
    # (text=False) since the file may be a binary that is not valid UTF-8.
    result2 = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "sh", built_image, "-c", "head -c 4 /usr/local/bin/claude"],
        capture_output=True,
        check=False,
    )
    assert result2.returncode == 0, result2.stderr
    head4 = result2.stdout  # bytes
    assert head4.startswith(b"\x7fELF") or head4.startswith(b"#!"), (
        f"claude is neither an ELF binary nor a shebang script; head4={head4!r}"
    )


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
    drift guards (no SSH, no git+ URLs) preserved; the vendored COPY +
    install pins are INVERTED by T11 (chat_nextseek/torch stripped from
    the agent image — sidecar-only per U-11).
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

    # T11 (U-11, resolves OI-2): chat_nextseek + torch are STRIPPED from the
    # agent image — they live only in the sidecar image (sidecar/Dockerfile).
    # Inverts the Amendment 4/5 vendored-install pins that used to live here.
    assert "COPY vendor/chat_nextseek" not in text, (
        "T11 forbids `COPY vendor/chat_nextseek` in the AGENT Dockerfile. "
        "chat_nextseek is sidecar-only (U-11); the sidecar image keeps the "
        "vendored COPY in sidecar/Dockerfile."
    )
    assert re.search(r"uv pip install\b[^\n]*chat_nextseek", text) is None, (
        "T11 forbids installing chat_nextseek into the agent image."
    )
    assert re.search(r"uv pip install\b[^\n]*\btorch\b", text) is None, (
        "T11 forbids the torch-cpu install in the agent image (it existed "
        "only to satisfy chat_nextseek's sentence-transformers dependency)."
    )

    # AMD3-M2 leftover guard: no placeholder.
    assert "<CHAT_NEXTSEEK_REV>" not in text, (
        "Dockerfile contains the literal placeholder `<CHAT_NEXTSEEK_REV>`."
    )

    # Amendment 7 v2 (2026-04-30) removed markitdown from the image. The
    # 2026-05-04 docs-ingest stabilization removes it from build_tools too.
    # Drift guards below assert it stays out of both the Dockerfile and the
    # bridge pyproject.toml.
    assert "markitdown" not in text, (
        "Amendment 7 v2 forbids any markitdown reference in the Dockerfile. "
        "The image needs the COPYd doc artifacts, not the old PDF conversion "
        "library."
    )

    pyproject = REPO_ROOT / "pyproject.toml"
    pyproject_text = pyproject.read_text(encoding="utf-8")
    for line in pyproject_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        assert "markitdown" not in stripped, (
            f"Amendment 7 v2 forbids an active markitdown dep in bridge "
            f"pyproject.toml; found: {line!r}"
        )

    # The build_tools sibling project must declare its own pyproject.toml and
    # own lockfile so the bridge lockfile stays portable.
    build_tools_pyproject = REPO_ROOT / "build_tools" / "pyproject.toml"
    assert build_tools_pyproject.is_file(), (
        "build_tools/pyproject.toml is required for host-only doc ingestion."
    )
    build_tools_lock = REPO_ROOT / "build_tools" / "uv.lock"
    assert build_tools_lock.is_file(), (
        "Amendment 7 v2 requires build_tools/uv.lock (run `cd build_tools "
        "&& uv lock` if absent)."
    )


def test_dockerfile_copies_only_new_plugin():
    """Plan-body B14.3: Dockerfile uses the plugin-specific COPY form,
    contains zero references to legacy plugin paths,
    and references /app/plugins/nextseek/bin in the PATH ENV. Closes
    Wave-4 carryover risk #3 at the file-text level (paired with the
    behavioral assertions in test_image_smoke.py). The docs copy at
    /app/docs/nextseek-api/ is intentionally allowed.
    """
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY build_context/plugins/nextseek/ /app/plugins/nextseek/" in text, (
        "Dockerfile MUST contain the plugin-specific COPY "
        "(COPY build_context/plugins/nextseek/ /app/plugins/nextseek/). "
        "Found no match - likely still using the broad COPY form."
    )
    active_lines = "\n".join(
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    forbidden_plugin_paths = [
        "/app/plugins/nextseek-api",
        "build_context/plugins/nextseek-api",
    ]
    leaked = [path for path in forbidden_plugin_paths if path in active_lines]
    assert not leaked, (
        "Dockerfile still references legacy plugin path(s) in active instructions: "
        f"{leaked}. D25 amended requires the image to ship only the new "
        "plugin. The legacy plugin tree is preserved under "
        "build_context/plugins/nextseek-api/ (host-side codebase) but MUST "
        "NOT appear in Dockerfile plugin COPY/PATH instructions."
    )
    assert "/app/plugins/nextseek/bin" in text, (
        "Dockerfile MUST add /app/plugins/nextseek/bin to PATH so the in-image "
        "agent finds nextseek-entity-extract et al. Wave-4 carryover risk #3 "
        "is NOT closed without this."
    )
    assert 'test -n "$(ls /app/plugins/nextseek/context/min_*.json' in text, (
        "Dockerfile MUST contain the NEW-6 build-time catalog-presence guard "
        "so silent-empty-snapshot fails closed at docker build time. Pairs "
        "with B13's host-side test -d guard."
    )


def test_agent_image_ships_thin_client_modules():
    """T11 (U-11): runner_ns.py at /opt/dmac/ needs its sibling helper modules
    (_ws_contract / _assistant_models / _assistant_client / _sidecar_client)
    COPY'd next to it — the /opt/dmac path is outside the plugin bin dir that
    rides along via the broad plugin COPY."""
    text = (REPO_ROOT / "Dockerfile").read_text(encoding="utf-8")
    for mod in (
        "_ws_contract.py",
        "_assistant_models.py",
        "_assistant_client.py",
        "_sidecar_client.py",
    ):
        assert (
            f"COPY build_context/plugins/nextseek/bin/{mod} /opt/dmac/{mod}"
            in text
        ), (
            f"Dockerfile must COPY {mod} to /opt/dmac/ so runner_ns.py can "
            "import it (T11 step 1)."
        )


def test_sidecar_dockerfile_keeps_vendored_chat_nextseek():
    """T11: the vendored chat_nextseek install MOVED to the sidecar image.
    This is the relocated vendor-presence guard from the old agent-image
    `built_image` fixture: the SIDECAR Dockerfile must keep the vendored
    COPY (sidecar builds require `make sync-vendor-deps` first)."""
    text = (REPO_ROOT / "sidecar" / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY vendor/chat_nextseek" in text, (
        "sidecar/Dockerfile must keep `COPY vendor/chat_nextseek` — the "
        "sidecar is the ONLY image that ships chat_nextseek (U-11)."
    )


def test_image_build_does_not_restage_legacy_plugin():
    """B14: official image builds consume the committed new-plugin context.

    Running `image-stage` before `docker build` would wipe build_context/ and
    restage the old nextseek-api plugin, making the narrowed Dockerfile fail or
    ship stale artifacts. B13 owns catalog snapshots; B14 owns consuming them.
    """
    text = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    import re

    match = re.search(r"^image-build:\s*(?P<deps>.*)$", text, re.MULTILINE)
    assert match is not None, "Makefile must define an image-build target."
    deps = match.group("deps").split()
    assert "sync-vendor-deps" in deps, (
        "image-build must still sync vendored chat_nextseek before docker build."
    )
    assert "image-stage" not in deps, (
        "image-build must not run image-stage after B14; image-stage still "
        "defaults to the legacy nextseek-api source and would clobber the "
        "committed build_context/plugins/nextseek tree."
    )
