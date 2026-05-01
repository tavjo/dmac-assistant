"""Gate test: build_tools/ must not import smart-form-tool's heavy RAG deps."""
from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN = re.compile(
    r"^\s*(?:from|import)\s+(baml|duckdb|leiden|smart_form|openai)\b",
    re.MULTILINE,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_TOOLS = REPO_ROOT / "build_tools"


def test_build_tools_has_no_forbidden_imports() -> None:
    # Skip virtualenv directories — third-party transitive deps inside the
    # build_tools .venv (e.g. speech_recognition's optional `import openai`)
    # are not part of our source and must not be scanned.
    excluded_parts = {".venv", "site-packages", "__pycache__", ".tox", "build", "dist"}

    violations: list[tuple[Path, str]] = []
    for py in BUILD_TOOLS.rglob("*.py"):
        if any(part in excluded_parts for part in py.parts):
            continue
        src = py.read_text()
        for match in FORBIDDEN.finditer(src):
            violations.append((py.relative_to(REPO_ROOT), match.group(0).strip()))
    assert violations == [], (
        "build_tools/ contains forbidden imports (smart-form-tool RAG framework):\n"
        + "\n".join(f"  {p}: {line}" for p, line in violations)
    )
