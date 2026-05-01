"""Integration tests for the ingest-nextseek-docs Makefile target."""
from __future__ import annotations

import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
MAKEFILE = REPO_ROOT / "Makefile"


def test_makefile_exists() -> None:
    assert MAKEFILE.exists()


def test_makefile_recipe_uses_tab_indentation() -> None:
    """GNU and BSD make both require tabs for recipe lines."""
    content = MAKEFILE.read_text()
    lines = content.splitlines()
    inside_recipe = False
    recipe_lines: list[str] = []
    for line in lines:
        if line.startswith("ingest-nextseek-docs:"):
            inside_recipe = True
            continue
        if inside_recipe:
            if not line:
                break
            if line[0] not in (" ", "\t"):
                break
            recipe_lines.append(line)

    assert recipe_lines, "no recipe lines found under ingest-nextseek-docs target"
    for recipe_line in recipe_lines:
        assert recipe_line.startswith("\t"), (
            f"recipe line must start with TAB, got: {recipe_line!r}"
        )


def test_phony_declaration_includes_ingest_target() -> None:
    content = MAKEFILE.read_text()
    assert "ingest-nextseek-docs" in content
    phony_lines = [line for line in content.splitlines() if line.strip().startswith(".PHONY")]
    assert any("ingest-nextseek-docs" in line for line in phony_lines), (
        "ingest-nextseek-docs must be declared .PHONY"
    )


def test_make_dry_run_shows_uv_command() -> None:
    """make -n prints the commands that would run."""
    result = subprocess.run(
        ["make", "-n", "ingest-nextseek-docs", "ARGS=--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "uv run --project build_tools python -m build_tools.ingest_nextseek_docs" in combined
    assert "--help" in combined


def test_make_help_exits_zero_and_prints_argparse_help() -> None:
    """Actually invoking make with ARGS=--help runs through to argparse help."""
    result = subprocess.run(
        ["make", "ingest-nextseek-docs", "ARGS=--help"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"exit={result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "--force" in result.stdout
    assert "--help" in result.stdout
