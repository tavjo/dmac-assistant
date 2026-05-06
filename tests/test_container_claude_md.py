"""B17c: container/CLAUDE.md content invariants for the cred-masking stopgap.

Verifies that the in-container agent's instructions explicitly carry the
credential-masking guidance + acknowledge it as a stopgap pointing at the
authoritative output-scrubber design. These invariants are LOAD-BEARING:
removing or weakening this section silently regresses the leak-mitigation
contract documented in `task-B17c-cred-leak-mitigation.md` §6.5.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "container" / "CLAUDE.md"


def test_claude_md_includes_cred_masking_section() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    assert "## Credential masking when debugging" in text
    # Stopgap acknowledgement — must be visible in the doc, not just plan history.
    assert "stopgap" in text.lower()
    # Architectural pointer — must reference the output-scrubber spec.
    assert (
        "output-scrubber" in text.lower()
        or "2026-05-01-output-scrubber-design.md" in text
    )


def test_claude_md_forbids_unmasked_env_introspection() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # Canonical masking pattern present.
    assert (
        "sed 's/=.*/=***/'" in text or "sed 's|=.*|=***|'" in text
    ), "container/CLAUDE.md must show the canonical sed-based masking pattern"


def test_claude_md_section_appears_before_clarification_policy() -> None:
    """The cred-masking section must precede the Clarification policy section,
    so the masking rule reaches the agent before any general policy framing.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    masking_idx = text.find("## Credential masking when debugging")
    clarif_idx = text.find("## Clarification policy")
    assert masking_idx != -1, "cred-masking section missing"
    assert clarif_idx != -1, "Clarification policy section missing"
    assert masking_idx < clarif_idx
