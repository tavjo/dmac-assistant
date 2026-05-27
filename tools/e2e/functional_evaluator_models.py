"""T0.1 — Pydantic v2 mirrors of the BAML schemas declared in functional_evaluator.baml.

These mirror models are host-side boundary validation only. The BAML file IS the
runtime authority. BAML emits its own generated types at image-build time in
`tools/e2e/baml_client/` (gitignored); these Pydantic mirrors are for tests +
host-side ingestion only.

Locked anchors:
- DD-16: enum value sets verbatim
- DD-31: @@dynamic on three enums in BAML; Pydantic mirrors are seed values only
- DD-32 (as amended by AM-002 / D-6): Stage C reuses the canonical `client GCPReasoner` (gemini-3.1-pro-preview via google-ai); no new client declared
- §7: FunctionalEvaluationInput (11 fields), FunctionalEvaluation (6 fields)
- DL-017: PrimaryIssue.NoIssue replaces original `None` to avoid Python-keyword collision
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field

# Reuse FailureMode from the existing exporter — locked DD-16 explicit reuse rule.
from tools.hibayes.exporter import FailureMode

__all__ = [
    "ArtifactKind",
    "ArtifactStatus",
    "ExpectedBehavior",
    "FailureMode",
    "FunctionalEvaluation",
    "FunctionalEvaluationInput",
    "FunctionalOutcome",
    "PrimaryIssue",
    "ReviewPriority",
]


class ExpectedBehavior(str, Enum):
    """Locked DD-16: 6 values. Marked @@dynamic in BAML per DD-31 (extensible at runtime)."""

    AnswerDirectly = "AnswerDirectly"
    GenerateArtifact = "GenerateArtifact"
    ClarifyIfAmbiguous = "ClarifyIfAmbiguous"
    UsePriorContext = "UsePriorContext"
    StateUnsupportedBoundary = "StateUnsupportedBoundary"
    RefuseUnsafeOnly = "RefuseUnsafeOnly"


class ArtifactStatus(str, Enum):
    """Locked DD-16: 10 values (PartialAfterFailure added per DD-36)."""

    Valid = "Valid"
    Missing = "Missing"
    Inaccessible = "Inaccessible"
    Unreadable = "Unreadable"
    SchemaInvalid = "SchemaInvalid"
    Incomplete = "Incomplete"
    RuntimeFailed = "RuntimeFailed"
    PartialAfterFailure = "PartialAfterFailure"
    Indeterminate = "Indeterminate"
    NotExpected = "NotExpected"


class ArtifactKind(str, Enum):
    """Locked DD-16: 8 values. Marked @@dynamic in BAML per DD-31."""

    GEO_XLSX = "GEO_XLSX"
    SRA_PACKAGE = "SRA_PACKAGE"
    PRIDE_PACKAGE = "PRIDE_PACKAGE"
    NFCORE_RNASEQ_CSV = "NFCORE_RNASEQ_CSV"
    NFCORE_SCRNASEQ_CSV = "NFCORE_SCRNASEQ_CSV"
    SVG_CHART = "SVG_CHART"
    UNKNOWN_FILE = "UNKNOWN_FILE"
    NONE_EXPECTED = "NONE_EXPECTED"


class FunctionalOutcome(str, Enum):
    """Locked DD-16: 6 values. DD-08 maps {FullySatisfied, AppropriateClarification, AppropriateBoundary} to success."""

    FullySatisfied = "FullySatisfied"
    PartiallySatisfied = "PartiallySatisfied"
    AppropriateClarification = "AppropriateClarification"
    AppropriateBoundary = "AppropriateBoundary"
    NotSatisfied = "NotSatisfied"
    NotAssessable = "NotAssessable"


class PrimaryIssue(str, Enum):
    """Locked DD-16 + DL-017: 15 values. `NoIssue` replaces original `None` to avoid Python-keyword collision.

    Marked @@dynamic in BAML per DD-31.
    """

    NoIssue = "NoIssue"
    RuntimeFailure = "RuntimeFailure"
    Timeout = "Timeout"
    MissingArtifact = "MissingArtifact"
    InvalidArtifact = "InvalidArtifact"
    IncompleteArtifact = "IncompleteArtifact"
    MissingContext = "MissingContext"
    AmbiguousRequest = "AmbiguousRequest"
    OverBroadSearch = "OverBroadSearch"
    UpstreamApiError = "UpstreamApiError"
    UnsupportedRequest = "UnsupportedRequest"
    RefusalError = "RefusalError"
    OverclaimedSuccess = "OverclaimedSuccess"
    InsufficientEvidence = "InsufficientEvidence"
    Other = "Other"


class ReviewPriority(str, Enum):
    """Locked DD-16: 3 values."""

    Low = "Low"
    Medium = "Medium"
    High = "High"


class FunctionalEvaluationInput(BaseModel):
    """Locked §7: 11-field input class passed to EvaluateFunctionalUsefulness BAML function.

    DD-06: query_id is NOT a field (reattached programmatically post-evaluation).
    The CSV column order in `hibayes_functional_eval_inputs.csv` (§5.2) intentionally
    differs from this class's field declaration order; T2.1's CSV-to-BAML adapter MUST
    use keyword-argument construction (NOT positional) to avoid silent field swapping.
    See iter-06 reviewer D2 / DL-023 in the locked design.
    """

    model_config = ConfigDict(extra="forbid")

    task_family: str
    query_text: str
    final_answer: str | None
    answer_provided: bool
    runtime_success: bool
    failure_mode: FailureMode
    expected_behavior: ExpectedBehavior
    artifact_expected: bool
    artifact_status: ArtifactStatus | None
    artifact_kind: ArtifactKind | None
    declared_artifact_count: int


class FunctionalEvaluation(BaseModel):
    """Locked §7: 6-field output class returned by EvaluateFunctionalUsefulness."""

    model_config = ConfigDict(extra="forbid")

    outcome: FunctionalOutcome
    usefulness_score: int = Field(ge=0, le=4)
    primary_issue: PrimaryIssue
    needs_human_review: bool
    review_priority: ReviewPriority
    rationale: str
