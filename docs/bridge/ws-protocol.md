# `/ws/chat` Protocol

This document describes the current DMAC bridge WebSocket contract implemented in [`src/dmac_assistant/ws.py`](../../src/dmac_assistant/ws.py).

## Connection and auth

Authenticate the WebSocket upgrade request with a bearer token returned by [`POST /auth/login`](./README.md):

```http
Authorization: Bearer <token>
```

The bridge verifies that token before accepting the WebSocket. Missing, malformed, expired, or invalid tokens are rejected.

## Client to server

The first accepted client frame must be a normal chat message. It is also the only frame that can control whether the bridge tries to resume a prior Claude session.

```json
{"type":"user_message","content":"Show me the latest samples","new_session":false}
```

Rules:

- `type` must be `user_message`.
- `content` must be a string.
- `new_session` is optional and is honored only on the first frame.
- Later client frames should use `{"type":"user_message","content":"..."}`.

## Server to client

The bridge emits these JSON frames:

```json
{"type":"route_decided","route":"nextseek_query","model_class":null}
{"type":"session_started","session_id":"11111111-2222-3333-4444-555555555555"}
{"type":"assistant_message","content":"Hello"}
{"type":"tool_use","tool":"Bash","input":{"command":"echo hi"},"id":"toolu_123"}
{"type":"tool_use","tool":"ns:search_basic","input":{"query":"..."},"id":"ns_step_4"}
{"type":"error","reason":"resume_failed","requested":"...","actual":"..."}
{"type":"session_ended","session_id":"11111111-2222-3333-4444-555555555555"}
```

Frame meanings:

- `route_decided` is OPTIONAL. It is emitted only when the LLM router is enabled (via `DMAC_ROUTER_ENABLED`) and has decided a route for the incoming turn. `route` is one of `"nextseek_query"`, `"container_cc"`, or `"unrelated"`. `model_class` is one of `"opus"`, `"sonnet"`, `"haiku"`, or `null`. As of OI-5 the router no longer selects a model class for `container_cc` (it always runs the fixed `opus`-class model), so `model_class` is advisory and is `null` in practice; the field is retained for back-compat. The frame deliberately does NOT carry a `session_id` field - the routing decision is taken before any Claude session is started. See [Routing](#routing) below.
- `session_started` is sent once with the actual Claude session id.
- `assistant_message` is sent once per assistant text block.
- `tool_use` is sent once per Claude tool-use block. The `tool` field passes through verbatim with no allowlist; under the `nextseek_query` route, the chat_nextseek orchestrator's per-step events appear as `tool_use` frames with `tool` values prefixed `"ns:"` (e.g. `"ns:search_basic"`, `"ns:report_writer"`).
- `error` covers bridge or parser errors. A resume mismatch uses `reason: "resume_failed"` plus `requested` and `actual`.
- `session_ended` is emitted when Claude sends a `result` event or when the attach stream ends cleanly without one.

## Close codes

- `4401`: auth failure on the upgrade request.
- `4400`: the first accepted client frame was malformed.
- `1011`: internal bridge failure, including container startup or attach failure.

## Ordering rules

- When the LLM router is enabled and emits `route_decided`, that frame is sent BEFORE `session_started`. The router's decision is independent of any Claude session id.
- `session_started` always precedes any `assistant_message` or `tool_use` frame **on the `container_cc` and `nextseek_query` routes**. EXCEPTION: the `unrelated` route (OI-4) runs no agent turn, so it emits `route_decided` → `assistant_message` (the canned out-of-scope reply) → `session_ended` with **no** `session_started`, and the `session_ended` carries `session_id: null` (the turn ends no real session). Clients must not assume `session_started` precedes the first `assistant_message` when `route_decided.route == "unrelated"`.
- `resume_failed` may precede `session_started` when the requested session id is not the session id Claude actually started.

## Routing

The bridge runs a per-turn LLM router, controlled by `DMAC_ROUTER_ENABLED` and **ON by default** (opt-out) as of 2026-06-15. When enabled (the default), each user turn is first classified into one of three routes:

- `"nextseek_query"` - runs the deterministic `chat_nextseek` orchestrator pipeline. Per-step events appear on the WebSocket as `tool_use` frames with `tool` values prefixed `"ns:"`.
- `"container_cc"` - runs Claude Code inside the container on the fixed `opus`-class model (OI-5; `--permission-mode auto`). Per-step events appear as `tool_use` frames with the existing Claude tool names (`"Bash"`, `"Read"`, etc.).
- `"unrelated"` (OI-4) - the query is outside the assistant's scope (general trivia, pop-culture, chit-chat). It runs NO agent turn: the bridge emits `route_decided` → a single canned `assistant_message` → `session_ended` (`session_id: null`) and returns. No container_cc or nextseek_query work happens.

When a route is decided, the bridge emits one optional `route_decided` frame as the FIRST frame of the turn (before `session_started`). The frame schema is:

```json
{"type":"route_decided","route":"<route>","model_class":"<class>"}
```

- `route` is one of `"nextseek_query"`, `"container_cc"`, or `"unrelated"` (lowercase alias strings).
- `model_class` is one of `"opus"`, `"sonnet"`, `"haiku"`, or `null`. It is advisory only: `container_cc` always runs the fixed `opus`-class model (OI-5) regardless of this field, and it is `null` for `"nextseek_query"` and `"unrelated"`.
- The frame does NOT carry a `session_id`. The routing decision is independent of any Claude session.

When `DMAC_ROUTER_ENABLED` is set to a falsy value (`0`/`false`/`no`/`off`/empty), the bridge behaves exactly as it did before the router landed: no `route_decided` frame, no per-turn classification, all turns go to the long-lived Claude attach socket. The router is ON by default (unset ⇒ enabled); the flag is the on/off switch for the entire subsystem.

For the higher-level bridge flow, local setup, and resumption rules, see [Bridge README](./README.md).
