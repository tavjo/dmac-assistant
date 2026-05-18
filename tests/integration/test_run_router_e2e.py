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

REQUIRED_CREDS = (
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "NEXTSEEK_USERNAME",
    "NEXTSEEK_PASSWORD",
    "NEXTSEEK_URL",
    "GCP_API_KEY",
)

EXPECTED_QUERY_IDS = {
    "Search-Basic-1",
    "Graph-Lineage-1",
    "Edge-2",
    "Unsupported-1",
    "Unsupported-2",
}


def _missing_creds() -> list[str]:
    return [name for name in REQUIRED_CREDS if not os.environ.get(name)]


pytestmark = [
    pytest.mark.skipif(not docker_available(), reason="docker daemon not available"),
    pytest.mark.skipif(
        bool(_missing_creds()),
        reason=f"missing creds: {_missing_creds()!r}",
    ),
    pytest.mark.integration,
    pytest.mark.slow,
]


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
def test_run_router_e2e_full(_allow_unix_socket: None, tmp_path: Path) -> None:
    """Invoke the router E2E tool and assert on the emitted manifest."""
    output_base = tmp_path / "router-e2e"
    tool_path = REPO_ROOT / "tools" / "e2e" / "run_router_e2e.py"
    corpus_path = REPO_ROOT / "evidence" / "full-corpus-2026-05-07" / "corpus.json"
    assert tool_path.exists(), f"tool not found: {tool_path}"
    assert corpus_path.exists(), f"corpus not found: {corpus_path}"

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

    assert manifest["schema_version"] == 1
    assert manifest["run_id"] == run_dir.name
    assert isinstance(manifest["bridge_port"], int) and manifest["bridge_port"] > 0
    assert isinstance(manifest["bridge_pid"], int) and manifest["bridge_pid"] > 0

    queries = manifest["queries"]
    assert len(queries) == 5, f"expected 5 query records; got {len(queries)}"

    summary = manifest["summary"]
    assert summary["total"] == 5
    matched_recount = sum(1 for query in queries if query["route_match"])
    assert summary["matched"] == matched_recount

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

    assert summary["matched"] == 5, (
        f"route mismatches: matched={summary['matched']}; "
        f"mismatched={summary['mismatched']}; errored={summary['errored']}\n"
        f"records: "
        f"{[(q['query_id'], q['expected_route'], q['actual_route']) for q in queries]!r}"
    )
