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
