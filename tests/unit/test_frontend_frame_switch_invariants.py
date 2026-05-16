"""T0.1: pin the frontend frame-switch invariants that tolerate router frames.

These tests are regression protection for the LLM router's verifiable open
#1. The frontend must:
  1. Render unknown `type` values via the `default:` case (system row + JSON).
  2. Render `tool_use` frames with any `tool` name (including `ns:*`).

If a future static/ refactor breaks either invariant, these tests fail and
the router stops emitting `route_decided` or `ns:*` `tool_use` frames until
either the frontend is fixed or a T0.1a shim is added.

Asserting on source text (not behavior) is intentional -- the frontend has no
automated test runner (no jest/cypress/playwright per the Phase 3 recon
report), so source-pinning is the available regression gate.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

INDEX_HTML = Path(__file__).parent.parent.parent / "src" / "dmac_assistant" / "static" / "index.html"


@pytest.fixture(scope="module")
def index_source() -> str:
    """Read index.html once per test module."""
    if not INDEX_HTML.is_file():
        pytest.fail(f"index.html not found at {INDEX_HTML}; frontend source missing")
    return INDEX_HTML.read_text(encoding="utf-8")


def test_handle_frame_has_default_case(index_source: str) -> None:
    """T0.1 invariant: handleFrame's switch has a `default:` case.

    Without a default, unknown `type` values become silent no-ops or
    JavaScript errors. The router's `route_decided` frame has an
    unknown-to-the-frontend `type`, so the default case is load-bearing.
    """
    # `handleFrame` must exist.
    assert "function handleFrame" in index_source, (
        "handleFrame function not found in index.html; frame dispatch primitive missing"
    )
    # The default case must exist inside handleFrame. We search for the
    # exact pattern that appears in the round-3-reviewed source.
    assert re.search(
        r"default:\s*\n\s*addRow\(\s*[\"']system[\"']\s*,\s*JSON\.stringify\(f\)\s*\)\s*;",
        index_source,
    ), (
        "handleFrame default case must render unknown frame types as a "
        "system row via `addRow(\"system\", JSON.stringify(f))`. If this "
        "pattern was refactored, either restore it or add T0.1a as a "
        "frontend shim per plan DD-15."
    )


def test_default_case_renders_unknown_types_as_system_row(index_source: str) -> None:
    """T0.1 verdict pin: `route_decided` frames (unknown to current frontend)
    are rendered as system rows displaying the full JSON payload.

    The reviewer round-3 finding that prompted this audit said:
        "handleFrame default branch renders unknown frames as `system` rows,
         NOT silently no-op"

    This test pins that finding. If it fails, the reviewer's reading was
    wrong (very unlikely given the exact-source quote above) OR the source
    has been refactored -- either case requires re-running the audit.
    """
    # The render primitive used by the default case must be `addRow` with
    # the `"system"` row class. Any switch to a no-op (e.g., `return;`) or a
    # console.log-only path would invalidate the audit verdict.
    default_block_pattern = re.compile(
        r"default:\s*\n\s*(?P<body>[^\n}]+)",
        re.MULTILINE,
    )
    matches = default_block_pattern.findall(index_source)
    # There may be other `default:` cases in the file (unlikely given a
    # single-purpose chat UI, but possible). The handleFrame one must
    # include the addRow call.
    assert any(
        "addRow" in body and "system" in body and "JSON.stringify(f)" in body
        for body in matches
    ), (
        "No `default:` case in index.html renders unknown frame types via "
        "addRow(\"system\", JSON.stringify(f)). Either this is no longer "
        "true (re-run T0.1 audit and update verdict) or the source was "
        "refactored and T0.1a shim is now required."
    )


def test_tool_use_passes_tool_name_verbatim(index_source: str) -> None:
    """T0.1 invariant: the `case "tool_use":` block renders `f.tool` directly
    via template-string interpolation, with no allowlist, regex match, or
    exact-string filter.

    The router emits `tool_use` frames with `tool: "ns:run_query"` (or any
    `ns:*` prefix) for the NS path. If the frontend ever switches to an
    explicit allowlist of Claude tool names (Bash/Read/Edit/etc.), these
    frames would be rejected and the user would see no tool activity for
    the NS route.
    """
    assert 'case "tool_use":' in index_source, (
        "`case \"tool_use\":` not found in index.html; tool_use rendering "
        "primitive missing -- refactor will break router NS-path UI."
    )
    # The render line must be a template literal that uses `${f.tool}` (or
    # equivalent `f.tool` reference) inside the addRow `metatext` arg. We
    # accept the canonical Phase-3-recon form and reject any allowlist
    # pattern (e.g., `if (f.tool === "Bash")`).
    assert re.search(
        r"addRow\(\s*[\"']tool[\"']\s*,\s*input\s*,\s*[`\"']tool\s*·\s*\$\{f\.tool\s*\|\|\s*[\"']\?[\"']\}",
        index_source,
    ), (
        "tool_use case does not render `f.tool` verbatim through "
        "template-string interpolation. Either an allowlist was added "
        "(which breaks `ns:*` tools -- must add T0.1a shim) or the "
        "rendering primitive changed (re-run T0.1 audit)."
    )
    # Negative: there must be NO if-statement that filters tool names by an
    # allowlist within ~10 lines of the `case "tool_use":` line.
    tool_use_block = index_source[
        index_source.index('case "tool_use":') : index_source.index('case "tool_use":') + 500
    ]
    # Bare prohibition: any `if (f.tool ===` would be an allowlist gate.
    assert not re.search(
        r"if\s*\(\s*f\.tool\s*===",
        tool_use_block,
    ), (
        "An equality check on `f.tool` was found in or near the tool_use "
        "case. This is the allowlist pattern that breaks `ns:*` tools. "
        "Either remove it or add T0.1a as a permissive shim."
    )
