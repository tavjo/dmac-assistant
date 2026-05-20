#!/usr/bin/env python3
"""Drive a corpus through the LLM router headlessly and emit a manifest +
report that match `run_batch.py`'s shape plus router-decision metadata.

Per-query, this driver:
  1. Calls RouterAgent().route(text) and captures route + model_class +
     decision latency + fallback flag (R-03 — reasoning TEXT is NEVER
     persisted; only its character length).
  2. Dispatches CC-route queries via run_headless.run_one (with model_id
     resolved through src/dmac_assistant/router/models.resolve) or
     NS-route queries via tools/e2e/router_dispatch.dispatch_ns
     (docker run python /opt/dmac/runner_ns.py --session <id>).
  3. Merges router metadata into the QueryRecord, summarises, and writes
     manifest.json + report.html to evidence/router-headless/<run_id>/.

CLI surface mirrors run_batch.py; per-query timeout 180s; CC budget cap
0.50 USD; sequential dispatch (no parallelism).

USAGE
  # smoke (3 queries)
  uv run python tools/e2e/run_router_batch.py --limit 3

  # full 103-query batch (~80 min)
  uv run python tools/e2e/run_router_batch.py

OUTPUTS
  evidence/router-headless/<run_id>/
      manifest.json            aggregate + per-query summary + router_summary
      report.html              rendered via tools/e2e/render_report.py
      <qid>.stdout.jsonl       raw runner stdout (NS) or claude stream (CC)
      <qid>.stderr.log         stderr from the per-query subprocess
      <qid>.record.json        full QueryRecord (CC route; NS holds in-memory)
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import shutil
import sys
import tempfile
import time
from datetime import datetime, timezone

# pyproject `pythonpath = ["src", "."]` puts repo root + src on path under
# pytest. When this module is invoked as a script (`python tools/e2e/...`),
# we add repo root explicitly so both `tools.e2e.<sibling>` imports and
# `dmac_assistant.*` imports resolve.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
_SRC_DIR = _REPO_ROOT / "src"
if str(_SRC_DIR) not in sys.path:
    sys.path.insert(0, str(_SRC_DIR))
from tools.e2e import run_headless, router_dispatch, render_report  # noqa: E402

DEFAULT_CORPUS = (
    pathlib.Path(__file__).resolve().parents[2]
    / "evidence" / "full-corpus-2026-05-07" / "corpus.json"
)
DEFAULT_CATALOG = pathlib.Path("vendor/chat_nextseek/agent_model_catalog.json")
DEFAULT_OUTPUT_DIR = pathlib.Path("evidence/router-headless")


# --------------------------------------------------------------------- corpus


def _resolve_query_list(corpus_path: pathlib.Path,
                        corpus_key: str | None,
                        limit: int | None,
                        ids: list[str] | None) -> list[tuple[str, str]]:
    """Return [(qid, qtext), ...] from the corpus, applying limit/ids."""
    data = json.loads(corpus_path.read_text())
    if corpus_key:
        if not isinstance(data, dict) or corpus_key not in data:
            raise SystemExit(
                f"--corpus-key {corpus_key!r} not found in {corpus_path}"
            )
        queries = data[corpus_key]
        # Tolerate {description, tests} shape — chat_nextseek's testing.json
        # nests the list under `.tests`.
        if isinstance(queries, dict) and isinstance(queries.get("tests"),
                                                   list):
            queries = queries["tests"]
    elif isinstance(data, list):
        queries = data
    elif isinstance(data, dict):
        queries = None
        for k in ("queries", "smart_test", "full_test", "tests", "cases"):
            section = data.get(k)
            if isinstance(section, list):
                queries = section
                break
            if (isinstance(section, dict)
                    and isinstance(section.get("tests"), list)):
                queries = section["tests"]
                break
        if queries is None:
            raise SystemExit(
                f"Could not locate query list in {corpus_path}; "
                "pass --corpus-key explicitly."
            )
    else:
        raise SystemExit(f"Unsupported corpus shape in {corpus_path}")

    pairs: list[tuple[str, str]] = []
    for q in queries:
        if not isinstance(q, dict):
            continue
        qid = q.get("id") or q.get("name") or q.get("query_id")
        text = (q.get("query") or q.get("query_text")
                or q.get("text") or q.get("user_query"))
        if not (isinstance(qid, str) and isinstance(text, str)
                and text.strip()):
            continue
        pairs.append((qid, text))

    if ids:
        wanted = set(ids)
        pairs = [p for p in pairs if p[0] in wanted]
        missing = wanted - {p[0] for p in pairs}
        if missing:
            raise SystemExit(f"Query ids not found: {sorted(missing)}")
    elif limit is not None:
        pairs = pairs[:limit]
    return pairs


# ------------------------------------------------------------ manifest assembly


def assemble_manifest(*, run_id: str, started_at: str, completed_at: str,
                      image: str, corpus: str, corpus_key: str | None,
                      timeout_seconds: int, max_budget_usd: float | None,
                      records: list[dict]) -> dict:
    """Build the manifest dict that gets written to manifest.json.

    Pure function — no I/O, no docker. Each `records[i]` is a per-query
    record dict carrying both the CC/NS dispatch fields and the seven
    router fields. `summaries` mirrors the shape `render_report.py` reads.
    """
    n = len(records)
    n_timed_out = sum(1 for r in records if r.get("timed_out"))
    n_errored = sum(
        1 for r in records
        if r.get("is_error") and not r.get("timed_out")
    )
    n_answered = sum(
        1 for r in records
        if not r.get("is_error") and not r.get("timed_out")
    )

    cc_records = [r for r in records if r.get("route") == "container_cc"]
    ns_records = [r for r in records if r.get("route") == "nextseek_query"]
    n_fallback = sum(1 for r in records if r.get("router_fallback"))

    by_model_class: dict[str, int] = {}
    for r in records:
        key = r.get("model_class")
        bucket = key if isinstance(key, str) else "null"
        by_model_class[bucket] = by_model_class.get(bucket, 0) + 1

    decision_latencies = [
        r.get("router_decision_latency_ms")
        for r in records
        if isinstance(r.get("router_decision_latency_ms"), (int, float))
    ]
    avg_decision_latency = (
        sum(decision_latencies) / len(decision_latencies)
        if decision_latencies else 0.0
    )

    total_latency = sum(
        (r.get("latency_seconds") or 0.0) for r in records
    )
    total_cost = sum(
        r["cost_usd"] for r in records
        if isinstance(r.get("cost_usd"), (int, float))
    )

    summaries: list[dict] = []
    for r in records:
        summaries.append({
            # Keys render_report.py reads.
            "query_id": r.get("query_id"),
            "query_text": r.get("query_text"),
            "latency_seconds": r.get("latency_seconds"),
            "cost_usd": r.get("cost_usd"),
            "is_error": bool(r.get("is_error")),
            "tool_use_summary": r.get("tool_use_summary") or [],
            # Auxiliary fields run_batch.py also surfaces (kept for parity).
            "tool_calls_total": r.get("tool_calls_total", 0),
            "answer_provided": bool(
                not r.get("is_error") and not r.get("timed_out")
            ),
            "is_timed_out": bool(r.get("timed_out")),
            "error": r.get("error"),
            "timed_out": bool(r.get("timed_out")),
            "num_turns": r.get("num_turns"),
            "stop_reason": r.get("stop_reason"),
            "record_path": r.get("record_path"),
            "final_answer": r.get("final_answer"),
            # Artifacts promoted into artifacts/<qid>/ (per-query xlsx, html,
            # pdf, png, etc.). Empty list for queries that produced no
            # user-facing deliverables. Same shape as run_batch.py.
            "artifacts": r.get("artifacts") or [],
            # Router additions (seven fields).
            "route": r.get("route"),
            "model_class": r.get("model_class"),
            "model_id": r.get("model_id"),
            "router_decision_latency_ms":
                r.get("router_decision_latency_ms"),
            "router_reasoning_len": r.get("router_reasoning_len"),
            "router_fallback": bool(r.get("router_fallback")),
        })

    return {
        "run_id": run_id,
        "started_at": started_at,
        "completed_at": completed_at,
        "image": image,
        "corpus": corpus,
        "corpus_key": corpus_key,
        "timeout_seconds": timeout_seconds,
        "max_budget_usd": max_budget_usd,
        "queries_total": n,
        "queries_answered": n_answered,
        "queries_errored": n_errored,
        "queries_timed_out": n_timed_out,
        "answer_rate": (n_answered / n) if n else 0.0,
        "total_latency_seconds": round(total_latency, 3),
        "total_cost_usd": round(total_cost, 6),
        "avg_latency_seconds": round(total_latency / n, 3) if n else 0.0,
        "avg_cost_usd": (
            round(total_cost / len(cc_records), 6) if cc_records else 0.0
        ),
        "aborted": False,
        "abort_reason": None,
        "router_summary": {
            "queries_routed_cc": len(cc_records),
            "queries_routed_ns": len(ns_records),
            "queries_routed_fallback": n_fallback,
            "by_model_class": by_model_class,
            "avg_router_decision_latency_ms": round(avg_decision_latency, 3),
        },
        "summaries": summaries,
    }


# ------------------------------------------------------------------- driver


def _read_host_dotenv(path: pathlib.Path) -> dict[str, str]:
    """Parse a .env file without the run_headless allowlist filter.

    Needed because DMAC_DROPBOX_ROOT and DMAC_USERS are host-side
    routing config, not container env — they're absent from
    run_headless._ENV_KEYS by design.
    """
    out: dict[str, str] = {}
    if not path.exists():
        return out
    import re
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


def _resolve_scratch_from_env(env: dict[str, str]) -> pathlib.Path:
    """DMAC_DROPBOX_ROOT + first project of authed user."""
    dropbox = env.get("DMAC_DROPBOX_ROOT")
    if not dropbox:
        raise SystemExit("DMAC_DROPBOX_ROOT not in .env; pass --scratch-dir.")
    users_raw = env.get("DMAC_USERS")
    if not users_raw:
        raise SystemExit("DMAC_USERS not in .env; pass --scratch-dir.")
    users = json.loads(users_raw)
    # default to the demo user — only one project authorized for the POC
    user = next(iter(users))
    projects = users[user].get("projects") or []
    if not projects:
        raise SystemExit(
            f"DMAC_USERS[{user!r}] has no projects; pass --scratch-dir."
        )
    return pathlib.Path(dropbox).expanduser() / projects[0]


# File types promoted from raw/ into artifacts/<qid>/ (mirror run_batch.py).
_ARTIFACT_EXTS = {
    ".xlsx", ".xls", ".csv", ".tsv",
    ".html", ".htm",
    ".pptx", ".pdf",
    ".png", ".jpg", ".jpeg", ".svg", ".gif", ".webp",
    ".docx", ".md",
}


def _snapshot_files(root: pathlib.Path) -> set[pathlib.Path]:
    if not root.exists():
        return set()
    return {p for p in root.rglob("*") if p.is_file()}


def _promote_artifacts(*, fixed_scratch: pathlib.Path,
                       pre_snapshot: set[pathlib.Path],
                       artifacts_root: pathlib.Path,
                       qid: str) -> list[str]:
    """Copy new files (from raw/) into artifacts/<qid>/ with rename
    disambiguation. Returns the list of dest paths actually written.
    """
    new_files = _snapshot_files(fixed_scratch) - pre_snapshot
    qartifacts = artifacts_root / qid
    qartifacts.mkdir(parents=True, exist_ok=True)
    promoted: list[str] = []
    for src in sorted(new_files):
        if src.suffix.lower() not in _ARTIFACT_EXTS:
            continue
        dest = qartifacts / src.name
        n = 1
        while dest.exists():
            dest = qartifacts / f"{src.stem}__{n}{src.suffix}"
            n += 1
        shutil.copy2(src, dest)
        promoted.append(str(dest))
    if not promoted:
        # Keep the artifacts listing tidy if this query made nothing.
        try:
            qartifacts.rmdir()
        except OSError:
            pass
    return promoted


async def _drive(*, pairs: list[tuple[str, str]], image: str,
                 env: dict[str, str], env_file: pathlib.Path,
                 timeout: int, output_dir: pathlib.Path,
                 catalog_host: pathlib.Path,
                 fixed_scratch: pathlib.Path,
                 artifacts_root: pathlib.Path,
                 max_budget_usd: float,
                 run_id: str, quiet: bool) -> list[dict]:
    # Imported lazily to keep `assemble_manifest` test path free of
    # heavyweight router/BAML deps.
    from dmac_assistant.router import models as router_models
    from dmac_assistant.router.agent import RouterAgent
    from dmac_assistant.router.baml_client.types import ModelClass, Route

    _ROUTE_ALIAS = {
        Route.NextseekQuery: "nextseek_query",
        Route.ContainerCC: "container_cc",
    }
    _FALLBACK_REASONING = "<router_unavailable>"

    agent = RouterAgent()
    records: list[dict] = []

    for i, (qid, qtext) in enumerate(pairs, 1):
        if not quiet:
            print(f"[{i}/{len(pairs)}] {qid} | routing…",
                  file=sys.stderr)
        decision_started = time.monotonic()
        decision = await agent.route(qtext)
        decision_latency_ms = (time.monotonic() - decision_started) * 1000.0
        fallback = decision.reasoning == _FALLBACK_REASONING
        route = _ROUTE_ALIAS[decision.route]

        model_class = decision.model_class
        model_id: str | None = None

        # Per-query claude_dir tempdir (matches run_batch.py — fresh
        # session state per query, no leakage across queries). scratch is
        # the SHARED raw/ subtree so promote_artifacts() can diff before/
        # after to attribute new files to this query.
        qclaude = pathlib.Path(
            tempfile.mkdtemp(prefix="dmac-router-claude-"),
        )
        os.chmod(qclaude, 0o777)
        pre_snapshot = _snapshot_files(fixed_scratch)

        try:
            if route == "container_cc":
                mc = model_class or ModelClass.Sonnet
                try:
                    model_id = router_models.resolve(mc)
                except Exception as exc:  # noqa: BLE001
                    print(f"  ! model_class.resolve failed: {exc}",
                          file=sys.stderr)
                    model_id = None
                if not quiet:
                    print(f"    → CC route, model_class={mc.name.lower()}",
                          file=sys.stderr)
                record = router_dispatch.dispatch_cc(
                    query_text=qtext, query_id=qid, image=image, env=env,
                    timeout=timeout, output_dir=output_dir,
                    catalog_host_path=catalog_host,
                    scratch_dir=fixed_scratch,
                    claude_dir=qclaude, max_budget_usd=max_budget_usd,
                    model_id=model_id,
                )
            else:
                if not quiet:
                    print("    → NS route", file=sys.stderr)
                record = router_dispatch.dispatch_ns(
                    query_text=qtext, query_id=qid, image=image,
                    env_file=env_file, timeout=timeout,
                    output_dir=output_dir,
                    catalog_host_path=catalog_host,
                    scratch_dir=fixed_scratch,
                    claude_dir=qclaude,
                    session_id=f"{run_id}-{qid}",
                )
        finally:
            shutil.rmtree(qclaude, ignore_errors=True)

        # Promote user-facing files this query just wrote.
        record["artifacts"] = _promote_artifacts(
            fixed_scratch=fixed_scratch,
            pre_snapshot=pre_snapshot,
            artifacts_root=artifacts_root,
            qid=qid,
        )

        record["route"] = route
        record["model_class"] = (
            model_class.name.lower() if model_class else None
        )
        record["model_id"] = model_id if route == "container_cc" else None
        record["router_decision_latency_ms"] = round(decision_latency_ms, 3)
        record["router_reasoning_len"] = len(decision.reasoning or "")
        record["router_fallback"] = fallback
        records.append(record)

        if not quiet:
            cost = record.get("cost_usd")
            cost_str = f"${cost:.4f}" if isinstance(cost, (int, float)) \
                else "n/a"
            print(
                f"    ← latency={record.get('latency_seconds', 0):.1f}s  "
                f"cost={cost_str}  "
                f"error={record.get('error') or '-'}",
                file=sys.stderr,
            )

    return records


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1],
    )
    ap.add_argument("--corpus",
                    type=pathlib.Path, default=DEFAULT_CORPUS,
                    help=f"path to corpus JSON "
                         f"(default: {DEFAULT_CORPUS})")
    ap.add_argument("--corpus-key", default=None,
                    help="key inside corpus JSON whose value is the "
                         "query list; default None (loader finds 'queries')")
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--limit", type=int,
                    help="run only the first N queries")
    sel.add_argument("--ids",
                    help="comma-separated list of query ids to run")
    ap.add_argument("--image", default="dmac-assistant:poc",
                    help="docker image tag")
    ap.add_argument("--env-file", default=".env",
                    help="path to .env (default: ./.env)")
    ap.add_argument("--catalog-file", type=pathlib.Path,
                    default=DEFAULT_CATALOG)
    ap.add_argument("--output-dir", type=pathlib.Path,
                    default=DEFAULT_OUTPUT_DIR,
                    help="evidence root; a per-run subdir is created here")
    ap.add_argument("--run-id",
                    help="reuse a specific run subdir name "
                         "(default: UTC timestamp)")
    ap.add_argument("--timeout", type=int, default=180,
                    help="per-query timeout in seconds "
                         "(default 180; capped at "
                         f"{run_headless._TIMEOUT_HARD_MAX})")
    ap.add_argument("--max-budget-usd", type=float, default=0.50,
                    help="CC-route per-query budget cap (default 0.50)")
    ap.add_argument("--scratch-dir",
                    help="absolute scratch mount root; defaults to "
                         "DMAC_DROPBOX_ROOT / first authed-user project")
    ap.add_argument("--stop-on-fail", action="store_true",
                    help="abort the batch on first failure")
    ap.add_argument("--quiet", action="store_true",
                    help="suppress per-query progress lines")
    args = ap.parse_args()

    timeout = min(args.timeout, run_headless._TIMEOUT_HARD_MAX)
    ids = [s.strip() for s in args.ids.split(",")] if args.ids else None

    corpus_path = pathlib.Path(args.corpus).expanduser().resolve()
    pairs = _resolve_query_list(corpus_path, args.corpus_key,
                                args.limit, ids)
    if not pairs:
        raise SystemExit("No queries matched.")

    env_file = pathlib.Path(args.env_file).resolve()
    # Hydrate os.environ from .env without overwriting pre-existing values,
    # so the BAML router (running on the HOST process, not in the container)
    # can read GCP_API_KEY, AWS_BEARER_TOKEN_BEDROCK, etc. Matches the
    # convention run_router_e2e.py expects (`set -a; source .env; set +a`)
    # but lets the script work standalone.
    for k, v in _read_host_dotenv(env_file).items():
        os.environ.setdefault(k, v)
    env = run_headless.load_env_file(env_file)
    if "API_USER" not in env and "NEXTSEEK_USERNAME" in env:
        env["API_USER"] = env["NEXTSEEK_USERNAME"]
    if "API_PASS" not in env and "NEXTSEEK_PASSWORD" in env:
        env["API_PASS"] = env["NEXTSEEK_PASSWORD"]
    env.setdefault("CATALOG_FILE", "/etc/dmac/agent_model_catalog.json")

    catalog_host = pathlib.Path(args.catalog_file).resolve()
    if not catalog_host.exists():
        raise SystemExit(f"--catalog-file not found: {catalog_host}")

    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ",
    )
    output_dir = pathlib.Path(args.output_dir).resolve() / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    if args.scratch_dir:
        scratch_root = pathlib.Path(args.scratch_dir).expanduser().resolve()
    else:
        # DMAC_DROPBOX_ROOT / DMAC_USERS aren't in run_headless._ENV_KEYS
        # (host-only routing config); load them separately.
        host_env = _read_host_dotenv(env_file)
        scratch_root = _resolve_scratch_from_env(host_env).resolve()
    if not scratch_root.exists():
        raise SystemExit(f"scratch root does not exist: {scratch_root}")

    # Mirror run_batch.py's layout (see comment block lines 181-209 there):
    #   <scratch-root>/<user>/<run_id>/
    #     raw/         ← bind-mounted as /data/scratch; container writes here
    #     artifacts/   ← user-facing deliverables promoted per-query
    user_id = env.get("API_USER") or env.get("NEXTSEEK_USERNAME") or "demo"
    session_root = scratch_root / user_id / run_id
    fixed_scratch = session_root / "raw"
    artifacts_root = session_root / "artifacts"
    fixed_scratch.mkdir(parents=True, exist_ok=True)
    artifacts_root.mkdir(parents=True, exist_ok=True)
    os.chmod(fixed_scratch, 0o777)

    started_at = datetime.now(timezone.utc)
    if not args.quiet:
        print(
            f"[run_router_batch] {len(pairs)} queries  image={args.image}  "
            f"timeout={timeout}s  budget=${args.max_budget_usd}  "
            f"out={output_dir}",
            file=sys.stderr,
        )

    records = asyncio.run(_drive(
        pairs=pairs, image=args.image, env=env, env_file=env_file,
        timeout=timeout, output_dir=output_dir,
        catalog_host=catalog_host,
        fixed_scratch=fixed_scratch,
        artifacts_root=artifacts_root,
        max_budget_usd=args.max_budget_usd,
        run_id=run_id, quiet=args.quiet,
    ))

    completed_at = datetime.now(timezone.utc)
    manifest = assemble_manifest(
        run_id=run_id,
        started_at=started_at.isoformat().replace("+00:00", "Z"),
        completed_at=completed_at.isoformat().replace("+00:00", "Z"),
        image=args.image,
        corpus=str(corpus_path),
        corpus_key=args.corpus_key,
        timeout_seconds=timeout,
        max_budget_usd=args.max_budget_usd,
        records=records,
    )
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    report_path = output_dir / "report.html"
    try:
        render_report.render(manifest_path, report_path)
    except Exception as exc:  # noqa: BLE001
        print(f"[warn] render_report failed: {exc}", file=sys.stderr)

    print(
        f"\n[run_router_batch] done  run_id={run_id}  "
        f"answered={manifest['queries_answered']}/{manifest['queries_total']}  "
        f"errored={manifest['queries_errored']}  "
        f"cost=${manifest['total_cost_usd']:.4f}  "
        f"manifest={manifest_path}  report={report_path}",
        file=sys.stderr,
    )
    rc = 0 if manifest["queries_errored"] == 0 else 1
    sys.exit(rc)


if __name__ == "__main__":  # pragma: no cover
    main()
