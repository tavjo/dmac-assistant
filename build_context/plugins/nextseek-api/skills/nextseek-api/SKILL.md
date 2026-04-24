---
name: nextseek-api
description: >
  Interactive NExtSEEK API query skill for Claude Code. Trigger whenever the user
  types /nextseek-api, asks to query NExtSEEK, look up a sample, retrieve a sample
  by UID, get a sample count for a project, check a study's metadata, or explore
  the NExtSEEK endpoint catalog. This skill teaches Claude the exact bash commands
  to run — nextseek-init, nextseek-spec, nextseek-validate, nextseek-exec,
  nextseek-call, nextseek-vocab, nextseek-session — for bootstrapping a SchemaRAG
  session against the NExtSEEK dev or prod API, caching the minimal endpoint
  catalog once, fetching full endpoint specs on demand, statically validating
  request construction, and executing live calls under a 3-layer write-safety
  model (Claude Code permission allowlist + internal script denylist + behavioral
  plain-text write-confirmation gate). Works with both canonical (NEXTSEEK_BASE_URL / SEEK_USER /
  SEEK_PASSWORD) and legacy (API_BASE_URL / username / password) .env file
  formats so existing BMC credentials drop in without edits. The skill's goal is
  to save tokens across sessions by making endpoint discovery happen once at
  bootstrap (minimal catalog + entity tree cached to disk) and letting Claude pick
  endpoints from the cached file directly via the Read tool, without re-querying
  SchemaRAG for every question.
disable-model-invocation: false
---

# nextseek-api

A deterministic, token-efficient workflow for querying the NExtSEEK API from any
Claude Code session. **Read this entire file before taking any action.** Every
bash command, every write-safety rule, and every plain-text confirmation prompt is exact.

---

## Quick Start

Three commands, in order, answer almost every question:

1. `nextseek-init --env <dev|prod> --env-file <PATH>`  — once per session; bootstraps the SchemaRAG session, caches the minimal endpoint catalog and the entity tree.
2. `nextseek-spec --env <dev|prod> --query "<NL question or term>"` (or `--operation-id <ID>`) — picks an endpoint and emits a `request_spec_template` that is ready to fill.
3. `nextseek-call --env <dev|prod> --op "<operation_id>" [--path-params ...] [--query-params ...] [--body ...]` — resolves, validates, and executes in one step. For raw specs use `nextseek-call --spec -` and pipe a `RequestSpec` JSON on stdin.

For `advanced_search` (and any vocab-driven body), also consult one of:

- **Passive context**: `Read ~/.cache/nextseek-api/v2/<env>/entity_tree.json`
- **Active lookup**: `nextseek-vocab resolve <TERM> --env <env>`

Non-GET (POST/PATCH/DELETE) calls require `--confirmed-write` AND a Layer-3
plain-text user confirmation first. See **Write safety** below.

---

## Shim Reference

| Shim              | Purpose                                                     | Write-safe? |
|-------------------|-------------------------------------------------------------|-------------|
| `nextseek-init`   | Bootstrap session; cache minimal catalog + entity tree      | yes         |
| `nextseek-spec`   | Fetch endpoint spec (lazy full cache); emit request template| yes         |
| `nextseek-validate` | Static `RequestSpec` validation (no network)              | yes         |
| `nextseek-exec`   | Low-level execute (advanced; pipe a `RequestSpec`)          | POST needs `--confirmed-write` |
| `nextseek-call`   | Unified happy-path: resolve op + validate + execute         | POST needs `--confirmed-write` |
| `nextseek-vocab`  | `list` / `search` / `resolve` cached entity tree            | yes         |
| `nextseek-session`| Show current session TTL + cache paths (`--json` for machine) | yes      |

`nextseek-spec` is the canonical name (the prior shim name was hard-renamed in Task 06a and is no longer accepted).

---

## Prerequisites

1. Plugin enabled in `~/.claude/settings.json` under `enabledPlugins`:
   ```json
   "nextseek-api@local": true
   ```
2. Layer-1 permissions installed via `setup.sh`:
   ```bash
   bash ~/.claude/plugins/local/nextseek-api/skills/nextseek-api/scripts/setup.sh
   ```
3. A `.env` file with NExtSEEK credentials. Both naming conventions work:
   - Canonical: `NEXTSEEK_BASE_URL`, `SEEK_USER`, `SEEK_PASSWORD`
   - Legacy: `API_BASE_URL`, `username`, `password`

---

## Environment resolution (automated — no `AskUserQuestion`)

