# DMAC Bridge

This directory documents the FastAPI bridge POC that authenticates a DMAC user, starts one Claude container for that session, and relays `stream-json` events over `/ws/chat`.

Canonical architecture and mount guidance lives in [`../../.claude/CLAUDE.md`](../../.claude/CLAUDE.md). The broader design background remains the SDS and ADR set: [`../../dmac-assistant-sds.md`](../../dmac-assistant-sds.md) and [`../../dmac-assistant-adrs.md`](../../dmac-assistant-adrs.md). The WebSocket frame contract is documented in [`./ws-protocol.md`](./ws-protocol.md).

## What the bridge is

The bridge is a thin FastAPI service under [`src/dmac_assistant/`](../../src/dmac_assistant/) that exposes:

- `POST /auth/login` to exchange `{user_id, password}` for an opaque bearer token.
- `GET /health` for a basic liveness check.
- `WS /ws/chat` to send user messages to a Claude container and receive Claude `stream-json` output as chat-oriented frames.

The bridge is intentionally stateless with respect to Claude session history. Session files live in the mounted `.claude/` directory, and the bridge only discovers and resumes them.

## Quickstart

1. Copy the environment template:

```sh
cp .env.example .env
```

2. Fill in the bridge-side DMAC and AWS values in `.env`.
3. Sync dependencies:

```sh
uv sync
```

4. Start the bridge:

```sh
uv run python -m dmac_assistant.app
```

By default the app listens on `DMAC_BRIDGE_HOST:DMAC_BRIDGE_PORT`, which defaults to `127.0.0.1:8000`.

## Authentication flow

Login happens over HTTP before the WebSocket is opened.

Request:

```http
POST /auth/login
Content-Type: application/json
```

```json
{"user_id":"alice","password":"s3cret-alice"}
```

Response:

```json
{"token":"opaque-bearer-token","expires_at":"2026-04-24T16:00:00Z"}
```

Use that token on the WebSocket upgrade request:

```http
Authorization: Bearer <token>
```

The login password is also what the bridge passes into the container runtime as `NEXTSEEK_PASSWORD`; clients do not send separate NExtSEEK credentials to `/ws/chat`.

## Resumption flow

Unless the first accepted `user_message` frame sets `new_session: true`, the bridge looks for the newest prior Claude session under:

```text
{DMAC_CLAUDE_USERS_ROOT}/{user_id}/.claude/projects/-home-user/*.jsonl
```

That path comes from Claude's cwd encoding for `/home/user`, which is where the container runs Claude.

The first client frame looks like this:

```json
{"type":"user_message","content":"Show me the latest samples","new_session":false}
```

Resume behavior:

- If `new_session` is omitted or `false`, the bridge asks Claude to resume the newest discovered session for `/home/user`.
- If `new_session` is `true`, the bridge skips resume lookup and starts a fresh session.
- If no prior session file exists, the bridge simply starts a new Claude session.
- If Claude starts a different session id than the one the bridge requested, the bridge emits `{"type":"error","reason":"resume_failed",...}` first and then `{"type":"session_started",...}` with the actual session id.

## Environment reference

Only the following bridge-configurable variables are assigned in [`.env.example`](../../.env.example):

| Variable | Purpose |
|---|---|
| `DMAC_USERS` | JSON object mapping each `user_id` to its password and allowed project list. |
| `DMAC_BRIDGE_HOST` | Host interface for the FastAPI bridge. |
| `DMAC_BRIDGE_PORT` | Port for the FastAPI bridge. |
| `DMAC_CLAUDE_USERS_ROOT` | Host root that contains per-user mounted `.claude/` state. |
| `DMAC_SCRATCH_ROOT` | Host root for per-user writable scratch output. |
| `DMAC_DROPBOX_ROOT` | Host root for project data that is mounted read-only into the container. |
| `AWS_REGION` | AWS region passed through to the Claude runtime. |
| `AWS_BEARER_TOKEN_BEDROCK` | Bedrock bearer token passed through to the Claude runtime. |

