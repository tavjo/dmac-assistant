"""Plan B · T10 — SKILL.md content contract.

Markdown-only task. No chat_nextseek import; no importorskip needed.
The 9 assertions enforce the load-bearing invariants from D14, D19, D22,
CRITICAL-3, CRITICAL-4, and NEW-3.
"""
from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PATH = (
    REPO_ROOT
    / "build_context" / "plugins" / "nextseek"
    / "skills" / "nextseek" / "SKILL.md"
)

EIGHT_SHIM_NAMES = (
    "nextseek-entity-extract",
    "nextseek-parse",
    "nextseek-plan",
    "nextseek-api-read",
    "nextseek-api-write",
    "nextseek-graph",
    "nextseek-report",
    "nextseek-generate-submission",
)

SIX_EXIT_CODES = (
    "CONFIG_MISSING",
    "IMPORT_FAILED",
    "VALIDATION",
    "AGENT_FAILED",
    "WRITE_BLOCKED",
    "CONFIG_ERROR",
)


def _read_skill() -> str:
    return SKILL_PATH.read_text(encoding="utf-8")


def test_skill_md_exists():
    assert SKILL_PATH.exists(), f"SKILL.md missing at {SKILL_PATH}"


def test_yaml_frontmatter_shape():
    text = _read_skill()
    # Frontmatter is the first --- ... --- block at the very top.
    m = re.match(r"^---\n(.*?)\n---\n", text, flags=re.DOTALL)
    assert m, "SKILL.md must start with a YAML frontmatter block"
    fm = m.group(1)
    assert re.search(r"^name:\s*nextseek\s*$", fm, flags=re.MULTILINE), (
        "frontmatter must declare `name: nextseek`"
    )
    assert re.search(r"^disable-model-invocation:\s*false\s*$", fm, flags=re.MULTILINE), (
        "frontmatter must declare `disable-model-invocation: false`"
    )


def test_d14_always_first_preamble_present():
    """D14: every /nextseek invocation MUST run nextseek-entity-extract first."""
    text = _read_skill()
    assert "## Always-first preamble" in text
    # The exact bash command from plan body line 1833.
    assert "nextseek-entity-extract --query" in text
    # The 'never skip' enforcement phrasing.
    assert "Never skip" in text or "never skip" in text


def test_d19_dmac_path_mappings_referenced():
    """D19 / NEW-3: SKILL.md reads DMAC_PATH_MAPPINGS, never hard-codes the
    /persistent/output/{user_id} literal."""
    text = _read_skill()
    assert "DMAC_PATH_MAPPINGS" in text, (
        "Reply hygiene subsection must reference DMAC_PATH_MAPPINGS"
    )
    assert "/persistent/output/{user_id}" not in text, (
        "FORBIDDEN: SKILL.md must not hard-code /persistent/output/{user_id} "
        "(D19 / NEW-3)"
    )


def test_d22_l3_plain_text_prompt_no_askuserquestion():
    """D22-L3: SKILL.md MUST forbid AskUserQuestion and provide a plain-text
    confirmation template instead."""
    text = _read_skill()
    # L3 plain-text template (verbatim phrase from plan body line 1891).
    assert "About to execute a WRITE-classified operation" in text
    # The prohibition: 'NEVER' must precede 'AskUserQuestion' nearby.
    pattern = re.compile(r"\*?\*?NEVER\*?\*?[^\n]{0,64}AskUserQuestion", re.MULTILINE)
    assert pattern.search(text), (
        "D22-L3: SKILL.md must explicitly forbid AskUserQuestion"
    )
    # AskUserQuestion appears EXACTLY once — only inside the prohibition.
    assert text.count("AskUserQuestion") == 1, (
        f"AskUserQuestion must appear exactly once (the prohibition); "
        f"found {text.count('AskUserQuestion')}"
    )


def test_critical_3_4_api_write_excluded_from_l1():
    """CRITICAL-3 + CRITICAL-4: SKILL.md's Layer-1 description must state
    nextseek-api-write is NOT allowlisted."""
    text = _read_skill()
    # Find the Layer-1 sentence(s) and check api-write is mentioned with a
    # negative qualifier nearby.
    l1_section = re.search(
        r"\*\*Layer 1[^\n]*\*\*[^\n]*\n(?:[^\n]+\n){0,4}",
        text,
    )
    assert l1_section, "SKILL.md must contain a 'Layer 1' bold-prefixed paragraph"
    chunk = l1_section.group(0)
    assert "nextseek-api-write" in chunk, (
        "Layer-1 description must mention nextseek-api-write"
    )
    assert ("not allowlisted" in chunk
            or "are not allowlisted" in chunk
            or "is not allowlisted" in chunk), (
        "Layer-1 description must qualify nextseek-api-write as 'not allowlisted'"
    )


def test_tool_catalog_lists_all_eight_shims():
    text = _read_skill()
    assert "## Tool catalog" in text
    for shim in EIGHT_SHIM_NAMES:
        assert shim in text, f"Tool catalog must reference shim: {shim}"


def test_routing_decision_tree_present():
    text = _read_skill()
    assert "## Routing decision tree" in text
    # The 5 numbered routing rules from plan body line 1866-1870.
    for n in range(1, 6):
        assert re.search(rf"^{n}\.\s", text, flags=re.MULTILINE), (
            f"Routing decision tree must contain rule {n}."
        )


def test_errors_section_lists_all_six_runner_codes():
    """Errors block must enumerate the 6 exit-code mnemonics that
    _nextseek_runner.py emits, so the in-image agent can interpret them."""
    text = _read_skill()
    assert "## Errors" in text
    for code in SIX_EXIT_CODES:
        assert code in text, f"Errors section must document exit code {code}"
