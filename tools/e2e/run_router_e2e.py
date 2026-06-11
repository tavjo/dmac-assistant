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
from dotenv import load_dotenv
from websockets.asyncio.client import connect as ws_connect


REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent

# When invoked as a direct script (`python tools/e2e/run_router_e2e.py`), the
# repo root is NOT on sys.path, so `from tools.e2e.router_judge import ...`
# fails with ModuleNotFoundError — and the helper also imports
# `dmac_assistant.router.baml_client`, which lives under `src/`. Prepend both
# so direct-script execution works. The pyproject.toml::pythonpath setting
# only helps pytest. Must run BEFORE the `tools.e2e.router_judge` import.
for _path in (REPO_ROOT, REPO_ROOT / "src"):
    _path_str = str(_path)
    if _path_str not in sys.path:
        sys.path.insert(0, _path_str)

from tools.e2e.router_judge import (  # noqa: E402 — sys.path must be set first
    JudgeResult,
    VERDICT_INCONCLUSIVE,
    VERDICT_PASS,
    extract_reply_text,
    judge_reply,
    summarise_frames,
)
DEFAULT_CORPUS = REPO_ROOT / "evidence" / "full-corpus-2026-05-07" / "corpus.json"
OUTPUT_BASE = REPO_ROOT / "evidence" / "router-e2e"

# OI-5: raised 180->300 because auto-mode adds a classifier round-trip per CC
# tool call, slowing container_cc turns (the prior 180s Unsupported-1 timeout
# could otherwise worsen).
PER_QUERY_TIMEOUT_S = 300.0
BRIDGE_READY_TIMEOUT_S = 30.0
OVERALL_TIMEOUT_S = 30.0 + (6 * PER_QUERY_TIMEOUT_S) + 30.0

REQUIRED_CREDENTIALS = (
    "AWS_BEARER_TOKEN_BEDROCK",
    "AWS_REGION",
    "NEXTSEEK_USERNAME",
    "NEXTSEEK_PASSWORD",
    "NEXTSEEK_URL",
    "GCP_API_KEY",
)

# T13: the NS-route discriminators now traverse agent -> sidecar / assistant
# viewset (T9 moved NS parsing OUT of the agent). The agent container is on the
# `dmac-nextseek-net` sidecar network ONLY, so the viewset must be reached via the
# host gateway, not `localhost` (which is the container itself in-container). The
# host-side harness never calls NEXTSEEK_URL directly (it logs into its own
# 127.0.0.1 bridge), so this translation affects ONLY the value forwarded into the
# agent container. NEVER edit .env — this is a per-invocation, container-only seam.
#
# SEAM (E2E target = the LOCAL NExtSEEK stack, NOT the dev server). The host-side
# validation guard (build_tools.verify_env) requires NEXTSEEK_URL to be an https
# `dev` URL, so it cannot be repointed to the local http stack without making the
# live suite skip. The local target is therefore carried by a SEPARATE override,
# `DMAC_E2E_NS_URL` (host terms, default http://localhost:8000); NEXTSEEK_URL keeps
# its validated dev value (presence-checked here) while the agent is pointed at the
# local stack via the gateway-translated override below.
_AGENT_NS_GATEWAY_HOST = "host.docker.internal"
_LOCALHOST_HOSTS = frozenset({"localhost", "127.0.0.1", "0.0.0.0"})
_DEFAULT_E2E_NS_URL = "http://localhost:8000"

# T13: the sidecar must be reachable before the NS-route queries run. The harness
# does NOT own the compose lifecycle (it would race the operator's `make
# sidecar-up`/`-down` and the live_docker pytest fixture's session-scoped bring-up).
# Instead it ASSERTS the precondition and fails fast and loud — the operator brings
# the stack up via `make sidecar-up` (Step 3 run command) per R-6. The bridge's own
# start_container also fails fast on a missing network, but that surfaces only as a
# per-query transport error in bridge.stderr.log; this up-front check is louder.
_SIDECAR_NETWORK = os.environ.get("DMAC_SIDECAR_NETWORK", "dmac-nextseek-net")
_SIDECAR_CONTAINER = "dmac-nextseek-sidecar-nextseek-sidecar-1"

