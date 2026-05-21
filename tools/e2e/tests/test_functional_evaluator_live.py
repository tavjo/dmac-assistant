"""tools/e2e/tests/test_functional_evaluator_live.py — Stage C live BAML test (T2.2).

Cost envelope per `pytest -m live` invocation: ≈18 API calls (2 tests × 3 queries × 3
sequential calls per query); up to 54 worst-case if BAML's Exponential { max_retries 2 }
trips on every call. Cost ≈ $0.002–$0.02 on gemini-3.1-pro-preview paid tier.

(Plan R-BP-10 line 540 cites ≈9 calls / 27 worst-case for ONE `run_stage_c` exercise;
the file holds TWO live tests, each making one full `run_stage_c` exercise, so the
per-invocation total doubles. R-BP-10's per-exercise envelope is unchanged.)

Skipped by default — invoke with `pytest -m live --enable-socket` to run against
real Gemini. Requires GCP_API_KEY in environment.

Hardened per plan DL-006: pins the BAML SOURCE FILE to `gemini-3.1-pro-preview`
(compile-time check). Locked-spec DD-32 + R1 (design lines 333 + 1174) AND plan
T2.2 line 361 + DL-006 line 722 require per-evaluation-row recording of the
RESOLVED model identifier and Gemini API request fingerprint — that mitigation is
NOT delivered by this file alone (T2.1's CSVs carry no `resolved_model` column
today). See task-09 §9 Escalation; R-BP-10 mitigation is INCOMPLETE until T0.1 /
T2.1 amendments land.
"""
from __future__ import annotations

import csv
import os
from pathlib import Path

import pytest

from tools.e2e.functional_evaluator import (
    FUNCTIONAL_USEFULNESS_HEADER_12,
    REVIEW_SIDECAR_HEADER_12,
    STAGE_C_STATUS_COMPLETE,
    run_stage_c,
)


pytestmark = pytest.mark.live


@pytest.fixture(scope="module", autouse=True)
def _require_gcp_api_key() -> None:
    if not os.environ.get("GCP_API_KEY"):
        pytest.skip("GCP_API_KEY not set; live Stage C test requires Gemini access.")


def _seed_live_inputs(tmp_path: Path) -> tuple[Path, Path]:
    fei_csv = tmp_path / "fei.csv"
    fei_csv.write_text(
        "query_id,task_family,query_text,final_answer,answer_provided,runtime_success,failure_mode,artifact_expected,artifact_status,artifact_kind,declared_artifact_count,expected_behavior\n"
        "Search-Basic-1,Search-Basic,Find protein samples,Found 12 samples,True,True,none,False,,,0,AnswerDirectly\n"
        "Memory-1,Memory,Show me the last search results,Here are the last 12,True,True,none,False,,,0,UsePriorContext\n"
        "Unsupported-1,Unsupported,What is today's weather?,I cannot help with weather queries,True,True,none,False,,,0,StateUnsupportedBoundary\n"
    )
    av_csv = tmp_path / "av.csv"
    av_csv.write_text(
        "query_id,task_family,validation_notes\n"
        "Search-Basic-1,Search-Basic,no artifact expected\n"
        "Memory-1,Memory,no artifact expected\n"
        "Unsupported-1,Unsupported,no artifact expected\n"
    )
    return fei_csv, av_csv


def test_live_stage_c_runs_against_real_gemini(tmp_path: Path) -> None:
    """Single live end-to-end: 3 queries × 3 BAML calls each = 9 calls.

    Asserts:
    - Exit code 0 (all 9 calls succeed; no partial failure)
    - hibayes_functional_usefulness.csv has 3 data rows (one per input query)
    - hibayes_review_sidecar.csv has 3 data rows with stage_c_call_count == 3
    """
    fei_csv, av_csv = _seed_live_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    exit_code = run_stage_c(
        fei_csv_path=fei_csv,
        artifact_csv_path=av_csv,
        out_usefulness_csv=fu_csv,
        out_sidecar_csv=sidecar_csv,
        max_parallel_queries=1,  # keep wall-clock predictable
        allow_partial=False,
    )
    assert exit_code == 0, (
        "Live Stage C must complete all 9 calls; partial-failure indicates rate-limit / quota issue"
    )

    fu_rows = list(csv.DictReader(fu_csv.open(encoding="utf-8")))
    assert len(fu_rows) == 3
    sidecar_rows = list(csv.DictReader(sidecar_csv.open(encoding="utf-8")))
    assert len(sidecar_rows) == 3
    for row in sidecar_rows:
        assert row["stage_c_call_count"] == "3"
        assert row["stage_c_status"] == STAGE_C_STATUS_COMPLETE


