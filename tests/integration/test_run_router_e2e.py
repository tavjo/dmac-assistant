"""T5.1 wrapper test for ``tools/e2e/run_router_e2e.py``."""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from tests.harness.containers import docker_available, ensure_image


REPO_ROOT = Path(__file__).resolve().parent.parent.parent

EXPECTED_QUERY_IDS = {
    "Search-Basic-1",
    "Graph-Lineage-1",
    "Edge-2",
    "Unsupported-1",
    "Unsupported-2",
}


class _RedactedEnv(dict[str, str]):
    def __repr__(self) -> str:
        return "<redacted live env>"


pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.integration,
    # `live` is required (not just `live_bridge`) so the conftest session
    # guard at tests/conftest.py:158 counts this test toward the
    # "selected-but-none-ran" red-fail check. `live_bridge` is the narrower
    # marker for deselection via `-m "not live_bridge"`.
    pytest.mark.live,
    pytest.mark.live_bridge,
    pytest.mark.slow,
]


@pytest.fixture
def _router_e2e_env(live_env: dict[str, str]) -> _RedactedEnv:
    return _RedactedEnv(live_env)


@pytest.fixture(scope="module", autouse=True)
def _ensure_image() -> str:
    try:
        return ensure_image()
    except RuntimeError as exc:
        pytest.skip(str(exc))


@pytest.fixture
def _allow_unix_socket():
    """Allow AF_UNIX sockets for the docker-py image check."""
    try:
        import pytest_socket
    except ImportError:
        yield
        return

    pytest_socket.enable_socket()
    pytest_socket.disable_socket(allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


@pytest.mark.timeout(1200)
def test_run_router_e2e_full(
    _allow_unix_socket: None,
    _router_e2e_env: _RedactedEnv,
    tmp_path: Path,
) -> None:
    """Invoke the router E2E tool and assert on the emitted manifest."""
    output_base = tmp_path / "router-e2e"
    tool_path = REPO_ROOT / "tools" / "e2e" / "run_router_e2e.py"
    corpus_path = REPO_ROOT / "evidence" / "full-corpus-2026-05-07" / "corpus.json"
    assert tool_path.exists(), f"tool not found: {tool_path}"
    assert corpus_path.exists(), f"corpus not found: {corpus_path}"

    child_env = os.environ.copy()
    child_env.update(_router_e2e_env)

    result = subprocess.run(
        [
            sys.executable,
            str(tool_path),
            "--corpus",
            str(corpus_path),
            "--output-base",
            str(output_base),
        ],
        capture_output=True,
        env=child_env,
        text=True,
        timeout=1100,
        check=False,
    )
    print(result.stderr, file=sys.stderr)
    assert result.returncode == 0, (
        f"run_router_e2e.py exited {result.returncode}; stderr:\n{result.stderr}"
    )

    run_dirs = sorted(output_base.glob("[0-9]*T[0-9]*Z"))
    assert len(run_dirs) == 1, (
        f"expected exactly one run dir under {output_base}; got: {run_dirs!r}"
    )
    run_dir = run_dirs[0]
    manifest_path = run_dir / "manifest.json"
    assert manifest_path.exists(), f"manifest missing: {manifest_path}"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    # Phase 7 Residual #5 — manifest schema bumped 1 -> 2 when per-query
    # semantic-verdict fields were added. The run is also gated on
    # semantic PASS now, so the exit-code assertion above (== 0) implicitly
    # also asserts every query passed the BAML judge.
    assert manifest["schema_version"] == 2
    assert manifest["run_id"] == run_dir.name
    assert isinstance(manifest["bridge_port"], int) and manifest["bridge_port"] > 0
    assert isinstance(manifest["bridge_pid"], int) and manifest["bridge_pid"] > 0

    queries = manifest["queries"]
    assert len(queries) == 5, f"expected 5 query records; got {len(queries)}"

    summary = manifest["summary"]
    assert summary["total"] == 5
    matched_recount = sum(1 for query in queries if query["route_match"])
    assert summary["matched"] == matched_recount
    # New v2 summary fields are present and counts cohere with per-query data.
    semantic_pass_recount = sum(
        1 for query in queries if query["semantic_verdict"] == "PASS"
    )
    assert summary["semantically_passed"] == semantic_pass_recount
    assert summary["semantically_failed"] == sum(
        1 for query in queries if query["semantic_verdict"] == "FAIL"
    )
    assert summary["semantically_inconclusive"] == sum(
        1 for query in queries if query["semantic_verdict"] == "INCONCLUSIVE"
    )

    for query in queries:
        query_id = query["query_id"]
        assert query_id in EXPECTED_QUERY_IDS, f"unexpected query_id: {query_id!r}"
        assert query["actual_route"] in {"nextseek_query", "container_cc"}, (
            f"missing/invalid actual_route for {query_id!r}: "
            f"{query['actual_route']!r}"
        )
        if query["error"] is None:
            assert query["session_ended_reached"] is True, (
                f"{query_id}: error is None but session_ended_reached=False"
            )
        # Phase 7 Residual #5 — per-query manifest entries carry semantic
        # verdict surface (reply_length, verdict, reasoning, latency).
        assert query["semantic_verdict"] in {"PASS", "FAIL", "INCONCLUSIVE"}, (
            f"{query_id}: invalid semantic_verdict {query['semantic_verdict']!r}"
        )
        assert isinstance(query["reply_length"], int) and query["reply_length"] >= 0
        assert isinstance(query["semantic_reasoning"], str)
        assert isinstance(query["judge_latency_seconds"], (int, float))

        frame_path = run_dir / query["frame_path"]
        assert frame_path.exists(), f"per-query record missing: {frame_path}"
        record = json.loads(frame_path.read_text(encoding="utf-8"))
        frame_types = [frame["type"] for frame in record["frames"]]
        assert "route_decided" in frame_types, (
            f"{query_id}: no route_decided frame captured; "
            f"frame_types={frame_types!r}"
        )
        assert frame_types[0] == "route_decided", (
            f"{query_id}: route_decided was not first; saw {frame_types[0]!r}"
        )
        # Per-query record carries the full reply_text (manifest does not).
        assert "reply_text" in record, (
            f"{query_id}: record missing reply_text (Phase 7 Residual #5)"
        )

    assert summary["matched"] == 5, (
        f"route mismatches: matched={summary['matched']}; "
        f"mismatched={summary['mismatched']}; errored={summary['errored']}\n"
        f"records: "
        f"{[(q['query_id'], q['expected_route'], q['actual_route']) for q in queries]!r}"
    )
    # Exit code 0 already implies semantic PASS for every query, but assert
    # explicitly so the failure message is interpretable.
    assert summary["semantically_passed"] == 5, (
        f"semantic-judge failures: "
        f"passed={summary['semantically_passed']}; "
        f"failed={summary['semantically_failed']}; "
        f"inconclusive={summary['semantically_inconclusive']}\n"
        f"records: "
        f"{[(q['query_id'], q['semantic_verdict'], q['semantic_reasoning']) for q in queries]!r}"
    )
