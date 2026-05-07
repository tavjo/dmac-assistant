#!/usr/bin/env python3
"""Run a single NExtSEEK query through the dmac-assistant Docker image in headless
mode and emit a structured QueryRecord.

Headless mode bypasses the FastAPI bridge entirely: a `docker run --rm` directly
invokes `claude --print --input-format stream-json --output-format stream-json`
inside `dmac-assistant:<tag>`. Useful for plugin-quality benchmarking against
the chat_nextseek testing corpus or any ad-hoc query without the bridge UI.

USAGE
  # ad-hoc single query
  tools/e2e/run_headless.py --query "Find protein samples in project X"

  # pick a query from a corpus by id
  tools/e2e/run_headless.py \\
      --corpus evidence/run-2026-05-07/queries.json --id Search-Basic-1

  # chat_nextseek 103-question corpus (full_test) — corpus shape supports
  # {"queries": [...]}, {"smart_test": [...]}, {"full_test": [...]}, or a bare list
  tools/e2e/run_headless.py \\
      --corpus ~/Documents/Projects/work/chat_nextseek/testing.json \\
      --corpus-key full_test --id T17

OUTPUTS (per run)
  evidence/headless/<run_id>/<query_id>.record.json   structured record (see below)
  evidence/headless/<run_id>/<query_id>.stdout.jsonl  raw claude stream-json
  evidence/headless/<run_id>/<query_id>.stderr.log    docker/claude stderr

The script prints a 4-field summary to stdout:
  - latency_seconds
  - cost_usd
  - tool_use_summary  (list[{tool,count}] — what the in-container agent invoked)
  - answer_provided   (bool — did the runner produce a non-empty final reply)

Exit codes:
  0  answer_provided=True AND no error
  1  answer_provided=False OR error (timeout / runner / docker)

NOTES
  - Default timeout is 180 seconds, hard-capped at 180s per query.
  - Ephemeral /data/scratch and /home/user/.claude are mounted from per-run
    tmpdirs so successive queries don't share session state. Pass
    --keep-state to reuse a stable mount root across runs (e.g. for
    refine/memory queries).
  - Credentials read from .env via simple key=value parsing with shell-quote
    stripping. The script never logs values; the per-run env-file is written
    with mode 0600 and deleted on completion.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone

# Env keys forwarded into the container. CATALOG_FILE is set to the in-container
# bind path automatically; the rest come from .env if present.
_ENV_KEYS = {
    "API_USER", "API_PASS",
    "NEXTSEEK_USERNAME", "NEXTSEEK_PASSWORD", "NEXTSEEK_URL",
    "AWS_REGION", "AWS_BEARER_TOKEN_BEDROCK", "CLAUDE_CODE_USE_BEDROCK",
    "GCP_API_KEY", "ANTHROPIC_DEFAULT_SONNET_MODEL",
    "CATALOG_FILE",
    # DB credentials read by chat_nextseek's reporter / context bootstrap.
    # Without these forwarded, reporter-mode queries fail with
    # `[CONFIG][DB] Host not configured for env '<env>'`. The runner's
    # _sanitize_env_quotes() strips surrounding quotes before chat_nextseek
    # reads them.
    "MYSQL_HOST_PROD", "MYSQL_HOST_DEV", "MYSQL_PORT", "MYSQL_USER",
    "MYSQL_PROD_PASSWORD", "MYSQL_DEV_PASSWORD",
    # Neo4j credentials read by the graph agent.
    "NEO4J_URI", "NEO4J_USER", "NEO4J_PASSWORD", "NEO4J_DATABASE",
    "NEO4J_URI_PROD", "NEO4J_USER_PROD", "NEO4J_PASSWORD_PROD",
    "NEO4J_DATABASE_PROD",
    # Session DB (chat_nextseek SQLiteSessionState + future remote session
    # store). Forwarded so the remote variant works when the deployment
    # opts into it.
    "SESSION_DB_HOST", "SESSION_DB_USER", "SESSION_DB_PASSWORD",
    "SESSION_DB_NAME", "SESSION_DB_PATH", "SESSION_DB_TYPE",
}
_TIMEOUT_HARD_MAX = 180  # seconds; project rule

# Bedrock list pricing for Anthropic Claude models, USD per 1M tokens.
# Used only as a fallback estimate when stream-json's `result` event is
# missing (e.g. timeout). Real cost when available comes straight from
# `total_cost_usd`. Keep these synced with AWS Bedrock pricing for the
# models the dmac-assistant image ships.
_BEDROCK_PRICE_PER_MTOK = {
    "claude-sonnet-4-6":   {"in": 3.00, "out": 15.00, "cache_w": 3.75, "cache_r": 0.30},
    "claude-sonnet-4-5":   {"in": 3.00, "out": 15.00, "cache_w": 3.75, "cache_r": 0.30},
    "claude-opus-4-7":     {"in": 15.00, "out": 75.00, "cache_w": 18.75, "cache_r": 1.50},
    "claude-haiku-4-5":    {"in": 1.00, "out": 5.00, "cache_w": 1.25, "cache_r": 0.10},
}


def _estimate_cost_from_usage(events: list[dict]) -> float:
    """Sum per-assistant-event `usage` blocks against a static price table.

    Used only when stream-json's terminal `result` event is missing. The
    figure is a best-effort estimate; the record marks it via
    `cost_estimated: true`. Returns 0.0 if no usable events were seen.
    """
    total = 0.0
    for e in events:
        if e.get("type") != "assistant":
            continue
        msg = e.get("message", {})
        usage = msg.get("usage") or {}
        model = msg.get("model") or ""
        # match on substring so region-prefixed Bedrock model IDs still work
        prices = None
        for key, val in _BEDROCK_PRICE_PER_MTOK.items():
            if key in model:
                prices = val
                break
        if not prices:
            continue
        in_tok = usage.get("input_tokens", 0) or 0
        out_tok = usage.get("output_tokens", 0) or 0
        cache_w = usage.get("cache_creation_input_tokens", 0) or 0
        cache_r = usage.get("cache_read_input_tokens", 0) or 0
        total += (
            in_tok    * prices["in"]
            + out_tok   * prices["out"]
            + cache_w   * prices["cache_w"]
            + cache_r   * prices["cache_r"]
        ) / 1_000_000.0
    return total


def load_env_file(path: pathlib.Path) -> dict[str, str]:
    """Parse .env-style file, strip surrounding shell quotes from values,
    return only keys in _ENV_KEYS."""
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
        if k not in _ENV_KEYS:
            continue
        if (v.startswith('"') and v.endswith('"')) or (
            v.startswith("'") and v.endswith("'")
        ):
            v = v[1:-1]
        out[k] = v
    return out


def resolve_corpus_query(corpus_path: pathlib.Path, query_id: str,
                         corpus_key: str | None) -> str:
    """Find a query by id in a corpus JSON. Supports a few common shapes."""
    data = json.loads(corpus_path.read_text())
    if corpus_key:
        if not isinstance(data, dict) or corpus_key not in data:
            raise SystemExit(
                f"--corpus-key {corpus_key!r} not found in {corpus_path}"
            )
        queries = data[corpus_key]
    elif isinstance(data, list):
        queries = data
    elif isinstance(data, dict):
        # try common keys in priority order
        queries = None
        for k in ("queries", "smart_test", "full_test", "tests", "cases", "items"):
            if k in data and isinstance(data[k], list):
                queries = data[k]
                break
        if queries is None:
            raise SystemExit(
                f"Could not locate query list in {corpus_path}; "
                "pass --corpus-key explicitly."
            )
    else:
        raise SystemExit(f"Unsupported corpus shape in {corpus_path}")

    for q in queries:
        qid = q.get("id") or q.get("name") or q.get("query_id")
        if str(qid) == str(query_id):
            text = (q.get("query") or q.get("query_text")
                    or q.get("text") or q.get("user_query"))
            if not isinstance(text, str) or not text.strip():
                raise SystemExit(
                    f"Found query id {query_id!r} but no text field "
                    f"(query/query_text/text/user_query)"
                )
            return text
    raise SystemExit(f"Query id {query_id!r} not found in {corpus_path}")


def build_input_jsonl(query_text: str) -> str:
    msg = {
        "type": "user",
        "message": {
            "role": "user",
            "content": [{"type": "text", "text": query_text}],
        },
    }
    return json.dumps(msg) + "\n"


def cleanup_running_container(label: str) -> None:
    """Best-effort: stop any container still running with our run-label."""
    try:
        ids = subprocess.run(
            ["docker", "ps", "-q", "--filter", f"label={label}"],
            capture_output=True, text=True, timeout=10,
        ).stdout.strip().splitlines()
        for cid in ids:
            subprocess.run(
                ["docker", "stop", "-t", "2", cid],
                capture_output=True, timeout=15,
            )
    except Exception:
        pass


def run_one(*, query_text: str, query_id: str, image: str,
            env: dict[str, str], timeout: int, output_dir: pathlib.Path,
            catalog_host_path: pathlib.Path, scratch_dir: pathlib.Path,
            claude_dir: pathlib.Path,
            max_budget_usd: float | None = None) -> dict:
    """Run a single query through dmac-assistant headless.

    Returns the structured QueryRecord dict. Also writes side files under
    output_dir: <qid>.input.jsonl, <qid>.stdout.jsonl, <qid>.stderr.log,
    <qid>.record.json. The env-file is written with mode 0600 and deleted
    on completion regardless of outcome.

    Importable from a batch driver. Pass per-query mounts (scratch_dir,
    claude_dir) for an isolated session, or shared roots for chained
    refine/memory queries.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    stdin_path = output_dir / f"{query_id}.input.jsonl"
    stdin_path.write_text(build_input_jsonl(query_text))

    env_path = output_dir / f"{query_id}.env"
    env_path.write_text("\n".join(f"{k}={v}" for k, v in env.items()) + "\n")
    env_path.chmod(0o600)

    stdout_path = output_dir / f"{query_id}.stdout.jsonl"
    stderr_path = output_dir / f"{query_id}.stderr.log"

    label = f"dmac-headless-{query_id}-{uuid.uuid4().hex[:6]}"
    claude_args = [
        "claude", "--print",
        "--input-format", "stream-json",
        "--output-format", "stream-json",
        "--verbose", "--dangerously-skip-permissions",
    ]
    if max_budget_usd is not None and max_budget_usd > 0:
        claude_args.extend(["--max-budget-usd", str(max_budget_usd)])
    # The skill formats artifact paths to the user using DMAC_PATH_MAPPINGS
    # to translate container paths back to host paths. The bridge supplies
    # this in prod; in the headless harness we know the mapping exactly
    # because we own the mount, so inject it here. Without this the user
    # sees `/data/scratch/...` which doesn't exist on the host.
    path_mappings = json.dumps({"/data/scratch": str(scratch_dir)})
    # CHAT_NEXTSEEK_DB_ENV: only dev credentials are populated in our .env
    # (MYSQL_HOST_DEV / MYSQL_DEV_PASSWORD). Without this var, chat_nextseek's
    # reporter / context bootstrap defaults to env="prod" and fails with
    # `[CONFIG][DB] Host not configured for env 'prod'`. Caller can override
    # by setting CHAT_NEXTSEEK_DB_ENV in the .env file (env-file wins over
    # later -e flags only if the same key isn't repeated; we set it here as
    # the headless default so a stock .env Just Works).
    env_overrides = [
        "-e", f"DMAC_PATH_MAPPINGS={path_mappings}",
    ]
    if os.environ.get("CHAT_NEXTSEEK_DB_ENV"):
        env_overrides.extend(["-e",
            f"CHAT_NEXTSEEK_DB_ENV={os.environ['CHAT_NEXTSEEK_DB_ENV']}"])
    else:
        env_overrides.extend(["-e", "CHAT_NEXTSEEK_DB_ENV=dev"])
    cmd = [
        "docker", "run", "--rm", "-i",
        "--env-file", str(env_path),
        *env_overrides,
        "-v", f"{catalog_host_path}:/etc/dmac/agent_model_catalog.json:ro",
        "-v", f"{scratch_dir}:/data/scratch:rw",
        "-v", f"{claude_dir}:/home/user/.claude:rw",
        "--label", label,
        image,
        *claude_args,
    ]

    started_at = datetime.now(timezone.utc)
    timed_out = False
    rc: int | None = None
    try:
        with stdin_path.open("rb") as fin, \
             stdout_path.open("wb") as fout, \
             stderr_path.open("wb") as ferr:
            proc = subprocess.run(
                cmd, stdin=fin, stdout=fout, stderr=ferr, timeout=timeout,
            )
            rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        cleanup_running_container(label)
    completed_at = datetime.now(timezone.utc)
    latency = (completed_at - started_at).total_seconds()

    # Always remove the env-file (contains creds) before parsing.
    try:
        env_path.unlink()
    except Exception:
        pass

    record = _build_record(
        qid=query_id, qtext=query_text, stdout_path=stdout_path,
        stderr_path=stderr_path, started=started_at, completed=completed_at,
        latency=latency, timed_out=timed_out, rc=rc, image=image,
        timeout=timeout,
    )
    if max_budget_usd is not None:
        record["max_budget_usd"] = max_budget_usd
    record_path = output_dir / f"{query_id}.record.json"
    record_path.write_text(json.dumps(record, indent=2) + "\n")
    record["record_path"] = str(record_path)
    return record


