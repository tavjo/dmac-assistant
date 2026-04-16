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
        "/app/plugins/nextseek-api /usr/local/bin/entrypoint.sh; do "
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
def test_uv_prewarm_imports_succeed(built_image: str) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "uv",
            built_image,
            "run",
            "--with",
            "httpx",
            "--with",
            "pydantic",
            "--with",
            "python-dotenv",
            "--with",
            "markitdown",
            "python",
            "-c",
            "import httpx, pydantic, dotenv, markitdown; print('IMPORT_OK')",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_OK" in result.stdout


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
