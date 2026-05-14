"""
QueryRecord schema for the dmac-assistant E2E walkthrough.

Plan: dmac-assistant-e2e-ui-test-2026-05-06 (DD-04, DD-07, DD-08).

12 walkthrough fields are populated by T6 (the agent-driven walkthrough).
3 judge fields default to None and are populated by T7 (BAML judge invocation).

The judge_verdict literal set is the authoritative spellings — T5's BAML
output enum (in tools/e2e/baml_src/judge.baml) must match exactly. If
they ever drift, fix the BAML file, NOT this enum (per Amendment 3 / N3).
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

JudgeVerdict = Literal[
    "passed",
    "failed",
    "refused",
    "unsupported",
    "fabricated",
    "error",
]

# Convenience tuple for cross-task assertions and runtime introspection.
JUDGE_VERDICT_LITERALS: tuple[str, ...] = get_args(JudgeVerdict)


class QueryRecord(BaseModel):
    """One record per walkthrough query (10 per run).

    DD-04 — fields enumerated by the plan. Frozen; round-trippable as JSON.
    """

    model_config = ConfigDict(frozen=True)

    # --- 13 walkthrough fields (populated by T6; ui_answer declared below judge block) ---
    query_id: str = Field(min_length=1)
    query_text: str = Field(min_length=1)
    started_at: str = Field(min_length=1)  # ISO-8601 string
    completed_at: str = Field(min_length=1)  # ISO-8601 string
    latency_seconds: float | None = Field(default=None, ge=0.0)
    cost_usd: float = Field(ge=0.0)
    answer_provided: bool
    plugin_fidelity: bool
    transcript_path: str = Field(min_length=1)
    screenshot_path: str = Field(min_length=1)
    tool_use_summary: list[dict[str, Any]] = Field(default_factory=list)
    error: str | None = None

    # --- 3 judge fields (populated by T7; default None) ---
    judge_verdict: JudgeVerdict | None = None
    judge_reasoning: str | None = None
    judge_model: str | None = None

    # --- Walkthrough payload that the judge reads (T6 captures from chat UI) ---
    # str | None to accommodate crashed-query records where no answer text was rendered.
    # T7's judge_runner.py refuses to judge (returns judge_verdict=error) when None.
    # Added by Amendment 4 / F-05-03 fix: removes the prior `_ui_answer` private-key convention.
    ui_answer: str | None = None
