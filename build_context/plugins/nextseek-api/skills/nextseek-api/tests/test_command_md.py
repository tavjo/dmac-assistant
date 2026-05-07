"""
Structural tests for commands/nextseek-api.md.

These tests parse the frontmatter with pyyaml and assert the required keys
exist, and grep the body for a reference to the nextseek-api skill.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


# skills/nextseek-api/tests/test_command_md.py — 4 parents up = plugin root
PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
COMMAND_FILE = PLUGIN_ROOT / "commands" / "nextseek-api.md"


def _split_frontmatter(content: str) -> tuple[dict, str]:
    """
    Split a markdown file's YAML frontmatter from its body.

    Returns a tuple of (parsed_frontmatter_dict, body_str).
    Raises ValueError if the file does not start with '---\\n' or the
    closing '---\\n' delimiter is missing.
    """
    if not content.startswith("---\n"):
        raise ValueError("File does not start with YAML frontmatter delimiter '---'")
    # Find the closing delimiter on its own line
    match = re.search(r"\n---\n", content[4:])
    if not match:
        raise ValueError("Closing '---' frontmatter delimiter not found")
    fm_raw = content[4 : 4 + match.start()]
    body = content[4 + match.end() :]
    fm = yaml.safe_load(fm_raw) or {}
    return fm, body


@pytest.fixture
def command_frontmatter_and_body() -> tuple[dict, str]:
    assert COMMAND_FILE.is_file(), f"{COMMAND_FILE} does not exist"
    content = COMMAND_FILE.read_text()
    return _split_frontmatter(content)


# ----- Test 1 -----
def test_frontmatter_has_description(command_frontmatter_and_body) -> None:
    """The frontmatter must declare a non-empty `description` string."""
    fm, _body = command_frontmatter_and_body
    assert "description" in fm, f"Missing 'description' key in frontmatter: {fm}"
    desc = fm["description"]
    assert isinstance(desc, str), f"description must be a string, got {type(desc)}"
    assert len(desc.strip()) >= 20, (
        f"description too short ({len(desc.strip())} chars); needs a meaningful summary"
    )
    # Must mention NExtSEEK to be searchable in the slash command picker
    assert "NExtSEEK" in desc or "nextseek" in desc.lower(), (
        f"description must mention NExtSEEK so the slash picker is searchable: {desc!r}"
    )


# ----- Test 2 -----
def test_frontmatter_has_argument_hint(command_frontmatter_and_body) -> None:
    """The frontmatter must declare an `argument-hint` string."""
    fm, _body = command_frontmatter_and_body
    assert "argument-hint" in fm, f"Missing 'argument-hint' key in frontmatter: {fm}"
    hint = fm["argument-hint"]
    assert isinstance(hint, str), f"argument-hint must be a string, got {type(hint)}"
    assert len(hint.strip()) > 0, "argument-hint must not be empty"


# ----- Test 3 -----
def test_body_references_skill(command_frontmatter_and_body) -> None:
    """The markdown body must tell Claude to load the nextseek-api skill."""
    _fm, body = command_frontmatter_and_body
    assert "nextseek-api" in body, (
        "Body must reference the nextseek-api skill by name"
    )
    # The body should use the word 'skill' explicitly so Claude unambiguously
    # knows to load the SKILL.md workflow rather than execute inline instructions.
    assert re.search(r"\bskill\b", body, re.IGNORECASE), (
        "Body must use the word 'skill' so Claude loads the SKILL.md workflow"
    )


# ----- Test 4 (DD-4) -----
def test_body_references_nextseek_spec_not_get(command_frontmatter_and_body) -> None:
    """DD-4 (task-06a): command must reference nextseek-spec, never nextseek-get."""
    _fm, body = command_frontmatter_and_body
    content = COMMAND_FILE.read_text()
    assert "nextseek-get" not in content, (
        "DD-4: command file must not mention the old nextseek-get shim name"
    )
    assert "nextseek-spec" in body, (
        "DD-4: command body must mention the new nextseek-spec shim"
    )