# OI-4/OI-5 demo set: 3 NS + 2 container_cc (lab-data TASKS, not the off-topic-
# knowledge queries that now route `unrelated`) + 1 unrelated (Taylor Swift).
DISCRIMINATORS: tuple[tuple[str, str], ...] = (
    ("Search-Basic-1", "nextseek_query"),
    ("Graph-Lineage-1", "nextseek_query"),
    ("Edge-2", "nextseek_query"),
    ("Unsupported-1", "container_cc"),
    ("Unsupported-4", "container_cc"),
    ("Unrelated-1", "unrelated"),
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

# Bridge auth + container NS-credential propagation
# -------------------------------------------------
# The bridge passes the WS login user_id/password straight through to the
# container as NEXTSEEK_USERNAME / NEXTSEEK_PASSWORD (see
# src/dmac_assistant/containers.py::_build_environment). To make live NS API
# calls land with real credentials, the harness logs in with the same
# NEXTSEEK_* values it ultimately wants forwarded into the container.
# `_check_credentials()` validates both env vars are present before
# `_build_child_env` / `_login` are called.
def _ns_user_id() -> str:
    return os.environ["NEXTSEEK_USERNAME"]


def _ns_password() -> str:
    return os.environ["NEXTSEEK_PASSWORD"]


_DEFAULT_E2E_PROJECT = "proj-a"


def _synthetic_project() -> str:
    """Project label written into the synthetic user record + dropbox state.

    Override via ``DMAC_E2E_PROJECT`` env var when ``proj-a`` is not in the
    bridge project allowlist (multi-user deployments). Empty string is
    treated as unset so operator typos like ``DMAC_E2E_PROJECT=`` fall back
    to the default rather than silently propagating into the user record
    and the dropbox mkdir.
    """
    value = os.environ.get("DMAC_E2E_PROJECT", "")
    return value or _DEFAULT_E2E_PROJECT


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
    # Phase 7 Residual #5 — semantic judge fields. Default `INCONCLUSIVE` so
    # records that never reach the judge (timeout, websocket crash) do not
    # accidentally satisfy the exit-code gate. `reply_text` is the full agent
    # reply persisted only to the per-query record file (NOT stdout/stderr).
    reply_text: str = ""
    semantic_verdict: str = VERDICT_INCONCLUSIVE
    semantic_reasoning: str = ""
    judge_latency_seconds: float = 0.0


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


def _agent_nextseek_url() -> str:
    """The NEXTSEEK_URL value to FORWARD INTO the agent container.

    Prefers the local-stack override `DMAC_E2E_NS_URL` (default
    http://localhost:8000); falls back to `NEXTSEEK_URL`. Translates a host-local
    host (`localhost`/`127.0.0.1`) to the Docker host gateway so the in-container
    thin runner_ns -> assistant viewset call resolves. A non-local host (the dev
    server, an in-network DNS name) is passed through unchanged.
    """
    import urllib.parse

    raw = (
        os.environ.get("DMAC_E2E_NS_URL")
        or os.environ.get("NEXTSEEK_URL")
        or _DEFAULT_E2E_NS_URL
    )
    parsed = urllib.parse.urlsplit(raw)
    if parsed.hostname in _LOCALHOST_HOSTS:
        netloc = _AGENT_NS_GATEWAY_HOST
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urllib.parse.urlunsplit(parsed._replace(netloc=netloc))
    return raw


def _check_sidecar() -> str | None:
    """Return a human error string if the sidecar precondition is unmet, else None.

    Verifies (a) the sidecar Docker network exists and (b) the sidecar container is
    running. Both are required for the NS-route discriminators to traverse
    agent -> sidecar / viewset. Best-effort: a docker CLI failure is reported, not
    swallowed.
    """
    try:
        net = subprocess.run(
            ["docker", "network", "inspect", _SIDECAR_NETWORK, "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if net.returncode != 0 or _SIDECAR_NETWORK not in net.stdout:
            return (
                f"sidecar network {_SIDECAR_NETWORK!r} not found; "
                "run `make sidecar-up` first"
            )
        ps = subprocess.run(
            ["docker", "ps", "--filter", f"name={_SIDECAR_CONTAINER}",
             "--filter", "status=running", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=10, check=False,
        )
        if _SIDECAR_CONTAINER not in ps.stdout:
            return (
                f"sidecar container {_SIDECAR_CONTAINER!r} not running; "
                "run `make sidecar-up` first"
            )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return f"could not verify sidecar precondition: {type(exc).__name__}"
    return None


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
            _ns_user_id(): {
                "password": _ns_password(),
                "projects": [_synthetic_project()],
            }
        }
    )
    child_env["DMAC_CLAUDE_USERS_ROOT"] = str(scratch_root / "claude-users")
    child_env["DMAC_SCRATCH_ROOT"] = str(scratch_root / "scratch")
    child_env["DMAC_DROPBOX_ROOT"] = str(dropbox_root)
    child_env["DMAC_OUTPUT_ROOT"] = str(output_root)
    child_env["DMAC_CATALOG_FILE_HOST_PATH"] = str(catalog_file)
    child_env["DMAC_ROUTER_ENABLED"] = "1"
    # T13: forward the AGENT-reachable NEXTSEEK_URL (host-gateway-translated) so the
    # in-container runner_ns -> assistant viewset call resolves from inside the
    # sidecar-network-only agent container. The host-side harness keeps using its
    # own 127.0.0.1 bridge for login, so this only changes the container's view.
    child_env["NEXTSEEK_URL"] = _agent_nextseek_url()
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
    payload = {"user_id": _ns_user_id(), "password": _ns_password()}
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
    (dropbox_root / _synthetic_project()).mkdir(parents=True, exist_ok=True)

    # T13 vendored-catalog decision (vet finding 18): KEPT as a documented
    # invariant, NOT relaxed. RATIONALE: the in-agent NS parser that historically
    # consumed this catalog (gemini-3.1-pro-preview + thinking_budget=16000) no
    # longer runs in the agent — T9 moved NS parsing to the NExtSEEK assistant
    # viewset, and the 16 shared-cred keys are stripped from the agent env. So the
    # catalog is no longer load-bearing for the NS ROUTE'S ANSWER. It is, however,
    # still REQUIRED because the bridge's _build_volumes ALWAYS bind-mounts the
    # catalog file into every agent container (containers.py: catalog -> CATALOG_FILE,
    # ro) and a missing host file makes the mount fail. Keeping the existence check
    # therefore preserves a real precondition (container boot) rather than a stale
    # one (a parser that no longer runs). The container_cc route does not read it.
    catalog_file = REPO_ROOT / "vendor" / "chat_nextseek" / "agent_model_catalog.json"
    if not catalog_file.exists():
        raise FileNotFoundError(
            f"chat_nextseek agent-model catalog not found at {catalog_file}; "
            "the E2E harness requires it because the bridge always bind-mounts a "
            "catalog file into every agent container (CATALOG_FILE) — without it "
            "the container mount fails. NS parsing itself moved to the viewset (T9)."
        )

    sidecar_problem = _check_sidecar()
    if sidecar_problem is not None:
        print(f"[run_router_e2e] sidecar precondition failed: {sidecar_problem}",
              file=sys.stderr)
        return 2

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
            # Phase 7 Residual #5 — semantic judging. Reply text is extracted
            # from the captured frames (last assistant_message before
            # session_ended; falls back to a stub describing any terminal
            # error frame). Judge is invoked unconditionally so even
            # route-mismatched or errored queries get a verdict on disk;
            # the exit-code gate later requires PASS, so this is safe.
            record.reply_text = extract_reply_text(record.frames)
            frames_summary = summarise_frames(record.frames)
            judge_result: JudgeResult = await judge_reply(
                query_id=record.query_id,
                query_text=record.query_text,
                expected_route=record.expected_route,
                actual_route=record.actual_route,
                reply_text=record.reply_text,
                frames_summary=frames_summary,
            )
            record.semantic_verdict = judge_result.verdict
            record.semantic_reasoning = judge_result.reasoning
            record.judge_latency_seconds = judge_result.latency_seconds
            records.append(record)
            (run_dir / f"{query_id}.record.json").write_text(
                json.dumps(asdict(record), indent=2),
                encoding="utf-8",
            )
            # Logging contract: NEVER write the raw reply text to stderr
            # where it could be captured by CI. Only structural facts.
            print(
                f"[run_router_e2e]   actual_route={record.actual_route!r} "
                f"match={record.route_match} latency={record.latency_seconds}s "
                f"error={record.error!r} "
                f"reply_len={len(record.reply_text)} "
                f"semantic_verdict={record.semantic_verdict!r} "
                f"judge_latency={record.judge_latency_seconds}s",
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
        # Phase 7 Residual #5 — semantic-verdict tallies. The exit-code gate
        # requires BOTH route_match AND semantic_verdict == "PASS" for every
        # query, so these counts let operators triage failures quickly.
        "semantically_passed": sum(
            1 for record in records if record.semantic_verdict == VERDICT_PASS
        ),
        "semantically_failed": sum(
            1 for record in records if record.semantic_verdict == "FAIL"
        ),
        "semantically_inconclusive": sum(
            1
            for record in records
            if record.semantic_verdict == VERDICT_INCONCLUSIVE
        ),
    }
    manifest = Manifest(
        schema_version=2,
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
                # Phase 7 Residual #5 — per-query semantic verdict surface.
                # `reply_text` is NOT included in the manifest — only in the
                # per-query record file — to keep manifest.json compact and
                # auditable. Use `frame_path` to fetch the full reply.
                "reply_length": len(record.reply_text),
                "semantic_verdict": record.semantic_verdict,
                "semantic_reasoning": record.semantic_reasoning,
                "judge_latency_seconds": record.judge_latency_seconds,
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
        f"errored={summary['errored']} "
        f"semantically_passed={summary['semantically_passed']} "
        f"semantically_failed={summary['semantically_failed']} "
        f"semantically_inconclusive={summary['semantically_inconclusive']}",
        file=sys.stderr,
    )
    # Phase 7 Residual #5 — exit-code gate. Previously: 0 iff every query's
    # actual_route matched its expected_route. Now: 0 iff every query also
    # has semantic_verdict == "PASS". A FAIL or INCONCLUSIVE verdict (or a
    # route mismatch, or a transport error) all flip the run to exit 1.
    fully_passed = sum(
        1
        for record in records
        if record.route_match and record.semantic_verdict == VERDICT_PASS
    )
    return 0 if fully_passed == summary["total"] else 1


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

    load_dotenv(REPO_ROOT / ".env", override=False)

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
