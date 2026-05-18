#!/usr/bin/env python3
"""T5.1 end-to-end routing-discriminator runner."""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import pathlib
import socket
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import httpx
from websockets.asyncio.client import connect as ws_connect


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
DEFAULT_CORPUS = REPO_ROOT / "evidence" / "full-corpus-2026-05-07" / "corpus.json"
OUTPUT_BASE = REPO_ROOT / "evidence" / "router-e2e"

PER_QUERY_TIMEOUT_S = 180.0
BRIDGE_READY_TIMEOUT_S = 30.0
OVERALL_TIMEOUT_S = 30.0 + (5 * PER_QUERY_TIMEOUT_S) + 30.0

REQUIRED_CREDENTIALS = (
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "NEXTSEEK_USERNAME",
    "NEXTSEEK_PASSWORD",
    "NEXTSEEK_URL",
    "GCP_API_KEY",
)

DISCRIMINATORS: tuple[tuple[str, str], ...] = (
    ("Search-Basic-1", "nextseek_query"),
    ("Graph-Lineage-1", "nextseek_query"),
    ("Edge-2", "nextseek_query"),
    ("Unsupported-1", "container_cc"),
    ("Unsupported-2", "container_cc"),
)

KNOWN_FRAME_TYPES = frozenset(
    {
        "route_decided",
        "session_started",
        "assistant_message",
        "tool_use",
        "session_ended",
        "error",
    }
)

SYNTHETIC_USER_ID = "alice"
SYNTHETIC_PASSWORD = "s3cret-alice"
SYNTHETIC_PROJECT = "proj-a"


@dataclass
class QueryRecord:
    query_id: str
    query_text: str
    expected_route: str
    actual_route: str | None = None
    actual_model_class: str | None = None
    route_match: bool = False
    frames: list[dict[str, Any]] = field(default_factory=list)
    frames_captured: int = 0
    latency_seconds: float = 0.0
    started_at: str = ""
    completed_at: str = ""
    session_ended_reached: bool = False
    error: str | None = None


@dataclass
class Manifest:
    schema_version: int
    run_id: str
    started_at: str
    completed_at: str
    bridge_pid: int
    bridge_port: int
    queries: list[dict[str, Any]] = field(default_factory=list)
    summary: dict[str, int] = field(default_factory=dict)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat()


def _check_credentials() -> list[str]:
    return [name for name in REQUIRED_CREDENTIALS if not os.environ.get(name)]


