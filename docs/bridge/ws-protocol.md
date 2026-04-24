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
{"type":"session_started","session_id":"11111111-2222-3333-4444-555555555555"}
{"type":"assistant_message","content":"Hello"}
{"type":"tool_use","tool":"Bash","input":{"command":"echo hi"},"id":"toolu_123"}
{"type":"error","reason":"resume_failed","requested":"...","actual":"..."}
{"type":"session_ended","session_id":"11111111-2222-3333-4444-555555555555"}
```

Frame meanings:

- `session_started` is sent once with the actual Claude session id.
- `assistant_message` is sent once per assistant text block.
- `tool_use` is sent once per Claude tool-use block.
- `error` covers bridge or parser errors. A resume mismatch uses `reason: "resume_failed"` plus `requested` and `actual`.
- `session_ended` is emitted when Claude sends a `result` event or when the attach stream ends cleanly without one.

## Close codes

- `4401`: auth failure on the upgrade request.
- `4400`: the first accepted client frame was malformed.
- `1011`: internal bridge failure, including container startup or attach failure.

## Ordering rules

- `session_started` always precedes any `assistant_message` or `tool_use` frame.
- `resume_failed` may precede `session_started` when the requested session id is not the session id Claude actually started.

For the higher-level bridge flow, local setup, and resumption rules, see [Bridge README](./README.md).
