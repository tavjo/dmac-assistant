"""Headless dispatch helpers for the router batch driver.

Two entry points:
  * `dispatch_cc(...)` — container_cc route. Thin wrapper around
    `run_headless.run_one()`; forwards `model_id` so claude consumes the
    router-chosen Bedrock model. Inherits all run_one semantics for cost,
    num_turns, stop_reason from the in-container stream-json result event.
  * `dispatch_ns(...)` — nextseek_query route. Spawns `docker run --rm -i
    <image> python /opt/dmac/runner_ns.py --session <id>` per query.
    Parses the runner's JSONL on stdout (`query_complete`, `query_error`,
    `ns_runner_error`) into a QueryRecord-shaped dict. CC-only metrics
    are explicitly null (honest N/A — chat_nextseek does not emit them).

Both dispatchers return a dict shaped like `run_headless.run_one`'s
QueryRecord, augmented with NS-route fields where appropriate. The
router-decision fields (`route`, `model_class`, `model_id`,
`router_decision_latency_ms`, `router_reasoning_len`, `router_fallback`)
are layered on by the caller in `run_router_batch.py`.
"""
from __future__ import annotations

import json
import pathlib
import subprocess
import sys
from datetime import datetime, timezone

# Under pytest, pyproject's `pythonpath = ["src", "."]` covers this. When
# this module is reached via `python tools/e2e/run_router_batch.py`, add
# the repo root so `tools.e2e.<sibling>` imports still resolve.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
from tools.e2e import run_headless  # noqa: E402


def dispatch_cc(*, query_text: str, query_id: str, image: str,
                env: dict[str, str], timeout: int,
                output_dir: pathlib.Path,
                catalog_host_path: pathlib.Path,
                scratch_dir: pathlib.Path, claude_dir: pathlib.Path,
                model_id: str | None,
                max_budget_usd: float | None = None) -> dict:
    """Run a container_cc query via the existing headless runner.

    Returns the QueryRecord dict from run_headless.run_one. `model_id`
    is forwarded verbatim (None preserves the pre-router default model).
    """
    return run_headless.run_one(
        query_text=query_text,
        query_id=query_id,
        image=image,
        env=env,
        timeout=timeout,
        output_dir=output_dir,
        catalog_host_path=catalog_host_path,
        scratch_dir=scratch_dir,
        claude_dir=claude_dir,
        max_budget_usd=max_budget_usd,
        model_id=model_id,
    )


def _read_dotenv_stripping_quotes(path: pathlib.Path) -> dict[str, str]:
    """Parse a .env file the way python expects: strip a single layer of
    matching surrounding quotes from each value.

    Why this exists (and not `--env-file`): docker's `--env-file` does NOT
    strip wrapping quotes. A line like `GCP_API_KEY="AIzaSy..."` in .env is
    forwarded into the container as a 41-char value starting with `"AI`,
    which Google's API rejects as INVALID_ARGUMENT. The bridge avoids this
    because it passes env vars to docker-py as a dict pre-loaded from
    os.environ (already stripped); we replicate that by reading the file
    here and emitting `-e KEY=VALUE` flags per entry.
    """
    import re
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^([A-Z_][A-Z0-9_]*)=(.*)$", line)
        if not m:
            continue
        k, v = m.group(1), m.group(2)
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        out[k] = v
    return out