`DMAC_DEV_MODE` is optional. When set to a truthy value, the bridge falls back to macOS-friendly default roots for the three path variables if they are not explicitly set.

At runtime the bridge also injects `NEXTSEEK_USERNAME` and `NEXTSEEK_PASSWORD` into the container. Those values are derived from the authenticated login, not configured separately for `/ws/chat`.

When the LLM router is enabled (see below), `GCP_API_KEY` must also be set on the bridge host - the router calls Gemini Pro (currently `gemini-3.1-pro-preview`) via BAML to classify each turn into a route. The bridge also forwards `GCP_API_KEY` to the container when set, so in-container plugins that need GCP access can read it from their process environment.

## Routing and model selection

The bridge supports an optional LLM router (flag-gated by `DMAC_ROUTER_ENABLED`). When the flag is unset or falsy, the bridge dispatches every turn through the legacy long-lived Claude attach socket exactly as before; when set, the bridge classifies each user turn into one of two routes:

- `nextseek_query` - runs the deterministic `chat_nextseek` orchestrator pipeline inside the long-lived container (per-turn `docker exec`). Used for NExtSEEK-shaped queries (catalog lookups, sample lineage, study metadata).
- `container_cc` - runs Claude Code inside the container with a router-chosen model class (`"opus"`, `"sonnet"`, or `"haiku"`). Used for everything else.

The route decision and (for `container_cc`) the model class are emitted to the client as an optional `route_decided` WebSocket frame BEFORE `session_started`. See [`ws-protocol.md`](./ws-protocol.md) for the full frame schema.

Bridge-side env vars added by the router:

| Variable | Purpose |
|---|---|
| `DMAC_ROUTER_ENABLED` | When truthy, enables the per-turn router. Default: unset (router off, byte-identical legacy behavior). |
| `GCP_API_KEY` | Required when `DMAC_ROUTER_ENABLED=1`. Consumed by the BAML `GCPReasoner` client that drives the route-decision call. Also forwarded to the container when set (both routes) so in-container plugins can reach GCP. Redacted in `ContainerSpec.__repr__` / `model_dump`. |