def _build_record(*, qid: str, qtext: str, stdout_path: pathlib.Path,
                  stderr_path: pathlib.Path, started: datetime,
                  completed: datetime, latency: float, timed_out: bool,
                  rc: int | None, image: str, timeout: int) -> dict:
    events: list[dict] = []
    if stdout_path.exists():
        for line in stdout_path.read_text().splitlines():
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass

    result_event = next(
        (e for e in events if e.get("type") == "result"),
        None,
    )

    counter: collections.Counter[str] = collections.Counter()
    for e in events:
        if e.get("type") != "assistant":
            continue
        msg = e.get("message", {})
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for blk in content:
            if blk.get("type") == "tool_use":
                counter[blk.get("name", "unknown")] += 1
    tool_use_summary = [
        {"tool": t, "count": c} for t, c in counter.most_common()
    ]

    final_answer: str | None = None
    if result_event:
        candidate = result_event.get("result")
        if isinstance(candidate, str) and candidate.strip():
            final_answer = candidate
    if not final_answer:
        for e in reversed(events):
            if e.get("type") != "assistant":
                continue
            for blk in e.get("message", {}).get("content", []):
                if blk.get("type") == "text" and blk.get("text", "").strip():
                    final_answer = blk["text"]
                    break
            if final_answer:
                break

    answer_provided = bool(final_answer and final_answer.strip())

    err: str | None = None
    if timed_out:
        err = f"timeout-after-{timeout}s"
    elif rc not in (None, 0):
        err = f"docker-exit-{rc}"
    elif result_event and result_event.get("is_error"):
        err = "runner-error"

    cost = 0.0
    cost_estimated = False
    if result_event and "total_cost_usd" in result_event:
        try:
            cost = float(result_event["total_cost_usd"])
        except (TypeError, ValueError):
            cost = 0.0
    else:
        # No `result` event (typically: timeout killed the process before
        # Claude Code emitted the final summary). Best-effort estimate from
        # the per-assistant-event `usage` blocks. Better than reporting
        # $0.00 on a multi-tool-call timeout, which under-reports the run's
        # actual budget burn and corrupts manifest totals.
        cost = _estimate_cost_from_usage(events)
        cost_estimated = cost > 0.0

    return {
        "query_id": qid,
        "query_text": qtext,
        "started_at": started.isoformat().replace("+00:00", "Z"),
        "completed_at": completed.isoformat().replace("+00:00", "Z"),
        "latency_seconds": round(latency, 3),
        "cost_usd": round(cost, 6),
        "cost_estimated": cost_estimated,
        "answer_provided": answer_provided,
        "final_answer": final_answer,
        "tool_use_summary": tool_use_summary,
        "tool_calls_total": sum(counter.values()),
        "num_turns": (
            result_event.get("num_turns") if result_event else None
        ),
        "stop_reason": (
            result_event.get("stop_reason") if result_event else None
        ),
        "is_error": (
            bool(result_event and result_event.get("is_error"))
            or timed_out or (rc not in (None, 0))
        ),
        "error": err,
        "timed_out": timed_out,
        "timeout_seconds": timeout,
        "image": image,
        "stdout_path": str(stdout_path),
        "stderr_path": str(stderr_path),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1],
    )
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--query", help="ad-hoc query text")
    src.add_argument("--corpus",
                     help="path to corpus JSON; pair with --id")
    ap.add_argument("--id",
                    help="query id (required with --corpus; "
                         "label only with --query)")
    ap.add_argument("--corpus-key",
                    help="key inside the corpus JSON whose value is the query "
                         "list (e.g. 'smart_test', 'full_test'). If omitted, "
                         "the loader probes common keys.")
    ap.add_argument("--image", default="dmac-assistant:e2e-20260506",
                    help="docker image tag (default: dmac-assistant:e2e-20260506)")
    ap.add_argument("--env-file", default=".env",
                    help="path to .env (default: ./.env)")
    ap.add_argument("--catalog-file",
                    default="vendor/chat_nextseek/agent_model_catalog.json",
                    help="host path to agent_model_catalog.json (mounted "
                         "read-only into /etc/dmac/)")
    ap.add_argument("--output-dir", default="evidence/headless",
                    help="evidence root; a per-run subdir is created here")
    ap.add_argument("--run-id",
                    help="reuse a specific run subdir name (default: UTC "
                         "timestamp)")
    ap.add_argument("--timeout", type=int, default=120,
                    help=f"per-query timeout in seconds (default: 120; hard "
                         f"max: {_TIMEOUT_HARD_MAX})")
    ap.add_argument("--max-budget-usd", type=float, default=0.50,
                    help="hard dollar cap per query (passed to claude "
                         "--max-budget-usd; 0 to disable; default: 0.50)")
    ap.add_argument("--keep-state", action="store_true",
                    help="reuse stable scratch + claude mount roots under "
                         "evidence/headless/_state/ (persists session DB "
                         "across runs)")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress progress output to stderr")
    args = ap.parse_args()

    timeout = min(args.timeout, _TIMEOUT_HARD_MAX)

    # resolve query
    if args.corpus:
        if not args.id:
            ap.error("--corpus requires --id")
        qid = args.id
        qtext = resolve_corpus_query(
            pathlib.Path(args.corpus).expanduser().resolve(),
            args.id, args.corpus_key,
        )
    else:
        qtext = args.query
        qid = args.id or "adhoc-" + uuid.uuid4().hex[:8]

    # env
    env = load_env_file(pathlib.Path(args.env_file))
    if "API_USER" not in env and "NEXTSEEK_USERNAME" in env:
        env["API_USER"] = env["NEXTSEEK_USERNAME"]
    if "API_PASS" not in env and "NEXTSEEK_PASSWORD" in env:
        env["API_PASS"] = env["NEXTSEEK_PASSWORD"]
    env.setdefault("CATALOG_FILE", "/etc/dmac/agent_model_catalog.json")

    if not env.get("AWS_BEARER_TOKEN_BEDROCK"):
        ap.error(
            "AWS_BEARER_TOKEN_BEDROCK not found in env-file; cannot reach "
            "Bedrock. Check that the .env file has the credential set."
        )

    # output dir
    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ",
    )
    output_dir = pathlib.Path(args.output_dir) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    # mount roots
    if args.keep_state:
        state_root = pathlib.Path(args.output_dir) / "_state"
        scratch_dir = state_root / "scratch"
        claude_dir = state_root / "claude"
        scratch_dir.mkdir(parents=True, exist_ok=True)
        claude_dir.mkdir(parents=True, exist_ok=True)
    else:
        scratch_dir = pathlib.Path(
            tempfile.mkdtemp(prefix="dmac-headless-scratch-"),
        )
        claude_dir = pathlib.Path(
            tempfile.mkdtemp(prefix="dmac-headless-claude-"),
        )
    # Permissive so the in-container 'user' uid can write.
    os.chmod(scratch_dir, 0o777)
    os.chmod(claude_dir, 0o777)

    catalog_host = pathlib.Path(args.catalog_file).resolve()
    if not catalog_host.exists():
        ap.error(f"--catalog-file not found: {catalog_host}")

    if not args.quiet:
        print(
            f"[run_headless] qid={qid} image={args.image} "
            f"timeout={timeout}s output={output_dir}",
            file=sys.stderr,
        )

    record = run_one(
        query_text=qtext, query_id=qid, image=args.image,
        env=env, timeout=timeout, output_dir=output_dir,
        catalog_host_path=catalog_host,
        scratch_dir=scratch_dir, claude_dir=claude_dir,
        max_budget_usd=(
            args.max_budget_usd if args.max_budget_usd > 0 else None
        ),
    )

    if not args.keep_state:
        shutil.rmtree(scratch_dir, ignore_errors=True)
        shutil.rmtree(claude_dir, ignore_errors=True)

    summary = {
        "query_id": record["query_id"],
        "latency_seconds": record["latency_seconds"],
        "cost_usd": record["cost_usd"],
        "tool_use_summary": record["tool_use_summary"],
        "answer_provided": record["answer_provided"],
        "final_answer": record["final_answer"],
        "is_error": record["is_error"],
        "error": record["error"],
        "record_path": record["record_path"],
    }
    print(json.dumps(summary, indent=2))
    sys.exit(0 if record["answer_provided"] and not record["is_error"] else 1)


if __name__ == "__main__":
    main()
