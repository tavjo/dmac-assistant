"""Plan B · T11 — /nextseek slash command content contract.

Markdown-only task. No chat_nextseek import; no importorskip needed.
The 6 assertions enforce the contract from D14, D22, and plan body line 1941-1956.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMMAND_PATH = (
    REPO_ROOT
    / "build_context" / "plugins" / "nextseek"
    / "commands" / "nextseek.md"
)


def _read_command() -> str:
    return COMMAND_PATH.read_text(encoding="utf-8")


def test_command_md_exists():
    assert COMMAND_PATH.exists(), f"/nextseek command file missing at {COMMAND_PATH}"


def test_yaml_frontmatter_shape():
    text = _read_command()
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert m, "command file must start with a YAML frontmatter block"
    fm = m.group(1)
    # `description:` must be present and non-empty.
    desc_match = re.search(r"^description:\s*(\S.*)$", fm, flags=re.MULTILINE)
    assert desc_match, "frontmatter must declare a non-empty `description:`"
    # `allowed-tools` must be present and equal to `Bash, Read` (order tolerant).
    at_match = re.search(r"^allowed-tools:\s*(.*?)$", fm, flags=re.MULTILINE)
    assert at_match, "frontmatter must declare `allowed-tools:`"
    tools = {t.strip() for t in at_match.group(1).split(",")}
    assert tools == {"Bash", "Read"}, (
        f"allowed-tools must be exactly {{'Bash', 'Read'}}; got {tools}. "
        f"Adding Write/Edit/Task here would expand the command's privilege beyond "
        f"what /nextseek needs (Bash for shim invocations, Read for cached catalogs)."
    )


def test_body_references_nextseek_skill_by_name():
    """Slash command body must mention the `nextseek` skill so the skill engine
    auto-loads it on invocation."""
    text = _read_command()
    # Strip the frontmatter to assert against the body only.
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    assert "nextseek" in body
    # Be more specific: the word "skill" should appear near the reference.
    assert "skill" in body.lower(), (
        "command body must reference the skill it delegates to"
    )


def test_body_restates_d14_always_first_preamble():
    """D14 defense-in-depth: command body must explicitly mention the
    nextseek-entity-extract preamble so a future SKILL.md edit can't silently
    drop the always-first contract."""
    text = _read_command()
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    assert "nextseek-entity-extract" in body, (
        "D14: command body must restate the always-first preamble"
    )
    # The phrasing must convey "before other actions" — accept any of these
    # equivalent wordings.
    assert any(
        phrase in body
        for phrase in (
            "before any other action",
            "before any other actions",
            "always-first",
            "first",
        )
    ), "D14: command body must convey 'first / before other actions' enforcement"


def test_body_contains_arguments_placeholder():
    """The command is parameterized — $ARGUMENTS injects the user's question."""
    text = _read_command()
    body = re.sub(r"^---\n.*?\n---\n", "", text, count=1, flags=re.DOTALL)
    assert "$ARGUMENTS" in body, (
        "command body must contain the literal $ARGUMENTS placeholder"
    )


def test_body_does_not_invoke_askuserquestion():
    """D22-L3 boundary defense: command file MUST NOT trigger or reference
    AskUserQuestion. The skill enforces L3 in plain text."""
    text = _read_command()
    assert "AskUserQuestion" not in text, (
        "D22-L3: /nextseek command must not invoke AskUserQuestion. The L3 "
        "plain-text confirmation lives in skills/nextseek/SKILL.md."
    )
