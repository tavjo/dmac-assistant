"""T2.1 — Stage C: BAML-driven functional usefulness runner.

Per locked DD-44: 3 BAML calls per query (strictly sequential per query), per-field
aggregation, cross-query concurrency via --max-parallel-queries (default 4).
Per locked DD-43: emit both hibayes_functional_usefulness.csv and
hibayes_review_sidecar.csv at every invocation.
Per plan DL-018: tests scope --cov to this module + functional_evaluator_models.
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from tools.e2e.functional_evaluator_models import (
    FunctionalEvaluation,
    FunctionalEvaluationInput,
    FunctionalOutcome,
    PrimaryIssue,
    ReviewPriority,
)


__all__ = [
    "FUNCTIONAL_USEFULNESS_HEADER_12",
    "PARTIAL_FAILURE_RATIONALE_FMT",
    "REVIEW_SIDECAR_HEADER_12",
    "STAGE_C_STATUS_COMPLETE",
    "STAGE_C_STATUS_FAILED",
    "STAGE_C_STATUS_PARTIAL",
    "aggregate_outcome",
    "aggregate_primary_issue",
    "aggregate_review_priority",
    "build_arg_parser",
    "build_input_kwargs_from_row",
    "main",
    "run_stage_c",
    # DD-31 TypeBuilder surface (per-query construction, shared across 3 calls).
    "_build_typebuilder_for_query",
    "_collect_dynamic_enum_extensions",
]


# Locked §5.3 — 12 columns in exact order.
FUNCTIONAL_USEFULNESS_HEADER_12: tuple[str, ...] = (
    "query_id",
    "task_family",
    "expected_behavior",
    "runtime_success",
    "artifact_status",
    "outcome",
    "usefulness_score",
    "primary_issue",
    "functional_success",
    "needs_human_review",
    "review_priority",
    "rationale",
)


# Locked DD-43 — 12 columns in exact order.
REVIEW_SIDECAR_HEADER_12: tuple[str, ...] = (
    "query_id",
    "task_family",
    "query_text",
    "final_answer",
    "validation_notes",
    "aggregated_outcome",
    "aggregated_usefulness_score",
    "aggregated_primary_issue",
    "aggregated_rationale",
    "all_3_judgments_json",
    "stage_c_call_count",
    "stage_c_status",
)


STAGE_C_STATUS_COMPLETE = "Complete"
STAGE_C_STATUS_PARTIAL = "PartialSuccess"
STAGE_C_STATUS_FAILED = "Failed"


PARTIAL_FAILURE_RATIONALE_FMT = (
    "Stage C: {k} of 3 BAML calls exhausted Exponential retry budget; "
    "outcome marked NotAssessable per DD-43 partial-failure rule."
)


# DD-44 partition + strict ordering for outcome aggregation.
_FAILURE_SIDE = {"NotSatisfied", "PartiallySatisfied", "NotAssessable"}
_OUTCOME_STRICT_ORDER = {
    "NotSatisfied": 0,
    "PartiallySatisfied": 1,
    "NotAssessable": 2,
    "AppropriateClarification": 3,
    "AppropriateBoundary": 4,
    "FullySatisfied": 5,
}


# DD-44 severity tie-break for primary_issue (most-severe-first).
_PRIMARY_ISSUE_SEVERITY = [
    "RuntimeFailure",
    "Timeout",
    "MissingArtifact",
    "InvalidArtifact",
    "IncompleteArtifact",
    "UpstreamApiError",
    "OverclaimedSuccess",
    "InsufficientEvidence",
    "RefusalError",
    "UnsupportedRequest",
    "MissingContext",
    "AmbiguousRequest",
    "OverBroadSearch",
    "Other",
    "NoIssue",
]
_PRIMARY_ISSUE_RANK = {name: i for i, name in enumerate(_PRIMARY_ISSUE_SEVERITY)}


# DD-08 success-side outcomes.
_FUNCTIONAL_SUCCESS_SET = {
    "FullySatisfied",
    "AppropriateClarification",
    "AppropriateBoundary",
}


def aggregate_outcome(votes: tuple[str, str, str]) -> str:
    """DD-44 pseudocode: plurality with failure-partition-tiebreak."""
    counter = Counter(votes)
    winner, count = counter.most_common(1)[0]
    if count >= 2:
        return winner
    # All three distinct — failure-partition-first, then strict within-partition order.
    def sort_key(v: str) -> tuple[int, int]:
        partition_rank = 0 if v in _FAILURE_SIDE else 1
        return (partition_rank, _OUTCOME_STRICT_ORDER[v])

    return sorted(votes, key=sort_key)[0]


def aggregate_primary_issue(votes: tuple[str, str, str]) -> str:
    """DD-44: majority; tie-break = severity order (most-severe-first)."""
    counter = Counter(votes)
    winner, count = counter.most_common(1)[0]
    if count >= 2:
        return winner
    # All distinct — pick by severity (lowest rank = most severe).
    return sorted(votes, key=lambda v: _PRIMARY_ISSUE_RANK.get(v, 999))[0]


def aggregate_review_priority(votes: tuple[str, str, str]) -> str:
    """DD-44: max of 3 (Low<Medium<High)."""
    order = {"Low": 0, "Medium": 1, "High": 2}
    return max(votes, key=lambda v: order.get(v, -1))


def _aggregate_usefulness_score_median(scores: tuple[int, int, int]) -> int:
    sorted_scores = sorted(scores)
    return sorted_scores[1]


def _aggregate_needs_review_or(votes: tuple[bool, bool, bool]) -> bool:
    return any(votes)


def _aggregate_rationale(
    evaluations: tuple[FunctionalEvaluation, FunctionalEvaluation, FunctionalEvaluation],
    aggregate_outcome_value: str,
) -> str:
    """DD-44: rationale of the call matching the aggregate outcome."""
    for ev in evaluations:
        if ev.outcome.value == aggregate_outcome_value:
            return ev.rationale
    return evaluations[0].rationale


def build_input_kwargs_from_row(row: dict[str, str]) -> dict[str, Any]:
    """Convert a Stage B CSV row into kwargs for FunctionalEvaluationInput.

    KEYWORD-construction is mandatory per locked §5.2 post-table note.

    FR-1 (Wave 1 reviewer): Stage B emits an empty STRING for `failure_mode`
    (and may for `expected_behavior`) when a query is absent from the runtime
    CSV. `dict.get(key, default)` only returns the default on a MISSING key —
    never on a present-but-empty value — so an empty string would flow into the
    typed `FailureMode` / `ExpectedBehavior` enums and raise a Pydantic
    ValidationError, crashing that query instead of producing a partial-failure
    row. Coerce empties with `or` so the seed default fires for empty values too.
    """
    def _bool(s: str) -> bool:
        return s.strip().lower() in ("true", "1", "yes")

    def _opt(s: str) -> str | None:
        return s if s else None

    return {
        "task_family": row["task_family"],
        "query_text": row["query_text"],
        "final_answer": _opt(row.get("final_answer", "")),
        "answer_provided": _bool(row.get("answer_provided", "")),
        "runtime_success": _bool(row.get("runtime_success", "")),
        # FR-1: coerce empty STRING (not just missing key) to the seed default.
        "failure_mode": row.get("failure_mode") or "none",
        "expected_behavior": row.get("expected_behavior") or "AnswerDirectly",
        "artifact_expected": _bool(row.get("artifact_expected", "")),
        "artifact_status": _opt(row.get("artifact_status", "")),
        "artifact_kind": _opt(row.get("artifact_kind", "")),
        "declared_artifact_count": int(row.get("declared_artifact_count", "0") or 0),
    }


def _invoke_baml_evaluator(  # pragma: no cover
    inp: FunctionalEvaluationInput,
    tb: Any,
) -> FunctionalEvaluation:
    """Wrapper around the BAML client call. Mocked in unit tests.

    Routes through `tools.e2e.baml_client.b.EvaluateFunctionalUsefulness` at runtime;
    real call happens only in T2.2 (live test) or end-to-end runs. Marked
    `# pragma: no cover` because every unit test patches this function — the
    body is never executed under the mocked test suite that the 95% coverage
    gate measures (DL-018).

    Per DD-31, the per-query `TypeBuilder` is forwarded via `baml_options={"tb": tb}`
    so any corpus-load-time dynamic enum extensions are honored on every call.
    """
    from tools.e2e.baml_client import b  # type: ignore[import-not-found]

    return b.EvaluateFunctionalUsefulness(input=inp, baml_options={"tb": tb})


def _build_typebuilder_for_query(  # pragma: no cover
    dynamic_enum_extensions: dict[str, set[str]],
) -> Any:
    """Construct a per-query `TypeBuilder` with all corpus-load-time extensions applied.

    Per DD-31: the corpus-load-time extension set is identical across queries (the
    corpus does not evolve within a single run), but a fresh TypeBuilder is built
    at each query boundary so per-query state never leaks across queries. The
    SAME instance is reused across all three sequential BAML calls for that query
    (per DD-44). Marked `# pragma: no cover` because every unit test either
    autouse-patches this function with a sentinel (default fixture) or
    explicitly patches it for the identity-share assertion. The real body
    requires the generated `baml_client` package and is exercised in the live
    T2.2 test, NOT under the mocked suite the 95% coverage gate measures.
    """
    from tools.e2e.baml_client.type_builder import TypeBuilder  # type: ignore[import-not-found]

    tb = TypeBuilder()
    for value in dynamic_enum_extensions.get("ExpectedBehavior", set()):
        tb.ExpectedBehavior.add_value(value)
    for value in dynamic_enum_extensions.get("ArtifactKind", set()):
        tb.ArtifactKind.add_value(value)
    for value in dynamic_enum_extensions.get("PrimaryIssue", set()):
        tb.PrimaryIssue.add_value(value)
    return tb


def _collect_dynamic_enum_extensions(
    rows: list[dict[str, str]],
) -> dict[str, set[str]]:
    """Corpus-load-time pass (DD-31 step 1): scan the input CSV once for any
    `expected_behavior` values not present in the BAML seed enum, and record
    them for per-query TypeBuilder extension. `ArtifactKind` / `PrimaryIssue`
    keys are also seeded as empty sets so the downstream TypeBuilder builder
    is uniform across all extensible enums.

    The seed `ExpectedBehavior` enum surface comes from
    `functional_evaluator_models.ExpectedBehavior`; the import is local to keep
    the module-import graph minimal.
    """
    from tools.e2e.functional_evaluator_models import ExpectedBehavior  # type: ignore

    seed_expected_behavior = {e.value for e in ExpectedBehavior.__members__.values()}
    extensions: dict[str, set[str]] = {
        "ExpectedBehavior": set(),
        "ArtifactKind": set(),
        "PrimaryIssue": set(),
    }
    for row in rows:
        eb = row.get("expected_behavior", "").strip()
        if eb and eb not in seed_expected_behavior:
            extensions["ExpectedBehavior"].add(eb)
    return extensions


@dataclass
class _PerQueryResult:
    query_id: str
    successful_evals: list[FunctionalEvaluation] = field(default_factory=list)
    call_count: int = 0


def _process_one_query(
    row: dict[str, str],
    dynamic_enum_extensions: dict[str, set[str]],
) -> _PerQueryResult:
    """Per-query: build input, construct ONE TypeBuilder (DD-31), call BAML 3×
    strictly sequentially passing that same TypeBuilder via `baml_options` on
    each call, collect results.
    """
    qid = row["query_id"]
    kwargs = build_input_kwargs_from_row(row)
    inp = FunctionalEvaluationInput(**kwargs)
    tb = _build_typebuilder_for_query(dynamic_enum_extensions)
    result = _PerQueryResult(query_id=qid)
    for _ in range(3):
        try:
            ev = _invoke_baml_evaluator(inp, tb)
            result.successful_evals.append(ev)
            result.call_count += 1
        except Exception:  # noqa: BLE001
            # Retry budget exhausted in BAML; record nothing for this call.
            pass
    return result


def _emit_partial_failure_usefulness_row(
    row: dict[str, str],
    call_count: int,
) -> list[Any]:
    k_failed = 3 - call_count
    rationale = PARTIAL_FAILURE_RATIONALE_FMT.format(k=k_failed)
    return [
        row["query_id"],
        row["task_family"],
        row.get("expected_behavior", ""),
        row.get("runtime_success", ""),
        row.get("artifact_status", ""),
        FunctionalOutcome.NotAssessable.value,
        "",  # usefulness_score null
        PrimaryIssue.RuntimeFailure.value,
        False,  # functional_success
        True,  # needs_human_review
        ReviewPriority.High.value,
        rationale,
    ]


def _read_artifact_validation_notes(av_csv_path: Path) -> dict[str, str]:
    """Build query_id → validation_notes map from Stage A's CSV."""
    notes: dict[str, str] = {}
    if not av_csv_path.is_file():
        return notes
    with av_csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            qid = row.get("query_id", "")
            # Aggregate by concatenating notes if multiple rows per query.
            existing = notes.get(qid, "")
            new = row.get("validation_notes", "")
            notes[qid] = (existing + "; " + new).strip("; ") if existing else new
    return notes


def run_stage_c(
    *,
    fei_csv_path: Path,
    artifact_csv_path: Path,
    out_usefulness_csv: Path,
    out_sidecar_csv: Path,
    max_parallel_queries: int = 4,
    allow_partial: bool = False,
) -> int:
    """Run Stage C end-to-end. Returns process exit code.

    Per DD-44, the 3 BAML calls per query are strictly sequential within
    _process_one_query; cross-query parallelism is the ThreadPoolExecutor with
    max_workers=max_parallel_queries.
    Per DD-43, both CSVs are emitted at every invocation.
    """
    with fei_csv_path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    notes_by_qid = _read_artifact_validation_notes(artifact_csv_path)

    # DD-31 step 1: corpus-load-time dynamic-enum-extension pass (once per run).
    dynamic_enum_extensions = _collect_dynamic_enum_extensions(rows)

    per_query_results: dict[str, _PerQueryResult] = {}
    with ThreadPoolExecutor(max_workers=max(1, max_parallel_queries)) as ex:
        futures = {
            ex.submit(_process_one_query, r, dynamic_enum_extensions): r for r in rows
        }
        for fut in as_completed(futures):
            res = fut.result()
            per_query_results[res.query_id] = res

    out_usefulness_csv.parent.mkdir(parents=True, exist_ok=True)
    out_sidecar_csv.parent.mkdir(parents=True, exist_ok=True)

    any_partial_or_failed = False

    with out_usefulness_csv.open("w", encoding="utf-8", newline="") as fu_fh, \
         out_sidecar_csv.open("w", encoding="utf-8", newline="") as sc_fh:
        fu_writer = csv.writer(fu_fh)
        sc_writer = csv.writer(sc_fh)
        fu_writer.writerow(FUNCTIONAL_USEFULNESS_HEADER_12)
        sc_writer.writerow(REVIEW_SIDECAR_HEADER_12)

        for row in rows:
            qid = row["query_id"]
            res = per_query_results.get(qid, _PerQueryResult(query_id=qid))
            call_count = res.call_count
            evals = res.successful_evals

            if call_count == 3:
                stage_c_status = STAGE_C_STATUS_COMPLETE
                outcomes = tuple(e.outcome.value for e in evals)
                scores = tuple(e.usefulness_score for e in evals)
                issues = tuple(e.primary_issue.value for e in evals)
                priorities = tuple(e.review_priority.value for e in evals)
                needs_reviews = tuple(e.needs_human_review for e in evals)
                agg_outcome = aggregate_outcome(outcomes)  # type: ignore[arg-type]
                agg_score = _aggregate_usefulness_score_median(scores)  # type: ignore[arg-type]
                agg_issue = aggregate_primary_issue(issues)  # type: ignore[arg-type]
                agg_priority = aggregate_review_priority(priorities)  # type: ignore[arg-type]
                agg_needs_review = _aggregate_needs_review_or(needs_reviews)  # type: ignore[arg-type]
                agg_rationale = _aggregate_rationale(evals, agg_outcome)  # type: ignore[arg-type]
                functional_success = agg_outcome in _FUNCTIONAL_SUCCESS_SET
                fu_writer.writerow([
                    qid,
                    row["task_family"],
                    row.get("expected_behavior", ""),
                    row.get("runtime_success", ""),
                    row.get("artifact_status", ""),
                    agg_outcome,
                    agg_score,
                    agg_issue,
                    functional_success,
                    agg_needs_review,
                    agg_priority,
                    agg_rationale,
                ])
                sc_writer.writerow([
                    qid,
                    row["task_family"],
                    row["query_text"],
                    row.get("final_answer", ""),
                    notes_by_qid.get(qid, ""),
                    agg_outcome,
                    agg_score,
                    agg_issue,
                    agg_rationale,
                    json.dumps([e.model_dump(mode="json") for e in evals]),
                    call_count,
                    stage_c_status,
                ])
            else:
                any_partial_or_failed = True
                stage_c_status = (
                    STAGE_C_STATUS_PARTIAL if call_count > 0 else STAGE_C_STATUS_FAILED
                )
                fu_writer.writerow(_emit_partial_failure_usefulness_row(row, call_count))
                k_failed = 3 - call_count
                rationale = PARTIAL_FAILURE_RATIONALE_FMT.format(k=k_failed)
                sc_writer.writerow([
                    qid,
                    row["task_family"],
                    row["query_text"],
                    row.get("final_answer", ""),
                    notes_by_qid.get(qid, ""),
                    FunctionalOutcome.NotAssessable.value,
                    "",
                    PrimaryIssue.RuntimeFailure.value,
                    rationale,
                    json.dumps([e.model_dump(mode="json") for e in evals]),
                    call_count,
                    stage_c_status,
                ])

    if any_partial_or_failed:
        sys.stderr.write(
            "Stage C: one or more queries finished with stage_c_call_count < 3 "
            "(PartialSuccess or Failed); see hibayes_review_sidecar.csv columns "
            "stage_c_call_count, stage_c_status.\n"
        )
        if not allow_partial:
            out_usefulness_csv.unlink(missing_ok=True)
            sys.stderr.write(
                f"Stage C: deleted {out_usefulness_csv} so downstream callers "
                "(e.g. GNU make) do not treat partial output as a valid target. "
                "Sidecar CSV preserved for inspection. Re-run with "
                "--allow-partial-stage-c to keep the usefulness CSV.\n"
            )
            return 1
    return 0


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="tools.e2e.functional_evaluator")
    parser.add_argument("--fei-csv", type=Path, required=True)
    parser.add_argument("--av-csv", type=Path, required=True)
    parser.add_argument("--out-usefulness", type=Path, required=True)
    parser.add_argument("--out-sidecar", type=Path, required=True)
    parser.add_argument(
        "--max-parallel-queries",
        type=int,
        default=4,
        help="Cross-query concurrency (DD-44/R5). Per-query 3 calls remain sequential.",
    )
    parser.add_argument(
        "--allow-partial-stage-c",
        action="store_true",
        dest="allow_partial",
    )
    return parser


_REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def main(argv: list[str] | None = None) -> int:
    load_dotenv(_REPO_ROOT / ".env", override=False)
    args = build_arg_parser().parse_args(argv)
    return run_stage_c(
        fei_csv_path=args.fei_csv,
        artifact_csv_path=args.av_csv,
        out_usefulness_csv=args.out_usefulness,
        out_sidecar_csv=args.out_sidecar,
        max_parallel_queries=args.max_parallel_queries,
        allow_partial=args.allow_partial,
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