def _check_image() -> bool:
    try:
        result = subprocess.run(
            [
                "docker",
                "images",
                "dmac-assistant:poc",
                "--format",
                "{{.Repository}}:{{.Tag}}",
            ],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False
    return "dmac-assistant:poc" in result.stdout


def _load_corpus(corpus_path: pathlib.Path) -> dict[str, str]:
    if not corpus_path.exists():
        raise FileNotFoundError(f"corpus not found: {corpus_path}")
    data = json.loads(corpus_path.read_text(encoding="utf-8"))
    queries = data.get("queries", [])
    by_id = {q["id"]: q["query"] for q in queries if "id" in q and "query" in q}
    missing = [qid for qid, _ in DISCRIMINATORS if qid not in by_id]
    if missing:
        raise KeyError(f"corpus missing required discriminator IDs: {missing!r}")
    return {qid: by_id[qid] for qid, _ in DISCRIMINATORS}


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _build_child_env(
    *,
    scratch_root: pathlib.Path,
    output_root: pathlib.Path,
    dropbox_root: pathlib.Path,
    catalog_file: pathlib.Path,
) -> dict[str, str]:
    child_env = os.environ.copy()
    pythonpath_parts = [str(REPO_ROOT / "src"), str(REPO_ROOT)]
    if child_env.get("PYTHONPATH"):
        pythonpath_parts.append(child_env["PYTHONPATH"])
    child_env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    child_env["DMAC_USERS"] = json.dumps(
        {
            SYNTHETIC_USER_ID: {
                "password": SYNTHETIC_PASSWORD,
                "projects": [SYNTHETIC_PROJECT],
            }
        }
    )
    child_env["DMAC_CLAUDE_USERS_ROOT"] = str(scratch_root / "claude-users")
    child_env["DMAC_SCRATCH_ROOT"] = str(scratch_root / "scratch")
    child_env["DMAC_DROPBOX_ROOT"] = str(dropbox_root)
    child_env["DMAC_OUTPUT_ROOT"] = str(output_root)
    child_env["DMAC_CATALOG_FILE_HOST_PATH"] = str(catalog_file)
    child_env["DMAC_ROUTER_ENABLED"] = "1"
    return child_env


def _launch_bridge(
    *,
    port: int,
    child_env: dict[str, str],
    stdout_log: pathlib.Path,
    stderr_log: pathlib.Path,
) -> subprocess.Popen[bytes]:
    cmd = [
        "uvicorn",
        "dmac_assistant.app:app",
        "--host",
        "127.0.0.1",
        "--port",
        str(port),
        "--log-level",
        "error",
    ]
    return subprocess.Popen(
        cmd,
        env=child_env,
        stdout=stdout_log.open("wb"),
        stderr=stderr_log.open("wb"),
    )


def _wait_for_ready(*, port: int, deadline: float) -> bool:
    url = f"http://127.0.0.1:{port}/health"
    while time.monotonic() < deadline:
        try:
            with httpx.Client(timeout=2.0) as client:
                if client.get(url).status_code == 200:
                    return True
        except (httpx.HTTPError, httpx.RequestError):
            pass
        time.sleep(0.5)
    return False


def _terminate_bridge(proc: subprocess.Popen[bytes]) -> None:
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        with contextlib.suppress(subprocess.TimeoutExpired):
            proc.wait(timeout=5)


def _login(*, port: int) -> str:
    url = f"http://127.0.0.1:{port}/auth/login"
    payload = {"user_id": SYNTHETIC_USER_ID, "password": SYNTHETIC_PASSWORD}
    with httpx.Client(timeout=10.0) as client:
        response = client.post(url, json=payload)
        response.raise_for_status()
    body = response.json()
    token = body.get("token") or body.get("access_token")
    if not token:
        raise RuntimeError(f"login response missing token field: {body!r}")
    return str(token)


async def _run_one_query(
    *,
    port: int,
    token: str,
    query_id: str,
    query_text: str,
    expected_route: str,
) -> QueryRecord:
    record = QueryRecord(
        query_id=query_id,
        query_text=query_text,
        expected_route=expected_route,
        started_at=_utc_now(),
    )
    started = time.monotonic()
    uri = f"ws://127.0.0.1:{port}/ws/chat"
    try:
        async with asyncio.timeout(PER_QUERY_TIMEOUT_S):
            async with ws_connect(
                uri,
                additional_headers={"authorization": f"Bearer {token}"},
            ) as ws:
                await ws.send(
                    json.dumps({"type": "user_message", "content": query_text})
                )
                while True:
                    raw = await ws.recv()
                    frame = json.loads(raw)
                    record.frames.append(frame)
                    frame_type = frame.get("type")
                    if frame_type not in KNOWN_FRAME_TYPES:
                        print(
                            f"[run_router_e2e] unknown frame type: {frame_type!r}",
                            file=sys.stderr,
                        )
                    if frame_type == "route_decided" and record.actual_route is None:
                        record.actual_route = frame.get("route")
                        record.actual_model_class = frame.get("model_class")
                    if frame_type == "session_ended":
                        record.session_ended_reached = True
                        break
    except TimeoutError:
        record.error = "timeout"
    except Exception as exc:  # noqa: BLE001 - E2E manifests should capture failures
        record.error = f"{type(exc).__name__}: {exc}"
    finally:
        record.latency_seconds = round(time.monotonic() - started, 3)
        record.completed_at = _utc_now()
        record.frames_captured = len(record.frames)
        record.route_match = (
            record.actual_route == expected_route and record.error is None
        )
    return record


async def _async_main(*, corpus_path: pathlib.Path, run_dir: pathlib.Path) -> int:
    queries_by_id = _load_corpus(corpus_path)
    run_id = run_dir.name
    started_at = _utc_now()

    scratch_root = run_dir / "scratch_state"
    output_root = run_dir / "output_state"
    dropbox_root = run_dir / "dropbox_state"
    scratch_root.mkdir(parents=True, exist_ok=True)
    output_root.mkdir(parents=True, exist_ok=True)
    dropbox_root.mkdir(parents=True, exist_ok=True)
    (dropbox_root / SYNTHETIC_PROJECT).mkdir(parents=True, exist_ok=True)

    catalog_file = run_dir / "agent_model_catalog.json"
    catalog_file.write_text('{"default": {}}', encoding="utf-8")

    port = _free_port()
    child_env = _build_child_env(
        scratch_root=scratch_root,
        output_root=output_root,
        dropbox_root=dropbox_root,
        catalog_file=catalog_file,
    )
    stdout_log = run_dir / "bridge.stdout.log"
    stderr_log = run_dir / "bridge.stderr.log"
    proc = _launch_bridge(
        port=port,
        child_env=child_env,
        stdout_log=stdout_log,
        stderr_log=stderr_log,
    )
    records: list[QueryRecord] = []
    try:
        if not _wait_for_ready(
            port=port,
            deadline=time.monotonic() + BRIDGE_READY_TIMEOUT_S,
        ):
            print(
                "[run_router_e2e] bridge did not become ready within "
                f"{BRIDGE_READY_TIMEOUT_S}s; check {stderr_log}",
                file=sys.stderr,
            )
            return 2
        token = _login(port=port)
        for query_id, expected in DISCRIMINATORS:
            query_text = queries_by_id[query_id]
            print(
                f"[run_router_e2e] running {query_id!r} ({expected})...",
                file=sys.stderr,
            )
            record = await _run_one_query(
                port=port,
                token=token,
                query_id=query_id,
                query_text=query_text,
                expected_route=expected,
            )
            records.append(record)
            (run_dir / f"{query_id}.record.json").write_text(
                json.dumps(asdict(record), indent=2),
                encoding="utf-8",
            )
            print(
                f"[run_router_e2e]   actual_route={record.actual_route!r} "
                f"match={record.route_match} latency={record.latency_seconds}s "
                f"error={record.error!r}",
                file=sys.stderr,
            )
    finally:
        _terminate_bridge(proc)

    summary = {
        "total": len(records),
        "matched": sum(1 for record in records if record.route_match),
        "mismatched": sum(
            1
            for record in records
            if record.actual_route is not None
            and not record.route_match
            and record.error is None
        ),
        "errored": sum(1 for record in records if record.error is not None),
    }
    manifest = Manifest(
        schema_version=1,
        run_id=run_id,
        started_at=started_at,
        completed_at=_utc_now(),
        bridge_pid=proc.pid,
        bridge_port=port,
        queries=[
            {
                "query_id": record.query_id,
                "query_text": record.query_text,
                "expected_route": record.expected_route,
                "actual_route": record.actual_route,
                "actual_model_class": record.actual_model_class,
                "route_match": record.route_match,
                "frames_captured": record.frames_captured,
                "frame_path": f"{record.query_id}.record.json",
                "latency_seconds": record.latency_seconds,
                "session_ended_reached": record.session_ended_reached,
                "error": record.error,
            }
            for record in records
        ],
        summary=summary,
    )
    manifest_path = run_dir / "manifest.json"
    manifest_path.write_text(json.dumps(asdict(manifest), indent=2), encoding="utf-8")
    print(f"[run_router_e2e] wrote manifest: {manifest_path}", file=sys.stderr)
    print(
        f"[run_router_e2e] summary: total={summary['total']} "
        f"matched={summary['matched']} mismatched={summary['mismatched']} "
        f"errored={summary['errored']}",
        file=sys.stderr,
    )
    return 0 if summary["matched"] == summary["total"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="LLM router E2E routing-discriminator runner"
    )
    parser.add_argument(
        "--corpus",
        type=pathlib.Path,
        default=DEFAULT_CORPUS,
        help=f"Path to corpus.json (default: {DEFAULT_CORPUS})",
    )
    parser.add_argument(
        "--output-base",
        type=pathlib.Path,
        default=OUTPUT_BASE,
        help=f"Output root for per-run dirs (default: {OUTPUT_BASE})",
    )
    args = parser.parse_args(argv)

    missing = _check_credentials()
    if missing:
        print(
            f"[run_router_e2e] missing required credentials: {missing!r}",
            file=sys.stderr,
        )
        return 2
    if not _check_image():
        print(
            "[run_router_e2e] dmac-assistant:poc image not present; "
            "run `make image-build` first",
            file=sys.stderr,
        )
        return 2

    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    run_dir = args.output_base / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    try:
        return asyncio.run(
            asyncio.wait_for(
                _async_main(corpus_path=args.corpus, run_dir=run_dir),
                timeout=OVERALL_TIMEOUT_S,
            )
        )
    except TimeoutError:
        print(
            f"[run_router_e2e] overall timeout ({OVERALL_TIMEOUT_S}s)",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