def test_baml_source_pins_gemini_3_1_pro_preview(tmp_path: Path) -> None:
    """Compile-time pin of the BAML SOURCE FILE to `gemini-3.1-pro-preview`.

    SCOPE: this is a static text grep of `baml_src/functional_evaluator.baml`
    (for the `client GCPReasoner` wiring) plus `baml_src/clients.baml` (for the
    model + provider declared on the GCPReasoner client block — post-cc2c43b /
    AM-002 these live in the shared clients file, not the per-function file).
    It catches edits to the BAML source that would change the declared model identifier
    or provider. It does NOT catch:
      - a stale / cached `tools/e2e/baml_client/` whose generated client routes to a
        different model than the BAML source declares,
      - runtime env-var or BAML-CLI overrides that re-route the request,
      - silent server-side model migration by Google.

    Per locked-spec DD-32 + R1 (design lines 333 + 1174) AND plan T2.2 line 361 +
    DL-006 line 722, the FULL R-BP-10 mitigation requires per-evaluation-row capture
    of the RESOLVED model identifier (and the Gemini API request fingerprint) emitted
    by `run_stage_c` into `hibayes_functional_usefulness.csv` (or the sidecar). T2.1's
    current 12-column `FUNCTIONAL_USEFULNESS_HEADER_12` and `REVIEW_SIDECAR_HEADER_12`
    (see task-08-stage-c-mocked.md §5 lines 596-626 of that spec) include NEITHER a
    `resolved_model` nor a `model_fingerprint` column. Until that amendment lands
    (see task-09 §9 Escalation), this test stays a compile-time pin — accurately
    named — rather than masquerading as drift detection.

    This test also executes one full `run_stage_c` invocation to ensure the live BAML
    pipeline is exercised end-to-end (≈9 API calls / ≤27 worst-case per this test;
    accounted for in module docstring cost envelope).
    """
    fei_csv, av_csv = _seed_live_inputs(tmp_path)
    fu_csv = tmp_path / "fu.csv"
    sidecar_csv = tmp_path / "sidecar.csv"

    run_stage_c(
        fei_csv_path=fei_csv,
        artifact_csv_path=av_csv,
        out_usefulness_csv=fu_csv,
        out_sidecar_csv=sidecar_csv,
        max_parallel_queries=1,
        allow_partial=False,
    )

    # Compile-time pin of the BAML source (post-cc2c43b / AM-002 layout):
    # functional_evaluator.baml wires the Stage C function to `client GCPReasoner`;
    # the GCPReasoner client block in clients.baml carries the model + provider.
    baml_dir = Path(__file__).resolve().parents[3] / "baml_src"
    fe_content = (baml_dir / "functional_evaluator.baml").read_text(encoding="utf-8")
    clients_content = (baml_dir / "clients.baml").read_text(encoding="utf-8")
    assert "client GCPReasoner" in fe_content, (
        "functional_evaluator.baml no longer wires EvaluateFunctionalUsefulness "
        "to client GCPReasoner per AM-002"
    )
    assert "gemini-3.1-pro-preview" in clients_content, (
        "clients.baml GCPReasoner no longer pins gemini-3.1-pro-preview per locked DD-32"
    )
    assert "provider google-ai" in clients_content, (
        "clients.baml GCPReasoner no longer routes through google-ai per locked DD-32"
    )
