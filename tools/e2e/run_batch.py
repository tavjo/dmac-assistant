#!/usr/bin/env python3
"""Drive a batch of queries through dmac-assistant in headless mode and
emit per-query QueryRecord JSONs plus an aggregate manifest.json.

This is a thin sequential driver around `run_headless.run_one`. Each query
gets its own ephemeral scratch + claude state mounts (no session-state
leakage between queries) by default. Pass --keep-state to reuse a stable
mount root across the whole batch (only useful when the corpus has
intentional dependency chains like setup_queries / refine / memory turns).

USAGE
  # first 10 from the dmac e2e corpus
  tools/e2e/run_batch.py --corpus evidence/run-2026-05-07/queries.json --limit 10

  # specific ids
  tools/e2e/run_batch.py \\
      --corpus evidence/run-2026-05-07/queries.json \\
      --ids Search-Basic-1,Retrieve-1,SampleTree-1

  # chat_nextseek 103-question full_test (smoke run with --limit 3 first!)
  tools/e2e/run_batch.py \\
      --corpus ~/Documents/Projects/work/chat_nextseek/testing.json \\
      --corpus-key full_test --limit 10

OUTPUTS
  evidence/headless/<run_id>/
      manifest.json            aggregate run metadata + per-query summary
      <qid>.record.json        full QueryRecord (per query)
      <qid>.input.jsonl        the stream-json user message sent
      <qid>.stdout.jsonl       raw claude stdout
      <qid>.stderr.log         claude stderr (chat_nextseek debug noise)

After the batch completes, render a dashboard with:
  tools/e2e/render_report.py --manifest evidence/headless/<run_id>/manifest.json
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import sys
import tempfile
from datetime import datetime, timezone

# Local import — run_headless.py exposes run_one + helpers as a library.
sys.path.insert(0, str(pathlib.Path(__file__).parent))
import run_headless  # noqa: E402


def _resolve_query_list(corpus_path: pathlib.Path, corpus_key: str | None,
                        limit: int | None, ids: list[str] | None
                        ) -> list[tuple[str, str]]:
    """Return [(qid, qtext), ...] for the queries to run."""
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
        queries = None
        for k in ("queries", "smart_test", "full_test", "tests", "cases"):
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

    pairs: list[tuple[str, str]] = []
    for q in queries:
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


def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__.split("\n", 1)[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("\n", 1)[1],
    )
    ap.add_argument("--corpus", required=True,
                    help="path to corpus JSON")
    ap.add_argument("--corpus-key",
                    help="key inside corpus JSON whose value is the "
                         "query list (e.g. 'smart_test', 'full_test')")
    sel = ap.add_mutually_exclusive_group()
    sel.add_argument("--limit", type=int,
                     help="run only the first N queries (default: all)")
    sel.add_argument("--ids",
                     help="comma-separated list of query ids to run "
                          "(in corpus order)")
    ap.add_argument("--image",
                    default="dmac-assistant:e2e-20260506",
                    help="docker image tag")
    ap.add_argument("--env-file", default=".env",
                    help="path to .env (default: ./.env)")
    ap.add_argument("--catalog-file",
                    default="vendor/chat_nextseek/agent_model_catalog.json")
    ap.add_argument("--output-dir", default="evidence/headless",
                    help="evidence root; per-run subdir created here")
    ap.add_argument("--run-id",
                    help="reuse a specific run subdir name (default: "
                         "UTC timestamp)")
    ap.add_argument("--timeout", type=int, default=120,
                    help=f"per-query timeout in seconds (default: 120; "
                         f"hard max: {run_headless._TIMEOUT_HARD_MAX})")
    ap.add_argument("--max-budget-usd", type=float, default=0.50,
                    help="per-query --max-budget-usd cap "
                         "(0 to disable; default: 0.50)")
    ap.add_argument("--keep-state", action="store_true",
                    help="reuse a single scratch + claude mount root "
                         "across the entire batch (chained refine/memory)")
    ap.add_argument("--scratch-dir",
                    help="absolute path to use as the /data/scratch mount "
                         "for every query; outputs land under this dir "
                         "(no temp dir, no cleanup). Useful for landing "
                         "outputs in a Dropbox project folder so the user "
                         "can see them.")
    ap.add_argument("--stop-on-fail", action="store_true",
                    help="abort the batch as soon as one query "
                         "fails / times out")
    args = ap.parse_args()

    timeout = min(args.timeout, run_headless._TIMEOUT_HARD_MAX)
    ids = [s.strip() for s in args.ids.split(",")] if args.ids else None

    corpus_path = pathlib.Path(args.corpus).expanduser().resolve()
    pairs = _resolve_query_list(corpus_path, args.corpus_key,
                                args.limit, ids)
    if not pairs:
        raise SystemExit("No queries matched.")

    env = run_headless.load_env_file(pathlib.Path(args.env_file))
    if "API_USER" not in env and "NEXTSEEK_USERNAME" in env:
        env["API_USER"] = env["NEXTSEEK_USERNAME"]
    if "API_PASS" not in env and "NEXTSEEK_PASSWORD" in env:
        env["API_PASS"] = env["NEXTSEEK_PASSWORD"]
    env.setdefault("CATALOG_FILE", "/etc/dmac/agent_model_catalog.json")
    if not env.get("AWS_BEARER_TOKEN_BEDROCK"):
        raise SystemExit(
            "AWS_BEARER_TOKEN_BEDROCK not in env-file; cannot reach Bedrock."
        )

    catalog_host = pathlib.Path(args.catalog_file).resolve()
    if not catalog_host.exists():
        raise SystemExit(f"--catalog-file not found: {catalog_host}")

    run_id = args.run_id or datetime.now(timezone.utc).strftime(
        "%Y%m%dT%H%M%SZ",
    )
    output_dir = pathlib.Path(args.output_dir) / run_id
    output_dir.mkdir(parents=True, exist_ok=True)

    fixed_scratch: pathlib.Path | None = None
    artifacts_root: pathlib.Path | None = None
    if args.scratch_dir:
        # User-supplied scratch (typically a Dropbox project folder).
        # Layout we create inside it for clean browsing:
        #
        #   <scratch-dir>/<user>/<run_id>/
        #     artifacts/<qid>/    ← user-facing outputs (xlsx, html, png ...)
        #     raw/                ← bind-mounted as /data/scratch; debug tree
        #
        # Why split: chat_nextseek dumps a per-call timestamped folder with
        # console.txt, api_requests.json, intermediate JSONs, etc. into the
        # same tree as the report .xlsx. Mixing run metadata with the actual
        # deliverable makes "where's my GEO submission" unnecessarily hard.
        # We bind-mount only the raw/ subtree as /data/scratch so the
        # container can write freely; after each query we snapshot the
        # filesystem and copy artifact-typed files to artifacts/<qid>/.
        scratch_root = pathlib.Path(
            args.scratch_dir,
        ).expanduser().resolve()
        if not scratch_root.exists():
            raise SystemExit(
                f"--scratch-dir does not exist: {scratch_root}",
            )
        user_id = env.get("API_USER") or env.get("NEXTSEEK_USERNAME") or "demo"
        session_root = scratch_root / user_id / run_id
        fixed_scratch = session_root / "raw"
        artifacts_root = session_root / "artifacts"
        fixed_scratch.mkdir(parents=True, exist_ok=True)
        artifacts_root.mkdir(parents=True, exist_ok=True)
        os.chmod(fixed_scratch, 0o777)

    if args.keep_state:
        # Docker -v rejects relative paths, so resolve before mounting.
        scratch_dir = (output_dir / "_state" / "scratch").resolve()
        claude_dir = (output_dir / "_state" / "claude").resolve()
        scratch_dir.mkdir(parents=True, exist_ok=True)
        claude_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(scratch_dir, 0o777)
        os.chmod(claude_dir, 0o777)

    started_at = datetime.now(timezone.utc)
    print(
        f"[run_batch] {len(pairs)} queries  image={args.image}  "
        f"timeout={timeout}s  budget=${args.max_budget_usd}  "
        f"keep_state={args.keep_state}  out={output_dir}",
        file=sys.stderr,
    )

    summaries: list[dict] = []
    aborted = False
    abort_reason: str | None = None

    # Files that count as user-facing artifacts (vs run metadata that stays
    # in raw/). Deliberately narrow: .json/.txt are usually intermediate
    # state, not what the user opens.
    _artifact_exts = {
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

    for i, (qid, qtext) in enumerate(pairs, 1):
        if args.keep_state:
            qscratch = scratch_dir
            qclaude = claude_dir
        else:
            if fixed_scratch is not None:
                qscratch = fixed_scratch
            else:
                qscratch = pathlib.Path(
                    tempfile.mkdtemp(prefix="dmac-batch-scratch-"),
                )
                os.chmod(qscratch, 0o777)
            qclaude = pathlib.Path(
                tempfile.mkdtemp(prefix="dmac-batch-claude-"),
            )
            os.chmod(qclaude, 0o777)

        # Snapshot raw/ before this query so we can isolate what THIS query
        # produced. With a shared mount across queries (fixed_scratch is
        # the same path each iteration), set difference gives us exactly
        # the new files written during run_one().
        pre_snapshot = (
            _snapshot_files(fixed_scratch) if fixed_scratch is not None else set()
        )

        print(
            f"[{i}/{len(pairs)}] {qid}  q={qtext[:60]!r}",
            file=sys.stderr,
        )
        try:
            record = run_headless.run_one(
                query_text=qtext, query_id=qid, image=args.image,
                env=env, timeout=timeout, output_dir=output_dir,
                catalog_host_path=catalog_host,
                scratch_dir=qscratch, claude_dir=qclaude,
                max_budget_usd=(
                    args.max_budget_usd if args.max_budget_usd > 0 else None
                ),
            )
        finally:
            if not args.keep_state:
                # Never remove a user-supplied --scratch-dir (that's their
                # Dropbox / project data). Only clean up our own tempdirs.
                if fixed_scratch is None:
                    shutil.rmtree(qscratch, ignore_errors=True)
                shutil.rmtree(qclaude, ignore_errors=True)

        # Promote artifacts (xlsx, html, csv, etc.) from raw/ into
        # artifacts/<qid>/ so the user can find deliverables without
        # spelunking through chat_nextseek's per-call dirs.
        promoted_paths: list[str] = []
        if fixed_scratch is not None and artifacts_root is not None:
            new_files = _snapshot_files(fixed_scratch) - pre_snapshot
            qartifacts = artifacts_root / qid
            qartifacts.mkdir(parents=True, exist_ok=True)
            for src in sorted(new_files):
                if src.suffix.lower() not in _artifact_exts:
                    continue
                dest = qartifacts / src.name
                n = 1
                while dest.exists():
                    dest = qartifacts / f"{src.stem}__{n}{src.suffix}"
                    n += 1
                shutil.copy2(src, dest)
                promoted_paths.append(str(dest))
            if not promoted_paths:
                # No artifacts produced — keep the listing tidy.
                try:
                    qartifacts.rmdir()
                except OSError:
                    pass

        summaries.append({
            "query_id": record["query_id"],
            "query_text": record["query_text"],
            "latency_seconds": record["latency_seconds"],
            "cost_usd": record["cost_usd"],
            "cost_estimated": record.get("cost_estimated", False),
            "artifacts": promoted_paths,
            "tool_use_summary": record["tool_use_summary"],
            "tool_calls_total": record["tool_calls_total"],
            "answer_provided": record["answer_provided"],
            "is_error": record["is_error"],
            "error": record["error"],
            "timed_out": record["timed_out"],
            "num_turns": record["num_turns"],
            "stop_reason": record["stop_reason"],
            "record_path": record["record_path"],
        })
        cost_marker = "~" if record.get("cost_estimated") else ""
        print(
            f"    -> latency={record['latency_seconds']:.1f}s  "
            f"cost={cost_marker}${record['cost_usd']:.4f}  "
            f"tools={record['tool_calls_total']}  "
            f"answer={'Y' if record['answer_provided'] else 'N'}"
            + (f"  ERROR={record['error']}" if record['error'] else ""),
            file=sys.stderr,
        )

        if args.stop_on_fail and record["is_error"]:
            aborted = True
            abort_reason = f"stop-on-fail: {record['error']}"
            break

    completed_at = datetime.now(timezone.utc)

    total_latency = sum(s["latency_seconds"] for s in summaries)
    total_cost = sum(s["cost_usd"] for s in summaries)
    n_cost_estimated = sum(1 for s in summaries if s.get("cost_estimated"))
    n = len(summaries)
    n_answered = sum(1 for s in summaries if s["answer_provided"])
    n_errored = sum(1 for s in summaries if s["is_error"])
    n_timed_out = sum(1 for s in summaries if s["timed_out"])

    manifest = {
        "run_id": run_id,
        "started_at": started_at.isoformat().replace("+00:00", "Z"),
        "completed_at": completed_at.isoformat().replace("+00:00", "Z"),
        "image": args.image,
        "corpus": str(corpus_path),
        "corpus_key": args.corpus_key,
        "timeout_seconds": timeout,
        "max_budget_usd": args.max_budget_usd,
        "keep_state": args.keep_state,
        "queries_total": n,
        "queries_answered": n_answered,
        "queries_errored": n_errored,
        "queries_timed_out": n_timed_out,
        "answer_rate": (n_answered / n) if n else 0.0,
        "total_latency_seconds": round(total_latency, 3),
        "total_cost_usd": round(total_cost, 6),
        "queries_cost_estimated": n_cost_estimated,
        "avg_latency_seconds": round(total_latency / n, 3) if n else 0.0,
        "avg_cost_usd": round(total_cost / n, 6) if n else 0.0,
        "aborted": aborted,
        "abort_reason": abort_reason,
        "summaries": summaries,
    }
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")

    print(
        f"\n[run_batch] done  run_id={run_id}  "
        f"answered={n_answered}/{n}  "
        f"errored={n_errored}  "
        f"total_cost=${total_cost:.4f}  "
        f"manifest={manifest_path}",
        file=sys.stderr,
    )
    print(json.dumps({
        "run_id": run_id,
        "manifest_path": str(manifest_path),
        "queries_total": n,
        "queries_answered": n_answered,
        "queries_errored": n_errored,
        "queries_timed_out": n_timed_out,
        "answer_rate": (n_answered / n) if n else 0.0,
        "total_cost_usd": round(total_cost, 6),
        "total_latency_seconds": round(total_latency, 3),
        "aborted": aborted,
    }, indent=2))
    sys.exit(0 if not aborted and n_errored == 0 else 1)


if __name__ == "__main__":
    main()
