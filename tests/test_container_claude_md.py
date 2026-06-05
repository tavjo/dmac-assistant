"""B17c: container/CLAUDE.md credential-rules content invariants.

Verifies that the in-container agent's instructions explicitly carry the
credential-masking guidance. These invariants are LOAD-BEARING: removing or
weakening this section silently regresses the leak-mitigation contract
documented in `task-B17c-cred-leak-mitigation.md` §6.5.

History: the section was titled `## Credential masking when debugging` with a
"STOPGAP / output-scrubber" framing when B17c (8c9c87c) landed. Commit 60649f5
(2026-05-20) intentionally consolidated it into a tighter `## Credentials`
section, preserving the bare-env warning + masking patterns and dropping the
stopgap framing. These tests assert the consolidated structure.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
CLAUDE_MD = REPO_ROOT / "container" / "CLAUDE.md"


def test_claude_md_includes_credentials_section() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # Consolidated section header (renamed from "## Credential masking when
    # debugging" in 60649f5).
    assert "## Credentials" in text
    # Load-bearing rule: env values are secrets and must never be exfiltrated.
    assert "secret" in text.lower()
    assert "exfiltrate" in text.lower()
    # The bare-env warning must survive (the core masking guidance).
    assert "printenv" in text.lower()


def test_claude_md_forbids_unmasked_env_introspection() -> None:
    text = CLAUDE_MD.read_text(encoding="utf-8")
    # Canonical masking pattern present.
    assert (
        "sed 's/=.*/=***/'" in text or "sed 's|=.*|=***|'" in text
    ), "container/CLAUDE.md must show the canonical sed-based masking pattern"


def test_claude_md_section_appears_before_clarification_policy() -> None:
    """The credentials section must precede the Clarification policy section,
    so the masking rule reaches the agent before any general policy framing.
    """
    text = CLAUDE_MD.read_text(encoding="utf-8")
    credentials_idx = text.find("## Credentials")
    clarif_idx = text.find("## Clarification policy")
    assert credentials_idx != -1, "Credentials section missing"
    assert clarif_idx != -1, "Clarification policy section missing"
    assert credentials_idx < clarif_idx
