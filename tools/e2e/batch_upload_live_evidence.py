"""Pure evidence/verdict logic for the T10 live paid batch-upload E2E ($0, hermetic).

Split from the live driver (``run_batch_upload_live_e2e.py``) so ALL verdict + cost logic is
unit-testable without spending a cent. Mirrors the NExtSEEK ``step7d`` harness discipline
(owner directive 2026-07-07 — that harness is a rigor reference, not a target):

* authoritative-cost-first with ``cost_source`` provenance + an estimate fallback that NEVER
  overrides a real >0 figure;
* invocation proof parsed from the transcript (the agent must actually Bash-exec the shim), with
  basename-exact tokenization so ``nextseek-api`` never matches ``nextseek-api-write`` and
  ``command -v <shim>`` / ``echo <shim>`` argument-only mentions do not count;
* a verdict taxonomy that separates HARD failures (red) from GREEN-but-flagged review notes so
  LLM route nondeterminism does not manufacture false reds.

The WS frame contract this consumes (emitted by ``src/dmac_assistant/ws.py``):
  route_decided  {type, route, model_class}
  tool_use       {type, tool, input, id}          # tool=="Bash", input.command names a shim
  assistant_message {type, content}
  session_ended  {type, session_id, usage, total_cost_usd}   # total_cost_usd = CC authoritative
"""
from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Constants

# The batch-upload shims the agent is expected to Bash-exec (basename-exact match set).
BATCH_UPLOAD_SHIMS: tuple[str, ...] = (
    "nextseek-project-resolve",
    "nextseek-sampletype-attrs",
    "nextseek-sample-search",
    "nextseek-assay-resolve",
    "nextseek-build-payload",
    "nextseek-validate-upload",
)
# The load-bearing terminal shim: the delivered-workbook validate. A turn that never reaches
# this did not exercise the skill's core deliverable (build + validate a workbook).
VALIDATE_SHIM = "nextseek-validate-upload"

EXPECTED_ROUTE = "container_cc"

# Published Opus-4.8 Bedrock rates (USD per token) for the timeout ESTIMATE fallback ONLY.
# Authoritative cost is Claude Code's own ``total_cost_usd``; this table prices a killed turn's
# aggregate usage when no result frame arrived. Mirrors step7d ``_OPUS48_RATES``.
PUBLISHED_RATE_TABLE_VERSION = "2026-07-opus48-bedrock"
_OPUS48_RATES = {
    "input": 5.0 / 1_000_000,
    "output": 25.0 / 1_000_000,
    "cache_write": 6.25 / 1_000_000,  # 5-minute cache write = 1.25x input
    "cache_read": 0.50 / 1_000_000,  # cache read = 0.1x input
}

COST_SOURCE_AUTHORITATIVE = "claude_code_result"
COST_SOURCE_ESTIMATE = "usage_estimate_on_timeout"
COST_SOURCE_NONE = "unavailable"

# Control operators that separate a shell command into independently-headed segments.
_SEGMENT_SPLIT = re.compile(r"&&|\|\||[;|&]")


# ---------------------------------------------------------------------------
# Cost


@dataclass
class CostResult:
    cost_usd: float
    cost_source: str
    usage: dict[str, Any]
    has_result_frame: bool


def _session_ended(frames: list[dict[str, Any]]) -> dict[str, Any] | None:
    for frame in frames:
        if frame.get("type") == "session_ended":
            return frame
    return None


def estimate_cost_from_usage(usage: dict[str, Any]) -> float:
    """Price an aggregate usage block at published Opus-4.8 rates (fallback only)."""
    inp = int(usage.get("input_tokens", 0) or 0)
    out = int(usage.get("output_tokens", 0) or 0)
    cache_write = int(usage.get("cache_creation_input_tokens", 0) or 0)
    cache_read = int(usage.get("cache_read_input_tokens", 0) or 0)
    return (
        inp * _OPUS48_RATES["input"]
        + out * _OPUS48_RATES["output"]
        + cache_write * _OPUS48_RATES["cache_write"]
        + cache_read * _OPUS48_RATES["cache_read"]
    )


