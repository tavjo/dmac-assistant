"""Bootstrap the nextseek-api plugin: ingest + bulk minimal catalog fetch.

Invoked at the top of the /nextseek-api interactive workflow. Loads credentials,
opens a SchemaRAG session (auto-reingesting if expired), retrieves the entire
minimal endpoint catalog in one call, and writes it to an env-scoped cache dir
for downstream scripts to consume.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

# CL-1: All lib imports via `from lib.X import ...`. The task-01 conftest.py
# puts `scripts/` on sys.path so `lib.*` resolves at test time and runtime.
from lib.cache_paths import (
    resolve_endpoints_minimal_path,
    resolve_env_cache_dir,
    resolve_plugin_cache_base,
)
from lib.cli_common import add_env_file_arg
from lib.entity_tree_client import EntityTreeClient
from lib.env_loader import EnvMissingError, detect_env_mismatch, load_environment
from lib.logging_config import configure_quiet_logging
from lib.models import SchemaRAGResponse, SessionState
from lib.nextseek_client import NextseekClient, NextseekConfig, preflight_schema
from lib.schema_rag_client import SchemaRAGClient

EXIT_OK = 0
EXIT_FAIL = 1
EXIT_API = 2
EXIT_CONFIG = 3


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="init_session.py",
        description="Bootstrap NExtSEEK SchemaRAG session and fetch minimal endpoint catalog.",
    )
    parser.add_argument(
        "--env",
        choices=["dev", "prod"],
        required=False,
        help="Target NExtSEEK environment (dev or prod).",
    )
    add_env_file_arg(parser)
    parser.add_argument(
        "--assume-yes",
        action="store_true",
        help=(
            "Auto-confirm env/URL mismatch prompts. Use in automation; "
            "equivalent to answering 'y' at the interactive prompt."
        ),
    )
    parser.add_argument(
        "--skip-preflight",
        action="store_true",
        help="Skip the schema/?format=yaml preflight probe (tests/automation).",
    )
    parser.add_argument(
        "--clear-cache",
        action="store_true",
        help=(
            "Wipe the env-scoped cache directory (session.json, "
            "endpoints_minimal.json, endpoints_full/) before bootstrapping. "
            "Sibling env caches are left untouched. See "
            "lib/cache_paths.py for the exact layout."
        ),
    )
    return parser.parse_args(argv)


def _warn_and_confirm(mismatch: str, base_url: str, selected_env: str) -> bool:
    """Warn about an env/URL mismatch and ask the user whether to proceed.

    Returns True when the user explicitly confirms ``y``/``yes``. On a
    non-TTY stdin (piped / CI), returns False (fail-closed) so automation
    never silently talks to the wrong environment.
    """
    messages = {
        "prod-dev": (
            f"Selected env=dev but base_url {base_url} points at production."
        ),
        "dev-prod": (
            f"Selected env=prod but base_url {base_url} points at dev."
        ),
        "unknown-host": (
            f"Base URL {base_url} does not match a known NExtSEEK host; "
            f"cannot verify selected env={selected_env}."
        ),
    }
    msg = messages.get(mismatch, f"Env/URL mismatch ({mismatch}): {base_url}")
    print(f"[nextseek-init] WARNING: {msg}", file=sys.stderr)

    if not sys.stdin.isatty():
        return False
    try:
        answer = input("Proceed anyway? [y/N]: ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


def _prompt_env_interactive() -> tuple[str, Path]:  # pragma: no cover
    """Interactive fallback if --env / --env-file were not provided.

    Isolated so unit tests never exercise real stdin.
    """
    env = input("Environment [dev/prod]: ").strip().lower()
    env_path = input("Path to .env file: ").strip()
    return env, Path(env_path).expanduser()


def main(argv: list[str] | None = None) -> int:
    # DD-13 (task-02 / issue #14): quiet success. Route library warnings
    # (``server_error_retry``, ``request_timeout``, etc.) to stderr before
    # any client is constructed, so stdout stays clean for downstream
    # consumers (Read of endpoints_minimal.json, piped JSON).
    configure_quiet_logging()

    args = _parse_args(argv)

    # DD-14 (task-02 / issue #16): ``--clear-cache`` wipes only the
    # env-scoped subtree; sibling envs are untouched. Runs BEFORE any
    # network call so a corrupted cache can't taint the bootstrap.
    if args.clear_cache and args.env:
        env_cache_dir = resolve_env_cache_dir(args.env)
        shutil.rmtree(env_cache_dir, ignore_errors=True)
        print(
            f"[nextseek-init] cleared cache dir {env_cache_dir}",
            file=sys.stderr,
        )

    if not args.env or not args.env_file:  # pragma: no cover
        try:
            env_val, env_file = _prompt_env_interactive()
        except (KeyboardInterrupt, EOFError):
            print("Aborted.", file=sys.stderr)
            return EXIT_CONFIG
    else:
        env_val = args.env
        env_file = args.env_file

    # CL-12: load_environment returns a NextseekConfig directly.
    try:
        config: NextseekConfig = load_environment(
            env_path=env_file,
            use_dev=(env_val == "dev"),
        )
    except EnvMissingError as exc:
        print(f"ERROR: missing credentials ({exc})", file=sys.stderr)
        return EXIT_CONFIG
    except FileNotFoundError as exc:  # pragma: no cover
        print(f"ERROR: missing credentials (env file not found: {exc})", file=sys.stderr)
        return EXIT_CONFIG

    # Surface the resolved URL + precedence source so users can see exactly
    # which env var won (issue #3: env-var precedence visibility).
    print(
        f"[nextseek-init] resolved base_url={config.base_url}",
        file=sys.stderr,
    )
    print(
        f"[nextseek-init] source={config.base_url_source or 'default'}",
        file=sys.stderr,
    )

    # Issue #4: warn if the resolved URL's host doesn't match the env
    # (dev/prod) the user selected at the CLI.
    mismatch = detect_env_mismatch(config.base_url, env_val)
    if mismatch != "match":
        confirmed = args.assume_yes or _warn_and_confirm(
            mismatch, config.base_url, env_val,
        )
        if not confirmed:
            print(
                "[nextseek-init] aborted: env/URL mismatch not confirmed.",
                file=sys.stderr,
            )
            return EXIT_CONFIG

    # Issue #2: preflight before ingest so a bad URL is distinguished from
    # bad credentials.
    if args.skip_preflight:
        pre = None
    else:
        pre = preflight_schema(config)
    if pre is not None and not pre.ok:
        print(
            f"[nextseek-init] preflight failed: {pre.diagnosis} at "
            f"{pre.resolved_url}: {pre.detail}",
            file=sys.stderr,
        )
        return EXIT_API

    # CL-7: resolve env-scoped cache dir via the helper module.
    cache_dir = resolve_env_cache_dir(env_val)
    cache_dir.mkdir(parents=True, exist_ok=True)

    # Fetch minimal catalog via SchemaRAG with silent auto-reingest.
    # CL-3: SchemaRAGClient is a context manager; kwargs are http_client (positional),
    # env_tag, base_url (NEW required), cache_base_dir (BASE dir, no env suffix —
    # the client appends /{env_tag} internally).
    try:
        with NextseekClient(config=config) as http_client:
            with SchemaRAGClient(
                http_client,
                env_tag=env_val,
                base_url=config.base_url,
                cache_base_dir=resolve_plugin_cache_base(),
            ) as rag_client:
                response: SchemaRAGResponse = rag_client.retrieve_with_auto_ingest(
                    query="all endpoints",
                    mode="minimal",
                    top_k="ALL",
                    min_score=0.0,
                )
                # CL-3: SchemaRAGResponse has session_id but NOT expires_at.
                # Read session metadata from the client's on-disk state via the
                # locked current_session_state() method.
                session: SessionState | None = rag_client.current_session_state()
    except Exception as exc:  # noqa: BLE001 — surface any API/network error
        print(f"ERROR: API call failed: {exc}", file=sys.stderr)
        return EXIT_API

    if session is None:
        print(
            "ERROR: SchemaRAG reported success but no session state was persisted.",
            file=sys.stderr,
        )
        return EXIT_API

    # CL-3 + DD-5: response is a pydantic SchemaRAGResponse; convert endpoint
    # models to plain dicts in the snake_case canonical form (operation_id /
    # endpoint) before JSON serialization. The agent-visible cache file MUST
    # be snake_case end-to-end — the camelCase wire alias is dropped here.
    endpoints_as_dicts = [ep.model_dump(by_alias=False) for ep in response.endpoints]
    fetched_at = datetime.now(timezone.utc).isoformat()
    cache_payload = {
        "env_tag": env_val,
        "session_id": session.session_id,
        "expires_at": session.expires_at.isoformat(),
        "base_url": config.base_url,
        "fetched_at": fetched_at,
        "endpoints": endpoints_as_dicts,
    }

    # CL-7: write to the path returned by resolve_endpoints_minimal_path(env_tag).
    cache_file = resolve_endpoints_minimal_path(env_val)
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = cache_file.with_suffix(".json.tmp")
    tmp_path.write_text(json.dumps(cache_payload, indent=2))
    tmp_path.replace(cache_file)

    # Task-07: fetch + cache the entity tree (vocab) for downstream
    # advanced_search construction. Failure is non-fatal — the minimal
    # catalog is already cached and agents can proceed; we surface the
    # error on stderr and continue.
    try:
        tree = EntityTreeClient(config).fetch_tree(session.session_id)
        tree_path = cache_dir / "entity_tree.json"
        tree_tmp = tree_path.with_suffix(".json.tmp")
        tree_tmp.write_text(tree.model_dump_json(indent=2))
        tree_tmp.replace(tree_path)
        print(
            f"[nextseek-init] entity tree cached: {tree_path} "
            f"(nodes={len(tree.nodes)}, edges={len(tree.edges)})",
            file=sys.stderr,
        )
    except Exception as exc:  # noqa: BLE001 — non-fatal
        print(
            f"[nextseek-init] WARNING: entity tree fetch failed: {exc}",
            file=sys.stderr,
        )

    # DD-13 (task-02 / issue #14): structured banner on stderr exactly once.
    # stdout is reserved for machine-consumed summary lines. Use a distinct
    # prefix from the Task-01 preamble so the two banners are countable
    # independently (tests rely on "resolved base_url=" appearing exactly once).
    print(
        f"[nextseek-init] ready base_url={config.base_url} "
        f"env={env_val} session_id={session.session_id} "
        f"expires_at={session.expires_at.isoformat()} "
        f"cache={cache_file}",
        file=sys.stderr,
    )

    # Summary output.
    print(f"Cached {len(endpoints_as_dicts)} endpoints to {cache_file}")
    print(f"session_id = {cache_payload['session_id']}")
    print(f"expires_at = {cache_payload['expires_at']}")
    print("Top endpoints:")
    for ep in endpoints_as_dicts[:5]:
        op_id = ep.get("operation_id") or "<unknown>"
        method = ep.get("method", "?")
        path = ep.get("endpoint", "?")
        print(f"  - [{method}] {op_id} {path}")

    return EXIT_OK


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
