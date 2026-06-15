"""T8: pin the OI-3 Bedrock auth-proxy documentation invariants.

T8 is a DOCS-ONLY task that records the as-built state of the Option B
Bedrock auth-proxy sidecar (ADR-015).  These tests are regression
protection for four documents:

  - ``dmac-assistant-adrs.md`` — must contain ADR-015 describing the proxy
    and naming zero-creds agent containers.
  - ``container/CLAUDE.md`` — must NOT list ``AWS_BEARER_TOKEN_BEDROCK`` as
    a credential "present in this container"; the token now lives only in the
    proxy sidecar (ADR-015, T4).
  - ``.claude/known-issues/bedrock-token-exposure.md`` (GITIGNORED) — must
    state the Bedrock token is CONTAINED via Option B.  Guarded with
    ``pytest.skip`` when the file is absent (fresh checkout / CI).
  - ``.claude/plans/nextseek-integration-open-items.md`` (GITIGNORED) — OI-3
    row must be RESOLVED.  Guarded with ``pytest.skip`` when absent.

Source: tests/unit/test_docs_router_invariants.py for the pattern.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

ADRS = REPO_ROOT / "dmac-assistant-adrs.md"
CONTAINER_CLAUDEMD = REPO_ROOT / "container" / "CLAUDE.md"

# Gitignored — present on the developer's machine, absent on CI.
KNOWN_ISSUE = REPO_ROOT / ".claude" / "known-issues" / "bedrock-token-exposure.md"
OI_TRACKER = REPO_ROOT / ".claude" / "plans" / "nextseek-integration-open-items.md"


# ---------------------------------------------------------------------------
# Tracked files — always present; fail hard if absent.
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def adrs_text() -> str:
    if not ADRS.is_file():
        pytest.fail(f"required doc file not found at {ADRS}")
    return ADRS.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def container_md_text() -> str:
    if not CONTAINER_CLAUDEMD.is_file():
        pytest.fail(f"required doc file not found at {CONTAINER_CLAUDEMD}")
    return CONTAINER_CLAUDEMD.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# ADR-015 assertions
# ---------------------------------------------------------------------------


def test_adrs_has_adr_015_header(adrs_text: str) -> None:
    """dmac-assistant-adrs.md must have an ADR-015 section header."""
    assert re.search(r"^## ADR-015\b", adrs_text, re.MULTILINE), (
        "dmac-assistant-adrs.md is missing the `## ADR-015` section. "
        "T8 adds ADR-015 (Bedrock Auth-Proxy Sidecar, Option B as built)."
    )


def test_adrs_015_names_proxy(adrs_text: str) -> None:
    """The ADR-015 section must name the proxy sidecar."""
    # Extract the ADR-015 block (from its header to the next `## ADR-` header or EOF).
    match = re.search(
        r"^## ADR-015\b.*?(?=^## ADR-|\Z)",
        adrs_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Could not locate the ADR-015 section body."
    adr015 = match.group(0)

    # Must name the proxy (the sidecar that holds the token).
    assert re.search(r"\bproxy\b", adr015, re.IGNORECASE), (
        "ADR-015 section must mention 'proxy' — the Bedrock auth-proxy sidecar is "
        "the core architectural element (T8 requirement)."
    )


def test_adrs_015_names_zero_creds_agent(adrs_text: str) -> None:
    """The ADR-015 section must state the agent holds zero AWS credentials."""
    match = re.search(
        r"^## ADR-015\b.*?(?=^## ADR-|\Z)",
        adrs_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Could not locate the ADR-015 section body."
    adr015 = match.group(0)

    # Accept: "zero AWS cred", "zero AWS credentials", "zero credentials", "no AWS cred", etc.
    assert re.search(
        r"(zero|no)\s+(AWS\s+)?cred(ential)?",
        adr015,
        re.IGNORECASE,
    ), (
        "ADR-015 section must state the agent container holds zero (AWS) credentials. "
        "This is the core containment claim: the token is moved out of the agent container "
        "and into the proxy sidecar."
    )


def test_adrs_015_names_option_b(adrs_text: str) -> None:
    """ADR-015 must reference Option B (the proxy sidecar option from the known-issue)."""
    match = re.search(
        r"^## ADR-015\b.*?(?=^## ADR-|\Z)",
        adrs_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Could not locate the ADR-015 section body."
    adr015 = match.group(0)

    assert "Option B" in adr015, (
        "ADR-015 section must reference 'Option B' — the Option B label connects "
        "this ADR to the known-issue's Options A/B/C analysis for cross-navigation."
    )


def test_adrs_015_references_t6_evidence(adrs_text: str) -> None:
    """ADR-015 must cite the T6 paid acceptance evidence run."""
    match = re.search(
        r"^## ADR-015\b.*?(?=^## ADR-|\Z)",
        adrs_text,
        re.MULTILINE | re.DOTALL,
    )
    assert match is not None, "Could not locate the ADR-015 section body."
    adr015 = match.group(0)

    assert "20260615T131344Z" in adr015, (
        "ADR-015 section must reference the committed T6 evidence run directory "
        "`runs/20260615T131344Z/` (all 7 conditions PASS, $0.25). "
        "This is the non-ephemeral provenance anchor for the acceptance claim."
    )


# ---------------------------------------------------------------------------
# container/CLAUDE.md — token must NOT appear in "present in this container" context
# ---------------------------------------------------------------------------


def test_container_md_token_not_in_present_warning(container_md_text: str) -> None:
    """container/CLAUDE.md must NOT list AWS_BEARER_TOKEN_BEDROCK as present in container.

    Pre-T4 (T8), the bare-env warning read:
      "the full output (including `NEXTSEEK_PASSWORD` and `AWS_BEARER_TOKEN_BEDROCK`)"
    After T4 + T8, `AWS_BEARER_TOKEN_BEDROCK` is removed from that list because
    the token no longer exists in the agent container (proxy sidecar holds it).

    The test asserts the specific pre-T4 pattern is absent: the token must NOT
    appear in a comma/and-separated list right after the word "including" in the
    Credentials section warning.
    """
    # The forbidden pre-T4 pattern: "including ... AWS_BEARER_TOKEN_BEDROCK"
    # (with anything in between — the token was one of the items listed as present).
    assert not re.search(
        r"\bincluding\b[^)]{0,200}AWS_BEARER_TOKEN_BEDROCK",
        container_md_text,
        re.IGNORECASE,
    ), (
        "container/CLAUDE.md still lists `AWS_BEARER_TOKEN_BEDROCK` in the "
        "'including ...' clause of the bare-`env` warning, which implies the token "
        "IS present in the container. After T4, it is held by the Bedrock proxy "
        "sidecar and must NOT be listed as a present credential. "
        "Update the warning to remove it from the 'including' clause."
    )


def test_container_md_token_not_present_statement(container_md_text: str) -> None:
    """container/CLAUDE.md must positively state the Bedrock token is NOT in the container.

    T8 added a parenthetical explaining where the token actually lives:
    "`AWS_BEARER_TOKEN_BEDROCK` is **not** present in this container — it is held
    exclusively by the Bedrock auth-proxy sidecar, per ADR-015."
    """
    # The phrase is: `AWS_BEARER_TOKEN_BEDROCK` is **not** present — markdown bold
    # markers (**) surround "not", so we allow 0–2 asterisks around the word.
    assert re.search(
        r"AWS_BEARER_TOKEN_BEDROCK[^\n.]{0,80}\*{0,2}not\*{0,2}\s+present",
        container_md_text,
        re.IGNORECASE,
    ), (
        "container/CLAUDE.md must state that `AWS_BEARER_TOKEN_BEDROCK` is NOT "
        "present in this container (may be written as `is **not** present` with "
        "markdown bold). T8 adds this parenthetical so the in-container agent "
        "knows the token is proxy-held and not exfiltrable from the local env."
    )


# ---------------------------------------------------------------------------
# Gitignored files — guarded with skip when absent (CI-safe).
# ---------------------------------------------------------------------------


def test_known_issue_bedrock_token_contained() -> None:
    """known-issues/bedrock-token-exposure.md must state the Bedrock token is CONTAINED.

    Guarded: skips when the gitignored file is absent (fresh checkout / CI).
    On the developer's machine the file IS present, so the assertion runs.
    """
    if not KNOWN_ISSUE.exists():
        pytest.skip(
            "bedrock-token-exposure.md is gitignored and absent on this checkout; "
            "skipping local-only assertion."
        )
    text = KNOWN_ISSUE.read_text(encoding="utf-8")

    # Must have an explicit CONTAINED statement (not just Option B mentioned).
    assert re.search(
        r"CONTAINED[^\n]{0,120}Option\s+B|Option\s+B[^\n]{0,120}CONTAINED",
        text,
        re.IGNORECASE,
    ), (
        "known-issues/bedrock-token-exposure.md must have a CONTAINED + Option B "
        "statement (e.g. 'CONTAINED via Option B'). T8 adds this to the Decision section "
        "to flip the Bedrock token's status from Option C (deferred) to Option B (resolved)."
    )

    # "current operating mode is Option C" must either be absent OR struck-through
    # (~~...~~).  Strikethrough preserves the historical record while marking it superseded.
    # A plain (non-struck) occurrence is the failure case.
    plain_match = re.search(r"current operating mode is Option C", text, re.IGNORECASE)
    if plain_match is not None:
        # Verify the match is inside a strikethrough block (~~...~~).
        start = plain_match.start()
        # Look back for an opening ~~ within the same paragraph (200 chars).
        prefix = text[max(0, start - 200) : start]
        assert prefix.count("~~") % 2 == 1, (
            "known-issues/bedrock-token-exposure.md still reads 'current operating "
            "mode is Option C' without being struck through (~~...~~). After T8 this "
            "phrase is superseded — it must be struck through or removed so it no "
            "longer reads as the definitive operative statement."
        )


def test_oi_tracker_oi3_resolved() -> None:
    """nextseek-integration-open-items.md must show OI-3 as RESOLVED.

    Guarded: skips when the gitignored file is absent (fresh checkout / CI).
    On the developer's machine the file IS present, so the assertion runs.
    """
    if not OI_TRACKER.exists():
        pytest.skip(
            "nextseek-integration-open-items.md is gitignored and absent on this "
            "checkout; skipping local-only assertion."
        )
    text = OI_TRACKER.read_text(encoding="utf-8")

    # OI-3 summary row must contain RESOLVED (not just VIABLE).
    # The table row format: | OI-3 | ... | ... | ✅ RESOLVED ... | ... |
    oi3_row_match = re.search(
        r"\|\s*OI-3\s*\|[^\n]+",
        text,
    )
    assert oi3_row_match is not None, (
        "nextseek-integration-open-items.md is missing the OI-3 summary table row."
    )
    oi3_row = oi3_row_match.group(0)
    assert "RESOLVED" in oi3_row, (
        f"OI-3 summary row must contain 'RESOLVED'. Current row: {oi3_row!r}. "
        "T8 flips OI-3 from VIABLE to RESOLVED after the T6 paid acceptance PASS."
    )

    # The OI-3 section must also name the T6 evidence run (non-gameable provenance).
    assert "20260615T131344Z" in text, (
        "nextseek-integration-open-items.md OI-3 section must reference the committed "
        "T6 evidence run `runs/20260615T131344Z/` so the resolution is traceable."
    )