def extract_cost(frames: list[dict[str, Any]]) -> CostResult:
    """Authoritative-cost-first cost extraction with provenance.

    * ``session_ended.total_cost_usd`` present and numeric -> authoritative (even 0.0, which the
      verdict layer then flags as a hard failure because a real CC turn always spends).
    * else ``session_ended.usage`` present -> estimate at published rates (the killed-turn path).
    * else -> 0.0, ``unavailable``.
    The estimate NEVER overrides a real total_cost_usd.
    """
    frame = _session_ended(frames)
    usage = {}
    if frame is not None and isinstance(frame.get("usage"), dict):
        usage = frame["usage"]
    if frame is not None:
        total = frame.get("total_cost_usd")
        if isinstance(total, (int, float)) and not isinstance(total, bool):
            return CostResult(float(total), COST_SOURCE_AUTHORITATIVE, usage, True)
    if usage:
        return CostResult(estimate_cost_from_usage(usage), COST_SOURCE_ESTIMATE, usage, False)
    return CostResult(0.0, COST_SOURCE_NONE, {}, False)


# ---------------------------------------------------------------------------
# Route + reply + fresh session


def classify_route(frames: list[dict[str, Any]]) -> str | None:
    for frame in frames:
        if frame.get("type") == "route_decided":
            route = frame.get("route")
            return route if isinstance(route, str) else None
    return None


def extract_reply(frames: list[dict[str, Any]]) -> str:
    parts = [
        frame["content"]
        for frame in frames
        if frame.get("type") == "assistant_message" and isinstance(frame.get("content"), str)
    ]
    return "\n".join(parts).strip()


def detect_error(frames: list[dict[str, Any]]) -> bool:
    """Transcript-only error detection: an explicit ``error`` frame, or no ``session_ended`` at all
    (a turn that never terminated cleanly — e.g. a killed/timed-out turn)."""
    if any(frame.get("type") == "error" for frame in frames):
        return True
    return _session_ended(frames) is None


def session_id_of(frames: list[dict[str, Any]]) -> str | None:
    frame = _session_ended(frames)
    if frame is None:
        return None
    sid = frame.get("session_id")
    return sid if isinstance(sid, str) and sid else None


def assert_fresh_sessions(session_ids: list[str | None]) -> list[str]:
    """Return a list of fresh-session violations (empty == all fresh).

    Fresh means every turn has a non-null session id AND all ids are distinct (no warm/resumed
    session silently riding another turn).
    """
    violations: list[str] = []
    seen: set[str] = set()
    for idx, sid in enumerate(session_ids):
        if not sid:
            violations.append(f"turn {idx}: missing session id")
            continue
        if sid in seen:
            violations.append(f"turn {idx}: duplicate session id {sid!r} (not a fresh session)")
        seen.add(sid)
    return violations


# ---------------------------------------------------------------------------
# Invocation proof


@dataclass
class Invocation:
    shim: str
    command_excerpt: str
    frame_id: str | None


def _segment_heads(command: str) -> list[list[str]]:
    """Split a shell command into control-operator segments, each shlex-tokenized.

    A shim counts as invoked only when it is the COMMAND WORD (first token) of a segment — so
    ``command -v nextseek-validate-upload`` (head ``command``) and ``echo nextseek-...`` (head
    ``echo``) do not count, and ``nextseek-api`` never matches ``nextseek-api-write``.
    """
    segments: list[list[str]] = []
    for raw in _SEGMENT_SPLIT.split(command):
        raw = raw.strip()
        if not raw:
            continue
        try:
            tokens = shlex.split(raw)
        except ValueError:
            continue
        # Skip leading ``env VAR=val`` prefixes and ``VAR=val`` assignments to find the head.
        head_tokens = [t for t in tokens if "=" not in t.split(" ")[0] or "/" in t]
        segments.append(head_tokens or tokens)
    return segments


def extract_tool_invocations(
    frames: list[dict[str, Any]], shims: tuple[str, ...] = BATCH_UPLOAD_SHIMS
) -> list[Invocation]:
    """Parse tool_use Bash frames into shim invocations (basename-exact, head-position-only)."""
    shim_set = set(shims)
    found: list[Invocation] = []
    for frame in frames:
        if frame.get("type") != "tool_use" or frame.get("tool") != "Bash":
            continue
        command = (frame.get("input") or {}).get("command")
        if not isinstance(command, str):
            continue
        for tokens in _segment_heads(command):
            if not tokens:
                continue
            head = tokens[0]
            if os.path.basename(head) in shim_set:
                found.append(
                    Invocation(
                        shim=os.path.basename(head),
                        command_excerpt=command[:500],
                        frame_id=frame.get("id") if isinstance(frame.get("id"), str) else None,
                    )
                )
    return found


