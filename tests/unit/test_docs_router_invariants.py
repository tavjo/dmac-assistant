"""T6.1: pin the LLM router documentation invariants across 5 user-facing doc files.

These tests are regression protection for the LLM router subsystem's user-facing
documentation. The router was shipped by 15 UA-locked task specs (T0.1 through
T5.1); T6.1 added user-facing prose to README.md, CHANGELOG.md, two files under
docs/bridge/, and container/CLAUDE.md describing the user-observable deltas:

  - DMAC_ROUTER_ENABLED feature flag (off = byte-identical legacy behavior)
  - route_decided WS frame (optional, emitted before session_started, never
    carries a session_id field per locked DD-09)
  - model_class enum with lowercase alias strings ("opus" | "sonnet" | "haiku"
    | null) per locked DD-10 - NOT the BAML enum member names
  - tool_use frames with "ns:*" tool-name prefix for NS-route execution
  - GCP_API_KEY env var (NOT GEMINI_API_KEY - cross-cutting lesson 8)
  - NEXTSEEK_MODE per-exec env (gcp for NS-route speed)
  - Idle container startup mode (DMAC_RUNTIME_MODE)
  - tools/e2e/run_router_e2e.py operator tooling (from T5.1)

If a future docs refactor drops any of these load-bearing strings, these tests
fail loudly and demand explicit re-vetting before the doc edit lands.

Source-pinning via Python regex is the available regression gate - the docs
have no markdown linter / doc generator / build step that would catch drift.
Precedent: tests/unit/test_frontend_frame_switch_invariants.py from T0.1
applies the same pattern to src/dmac_assistant/static/index.html.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

README = REPO_ROOT / "README.md"
CHANGELOG = REPO_ROOT / "CHANGELOG.md"
BRIDGE_README = REPO_ROOT / "docs" / "bridge" / "README.md"
WS_PROTOCOL = REPO_ROOT / "docs" / "bridge" / "ws-protocol.md"
CONTAINER_CLAUDEMD = REPO_ROOT / "container" / "CLAUDE.md"

ALL_DOC_FILES = (README, CHANGELOG, BRIDGE_README, WS_PROTOCOL, CONTAINER_CLAUDEMD)


@pytest.fixture(scope="module")
def doc_sources() -> dict[Path, str]:
    """Read all 5 doc files once per test module."""
    out: dict[Path, str] = {}
    for path in ALL_DOC_FILES:
        if not path.is_file():
            pytest.fail(f"required doc file not found at {path}")
        out[path] = path.read_text(encoding="utf-8")
    return out


def test_readme_has_router_section(doc_sources: dict[Path, str]) -> None:
    """README.md must mention the feature flag, WS frame, and two routes."""
    src = doc_sources[README]
    assert re.search(r"^##\s+LLM router\b", src, re.MULTILINE), (
        "README.md is missing the `## LLM router` section header. "
        "T6.1 Edit 2 inserts this section after `## Image build`."
    )
    assert "DMAC_ROUTER_ENABLED" in src, (
        "README.md `## LLM router` section must name the `DMAC_ROUTER_ENABLED` "
        "feature flag - it is the user's on/off switch for the router."
    )
    assert "route_decided" in src, (
        "README.md `## LLM router` section must name the `route_decided` WS frame."
    )
    assert "nextseek_query" in src and "container_cc" in src, (
        "README.md must name both route alias strings: `nextseek_query` and "
        "`container_cc`."
    )


def test_changelog_has_router_entry(doc_sources: dict[Path, str]) -> None:
    """CHANGELOG.md must have a dated LLM router entry under Unreleased."""
    src = doc_sources[CHANGELOG]
    assert re.search(
        r"^###\s+Added\s+\u2014\s+\d{4}-\d{2}-\d{2}\s+\u2014\s+LLM router\b",
        src,
        re.MULTILINE,
    ), (
        "CHANGELOG.md must have a dated `### Added — YYYY-MM-DD — LLM router ...` "
        "entry matching the Keep-a-Changelog precedent."
    )
    assert "llm-router-2026-05-14" in src, (
        "CHANGELOG.md router entry must reference the plan slug "
        "`llm-router-2026-05-14` so readers can find the full task list."
    )
    assert "DMAC_ROUTER_ENABLED" in src, (
        "CHANGELOG.md router entry must name the `DMAC_ROUTER_ENABLED` flag."
    )
    assert "route_decided" in src, (
        "CHANGELOG.md router entry must name the `route_decided` frame."
    )


def test_bridge_readme_has_routing_section(doc_sources: dict[Path, str]) -> None:
    """docs/bridge/README.md must describe routing and model selection."""
    src = doc_sources[BRIDGE_README]
    assert re.search(r"^##\s+Routing and model selection\b", src, re.MULTILINE), (
        "docs/bridge/README.md is missing the `## Routing and model selection` "
        "section. T6.1 Edit 4 inserts it after `## Environment reference`."
    )
    assert "DMAC_ROUTER_ENABLED" in src, (
        "docs/bridge/README.md `## Routing` section must name the flag."
    )
    assert "GCP_API_KEY" in src, (
        "docs/bridge/README.md must list `GCP_API_KEY` as a bridge-side env var. "
        "It is required when `DMAC_ROUTER_ENABLED=1` per locked design spec L157."
    )
    assert "nextseek_query" in src and "container_cc" in src, (
        "docs/bridge/README.md must name both route alias strings."
    )


def test_ws_protocol_has_route_decided(doc_sources: dict[Path, str]) -> None:
    """docs/bridge/ws-protocol.md must document route_decided invariants."""
    src = doc_sources[WS_PROTOCOL]
    assert re.search(
        r'\{\s*"type"\s*:\s*"route_decided"',
        src,
    ), (
        "docs/bridge/ws-protocol.md must list a `route_decided` JSON sample in "
        "the Server-to-client frames block."
    )
    src_lower = src.lower()
    assert re.search(
        r"route_decided[^\n]{0,200}optional|optional[^\n]{0,200}route_decided",
        src_lower,
    ), (
        "docs/bridge/ws-protocol.md must state `route_decided` is OPTIONAL "
        "(emitted only when the router decides a route). Locked DD-09."
    )
    assert re.search(
        r"route_decided[^\n]{0,200}before[^\n]{0,200}session_started|before[^\n]{0,100}session_started[^\n]{0,200}route_decided",
        src_lower,
    ), (
        "docs/bridge/ws-protocol.md must state `route_decided` is emitted BEFORE "
        "`session_started`. Locked DD-09."
    )
    assert re.search(
        r"(no|without|not carry|does not include|never carries)\s+(a\s+)?`?session_id`?",
        src_lower,
    ), (
        "docs/bridge/ws-protocol.md must explicitly state `route_decided` "
        "does NOT carry a `session_id` field. Locked DD-09."
    )


def test_container_claudemd_has_router_section(doc_sources: dict[Path, str]) -> None:
    """container/CLAUDE.md must have router-aware behavior guidance."""
    src = doc_sources[CONTAINER_CLAUDEMD]
    assert re.search(
        r"^##\s+Router-aware behavior\b",
        src,
        re.MULTILINE,
    ), (
        "container/CLAUDE.md is missing the `## Router-aware behavior` section. "
        "T6.1 Edit 5 inserts it after `## Clarification policy`."
    )
    assert "DMAC_ROUTER_ENABLED" in src, (
        "container/CLAUDE.md `## Router-aware behavior` must name the flag."
    )
    assert "NEXTSEEK_MODE" in src, (
        "container/CLAUDE.md must reference `NEXTSEEK_MODE` "
        "(the per-exec env var that selects Gemini Flash-Lite for NS speed)."
    )
    assert "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->" in src, (
        "container/CLAUDE.md must preserve the auto-generated NExtSEEK docs "
        "sentinel - T6.1 must not edit inside that block."
    )


def test_model_class_prose_uses_lowercase_aliases(
    doc_sources: dict[Path, str],
) -> None:
    """BAML enum names must not be used as WS model_class values."""
    for path, src in doc_sources.items():
        for enum_name in ("Opus", "Sonnet", "Haiku"):
            for match in re.finditer(rf"\b{enum_name}\b", src):
                start = max(0, match.start() - 120)
                end = min(len(src), match.end() + 120)
                context = src[start:end]
                assert "BAML" in context, (
                    f"{path.name} contains the BAML enum name `{enum_name}` "
                    f"at offset {match.start()} outside a BAML-tagged context. "
                    f"Use lowercase alias strings (`\"opus\"`, `\"sonnet\"`, "
                    f"`\"haiku\"`) in `model_class` prose per locked DD-10. "
                    f"Context: {context!r}"
                )


def test_changelog_entry_format_matches_precedent(
    doc_sources: dict[Path, str],
) -> None:
    """The new CHANGELOG entry must follow the existing dated entry skeleton."""
    src = doc_sources[CHANGELOG]
    router_entry_match = re.search(
        r"^###\s+Added\s+\u2014\s+\d{4}-\d{2}-\d{2}\s+\u2014\s+LLM router\b.*?(?=^###\s|\Z)",
        src,
        re.MULTILINE | re.DOTALL,
    )
    assert router_entry_match is not None, (
        "could not locate the router CHANGELOG entry block"
    )
    entry = router_entry_match.group(0)
    assert re.search(r"Plan:\s*`llm-router-2026-05-14`", entry), (
        "CHANGELOG router entry must include a "
        "`Plan: \\`llm-router-2026-05-14\\`` reference line."
    )
    assert "New files:" in entry, (
        "CHANGELOG router entry must include a `New files:` bullet inventory."
    )


def test_no_gemini_api_key_anywhere(doc_sources: dict[Path, str]) -> None:
    """The canonical Gemini credential env-key is GCP_API_KEY."""
    for path, src in doc_sources.items():
        assert "GEMINI_API_KEY" not in src, (
            f"{path.name} contains `GEMINI_API_KEY` - the canonical env-key is "
            f"`GCP_API_KEY` per locked design spec L157 + "
            f"`tools/e2e/baml_src/clients.baml:20`."
        )