Per-exec env vars the bridge passes on `docker exec` when the router is enabled. `docker exec` does **not** run the entrypoint shim, so the bridge re-derives the env that the entrypoint would have set; the list below highlights what is new or different on a per-turn exec relative to a long-lived `docker run` of the same image. Any bridge-host env var that `_build_environment` forwards (e.g. `GCP_API_KEY`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`) is included automatically when set on the bridge, because the per-exec env builder calls `_build_environment` first.

- Always set on every exec: `API_USER`, `API_PASS`, `NEXTSEEK_BASE_URL`, `AWS_REGION`, `AWS_BEARER_TOKEN_BEDROCK`.
- When `route="nextseek_query"`: `NEXTSEEK_MODE=gcp` (selects Gemini Flash-Lite for chat_nextseek's own classifier calls), `NEO4J_DATABASE`, `OUTPUTS_DIR`, `CHAT_NEXTSEEK_SESSION_DB`.
- When `route="container_cc"`: `CLAUDE_CODE_USE_BEDROCK=1` plus the model-class-specific Bedrock model ID (resolved via `build_context/router_model_class_map.json`).

When the router decides a route but the BAML call fails (network error, rate limit, schema mismatch), the bridge falls back to `route=container_cc, model_class=sonnet` and logs the failure with `extra={"router_fallback": True, "exc_type": <type>}`.

Per-turn router telemetry (success path) is emitted as a Python `logging` record named `router_decision` on the `dmac_assistant.router.agent` logger, with `extra={"route": <alias>, "model_class": <alias or None>, "decision_latency_ms": <float>, "reasoning_len": <int>}`. **Visibility**: the record is at INFO level; uvicorn's `--log-level error` (used by `tools/e2e/run_router_e2e.py`) silences it. To observe router telemetry in production, run the bridge with `--log-level info`, or wire a `logging.config.dictConfig` that captures `dmac_assistant.router.agent` at INFO or below. The reasoning text and user query are NEVER logged (R-03 redaction); only `reasoning_len` is loggable.

### NS-route stderr capture (diagnostic)

The in-container chat_nextseek runner (`container/runner_ns.py`) performs an fd-shuffle at startup so its `print()` debug output — including `[DEBUG][PARSER] Exception or parse error: <repr>` when the parser_agent fails structured-output validation — lands on docker exec **stderr**, while the JSONL events go to stdout. The bridge's `BridgeAttachSocket.read_event_line` reads both streams; stderr frames are not relayed to the chat UI (they may contain sensitive runtime debug data), and prior to 2026-05-18 they were truncated to 80 bytes and logged at DEBUG, which uvicorn's `--log-level error` discards entirely.

As of 2026-05-18 (Phase 7 residual #1 visibility):

- **INFO-level log per stderr frame**, truncated to 512 bytes — captured by `--log-level info` (or any user-configured handler at INFO+).
- **Opt-in file capture via `DMAC_BRIDGE_NS_STDERR_DIR`** — when this env var is set on the bridge process, every NS-route docker exec writes its docker-exec stderr verbatim (untruncated, binary append mode) to `<DMAC_BRIDGE_NS_STDERR_DIR>/<ns_session_id>.stderr.log`. The `ns_session_id` is the bridge-synthesized `^ns-[0-9a-f]{12}$` value emitted as the `session_id` in the `session_started` WS frame. When the env var is unset (production default), no file is created and behavior is byte-identical to the pre-2026-05-18 path.

| Variable | Purpose |
|---|---|
| `DMAC_BRIDGE_NS_STDERR_DIR` | When set, the bridge writes per-NS-session stderr to `<dir>/<ns_session_id>.stderr.log`. Designed for E2E harness and ad-hoc post-mortems; leave unset in production. The bridge auto-creates the directory; capture failure (disk full, bad path, malformed session id) is logged at WARNING and never blocks a turn. |

The CC route does not currently feed `BridgeAttachSocket.read_event_line`'s stderr branch — Claude Code prints to its own stderr but the bridge consumes that stream via the per-turn `exec_cc_turn` socket separately, and CC-route stderr capture is not implemented yet.

For full design rationale (10 locked design decisions, 16 task specs across 6 waves), see [`../superpowers/specs/2026-05-13-llm-router-design.md`](../superpowers/specs/2026-05-13-llm-router-design.md).

## Mount contract

The bridge and container follow the mount contract documented in [`../../.claude/CLAUDE.md`](../../.claude/CLAUDE.md):

| Container | Host | Mode |
|---|---|---|
| `/data/projects/{name}` | `~/Library/CloudStorage/Dropbox/DMAC_Data/{name}` in macOS dev, or the configured project root in other environments | `ro` |
| `/data/scratch` | `/persistent/scratch/{user_id}` | `rw` |
| `/home/user/.claude` | `/persistent/claude-users/{user_id}/.claude` | `rw` |

In current bridge code, the host-side roots come from `DMAC_DROPBOX_ROOT`, `DMAC_SCRATCH_ROOT`, and `DMAC_CLAUDE_USERS_ROOT`, and the bridge mounts only the authenticated user's allowed projects.

## POC boundary

This is still a POC bridge. It does not add generated API docs, token refresh, container pooling, SSO, or any new auth or frame types beyond the current `/auth/login` and `/ws/chat` contract.

## Troubleshooting

- Bad or missing auth: `/ws/chat` requires `Authorization: Bearer <token>` on the upgrade request, and tokens come only from `POST /auth/login`.
- `resume_failed`: the bridge requested the newest known session id, but Claude initialized a different one. Clients should continue using the `session_id` from the following `session_started` frame.
- Missing Docker image: the bridge expects the Claude container image to exist locally as `dmac-assistant:poc`. Startup failures surface as `{"type":"error","reason":"container_start_failed"}` and the socket closes with `1011`.
- No prior session to resume: if there is no matching `.jsonl` file under the encoded `/home/user` session directory, the bridge starts a new Claude session instead.