The DMAC chat UI does **not** render MCQ widgets. **Never use `AskUserQuestion`** for env or credential selection — the session would stall.

Resolve API base / `dev` vs `prod` for `nextseek-init --env` in this order (first match wins):

1. **`USE_DEV_API=1`** (truthy: `1`, `true`, `yes`, `on`) → use **dev**; log `env=dev (USE_DEV_API override)`.
2. **`NEXTSEEK_BASE_URL`** set and non-empty → use that URL; if the hostname matches `nextseek-dev.`, `dev.nextseek.`, or contains the substring `dev` (case-insensitive), log `env=dev`; otherwise log `env=prod`.
3. **`API_BASE_URL`** set → apply the same hostname heuristic as (2).
4. **`BASE_URL`** set (legacy) → same heuristic as (2).
5. None of the above → reply with plain text only: `NEXTSEEK_BASE_URL unset; set it in .env and restart the session.` Do not use `AskUserQuestion`.

**Credentials:** use `SEEK_USER` / `SEEK_PASSWORD` (canonical) or legacy `username` / `password`. In DMAC containers these are populated from `NEXTSEEK_USERNAME` / `NEXTSEEK_PASSWORD` via `entrypoint.sh`. If both canonical fields are empty after checking env, abort with a plain-text error — do not use `AskUserQuestion`.

---

## Bootstrap workflow

### Step 1 — Environment (no user MCQ)

Environment is resolved automatically; see **Environment resolution** above.

If the resolved target is **prod**, say explicitly: *"Confirmed: prod. Any write operation will hit live data and is irreversible. I will run the plain-text write-safety check before any non-GET call."*

### Step 2 — Credentials (no user MCQ)

Credentials come from environment variables (see Prerequisites). Abort with a plain-text error if required credential variables are missing.

### Step 3 — Run `nextseek-init`

```bash
nextseek-init --env <ENV> --env-file <PATH>
```

Optional flags:
- `--clear-cache` — wipe the env-scoped cache subtree before bootstrapping (sibling envs untouched).
- `--skip-preflight` — skip the `schema/?format=yaml` preflight probe (CI/automation only).
- `--assume-yes` — auto-confirm env/URL mismatch prompts.

Expected stdout includes the resolved `base_url` (so the user sees which env var won), the cached endpoint count, the session TTL, and a top-N preview of relevant endpoints.

### Step 4 — Read the cached catalog and entity tree

Use the Claude Code `Read` tool on:

- `~/.cache/nextseek-api/v2/<env>/endpoints_minimal.json` — every endpoint's `operation_id`, `method`, `endpoint`, `description`, `tags`, `relevance_score`. Scan this in-context for endpoint selection. **Do not** run `nextseek-spec` just to "list endpoints".
- `~/.cache/nextseek-api/v2/<env>/entity_tree.json` — the NExtSEEK vocab tree. Read this when building any `advanced_search` body so you use exact vocab values for fields like `sample_type` and `assay`.

Bootstrap is complete. Move to Per-query loop when the user asks a question.

---

## Per-query loop

For every user question:

1. **Pick the operation** by scanning the in-context minimal catalog (operation_id, summary, tags, path, relevance_score). For NL-only matches, `nextseek-spec --query "<NL>"` is allowed.
2. **Build the request** — preferred path: call `nextseek-call --op <id>` with `--path-params` / `--query-params` / `--body` flags (each accepts inline JSON or `@file.json`). Advanced path: build a `RequestSpec` JSON by hand and pipe to `nextseek-call --spec -` (or `nextseek-validate` + `nextseek-exec` for separate steps).
3. **Write-safety gate** — if `method != "GET"`, run the **plain-text Layer-3 confirmation** (below) before adding `--confirmed-write`. Never use `AskUserQuestion` for this — the UI cannot answer it.
4. **Execute** — `nextseek-call` does validate → execute in one shot.
5. **Summarize** — extract the fields the user asked about; do not dump raw JSON unless asked.

### `RequestSpec` shape (snake_case canonical)

```json
{
  "operation_id": "<OPERATION_ID>",
  "method": "GET",
  "endpoint": "/samples/{uid}/",
  "path_params": {"uid": "UID-123"},
  "query_params": {"page[size]": "100"},
  "request_body": {}
}
```

The validator emits `did you mean 'operation_id'?` hints if you accidentally use camelCase keys (e.g., `operationId`) — fix the casing and re-pipe.

`endpoint` is the TEMPLATE path. Do not interpolate `{uid}` yourself; the validator and executor render path tokens from `path_params`.

