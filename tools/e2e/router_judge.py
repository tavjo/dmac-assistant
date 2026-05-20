"""Phase 7 Residual #5 — semantic answer-quality judge for the router E2E harness.

This module is the bridge between `tools/e2e/run_router_e2e.py` and BAML's
`JudgeRouterAnswer` function (defined in
`baml_src/judge_router.baml`). It:

  * Extracts the agent's user-visible reply text from the captured WS frames.
  * Builds a one-line frames summary for context.
  * Invokes the BAML judge asynchronously.
  * Normalises the verdict to one of "PASS" | "FAIL" | "INCONCLUSIVE".

Why a separate module: keeps `run_router_e2e.py` focused on the bridge/WS
choreography and lets us unit-test extraction + verdict-normalisation
without a live Gemini call (the BAML call itself is mocked in unit tests).
"""
from __future__ import annotations

import time
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any


# Public verdict literals — match BAML's RouterJudgeVerdict @alias values.
VERDICT_PASS = "PASS"
VERDICT_FAIL = "FAIL"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VALID_VERDICTS = frozenset({VERDICT_PASS, VERDICT_FAIL, VERDICT_INCONCLUSIVE})


@dataclass(frozen=True)
class JudgeResult:
    verdict: str
    reasoning: str
    latency_seconds: float


def extract_reply_text(frames: Iterable[dict[str, Any]]) -> str:
    """Return the agent's terminal user-visible reply text.

    Strategy (matches both router paths today — see
    `evidence/router-e2e/20260518T133710Z/*.record.json`):

      * Walk frames in order.
      * The reply is the LAST ``assistant_message.content`` before
        ``session_ended``.
      * If no ``assistant_message`` frame was emitted but an ``error``
        frame is present, surface the error reason so the judge can mark
        it FAIL (rather than INCONCLUSIVE on empty text).
      * If neither is present, return "" — judge will mark FAIL.
    """
    last_assistant: str = ""
    last_error_reason: str = ""
    for frame in frames:
        ftype = frame.get("type")
        if ftype == "assistant_message":
            content = frame.get("content")
            if isinstance(content, str) and content:
                last_assistant = content
        elif ftype == "error":
            reason = frame.get("reason") or frame.get("message") or ""
            if isinstance(reason, str) and reason:
                last_error_reason = reason
    if last_assistant:
        return last_assistant
    if last_error_reason:
        return f"<error frame: {last_error_reason}>"
    return ""


def summarise_frames(frames: Iterable[dict[str, Any]]) -> str:
    """One-line ``type x N, type x M`` summary for the judge context."""
    counts: dict[str, int] = {}
    order: list[str] = []
    for frame in frames:
        ftype = frame.get("type")
        if not isinstance(ftype, str):
            continue
        if ftype not in counts:
            order.append(ftype)
        counts[ftype] = counts.get(ftype, 0) + 1
    return ", ".join(f"{ftype} x {counts[ftype]}" for ftype in order)


def _normalise_verdict(raw: Any) -> str:
    """Map BAML's verdict (enum or string) to a literal in ``VALID_VERDICTS``."""
    if raw is None:
        return VERDICT_INCONCLUSIVE
    text = str(raw)
    # BAML enums may render as "RouterJudgeVerdict.Pass" or "Pass".
    if "." in text:
        text = text.rsplit(".", 1)[-1]
    upper = text.upper()
    if upper in VALID_VERDICTS:
        return upper
    # Tolerate BAML enum member name (Pass/Fail/Inconclusive).
    if upper == "PASS":
        return VERDICT_PASS
    if upper == "FAIL":
        return VERDICT_FAIL
    if upper == "INCONCLUSIVE":
        return VERDICT_INCONCLUSIVE
    return VERDICT_INCONCLUSIVE


async def judge_reply(
    *,
    query_id: str,
    query_text: str,
    expected_route: str,
    actual_route: str | None,
    reply_text: str,
    frames_summary: str,
    baml_client: Any | None = None,
) -> JudgeResult:
    """Invoke the BAML judge and return a normalised result.

    On ANY exception (network error, BAML schema error, API quota), the
    function returns ``verdict=INCONCLUSIVE`` with the exception type name
    in ``reasoning``. The harness treats INCONCLUSIVE as a non-pass for
    its exit-code gate, but it does NOT crash the run — earlier query
    records still land on disk.

    `baml_client` is injected so unit tests can pass a mock without touching
    the real ``dmac_assistant.router.baml_client.b`` module.
    """
    started = time.monotonic()

    if baml_client is None:
        # Late import: the generated client may be regenerated between
        # test runs; importing at call time picks up the current version.
        from dmac_assistant.router.baml_client import b as baml_client_imported
        from dmac_assistant.router.baml_client.types import RouterJudgeInput
    else:
        try:
            from dmac_assistant.router.baml_client.types import RouterJudgeInput
        except ImportError:  # pragma: no cover — defensive only
            RouterJudgeInput = None  # type: ignore[assignment]
        baml_client_imported = baml_client

    # Build the BAML input. If the import failed (unit-test-only edge),
    # fall back to a plain dict — the mock client doesn't care about the type.
    if RouterJudgeInput is not None:
        payload = RouterJudgeInput(
            query_id=query_id,
            query_text=query_text,
            expected_route=expected_route,
            actual_route=str(actual_route) if actual_route is not None else "",
            reply_text=reply_text,
            frames_summary=frames_summary,
        )
    else:  # pragma: no cover — RouterJudgeInput always importable in real runs
        payload = {
            "query_id": query_id,
            "query_text": query_text,
            "expected_route": expected_route,
            "actual_route": str(actual_route) if actual_route is not None else "",
            "reply_text": reply_text,
            "frames_summary": frames_summary,
        }

    try:
        result = await baml_client_imported.JudgeRouterAnswer(input=payload)
    except BaseException as exc:  # noqa: BLE001 — surface ANY judge failure as INCONCLUSIVE
        latency = round(time.monotonic() - started, 3)
        return JudgeResult(
            verdict=VERDICT_INCONCLUSIVE,
            reasoning=f"<judge_unavailable: {type(exc).__name__}>",
            latency_seconds=latency,
        )

    latency = round(time.monotonic() - started, 3)
    verdict = _normalise_verdict(getattr(result, "verdict", None))
    reasoning_raw = getattr(result, "reasoning", "") or ""
    return JudgeResult(
        verdict=verdict,
        reasoning=str(reasoning_raw),
        latency_seconds=latency,
    )