# ---------------------------------------------------------------------------
# Verdict


@dataclass
class TurnRow:
    query: str
    route: str | None
    expected_route: str
    cc_session_id: str | None
    is_error: bool
    cost_usd: float
    cost_source: str
    invoked_shims: list[str]
    validate_invoked: bool
    answer_excerpt: str
    problems: list[str] = field(default_factory=list)
    review_notes: list[str] = field(default_factory=list)

    @property
    def needs_review(self) -> bool:
        return bool(self.review_notes) and not self.problems

    @property
    def passed(self) -> bool:
        return not self.problems

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "route": self.route,
            "expected_route": self.expected_route,
            "cc_session_id": self.cc_session_id,
            "is_error": self.is_error,
            "cost_usd": self.cost_usd,
            "cost_source": self.cost_source,
            "invoked_shims": self.invoked_shims,
            "validate_invoked": self.validate_invoked,
            "answer_excerpt": self.answer_excerpt,
            "passed": self.passed,
            "needs_review": self.needs_review,
            "problems": self.problems,
            "review_notes": self.review_notes,
        }


def evaluate_turn(
    *,
    query: str,
    frames: list[dict[str, Any]],
    is_error: bool,
    expected_route: str = EXPECTED_ROUTE,
) -> TurnRow:
    """Build a TurnRow verdict from the captured WS frames.

    HARD failures (problems -> red): transport/agent error; cost <= 0 (a real CC turn always
    spends a Bedrock turn); empty reply; the validate shim never invoked (core deliverable did
    not run); route != expected. GREEN-but-flagged review notes: an expected shim other than
    validate was skipped though validate ran (the agent took a valid shorter path).
    """
    route = classify_route(frames)
    cost = extract_cost(frames)
    invocations = extract_tool_invocations(frames)
    invoked_shims = sorted({inv.shim for inv in invocations})
    validate_invoked = VALIDATE_SHIM in invoked_shims
    reply = extract_reply(frames)
    row = TurnRow(
        query=query,
        route=route,
        expected_route=expected_route,
        cc_session_id=session_id_of(frames),
        is_error=is_error,
        cost_usd=cost.cost_usd,
        cost_source=cost.cost_source,
        invoked_shims=invoked_shims,
        validate_invoked=validate_invoked,
        answer_excerpt=reply[:1000],
    )
    if is_error:
        row.problems.append("turn errored (transport/agent error or timeout)")
    if route != expected_route:
        row.problems.append(f"route {route!r} != expected {expected_route!r}")
    if cost.cost_usd <= 0:
        row.problems.append(
            f"cost_usd={cost.cost_usd} <= 0 (a real CC turn always spends a Bedrock turn; "
            f"cost_source={cost.cost_source})"
        )
    if not reply:
        row.problems.append("empty agent reply")
    if not validate_invoked:
        row.problems.append(
            f"{VALIDATE_SHIM} was never invoked — the batch-upload deliverable (build+validate) "
            "did not run"
        )
    else:
        skipped = [s for s in BATCH_UPLOAD_SHIMS if s != VALIDATE_SHIM and s not in invoked_shims]
        if skipped:
            row.review_notes.append(
                "validate ran but these expected shims were not observed: " + ", ".join(skipped)
            )
    return row


def build_summary(
    row: TurnRow,
    *,
    ledger_total_usd: float,
    cap_usd: float,
    aborted_on_budget: bool,
    rate_table_version: str = PUBLISHED_RATE_TABLE_VERSION,
) -> dict[str, Any]:
    """Top-level per-turn summary (step7d ``per_op_summary`` analog)."""
    fresh_violations = assert_fresh_sessions([row.cc_session_id])
    return {
        "all_pass": row.passed and not aborted_on_budget and not fresh_violations,
        "aborted_on_budget": aborted_on_budget,
        "fresh_session_violations": fresh_violations,
        "total_cost_usd": ledger_total_usd,
        "cap_usd": cap_usd,
        "within_cap": ledger_total_usd <= cap_usd,
        "rate_table_version": rate_table_version,
        "expected_route": row.expected_route,
        "turn": row.to_dict(),
    }