---

## Example 1 — "List all assays I can see"

**Bootstrap (one-time):**

```bash
nextseek-init --env prod --env-file ./.env
```

```
preflight ok: https://nextseek.mit.edu/nextseek_api (resolved via NEXTSEEK_BASE_URL)
session_id = sess-7c4...
expires_at = 2026-04-13T18:42:11Z
Cached 47 endpoints to ~/.cache/nextseek-api/v2/prod/endpoints_minimal.json
Cached entity tree to ~/.cache/nextseek-api/v2/prod/entity_tree.json
```

**Pick endpoint:** `Read` `~/.cache/nextseek-api/v2/prod/endpoints_minimal.json`. Best match for "list assays" is the entry with `operation_id: "ListAssays"`, method `GET`, endpoint `/assays/`.

**Run the unified call (auto-paginate to gather every page):**

```bash
nextseek-call --env prod --op ListAssays --auto-paginate
```

Output (truncated):

```json
[
  {"id": 12, "title": "scRNA-seq pilot", "project_id": "SRP", "sample_type": "D.SEQ"},
  {"id": 13, "title": "Bulk RNA-seq", "project_id": "SRP", "sample_type": "D.SEQ"},
  {"id": 14, "title": "ATAC-seq batch 1", "project_id": "CGR", "sample_type": "D.ATAC"}
]
```

**Summarize:**
> "You can see **3 assays** across SRP and CGR projects. Two are scRNA/bulk RNA-seq (D.SEQ) on SRP; one is ATAC-seq (D.ATAC) on CGR."

---

## Example 2 — "Find samples where sample_type = D.SEQ and project_id = SRP"

This is an `advanced_search` call. The `sample_type` value must match the entity tree exactly.

**Resolve the vocab term:**

```bash
nextseek-vocab resolve "D.SEQ" --env prod
```

```json
{
  "match": "exact",
  "node": {"path": "Data.Sequencing", "code": "D.SEQ", "label": "Sequencing data"}
}
```

(Alternatively: `Read ~/.cache/nextseek-api/v2/prod/entity_tree.json` and search for `D.SEQ`.)

**Fetch the spec (so we know the body shape):**

```bash
nextseek-spec --env prod --operation-id AdvancedSearchSamples --print-example
```

```json
{
  "operation_id": "AdvancedSearchSamples",
  "method": "POST",
  "endpoint": "/samples/advanced_search/",
  "path_params": {},
  "query_params": {},
  "request_body": {"filters": [{"field": "<string>", "op": "eq", "value": "<any>"}]}
}
```

**Build and run** (advanced_search is a POST but read-only; still requires `--confirmed-write` and Layer-3 confirmation by the conservative gate):

**Layer-3 gate (plain text, not `AskUserQuestion`):** send the user a single assistant message:

```
Write-safety check: I'm about to execute POST /samples/advanced_search/ with path_params={} body={"filters":[{"field":"sample_type","op":"eq","value":"D.SEQ"},{"field":"project_id","op":"eq","value":"SRP"}]}
This will modify live data. Type "confirm" to proceed, anything else to abort.
```

Wait for the user's next plain-text `user_message`. Only add `--confirmed-write` if that message contains the literal substring `confirm` (case-insensitive). Otherwise reply `Aborted per user; no call made.` and return to the query loop.

User confirmed (message contains `confirm`):

```bash
nextseek-call --env prod \
  --op AdvancedSearchSamples \
  --body '{"filters":[{"field":"sample_type","op":"eq","value":"D.SEQ"},{"field":"project_id","op":"eq","value":"SRP"}]}' \
  --confirmed-write
```

Output:

```json
{
  "count": 42,
  "next": null,
  "results": [
    {"uid": "UID-9001", "title": "SRP scRNA-seq donor A", "sample_type": "D.SEQ", "project_id": "SRP"},
    {"uid": "UID-9002", "title": "SRP bulk RNA-seq donor B", "sample_type": "D.SEQ", "project_id": "SRP"}
  ]
}
```

**Summarize:**
> "Found **42 samples** in project SRP with `sample_type = D.SEQ`. The first two are scRNA-seq (UID-9001) and bulk RNA-seq (UID-9002) from donors A and B."

---

## Example 3 — "Bulk retrieve samples by identifiers ['UID-100', 'UID-101', 'UID-102']"

POST to a non-`schema_rag` endpoint that is read-only on the server but triggers the conservative write-safety gate.

**Build the spec by hand and pipe it to `nextseek-call --spec -`:**

