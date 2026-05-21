"""T0.2 — Canonical Python-side enum surface for the hibayes evaluator axes.

This module is a thin re-export layer: it imports the new-axis enums declared in
`tools.e2e.functional_evaluator_models` (T0.1) and re-exports them alongside
`FailureMode` from `tools.hibayes.exporter` so `tools.hibayes.*` consumers can
stay within their own namespace without a back-reference into `tools.e2e.*`.

There is exactly ONE class per enum. Identity comparisons across the two surfaces
work: `tools.hibayes.enums.ExpectedBehavior is tools.e2e.functional_evaluator_models.ExpectedBehavior`.

Locked-spec anchors:
- DD-16: enum value sets
- DD-31: ExpectedBehavior / ArtifactKind / PrimaryIssue marked @@dynamic in BAML
- DL-017: PrimaryIssue.NoIssue replaces original `None`
"""
from __future__ import annotations

# Re-export the existing FailureMode (do NOT redeclare per locked DD-16).
from tools.hibayes.exporter import FailureMode

# Re-export the six new enums from T0.1's mirror file.
from tools.e2e.functional_evaluator_models import (
    ArtifactKind,
    ArtifactStatus,
    ExpectedBehavior,
    FunctionalOutcome,
    PrimaryIssue,
    ReviewPriority,
)

__all__ = [
    "ArtifactKind",
    "ArtifactStatus",
    "ExpectedBehavior",
    "FailureMode",
    "FunctionalOutcome",
    "PrimaryIssue",
    "ReviewPriority",
]
