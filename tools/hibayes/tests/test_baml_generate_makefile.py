"""tools/hibayes/tests/test_baml_generate_makefile.py — Makefile pinning for task-7R1.

Pins the `baml-generate` target + `BAML_CLIENT_SENTINEL` / `BAML_SOURCES`
variables + Stage C prereq wiring. DD-07 exempt; these tests are the contract.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
MAKEFILE_PATH = REPO_ROOT / "Makefile"


def _makefile_text() -> str:
    return MAKEFILE_PATH.read_text(encoding="utf-8")


def test_baml_client_sentinel_variable_defined() -> None:
    """`BAML_CLIENT_SENTINEL ?= tools/e2e/baml_client/sync_client.py` is declared."""
    text = _makefile_text()
    assert re.search(
        r"^BAML_CLIENT_SENTINEL\s*\?=\s*tools/e2e/baml_client/sync_client\.py\s*$",
        text,
        flags=re.MULTILINE,
    ), "Makefile missing `BAML_CLIENT_SENTINEL ?= tools/e2e/baml_client/sync_client.py`"


def test_baml_sources_variable_defined() -> None:
    """`BAML_SOURCES := $(wildcard baml_src/*.baml)` is declared (simply-expanded)."""
    text = _makefile_text()
    assert re.search(
        r"^BAML_SOURCES\s*:=\s*\$\(wildcard\s+baml_src/\*\.baml\)\s*$",
        text,
        flags=re.MULTILINE,
    ), "Makefile missing `BAML_SOURCES := $(wildcard baml_src/*.baml)`"


def test_baml_client_sentinel_file_target_rule_exists() -> None:
    """`$(BAML_CLIENT_SENTINEL): $(BAML_SOURCES)` rule exists with a `uv run baml-cli generate` recipe.

    Per the uv-project convention used everywhere else in this Makefile (`@uv run python -m ...`),
    the BAML codegen invocation MUST be `uv run baml-cli` (NOT bare `baml-cli`), so the
    `.venv`-pinned `baml-py` console-script is used regardless of the developer's PATH.
    """
    text = _makefile_text()
    # Match the rule header + at least one recipe line containing `uv run baml-cli generate --from baml_src`.
    # Optional `@` silencing prefix (consistent with other Make recipe lines in this file).
    pattern = (
        r"^\$\(BAML_CLIENT_SENTINEL\):\s+\$\(BAML_SOURCES\)\s*\n"
        r"(?:\t.*\n)*?"   # zero or more recipe lines (tab-indented)
        r"\t@?uv\s+run\s+baml-cli\s+generate\s+--from\s+baml_src\s*$"
    )
    assert re.search(pattern, text, flags=re.MULTILINE), (
        "Makefile missing `$(BAML_CLIENT_SENTINEL): $(BAML_SOURCES)` rule with "
        "`uv run baml-cli generate --from baml_src` recipe"
    )


def test_baml_generate_alias_is_phony_and_aliases_sentinel() -> None:
    """`.PHONY: baml-generate` declared AND `baml-generate: $(BAML_CLIENT_SENTINEL)` alias exists."""
    text = _makefile_text()
    assert re.search(r"^\.PHONY:\s+baml-generate\b", text, flags=re.MULTILINE), (
        "Makefile missing `.PHONY: baml-generate` declaration"
    )
    assert re.search(
        r"^baml-generate:\s+\$\(BAML_CLIENT_SENTINEL\)\s*$",
        text,
        flags=re.MULTILINE,
    ), "Makefile missing `baml-generate: $(BAML_CLIENT_SENTINEL)` alias"


def test_stage_c_csv_depends_on_baml_client_sentinel() -> None:
    """`$(FUNCTIONAL_USEFULNESS_CSV)` rule lists `$(BAML_CLIENT_SENTINEL)` as a prereq."""
    text = _makefile_text()
    # Match the Stage C rule header line and assert the sentinel appears in its prereq list
    # BEFORE the first newline (file prereqs are space-separated on the rule line; order-only
    # prereqs after `|` would be unacceptable for this task — sentinel must drive mtime).
    match = re.search(
        r"^\$\(FUNCTIONAL_USEFULNESS_CSV\):\s+([^\n]+)$",
        text,
        flags=re.MULTILINE,
    )
    assert match is not None, "Makefile missing `$(FUNCTIONAL_USEFULNESS_CSV):` rule header"
    prereq_line = match.group(1)
    # Sentinel must appear as a file prereq, NOT after `|` (order-only).
    pre_order_only = prereq_line.split("|", 1)[0]
    assert "$(BAML_CLIENT_SENTINEL)" in pre_order_only, (
        f"`$(BAML_CLIENT_SENTINEL)` not found as a file prereq of "
        f"`$(FUNCTIONAL_USEFULNESS_CSV)` (prereq line: {prereq_line!r})"
    )


def test_make_dry_run_baml_generate_mentions_baml_cli() -> None:
    """`make --dry-run baml-generate` on a clean (sentinel-absent) state references `baml-cli generate`.

    Functional smoke — Make's parser actually resolves the rule and prints the recipe.
    Skipped if `make` is unavailable; sentinel file is moved aside temporarily so the
    rule is guaranteed to fire (dry-run does not modify the FS even if it weren't).
    """
    import shutil

    if shutil.which("make") is None:
        pytest.skip("`make` not available in test environment")
    sentinel = REPO_ROOT / "tools" / "e2e" / "baml_client" / "sync_client.py"
    backup = sentinel.with_suffix(".py.bak-pinning-test")
    moved = False
    if sentinel.exists():
        sentinel.rename(backup)
        moved = True
    try:
        result = subprocess.run(
            ["make", "--dry-run", "baml-generate"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, (
            f"`make --dry-run baml-generate` exited {result.returncode}; stderr: {result.stderr!r}"
        )
        assert "baml-cli generate --from baml_src" in result.stdout, (
            f"`make --dry-run baml-generate` did not mention `baml-cli generate --from baml_src`; "
            f"stdout: {result.stdout!r}"
        )
    finally:
        if moved:
            backup.rename(sentinel)