```bash
echo '{"operation_id":"samplesRetrieve","method":"POST","endpoint":"/admin/samples/retrieve/","path_params":{},"query_params":{},"request_body":{"identifiers":["UID-100","UID-101","UID-102"]}}' \
  | nextseek-call --env prod --spec - --confirmed-write
```

(Same plain-text Layer-3 confirmation as Example 2 before adding `--confirmed-write`.)

Output:

```json
{
  "results": [
    {"uid": "UID-100", "title": "Brain cortex", "sample_type": "Tissue"},
    {"uid": "UID-101", "title": "Plasma day-7", "sample_type": "Fluid"},
    {"uid": "UID-102", "title": "Liver section", "sample_type": "Tissue"}
  ],
  "total": 3
}
```

---

## Env Var Precedence

The base URL is resolved in this order (first hit wins):

1. `NEXTSEEK_BASE_URL` (canonical)
2. `API_BASE_URL` (legacy)
3. `BASE_URL` (legacy)
4. default — prod: `https://nextseek.mit.edu/nextseek_api`; dev: `https://nextseek-dev.mit.edu/nextseek_api`

`USE_DEV_API=1` is a **hard override** — when set, the dev base URL wins regardless of any of the above.

`nextseek-init` prints the resolved `base_url` and which env var supplied it, so the user sees exactly where requests will go before any HTTP call.

Credentials: `SEEK_USER`/`SEEK_PASSWORD` (canonical) take precedence over `username`/`password` (legacy).

---

## Cache Paths

Base: `~/.cache/nextseek-api/v2/{env}/`  (honors `XDG_CACHE_HOME`; the `v2/` segment isolates this generation of the cache from any prior layout).

| File                                         | Contents                                                | Lifetime    |
|----------------------------------------------|---------------------------------------------------------|-------------|
| `session.json`                               | SchemaRAG `session_id`, `base_url`, `expires_at`        | session TTL |
| `endpoints_minimal.json`                     | Minimal endpoint catalog (bulk, written by `nextseek-init`) | session TTL |
| `endpoints_full/<operation_id>.json`         | Per-op full spec — written lazily by `nextseek-spec`    | session TTL |
| `entity_tree.json`                           | NExtSEEK vocab tree (sample types, assays, …)           | session TTL |

Clear all caches for one env: `nextseek-init --env <env> --env-file <path> --clear-cache`. Sibling env caches are left untouched.

Inspect current session: `nextseek-session --env <env>` (add `--json` for machine output). Exit code `0` = present and unexpired; `1` = missing/expired/corrupt.

---

## Pagination

NExtSEEK list endpoints return:

```json
{"count": 1247, "next": "https://.../assays/?page[number]=2", "results": [...]}
```

Override page size:

```bash
nextseek-call --op ListAssays --query-params '{"page[size]":"500"}'
```

Auto-aggregate every page (caps at 100 pages to prevent runaway loops):

```bash
nextseek-call --op ListAssays --auto-paginate
```

`--auto-paginate` walks `page[number]` until `next` is null or `results` is empty. The aggregated output is a single flat JSON list (the envelope is unwrapped). For non-GET methods `--auto-paginate` is ignored with a stderr warning.

---

## Building `advanced_search` requests

`advanced_search` requires exact vocab values (sample type codes like `D.SEQ`, assay annotations, project IDs). Two ways to find them, both backed by the cached entity tree at `~/.cache/nextseek-api/v2/<env>/entity_tree.json`:

- **Passive** — `Read ~/.cache/nextseek-api/v2/<env>/entity_tree.json` to load the whole tree as context. Best when you need to scan multiple branches at once.
- **Active** — `nextseek-vocab resolve <TERM> --env <env>` for an exact-or-fuzzy single lookup. Sub-commands: `nextseek-vocab list`, `nextseek-vocab search <substring>`, `nextseek-vocab resolve <term>`.

Always use the resolved canonical value (e.g., `D.SEQ`, not `d-seq` or `Sequencing`) as the `value` in your filter body.

---

## Error Format & Diagnosis

Validator failures emit JSON of shape:

```json
{
  "ok": false,
  "errors": [
    {"code": "MISSING_PATH_PARAM", "message": "Path template has {uid} but path_params does not contain 'uid'"}
  ]
}
```

Common error codes and fixes:

| Symptom (stderr/exit)                                    | Meaning / Fix                                                                 |
|----------------------------------------------------------|-------------------------------------------------------------------------------|
| `session expired — run nextseek-init`                    | Cache past TTL and auto-reingest failed. Re-run `nextseek-init`.              |
| `preflight failed: bad-url`                              | Base URL resolved to a non-API path. Check env vars; see precedence above.    |
| `preflight failed: bad-auth`                             | 401 from preflight. Check `SEEK_USER` / `SEEK_PASSWORD`.                      |
| `validation failed: ... did you mean 'operation_id'?`    | `RequestSpec` uses snake_case; you passed camelCase. Rename the key.          |
| `non-GET request requires --confirmed-write`             | Layer-2 denylist tripped. Run Layer-3 plain-text confirmation, then add the flag.   |
| `multiple matches for --op ...`                          | `nextseek-call --op` resolved >1 candidate. Re-run with the exact `operation_id`. |
| `no operation matches ...`                               | `nextseek-call --op` found nothing. Check the cached catalog or rephrase.     |

`nextseek-call` exit codes: 0 ok, 1 generic, 2 no-match, 3 ambiguous, 4 validation, 5 confirm-required, 6 API/network, 7 config/session/env.

---

## Write Safety — 3 Layers

Three independent gates protect against accidental writes:

### Layer 1 — Claude Code permissions allowlist (mechanical)

`setup.sh` installs these patterns into `~/.claude/settings.json`:

```
Bash(nextseek-init:*)
Bash(nextseek-spec:*)
Bash(nextseek-validate:*)
Bash(nextseek-exec --method GET*)
Bash(nextseek-exec --endpoint schema_rag/*)
```

Anything outside this list (including `nextseek-call --confirmed-write` and any non-GET `nextseek-exec`) triggers Claude Code's built-in permission prompt. **You cannot bypass this.**

### Layer 2 — Script-internal denylist (`--confirmed-write`)

`nextseek-exec` and `nextseek-call` refuse non-GET methods unless `--confirmed-write` is explicitly passed. The flag is **not** in the Layer-1 allowlist, so adding it still triggers the Layer-1 prompt.

### Layer 3 — Plain-text behavioral gate (this skill)

**Before ANY non-GET HTTP operation, you MUST obtain plain-text confirmation from the user.** The `AskUserQuestion` tool is **prohibited** in DMAC for write gates; the chat UI cannot render MCQ answers.

Protocol:

1. Send an assistant message in this exact pattern (fill in real values):

   ```
   Write-safety check: I'm about to execute {METHOD} {endpoint} with path_params={...} body={...}
   This will modify live data. Type "confirm" to proceed, anything else to abort.
   ```

2. Wait for the user's next plain-text `user_message`.

3. Only pass `--confirmed-write` to `nextseek-call` / `nextseek-exec` if that message contains the literal substring `confirm` (case-insensitive).

4. If the user does not confirm (e.g. they say `cancel`), reply `Aborted per user; no call made.` and return to the query loop.

`AskUserQuestion` was **replaced by** this flow for all write gates. Legacy docs that mention `AskUserQuestion` for Layer 3 are obsolete.

---

## Session expiry

Scripts handle session expiry transparently. Every script that touches SchemaRAG checks `session.json.expires_at` before calling the API, and on a 401 with a session-related error it auto-reingests + retries once. You'll see `Session expired, reingesting...` in stderr if this happens — no action required.

`nextseek-session --env <env>` reports the current TTL and resolved cache paths without mutating anything.

---

## Troubleshooting

### Authentication failure
`nextseek-init` exits with `NextseekAuthError: 401 Unauthorized`. Check the `.env` file uses one of the accepted naming pairs (canonical `SEEK_USER`/`SEEK_PASSWORD` or legacy `username`/`password`). Canonical wins if both are present.

### `permission denied` on every shim call
Layer-1 allowlist not installed. Run `setup.sh` once.

### `jq: command not found` during setup.sh
`brew install jq` (macOS) or `sudo apt install jq` (Debian/Ubuntu).

### Cache miss on `nextseek-spec`
Run `nextseek-init` first. If it ran already, the session may have expired and reingest failed — check connectivity, then re-run init.

### POST to a non-`schema_rag` endpoint blocked
By design (Layer 2). Some POST endpoints (e.g., `admin/samples/retrieve/`, `samples/advanced_search/`) are read-only on the server but are conservatively gated. Run the Layer-3 gate, add `--confirmed-write`, and approve the Layer-1 prompt.

### Wrong environment hit
`nextseek-init` always prints the resolved `base_url`. If `USE_DEV_API=1` is set anywhere it forces dev. `rm -rf ~/.cache/nextseek-api/v2/` and re-bootstrap to start clean.
