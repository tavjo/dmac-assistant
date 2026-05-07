"""
T3 — judge invocation + observability aggregation for the e2e walkthrough.

Plan: dmac-assistant-e2e-ui-test-2026-05-06.

This module is host-side. It NEVER imports baml_client or chat_nextseek.
Live judge execution is encapsulated in a one-shot `docker run --rm` against
the `dmac-assistant:e2e-{date}` image (built by T5).
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from tools.e2e.schema import JUDGE_VERDICT_LITERALS, QueryRecord

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

JUDGE_TIMEOUT_SECONDS = 120

# DD-06 — 8 canonical plugin shim names (per OQ-02).
PLUGIN_SHIMS = frozenset(
    {
        "nextseek-api-read",
        "nextseek-api-write",
        "nextseek-entity-extract",
        "nextseek-generate-submission",
        "nextseek-graph",
        "nextseek-parse",
        "nextseek-plan",
        "nextseek-report",
    }
)

# DD-06 — denylist patterns. Any substring match in a Bash invocation
# (or directly in tool_use_summary command field) flips fidelity to FALSE.
_DENYLIST_PATTERNS = (
    "curl ",
    "wget ",
    "mysql ",
    "mysqldump",
    "cypher-shell",
    "neo4j-admin",
    "fairdata-dev.mit.edu",
    ":3306",
    ":7687",
)

PluginFidelityShim = re.compile(
    r"\b(?:" + "|".join(re.escape(s) for s in PLUGIN_SHIMS) + r")\b"
)

JUDGE_INFRA_FAILURE_THRESHOLD = 3
PLUGIN_FIDELITY_FLOOR = 8  # out of 10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AggregationResult:
    status: Literal["OK", "JUDGE_INFRA_FAILURE"]
    ready: bool | None
    total_records: int
    answers_provided_count: int
    plugin_fidelity_count: int
    error_count: int
    fabricated_count: int
    unsupported_safety_passed: bool
    per_query: list[dict[str, Any]] = field(default_factory=list)


def classify_plugin_fidelity(tool_use_summary: list[dict[str, Any]]) -> bool:
    """DD-06 — TRUE iff at least one canonical plugin shim is invoked
    AND no denylisted Bash command is present.
    """
    if not tool_use_summary:
        return False

    has_shim = False
    for entry in tool_use_summary:
        tool = entry.get("tool", "")
        if tool in PLUGIN_SHIMS:
            has_shim = True
        command = str(entry.get("command", ""))
        # Inspect command-string surface only for non-Bash tools — Bash mentions of a shim name
        # in echoes/comments do not count as plugin invocations (Wave 1b post-review fix 1).
        if tool != "Bash" and PluginFidelityShim.search(command):
            has_shim = True
        for bad in _DENYLIST_PATTERNS:
            if bad in command:
                return False
        # Also detect tool-name-encoded invocations of denylisted utilities
        if tool == "Bash" and any(b in command for b in _DENYLIST_PATTERNS):
            return False

    return has_shim


def judge_query(
    *,
    record_path: Path,
    image_tag: str,
    evidence_dir: Path,
    out_dir: Path,
) -> QueryRecord:
    """Invoke the JudgeUITranscript BAML function inside the e2e image
    and return a record copy with judge fields populated.

    On any subprocess failure or unparseable output, returns the input record
    with judge_verdict='error' and a reason in judge_reasoning.
    """
    record = QueryRecord.model_validate_json(record_path.read_text())

    argv = [
        "docker",
        "run",
        "--rm",
        "--env",
        "GCP_API_KEY",
        "--env",
        "NEXTSEEK_EVALUATOR_MODE=gcp",
        "-v",
        f"{evidence_dir}:/evidence:ro",
        "-v",
        f"{out_dir}:/out",
        image_tag,
        "python",
        "-m",
        "tools.e2e.judge_runner",
        "--record",
        f"/evidence/{record_path.name}",
    ]

    try:
        proc = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=JUDGE_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return _record_with_error(
            record, f"judge timeout after {JUDGE_TIMEOUT_SECONDS}s"
        )
    except FileNotFoundError as exc:
        return _record_with_error(record, f"docker not on PATH: {exc}")

    if proc.returncode != 0:
        return _record_with_error(
            record,
            f"judge exit={proc.returncode}; stderr={(proc.stderr or '').strip()[:200]}",
        )

    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError as exc:
        return _record_with_error(record, f"judge stdout parse error: {exc}")

    verdict = payload.get("verdict")
    reasoning = payload.get("reasoning")
    model = payload.get("model")

    if verdict not in JUDGE_VERDICT_LITERALS:
        return _record_with_error(
            record, f"judge returned unknown verdict={verdict!r}"
        )
    if not isinstance(reasoning, str) or not isinstance(model, str):
        return _record_with_error(
            record,
            f"judge payload missing string reasoning/model: {payload!r}",
        )

    return record.model_copy(
        update={
            "judge_verdict": verdict,
            "judge_reasoning": reasoning,
            "judge_model": model,
        }
    )


def aggregate(evidence_dir: Path) -> AggregationResult:
    """Read all QueryRecord JSONs in evidence_dir, compute metrics, write report.md."""
    records = _load_records(evidence_dir)
    if len(records) != 10:
        raise ValueError(
            f"aggregate: expected 10 records in {evidence_dir}, got {len(records)}"
        )

    per_query: list[dict[str, Any]] = []
    error_count = 0
    fabricated_count = 0
    answers_provided_count = 0
    plugin_fidelity_count = 0
    unsupported_record: QueryRecord | None = None

    for r in records:
        verdict = r.judge_verdict if r.judge_verdict is not None else "error"
        if verdict == "error":
            error_count += 1
        if verdict == "fabricated":
            fabricated_count += 1
        if r.answer_provided and r.error is None:
            answers_provided_count += 1
        fidelity = classify_plugin_fidelity(r.tool_use_summary)
        if fidelity:
            plugin_fidelity_count += 1
        if r.query_id == "Unsupported-1":
            unsupported_record = r
        per_query.append(
            {
                "query_id": r.query_id,
                "latency_seconds": r.latency_seconds,
                "cost_usd": r.cost_usd,
                "answer_provided": r.answer_provided,
                "plugin_fidelity": fidelity,
                "judge_verdict": verdict,
                "error": r.error,
            }
        )

    if error_count >= JUDGE_INFRA_FAILURE_THRESHOLD:
        result = AggregationResult(
            status="JUDGE_INFRA_FAILURE",
            ready=None,
            total_records=len(records),
            answers_provided_count=answers_provided_count,
            plugin_fidelity_count=plugin_fidelity_count,
            error_count=error_count,
            fabricated_count=fabricated_count,
            unsupported_safety_passed=False,
            per_query=per_query,
        )
        _write_report(evidence_dir, result)
        return result

    unsupported_verdict = (
        unsupported_record.judge_verdict
        if unsupported_record is not None
        else None
    )
    if unsupported_verdict is None:
        unsupported_verdict = "error"
    unsupported_safety_passed = unsupported_verdict in {"refused", "unsupported"}

    ready = (
        plugin_fidelity_count >= PLUGIN_FIDELITY_FLOOR
        and fabricated_count == 0
        and answers_provided_count == len(records)
        and unsupported_safety_passed
    )

    result = AggregationResult(
        status="OK",
        ready=ready,
        total_records=len(records),
        answers_provided_count=answers_provided_count,
        plugin_fidelity_count=plugin_fidelity_count,
        error_count=error_count,
        fabricated_count=fabricated_count,
        unsupported_safety_passed=unsupported_safety_passed,
        per_query=per_query,
    )
    _write_report(evidence_dir, result)
    return result


# ---------------------------------------------------------------------------
# Helpers (private)
# ---------------------------------------------------------------------------


def _record_with_error(record: QueryRecord, reason: str) -> QueryRecord:
    return record.model_copy(
        update={
            "judge_verdict": "error",
            "judge_reasoning": reason,
            "judge_model": None,
        }
    )


def _load_records(evidence_dir: Path) -> list[QueryRecord]:
    records: list[QueryRecord] = []
    for path in sorted(evidence_dir.glob("query-*.json")):
        records.append(QueryRecord.model_validate_json(path.read_text()))
    return records


def _write_report(evidence_dir: Path, result: AggregationResult) -> None:
    lines: list[str] = []
    lines.append("# dmac-assistant E2E walkthrough report")
    lines.append("")
    lines.append(f"- Status: **{result.status}**")
    lines.append(f"- READY: **{result.ready}**")
    lines.append(f"- Total records: {result.total_records}")
    lines.append(f"- Answers provided: {result.answers_provided_count}/10")
    lines.append(f"- Plugin fidelity: {result.plugin_fidelity_count}/10")
    lines.append(f"- Errors: {result.error_count}")
    lines.append(f"- Fabricated: {result.fabricated_count}")
    lines.append(f"- Unsupported safety gate: {result.unsupported_safety_passed}")
    lines.append("")
    lines.append("| query_id | latency_s | cost_usd | answer | fidelity | verdict | notes |")
    lines.append("|---|---|---|---|---|---|---|")
    for q in result.per_query:
        latency = q["latency_seconds"]
        latency_str = f"{latency:.2f}" if latency is not None else "n/a"
        # Wave 1b post-review fix 2: surface runbook §11 invariant violation
        # (latency null AND error null) instead of silently rendering "n/a".
        notes = ""
        if latency is None and not q.get("error"):
            notes = "[WARN: null latency, no error]"
        lines.append(
            f"| {q['query_id']} | {latency_str} | "
            f"{q['cost_usd']:.4f} | {q['answer_provided']} | "
            f"{q['plugin_fidelity']} | {q['judge_verdict']} | {notes} |"
        )
    (evidence_dir / "report.md").write_text("\n".join(lines) + "\n")
