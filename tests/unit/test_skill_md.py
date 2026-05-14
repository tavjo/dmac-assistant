"""SKILL.md content contract for the single-shot nextseek workflow.

Markdown-only task. No chat_nextseek import; no importorskip needed.
The assertions enforce load-bearing invariants of the single-shot design
that replaced the modular plan: D19 (DMAC_PATH_MAPPINGS) and NEW-3 still
hold; the modular-specific D14 / D22-L3 / CRITICAL-3 / CRITICAL-4 / tool-
catalog / routing-decision-tree assertions were rewritten for the single-
shot SKILL.md when the modular plugin was retired (faster path).
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

CAPABILITY_MATRIX_TOOLS = (
    "nextseek-query",
    "nextseek-api-write",
    "nextseek-generate-submission",
    "nextseek-report",
    "nextseek-entity-extract",
    "nextseek-parse",
    "nextseek-plan",
    "nextseek-api-read",
    "nextseek-graph",
)

FOUR_ESCAPE_HATCH_HEADINGS = (
    "### 1. Writes",
    "### 2. Submission generation",
    "### 3. Project summary reports",
    "### 4. Debugging / structured plan inspection",
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


def test_default_path_is_single_nextseek_query_call():
    """Single-shot replacement for D14: every /nextseek invocation defaults to
    one `nextseek-query` call that runs the full pipeline internally; the
    SKILL.md must expressly forbid pre-calling the fine-grained shims."""
    text = _read_skill()
    assert "## Default path: `nextseek-query`" in text, (
        "SKILL.md must declare `nextseek-query` as the default path"
    )
    # The canonical bash invocation.
    assert 'nextseek-query --query "' in text, (
        "SKILL.md must show the `nextseek-query --query \"...\"` pattern"
    )
    # The prohibition on running fine-grained shims first (the load-bearing
    # difference vs the retired modular design).
    assert "Do not run `nextseek-entity-extract`" in text, (
        "SKILL.md must forbid pre-calling nextseek-entity-extract"
    )
    assert "`nextseek-parse`" in text and "`nextseek-plan`" in text, (
        "SKILL.md must name nextseek-parse and nextseek-plan in the same "
        "prohibition (load-bearing — these are the discarded modular shims)"
    )


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


def test_l3_forbids_askuserquestion_and_uses_plain_text_prompt():
    """L3 (write-safety behavioral layer) survives the modular→single-shot
    pivot: SKILL.md MUST forbid AskUserQuestion and provide the plain-text
    confirmation template. The widget cannot render in the chat UI, so this
    is a load-bearing user-facing invariant for any write operation."""
    text = _read_skill()
    # L3 plain-text template — verbatim phrase the in-container agent emits
    # before invoking nextseek-api-write.
    assert "About to execute a WRITE-classified operation" in text
    # The prohibition: 'NEVER' must precede 'AskUserQuestion' nearby.
    pattern = re.compile(r"\*?\*?NEVER\*?\*?[^\n]{0,64}AskUserQuestion", re.MULTILINE)
    assert pattern.search(text), (
        "SKILL.md must explicitly forbid AskUserQuestion at the L3 boundary"
    )
    # Every line that mentions AskUserQuestion must do so in a prohibition
    # context (NEVER/MUST be plain text/does not render). A permissive usage
    # — e.g. "use AskUserQuestion to confirm" — would break the chat UI and
    # is the failure mode this assertion guards against.
    askuser_lines = [
        line for line in text.splitlines() if "AskUserQuestion" in line
    ]
    assert askuser_lines, "AskUserQuestion must be referenced at the L3 boundary"
    negative_pattern = re.compile(
        r"(NEVER|never|forbid|MUST be plain text|does not render|doesn't render|"
        r"can't render|don't|do not)",
        re.IGNORECASE,
    )
    for line in askuser_lines:
        assert negative_pattern.search(line), (
            f"every AskUserQuestion mention must carry a negative qualifier; "
            f"offending line: {line!r}"
        )


def test_layer_1_describes_dangerously_skip_permissions_bypass():
    """In the single-shot SKILL.md, Layer 1 (Claude Code permission allowlist)
    is described as BYPASSED in the dmac-assistant POC because the in-
    container Claude runs with `--dangerously-skip-permissions`. L2 (the
    `--confirmed-write` shim refusal) and L3 (the behavioral prompt) are the
    load-bearing layers. This test pins that contract so a future SKILL.md
    edit can't silently elevate L1 back to load-bearing status without
    updating the deployment story."""
    text = _read_skill()
    # The L1 paragraph must reference --dangerously-skip-permissions.
    assert "--dangerously-skip-permissions" in text, (
        "Layer 1 description must reference --dangerously-skip-permissions "
        "(the reason L1 is bypassed in the POC)"
    )
    # The bypass status must be explicit (not implied).
    assert "BYPASSED" in text, (
        "Layer 1 description must state BYPASSED for the POC"
    )
    # The defense-in-depth qualifier protects against future drift.
    assert "defense-in-depth" in text or "defence-in-depth" in text, (
        "Layer 1 must be described as defense-in-depth (not as a guarantee)"
    )
    # L2 and L3 must be named explicitly as the load-bearing layers.
    assert "L2 and L3" in text or "L3 and L2" in text, (
        "Write-safety section must name L2 and L3 as the load-bearing layers"
    )


def test_tool_capability_matrix_lists_all_known_tools():
    """Single-shot replacement for `test_tool_catalog_lists_all_eight_shims`.
    The single-shot SKILL.md has a capability matrix (not the modular
    'Tool catalog' heading); it documents one default tool plus the escape-
    hatch shims (which still exist as debug probes)."""
    text = _read_skill()
    assert "## Tool capability matrix" in text, (
        "SKILL.md must have a `## Tool capability matrix` section"
    )
    for tool in CAPABILITY_MATRIX_TOOLS:
        assert tool in text, (
            f"Tool capability matrix must reference: {tool}"
        )


def test_escape_hatch_section_lists_four_categories():
    """Single-shot replacement for `test_routing_decision_tree_present`. The
    single-shot design replaces the modular routing decision tree with a
    four-category escape-hatch section listing when to depart from the
    default `nextseek-query` path."""
    text = _read_skill()
    assert "## When NOT to use `nextseek-query`" in text, (
        "SKILL.md must have a `## When NOT to use \\`nextseek-query\\`` section"
    )
    for heading in FOUR_ESCAPE_HATCH_HEADINGS:
        assert heading in text, (
            f"Escape-hatch section must contain heading: {heading}"
        )


def test_errors_section_lists_all_six_runner_codes():
    """Errors block must enumerate the 6 exit-code mnemonics that
    _nextseek_runner.py emits, so the in-image agent can interpret them."""
    text = _read_skill()
    assert "## Errors" in text
    for code in SIX_EXIT_CODES:
        assert code in text, f"Errors section must document exit code {code}"
