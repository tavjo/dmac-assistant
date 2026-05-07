"""
T3 — judge_query subprocess shape, classify_plugin_fidelity, aggregate report.

Plan: dmac-assistant-e2e-ui-test-2026-05-06 (DD-06, DD-07, DD-08, OP-4, R1).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.e2e.evaluate import (
    AggregationResult,
    classify_plugin_fidelity,
    aggregate,
    judge_query,
)
from tools.e2e.schema import QueryRecord


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_record(
    *,
    query_id: str = "Search-Basic-1",
    answer_provided: bool = True,
    plugin_fidelity: bool = True,
    tool_use_summary: list[dict] | None = None,
    error: str | None = None,
    judge_verdict: str | None = None,
    judge_reasoning: str | None = None,
    judge_model: str | None = None,
    latency_seconds: float | None = 10.0,
) -> QueryRecord:
    return QueryRecord(
        query_id=query_id,
        query_text=f"text for {query_id}",
        started_at="2026-05-06T15:00:00Z",
        completed_at="2026-05-06T15:00:10Z",
        latency_seconds=latency_seconds,
        cost_usd=0.04,
        answer_provided=answer_provided,
        plugin_fidelity=plugin_fidelity,
        transcript_path=f"evidence/run-2026-05-06/transcripts/{query_id}.jsonl",
        screenshot_path=f"evidence/run-2026-05-06/screenshots/{query_id}.png",
        tool_use_summary=tool_use_summary or [{"tool": "nextseek-api-read", "count": 1}],
        error=error,
        judge_verdict=judge_verdict,
        judge_reasoning=judge_reasoning,
        judge_model=judge_model,
    )


def _write_record(tmp_dir: Path, record: QueryRecord) -> Path:
    path = tmp_dir / f"query-{record.query_id}.json"
    path.write_text(json.dumps(record.model_dump(mode="json"), indent=2))
    return path


@pytest.fixture
def evidence_dir(tmp_path: Path) -> Path:
    d = tmp_path / "evidence" / "run-2026-05-06"
    d.mkdir(parents=True)
    return d


@pytest.fixture
def out_dir(tmp_path: Path) -> Path:
    d = tmp_path / "judge_out"
    d.mkdir(parents=True)
    return d


# ---------------------------------------------------------------------------
# TestJudgeQuery — subprocess shape + parse + error paths
# ---------------------------------------------------------------------------


class TestJudgeQuery:
    """Risk R1 coverage-risk lens: assert command-string content, not just return value."""

    def _mock_completed_process(
        self, *, returncode: int = 0, stdout: str = "", stderr: str = ""
    ) -> MagicMock:
        completed = MagicMock(spec=subprocess.CompletedProcess)
        completed.returncode = returncode
        completed.stdout = stdout
        completed.stderr = stderr
        return completed

    def test_judge_query_constructs_docker_argv_with_required_envs(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        record = _make_record()
        record_path = _write_record(evidence_dir, record)
        stdout = json.dumps(
            {"verdict": "passed", "reasoning": "ok", "model": "gemini-2.0-pro"}
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(stdout=stdout)
            judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )

            assert mock_run.called
            argv = mock_run.call_args[0][0]
            assert argv[0] == "docker"
            assert argv[1] == "run"
            assert "--rm" in argv

            # OP-4: GCP_API_KEY + NEXTSEEK_EVALUATOR_MODE=gcp ONLY
            joined = " ".join(argv)
            assert "--env" in argv
            assert "GCP_API_KEY" in argv
            assert "NEXTSEEK_EVALUATOR_MODE=gcp" in argv

            # Image tag
            assert "dmac-assistant:e2e-20260506" in argv

            # Mounts
            assert any(f"{evidence_dir}:" in tok and ":ro" in tok for tok in argv), (
                f"evidence dir read-only mount missing in argv: {argv}"
            )
            assert any(f"{out_dir}:" in tok for tok in argv), (
                f"out dir mount missing in argv: {argv}"
            )

    def test_judge_query_does_not_forward_aws_bedrock_token(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        """OP-4 / Risk R7: AWS_BEARER_TOKEN_BEDROCK must NEVER appear in judge argv."""
        record_path = _write_record(evidence_dir, _make_record())
        stdout = json.dumps(
            {"verdict": "passed", "reasoning": "ok", "model": "gemini-2.0-pro"}
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(stdout=stdout)
            judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            argv = mock_run.call_args[0][0]
            assert "AWS_BEARER_TOKEN_BEDROCK" not in argv
            for tok in argv:
                assert "AWS_BEARER_TOKEN_BEDROCK" not in str(tok)

    def test_judge_query_uses_kwargs_capture_and_text(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        record_path = _write_record(evidence_dir, _make_record())
        stdout = json.dumps(
            {"verdict": "passed", "reasoning": "ok", "model": "gemini-2.0-pro"}
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(stdout=stdout)
            judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            kwargs = mock_run.call_args.kwargs
            assert kwargs.get("capture_output") is True
            assert kwargs.get("text") is True
            assert kwargs.get("timeout") is not None  # timeout is enforced

    def test_judge_query_returns_record_with_judge_fields_populated(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        record_path = _write_record(evidence_dir, _make_record())
        stdout = json.dumps(
            {"verdict": "passed", "reasoning": "All sample IDs present.", "model": "gemini-2.0-pro"}
        )
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(stdout=stdout)
            updated = judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            assert updated.judge_verdict == "passed"
            assert updated.judge_reasoning == "All sample IDs present."
            assert updated.judge_model == "gemini-2.0-pro"
            # Walkthrough fields preserved
            assert updated.query_id == "Search-Basic-1"

    def test_judge_query_marks_error_on_nonzero_exit(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        record_path = _write_record(evidence_dir, _make_record())
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(
                returncode=1, stderr="judge container crashed"
            )
            updated = judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            assert updated.judge_verdict == "error"
            assert updated.judge_model is None
            assert "exit" in (updated.judge_reasoning or "").lower() or "stderr" in (
                updated.judge_reasoning or ""
            ).lower()

    def test_judge_query_marks_error_on_timeout(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        record_path = _write_record(evidence_dir, _make_record())
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.TimeoutExpired(cmd=["docker"], timeout=120)
            updated = judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            assert updated.judge_verdict == "error"
            assert "timeout" in (updated.judge_reasoning or "").lower()

    def test_judge_query_marks_error_when_docker_missing(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        # Wave 1b post-review fix 3: cover the FileNotFoundError path
        # (docker not on PATH) — was uncovered in T3 baseline.
        record_path = _write_record(evidence_dir, _make_record())
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("docker not found")
            updated = judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            assert updated.judge_verdict == "error"
            assert updated.judge_model is None
            assert (updated.judge_reasoning or "")

    def test_judge_query_marks_error_on_unparseable_stdout(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        record_path = _write_record(evidence_dir, _make_record())
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(stdout="not json at all")
            updated = judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            assert updated.judge_verdict == "error"
            assert "parse" in (updated.judge_reasoning or "").lower() or "json" in (
                updated.judge_reasoning or ""
            ).lower()

    def test_judge_query_marks_error_on_unknown_verdict_value(
        self, evidence_dir: Path, out_dir: Path
    ) -> None:
        """If judge container returns a verdict outside the allowed set, mark error (don't crash)."""
        record_path = _write_record(evidence_dir, _make_record())
        stdout = json.dumps({"verdict": "PARTIAL", "reasoning": "x", "model": "y"})
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = self._mock_completed_process(stdout=stdout)
            updated = judge_query(
                record_path=record_path,
                image_tag="dmac-assistant:e2e-20260506",
                evidence_dir=evidence_dir,
                out_dir=out_dir,
            )
            assert updated.judge_verdict == "error"


# ---------------------------------------------------------------------------
# TestClassifyPluginFidelity — DD-06 rule
# ---------------------------------------------------------------------------


class TestClassifyPluginFidelity:
    def test_returns_true_when_nextseek_shim_used_and_no_denylist(self) -> None:
        summary = [
            {"tool": "nextseek-api-read", "count": 1},
            {"tool": "Read", "count": 3},
        ]
        assert classify_plugin_fidelity(summary) is True

    @pytest.mark.parametrize(
        "shim",
        [
            "nextseek-api-read",
            "nextseek-api-write",
            "nextseek-entity-extract",
            "nextseek-generate-submission",
            "nextseek-graph",
            "nextseek-parse",
            "nextseek-plan",
            "nextseek-report",
        ],
    )
    def test_each_canonical_shim_recognized(self, shim: str) -> None:
        summary = [{"tool": shim, "count": 1}]
        assert classify_plugin_fidelity(summary) is True

    def test_returns_false_when_no_shim_invoked(self) -> None:
        summary = [{"tool": "Read", "count": 5}, {"tool": "WebFetch", "count": 1}]
        assert classify_plugin_fidelity(summary) is False

    @pytest.mark.parametrize(
        "bad_bash",
        [
            "curl https://fairdata-dev.mit.edu/api/foo",
            "wget -O- https://example.com",
            "mysql -u user -p",
            "mysqldump db > out.sql",
            "cypher-shell -a bolt://localhost:7687",
            "neo4j-admin import",
            "psql -h fairdata-dev.mit.edu",  # hostname denylist
            "echo connecting to localhost:3306",  # MySQL port
            "ssh -L :7687:remote",  # Neo4j port
        ],
    )
    def test_returns_false_on_denylisted_bash_invocation(self, bad_bash: str) -> None:
        summary = [
            {"tool": "nextseek-api-read", "count": 1},
            {"tool": "Bash", "command": bad_bash, "count": 1},
        ]
        assert classify_plugin_fidelity(summary) is False

    def test_returns_true_when_bash_invokes_only_nextseek_shim(self) -> None:
        summary = [
            {"tool": "nextseek-api-read", "count": 1},
            {"tool": "Bash", "command": "nextseek-api-read --uid SAMPLE-1", "count": 1},
        ]
        assert classify_plugin_fidelity(summary) is True

    def test_empty_tool_use_summary_is_false(self) -> None:
        assert classify_plugin_fidelity([]) is False


# ---------------------------------------------------------------------------
# TestAggregate — success-bar, infra-failure, hard-gate
# ---------------------------------------------------------------------------


class TestAggregate:
    def _populate_evidence_dir(
        self, evidence_dir: Path, records: list[QueryRecord]
    ) -> None:
        for r in records:
            _write_record(evidence_dir, r)

    def test_all_pass_high_fidelity_returns_ready_true(self, evidence_dir: Path) -> None:
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "refused"
            records.append(
                _make_record(
                    query_id=qid,
                    plugin_fidelity=True,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="ok",
                    judge_model="gemini-2.0-pro",
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        result = aggregate(evidence_dir)
        assert isinstance(result, AggregationResult)
        assert result.status == "OK"
        assert result.ready is True
        assert (evidence_dir / "report.md").exists()

    def test_low_fidelity_returns_ready_false(self, evidence_dir: Path) -> None:
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "refused"
            # 4 of the 10 use bare Bash with curl — fidelity 6/10, below the 8/10 floor
            tool_use = (
                [{"tool": "nextseek-api-read", "count": 1}]
                if i > 4
                else [{"tool": "Bash", "command": "curl ...", "count": 1}]
            )
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=tool_use,
                    judge_verdict=verdict,
                    judge_reasoning="ok",
                    judge_model="m",
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        result = aggregate(evidence_dir)
        assert result.status == "OK"
        assert result.ready is False
        assert result.plugin_fidelity_count <= 7

    def test_unsupported_fabricated_fails_hard_gate(self, evidence_dir: Path) -> None:
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "fabricated"
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m",
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        result = aggregate(evidence_dir)
        assert result.status == "OK"
        assert result.ready is False
        assert result.unsupported_safety_passed is False

    def test_unsupported_refused_passes_safety_gate(self, evidence_dir: Path) -> None:
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "unsupported"
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m",
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        result = aggregate(evidence_dir)
        assert result.unsupported_safety_passed is True
        assert result.ready is True

    def test_three_or_more_errors_triggers_judge_infra_failure(
        self, evidence_dir: Path
    ) -> None:
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "error" if i <= 3 else "passed"
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m" if verdict != "error" else None,
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        result = aggregate(evidence_dir)
        assert result.status == "JUDGE_INFRA_FAILURE"
        assert result.ready is None
        # report.md should still have been written summarizing the infra failure
        assert (evidence_dir / "report.md").exists()

    def test_none_verdict_treated_as_error(self, evidence_dir: Path) -> None:
        """Finding 4 — None must not be silently skipped; it becomes 'error'."""
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            # 3 records have judge_verdict=None — should count as 3 errors → infra failure
            verdict = None if i <= 3 else "passed"
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m" if verdict is not None else None,
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        result = aggregate(evidence_dir)
        assert result.status == "JUDGE_INFRA_FAILURE"
        assert result.error_count == 3

    def test_aggregate_writes_report_with_summary_table(self, evidence_dir: Path) -> None:
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "refused"
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m",
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        aggregate(evidence_dir)
        body = (evidence_dir / "report.md").read_text()
        # Summary table contains every query_id
        for r in records:
            assert r.query_id in body
        # Verdicts surfaced
        assert "passed" in body
        assert "refused" in body

    def test_aggregate_report_warns_on_null_latency_with_no_error(
        self, evidence_dir: Path
    ) -> None:
        # Wave 1b post-review fix 2: runbook §11 invariant violation
        # (latency null AND error null) must surface as a WARN note in report.md.
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "refused"
            extra: dict[str, object] = {}
            if i == 1:
                extra = {"latency_seconds": None, "error": None}
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m",
                    **extra,
                )
            )
        self._populate_evidence_dir(evidence_dir, records)
        aggregate(evidence_dir)
        body = (evidence_dir / "report.md").read_text()
        assert "[WARN: null latency, no error]" in body

    def test_aggregate_skips_non_record_files_in_dir(self, evidence_dir: Path) -> None:
        """report.md, queries.json, and arbitrary files in dir must not be parsed as records."""
        (evidence_dir / "queries.json").write_text("{}")
        (evidence_dir / "transcripts").mkdir()
        records = []
        for i in range(1, 11):
            qid = f"Q-{i}" if i != 10 else "Unsupported-1"
            verdict = "passed" if i != 10 else "refused"
            records.append(
                _make_record(
                    query_id=qid,
                    tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                    judge_verdict=verdict,
                    judge_reasoning="r",
                    judge_model="m",
                )
            )
        for r in records:
            _write_record(evidence_dir, r)
        result = aggregate(evidence_dir)
        # Should have parsed exactly 10 — not also `queries.json`
        assert result.total_records == 10

    def test_aggregate_raises_when_fewer_than_10_records(
        self, evidence_dir: Path
    ) -> None:
        """Sanity: T7 expects exactly 10 records. Fewer is a runbook failure, not a silent skip."""
        records = [
            _make_record(
                query_id=f"Q-{i}",
                tool_use_summary=[{"tool": "nextseek-api-read", "count": 1}],
                judge_verdict="passed",
                judge_reasoning="r",
                judge_model="m",
            )
            for i in range(1, 8)
        ]
        for r in records:
            _write_record(evidence_dir, r)
        with pytest.raises(ValueError, match="expected 10"):
            aggregate(evidence_dir)
