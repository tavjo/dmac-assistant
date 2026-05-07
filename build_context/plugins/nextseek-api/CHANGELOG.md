# Changelog

All notable changes to the `nextseek-api` plugin are recorded here.
Format loosely follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-04-13

First UX + correctness pass over the initial plugin (`0.1.0`). Closes 17 reported issues from live usage, adds the entity-tree auto-cache, and introduces a unified `nextseek-call` shim. All work delivered under the `nextseek-api-fixes` ultraplan; merged to `main` at commit `3458e98`. 393 tests pass at 97.62% coverage.

### Added
- `nextseek-call` — unified resolve + validate + execute shim (preferred happy path over invoking `nextseek-validate` and `nextseek-exec` separately). Flags: `--op`, `--path-params`, `--query-params`, `--body`, `--dry-run`, `--confirmed-write`, `--auto-paginate`, `--spec FILE|-`, `--env-file`.
- `nextseek-vocab` — `list [--clade CLADE]`, `search QUERY`, `resolve TERM` against a session-cached NExtSEEK entity tree. Exact match first, top-5 fuzzy fallback.
- `nextseek-session` — reports env, session_id, expires_at, remaining TTL seconds, and expired flag. Also surfaces cache paths.
- Entity-tree auto-cache on `nextseek-init` — fetches `/entity_tree/nodes/` and `/entity_tree/edge_attributes/` and writes `~/.cache/nextseek-api/v2/{env}/entity_tree.json` so agents can resolve vocab terms passively (via `Read`) or actively (via `nextseek-vocab resolve`).
- `nextseek-init --clear-cache` — wipes the per-env cache before re-ingesting.
- `nextseek-spec` emits a `request_spec_template` block with snake_case keys and `<placeholder>` values for required parameters, ready to fill and pipe to `nextseek-call --spec -`.
- `nextseek-spec --print-example` — prints a fully-populated example RequestSpec.
- `--auto-paginate` on `nextseek-call` — iterates `page[number]` until an empty page; returns concatenated results.
- `--env-file PATH` — honored by all seven shims via a shared argparse helper.
- `USE_DEV_API` hard override — forces dev even when the resolved base URL points at prod.
- Bidirectional base-URL normalization — accepts the host with or without the `/nextseek_api` suffix and canonicalizes internally.
- Dev/prod mismatch detection — warns and prompts when selected env disagrees with the resolved base URL host.
- Preflight probe on `nextseek-init` — GETs the live auth-guarded schema route (`schema/?format=yaml`) to disambiguate bad URL, bad credentials, and network errors before proceeding.
- Humanized validation errors — `request_validator` produces one-line-per-field diagnostics with camelCase → snake_case hints (e.g. "did you mean `operation_id`?").

### Changed
- **BREAKING**: `nextseek-get` renamed to `nextseek-spec`. No alias. Script `get_endpoint_spec.py` renamed to `fetch_spec.py`. plugin.json, `bin/`, `commands/`, `SKILL.md`, and tests updated.
- **BREAKING**: agent-visible spec shape uses snake_case exclusively — `operation_id`, `endpoint`, `request_body` (formerly `operationId`, `path`, `body`). Server camelCase is mapped to snake_case once at ingest in `schema_rag_client.retrieve()`. `model_dump(by_alias=False)` enforced at all output boundaries.
- **BREAKING**: on-disk cache bumped to `~/.cache/nextseek-api/v2/` to avoid stale reads across the snake_case flip. Old `v1/` caches are not migrated; run `nextseek-init --clear-cache` once to bootstrap fresh.
- Full-spec cache is now lazy per operation (`endpoints_full/{operation_id}.json`) rather than bulk-fetched at init. Keeps init fast; pays the per-op cost only on first use.
- Init success output is a single structured banner (env, base URL, session_id, expires_at, cache paths). Prior warnings (`server_error_retry`, `request_timeout`) downgraded to stderr on success.
- `NextseekAPIError.__str__` now reports `[status] METHOD URL — {body snippet}` with the resolved URL always included, making 403/404 diagnoses self-service.
- Error messages distinguish bad-URL (path not an API endpoint) from bad-credentials on 403 by inspecting response body and content-type.
- SKILL.md rewritten with a three-command Quick Start at the top (`init` → `spec` → `call`), a seven-shim reference table, env URL precedence documentation (`NEXTSEEK_BASE_URL` > `API_BASE_URL` > `BASE_URL`), v2 cache path map, pagination section, advanced_search construction flow, and two new worked transcripts (`ListAssays` via `--auto-paginate`; `AdvancedSearchSamples` via vocab resolve + Layer-3 gate).

### Fixed
- Preflight default URL was `schema_rag/schema/` (404 on both dev and prod — that route does not exist). Corrected to the live auth-guarded `schema/?format=yaml`. Task 01 unit tests mocked response codes but never verified URL correctness; the bug shipped to integration and was caught only by the end-to-end smoke test. A new regression guard uses `respx` to assert the default resolves to the correct live path + query.
- 7 preflight tests were silently skipped because `respx>=0.21` was declared in the dev extras of `pyproject.toml` but never `uv sync`'d. Added a hard `import respx` at test-module top so the missing dep fails loudly; `uv sync --extra dev` now runs as part of bootstrap.
- 6 pre-existing F401 unused-import warnings in the `scripts/` tree (5 pre-existing on main, 1 net new from the error-messages refactor).

### Migration notes (for upgraders)

If you were using `nextseek-get`:
- Rename all calls to `nextseek-spec`. There is no alias. The script behavior is a superset — every flag still works and a new `request_spec_template` block is added to stdout.

If you have any cached state under `~/.cache/nextseek-api/dev/` or `~/.cache/nextseek-api/prod/`:
- Old caches are ignored; the plugin writes to `~/.cache/nextseek-api/v2/` now. Either leave the old directories in place (inert) or `rm -rf ~/.cache/nextseek-api/dev ~/.cache/nextseek-api/prod` to reclaim disk.

If you have scripts that parse `nextseek-spec` output:
- Keys are now snake_case. Replace `operationId` → `operation_id`, `path` → `endpoint`, `body` → `request_body`.

If you prompt an agent that relied on the old 4-step flow (`spec` → construct RequestSpec → `validate` → `exec`):
- The 4-step flow still works unchanged. `nextseek-call` is an additive shim for the one-step happy path.

---

## [0.1.0] - 2026-04-09

Initial release. Delivered under the `nextseek-api-plugin` ultraplan. SchemaRAG bootstrap, minimal endpoint catalog cache, per-op full-spec fetch, static validator, live executor with three-layer write-safety, and setup.sh installer for the Layer 1 permission allowlist.