def dispatch_ns(*, query_text: str, query_id: str, image: str,
                env_file: pathlib.Path, timeout: int,
                output_dir: pathlib.Path,
                catalog_host_path: pathlib.Path,
                scratch_dir: pathlib.Path, claude_dir: pathlib.Path,
                session_id: str) -> dict:
    """Run a nextseek_query via runner_ns.py in a fresh container.

    Pipes `query_text` on stdin. Captures JSONL events on stdout and
    raw stderr to disk. Parses query_complete / ns_runner_error /
    query_error events into a QueryRecord-shaped dict.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    stdout_path = output_dir / f"{query_id}.stdout.jsonl"
    stderr_path = output_dir / f"{query_id}.stderr.log"

    # See _read_dotenv_stripping_quotes for why we cannot use --env-file.
    # CATALOG_FILE + CHAT_NEXTSEEK_DB_ENV are container-side paths the
    # bridge sets dynamically (not in .env); add them explicitly.
    import os as _os
    env_pairs = _read_dotenv_stripping_quotes(env_file)
    env_pairs["CATALOG_FILE"] = "/etc/dmac/agent_model_catalog.json"
    env_pairs["CHAT_NEXTSEEK_DB_ENV"] = _os.environ.get(
        "CHAT_NEXTSEEK_DB_ENV", "dev",
    )
    # Steer chat_nextseek's per-call output dir UNDER /data/scratch so the
    # files cross the mount boundary and the host-side snapshot-diff in
    # run_router_batch._promote_artifacts() can attribute them to this query.
    # Without this, chat_nextseek defaults to
    # `~/.local/state/chat_nextseek/outputs/` inside the container (not in
    # any mount), and reporter-family xlsx/csv outputs are silently lost on
    # container exit. chat_nextseek reads the env var named
    # NEXTSEEK_OUTPUTS_DIR (not OUTPUTS_DIR — see chat_nextseek/config.py
    # line ~166: `os.getenv("NEXTSEEK_OUTPUTS_DIR", ...)`).
    env_pairs["NEXTSEEK_OUTPUTS_DIR"] = (
        f"/data/scratch/chat_nextseek/{session_id}/"
    )
    env_flags: list[str] = []
    for k, v in env_pairs.items():
        env_flags.extend(["-e", f"{k}={v}"])

    cmd = [
        "docker", "run", "--rm", "-i",
        *env_flags,
        "-v", f"{catalog_host_path}:/etc/dmac/agent_model_catalog.json:ro",
        "-v", f"{scratch_dir}:/data/scratch:rw",
        "-v", f"{claude_dir}:/home/user/.claude:rw",
        image,
        "python", "/opt/dmac/runner_ns.py",
        "--session", session_id,
    ]

    started_at = datetime.now(timezone.utc)
    timed_out = False
    rc: int | None = None
    try:
        with stdout_path.open("wb") as fout, stderr_path.open("wb") as ferr:
            proc = subprocess.run(
                cmd,
                input=(query_text + "\n").encode("utf-8"),
                stdout=fout,
                stderr=ferr,
                timeout=timeout,
            )
            rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
    completed_at = datetime.now(timezone.utc)
    latency = (completed_at - started_at).total_seconds()

    events = _parse_jsonl_events(stdout_path)
    return _build_ns_record(
        qid=query_id,
        qtext=query_text,
        events=events,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        started=started_at,
        completed=completed_at,
        latency=latency,
        timed_out=timed_out,
        rc=rc,
        image=image,
        timeout=timeout,
    )


def _parse_jsonl_events(stdout_path: pathlib.Path) -> list[dict]:
    """Parse one event per line; skip unparseable lines silently."""
    if not stdout_path.exists():
        return []
    events: list[dict] = []
    for line in stdout_path.read_text(encoding="utf-8",
                                      errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return events


def _find_event(events: list[dict], name: str) -> dict | None:
    for ev in events:
        if ev.get("event") == name:
            return ev
    return None


def _build_ns_record(*, qid: str, qtext: str, events: list[dict],
                     stdout_path: pathlib.Path, stderr_path: pathlib.Path,
                     started: datetime, completed: datetime, latency: float,
                     timed_out: bool, rc: int | None, image: str,
                     timeout: int) -> dict:
    qc = _find_event(events, "query_complete")
    qerr = _find_event(events, "query_error")
    rerr = _find_event(events, "ns_runner_error")

    final_answer: str | None = None
    is_error = False
    error: str | None = None
    answer_provided = False

    if qc:
        payload = qc.get("payload") or {}
        # Mirror runner_ns._has_failure_signal: status in {error,partial,
        # failure} OR error_type set OR top-level error set. Success path
        # in chat_nextseek has NO status field — only a `reply`.
        failure = (
            payload.get("status") in {"error", "partial", "failure"}
            or bool(payload.get("error_type"))
            or bool(payload.get("error"))
        )
        reply = payload.get("reply")
        if not failure:
            if isinstance(reply, str) and reply.strip():
                final_answer = reply
                answer_provided = True
        else:
            is_error = True
            error = (
                payload.get("error_type")
                or payload.get("error")
                or "ns_query_complete_with_error"
            )
            if isinstance(reply, str) and reply.strip() \
                    and not reply.startswith("<redacted"):
                final_answer = reply
    elif rerr:
        is_error = True
        error = (rerr.get("payload") or {}).get("error_type") \
            or "ns_runner_error"
    elif qerr:
        is_error = True
        error = (qerr.get("payload") or {}).get("error_type") \
            or "query_error"
    else:
        is_error = True
        error = "no_terminal_event"

    if timed_out:
        is_error = True
        error = error or "timeout"

    return {
        "query_id": qid,
        "query_text": qtext,
        "started_at": started.isoformat(),
        "completed_at": completed.isoformat(),
        "latency_seconds": latency,
        # CC-only fields — honest N/A on NS route.
        "cost_usd": None,
        "cost_estimated": False,
        "num_turns": None,
        "stop_reason": None,
        # NS-route fields.
        "tool_use_summary": [],
        "tool_calls_total": 0,
        "answer_provided": answer_provided,
        "final_answer": final_answer,
        "is_error": is_error,
        "error": error,
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "return_code": rc,
        "image": image,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }
