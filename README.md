# DMAC Assistant

A lab-aware Claude Code agent for the [MIT BioMicro Center (BMC)](https://biomicro.mit.edu/). DMAC Assistant wraps a containerized [`claude`](https://github.com/anthropics/claude-code) CLI behind a thin FastAPI bridge so lab users can chat with an agent that knows their projects, their NExtSEEK sample catalog, and their pipelines — without ever opening a terminal.

> **Status**: Proof-of-concept. Plan A (containerized POC + bridge) is complete; Plan B (production hardening + plugin swap-in) is the next milestone. See [Project Status](#project-status) for the full state.

---

## What this is

DMAC Assistant is **not** a custom agent framework. It is a deliberately small bridge around three load-bearing pieces:

1. **A FastAPI bridge** (`src/dmac_assistant/`) that authenticates lab users, resolves the project directories they're authorized to read, starts a per-user Docker container, and relays chat messages between a browser UI and Claude Code's `stream-json` output.
2. **A Docker image** (`dmac-assistant:poc`) that contains Claude Code, [`uv`](https://github.com/astral-sh/uv), the `nextseek-api` plugin, and the in-container agent instructions.
3. **Plugin and documentation surfaces** that the in-container Claude runtime reads from fixed paths inside the image — most importantly the NExtSEEK API documentation and the `chat_nextseek` Python orchestrator.

The agent runs **inside the container**. The bridge process never executes user-supplied code; it just forwards bytes.

### Why a containerized agent

- **Project data is mounted read-only.** The container can read a user's authorized Dropbox project folders but can never write to them.
- **Secrets stay in environment variables.** AWS Bedrock tokens, NExtSEEK credentials, and other secrets are injected per session and never persisted into the mounted Claude state directory.
- **Output goes through a copier.** Anything the agent writes to `/data/scratch/` is copied to a host-side `<output_root>/<user_id>/` after each turn; the agent never has direct write access to the published output mount.
- **Sessions resume.** The container's `~/.claude/` is a per-user persistent volume, so users can reconnect mid-analysis and pick up exactly where they left off.

---

## Architecture overview

```
┌─────────────────┐      WebSocket          ┌───────────────────────────────┐
│ Browser chat UI │ ────────────────────▶  │ FastAPI bridge (host)         │
│ (vanilla HTML)  │  /ws/chat (stream-json) │ src/dmac_assistant/           │
└─────────────────┘                         │   ├─ ws.py    (relay loop)    │
                                            │   ├─ auth.py  (token store)   │
                                            │   ├─ containers.py (docker)   │
                                            │   ├─ run_tracker.py (file-set │
                                            │   │   diff snapshot)          │
                                            │   └─ copier.py (publish)      │
                                            └────────────────┬──────────────┘
                                                             │ docker-py
                                                             ▼
                                            ┌───────────────────────────────┐
                                            │ Container: dmac-assistant:poc │
                                            │ ┌───────────────────────────┐ │
                                            │ │ claude --print            │ │
                                            │ │   --output-format         │ │
                                            │ │   stream-json             │ │
                                            │ │   --dangerously-skip-     │ │
                                            │ │   permissions             │ │
                                            │ └─────────┬─────────────────┘ │
                                            │           │                   │
                                            │ Plugins:  ▼                   │
                                            │   nextseek-api (chat_nextseek)│
                                            │                               │
                                            │ Mounts:                       │
                                            │   /data/projects/<name> (ro)  │
                                            │   /data/scratch         (rw)  │
                                            │   /data/output          (ro)  │
                                            │   /home/user/.claude    (rw)  │
                                            └───────────────────────────────┘
```

### The mount contract (load-bearing)

| Container path           | Host path (macOS dev)                                              | Mode |
|--------------------------|--------------------------------------------------------------------|------|
| `/data/projects/{name}`  | `~/Library/CloudStorage/Dropbox/DMAC_Data/{name}`                  | `ro` |
| `/data/scratch`          | `~/dmac-dev/scratch/{user_id}` (dev mode)                          | `rw` |
| `/data/output`           | `~/dmac-dev/output/{user_id}` (dev mode)                           | `ro` (in container) / `rw` (on host) |
| `/home/user/.claude`     | `~/dmac-dev/claude-users/{user_id}/.claude`                        | `rw` |

The container always sees the same paths; only the host roots change between dev (macOS) and production (Linux). This is the security boundary — there are no ad-hoc path checks in bridge code.

### How a turn flows

1. User sends a message in the browser. The bridge receives it on `/ws/chat`.
2. If this is a fresh session, the bridge starts a new container with `containers.run` and attaches to its stdin/stdout. Otherwise it resumes via `--resume <session_id>`.
3. Before forwarding the message, the bridge **snapshots `/data/scratch/<user_id>/` as a `{path: (size, mtime_ns)}` map**.
4. The user's message is fed to claude's stdin. Claude streams `stream-json` events back through the attached socket; the bridge parses them and emits frames to the WebSocket.
5. When the turn completes (`session_ended` or stream EOF), the bridge **re-snapshots scratch, diffs against the pre-turn map, and copies every new or changed file** to `<output_root>/<user_id>/<same/relative/path>`. Symlinks are skipped (M2 invariant); paths containing `..` or absolute components are refused.

This file-set-diff approach (Plan A T12, Amendment 10) replaced an earlier subdirectory-diff design that required the in-container agent to honor a per-turn directory naming convention. The new design moves that contract entirely to the bridge, so the agent just writes flat to `/data/scratch/`.

---

## Quick start (dev, macOS)

```sh
# 1. Toolchain
brew install uv bats-core shellcheck
uv sync --frozen

# 2. Vendor deps (clones chat_nextseek pinned source into vendor/)
make sync-vendor-deps

# 3. Build the image
make image-build

# 4. Configure the host environment
cp .env.example .env
# Edit .env to set real AWS Bedrock + NExtSEEK creds (see .env.example for the schema)

# 5. Run the bridge
PYTHONPATH=src DMAC_OUTPUT_ROOT=$HOME/dmac-dev/output \
  uv run uvicorn dmac_assistant.app:app --host 127.0.0.1 --port 8000

# 6. Open the chat UI
open http://127.0.0.1:8000/
```

The first chat message will spin up a per-user container; subsequent messages reuse it for the lifetime of the WebSocket session.

### Required environment variables

The `.env.example` file is the canonical schema. Required for the bridge to start:

- `DMAC_USERS` — a single-line JSON object mapping `user_id` → `{password, projects}`
- `AWS_BEARER_TOKEN_BEDROCK`, `AWS_REGION` — Bedrock auth for the in-container Claude
- `NEXTSEEK_USERNAME`, `NEXTSEEK_PASSWORD`, `NEXTSEEK_URL` — fallback creds (production reuses chat-UI login)
- `DMAC_DEV_MODE=1` — selects macOS-friendly default path roots (`~/dmac-dev/...`)

Optional: `GCP_API_KEY`, `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` are forwarded to the container if set.

---

## Repository layout

```
dmac-assistant/
├── src/dmac_assistant/        # FastAPI bridge
│   ├── app.py                 # Application factory + static UI mount
│   ├── auth.py                # Token store + identity model
│   ├── config.py              # Env-driven BridgeConfig
│   ├── containers.py          # docker-py wrapper, mount contract, env injection
│   ├── ws.py                  # /ws/chat WebSocket route + relay loop
│   ├── run_tracker.py         # Per-turn scratch file-set snapshot
│   ├── copier.py              # scratch → output publish (M2-safe)
│   ├── streamjson.py          # claude stream-json parser
│   ├── sessions.py            # Most-recent-session lookup for --resume
│   └── static/                # Vanilla HTML chat UI
├── tests/
│   ├── unit/                  # Hermetic unit tests
│   ├── integration/           # FastAPI TestClient + fake attach socket
│   └── harness/               # Live-runner test scaffolding
├── container/                 # In-container agent surface
│   ├── CLAUDE.md              # Auto-generated NExtSEEK instructions
│   └── entrypoint.sh          # Container entrypoint
├── build_tools/               # Sibling uv project: image build + ingest helpers
├── build_context/             # Files COPYd into the image (plugins, docs)
├── vendor/                    # Pinned chat_nextseek source (gitignored)
├── docs/                      # Bridge protocol notes, ADRs, SDS
├── dmac-assistant-sds.md      # Software Design Specification
├── dmac-assistant-adrs.md     # Architecture Decision Records
└── Makefile                   # image-build, image-stage, sync-vendor-deps, ingest-nextseek-docs, ...
```

### Authoritative design documents

- **[`dmac-assistant-sds.md`](dmac-assistant-sds.md)** — components, data flow, mount contract, env vars, milestones
- **[`dmac-assistant-adrs.md`](dmac-assistant-adrs.md)** — decisions and the reasoning behind them

These are the architecture background for the POC; the source code is consistent with them but they are the source of truth when in doubt.

### In-repo agent instructions

- **[`container/CLAUDE.md`](container/CLAUDE.md)** — in-container agent instructions; the NExtSEEK section is auto-generated by `make ingest-nextseek-docs`. The rest is human-authored.
- **`CLAUDE.md`** at the project root (gitignored, kept locally only) holds guidance for Claude Code working in this repo: load-bearing invariants, mount contract, headless invocation, POC-vs-post-POC scope boundary.
- **`.claude/known-issues/`** (gitignored) tracks open production-blockers that affect architecture decisions. Contributors with repo access should read these before changes that touch the relevant subsystem. Maintained outside the public tree by design — these documents enumerate containment failure modes the in-container agent must not be able to read.

---

## Testing

The full bridge suite uses `pytest` with a coverage gate of **95%**:

```sh
uv run pytest                                # full suite
uv run pytest tests/unit -q                  # unit tests only
uv run pytest tests/integration -q           # integration (FastAPI TestClient)
uv run pytest --cov-fail-under=95 -q         # gated run (CI behavior)
```

Bridge coverage at the latest tag is **98.89%** (Plan A T12 closure). Two acknowledged low-priority gaps remain in `run_tracker.py` (an `OSError` race-condition guard for files that vanish between `os.walk` and `stat()`) and `copier.py` (an empty-string lexical guard in `_is_safe_relpath` that's unreachable from snapshot output). Both are unreachable in normal flow and tracked for follow-up.

The `build_tools/` sibling project has its own `pyproject.toml` and is run separately:

```sh
cd build_tools && uv run pytest
```

### What the integration test exercises

`tests/integration/test_chat_ws_post_turn.py` drives `chat_ws` end-to-end with a fake attach socket that emits real Claude `stream-json` frames. It exercises:

- The full WS handshake (subprotocol-bearer auth)
- Container start (mocked at `dmac_assistant.ws.async_start_container`)
- The pre-turn snapshot, post-turn diff, and copier publish path
- The `DMAC_PATH_MAPPINGS` env-var contract
- Both the normal `result`-event turn-end and the synthetic-EOF branch

If you change `run_tracker.py`, `copier.py`, or `ws.py`'s `dispatch_post_turn_copy`, this test will tell you fast.

---

## Image build

The image is named `dmac-assistant:poc` (currently `sha256:933d13b572...` at ~1.27 GB). It is `linux/amd64` and contains Python 3.14, `uv`, Claude Code (Node-based with native-binary wrapper), the `nextseek-api` plugin, and the vendored `chat_nextseek` Python source.

```sh
make sync-vendor-deps    # clone chat_nextseek pinned source into vendor/ (HTTPS, uses GH Keychain auth)
make image-build         # builds with Buildx, runs the drift guard, pins claude-code version
make image-stage         # stages plugin + docs into build_context/ (used by image-build)
```

The Dockerfile uses `uv sync --locked --no-dev` for the bridge package and `uv pip install --system` for the vendored chat_nextseek source. **`--system` must NOT appear in the final image build output** (a drift guard test catches re-introduction). Image rebuilds are deterministic given a pinned `chat_nextseek` SHA in `scripts/sync-vendor-deps.sh`.

See [`docs/bridge/`](docs/bridge/) for protocol-level documentation of the WebSocket contract and the `stream-json` event shape.

---

## Project status

| Plan | Status | Notes |
|------|--------|-------|
| **Plan A** — POC bridge + container + plugin shims | ✅ **Complete** (2026-05-01) | All 12 tasks merged + T11 manual smoke 13/13 ✅ |
| **Plan B** — production hardening, plugin swap-in, multi-user pooling | ⏳ Not started | Unblocked by Plan A closure |

### What Plan A delivered

- Authenticated WebSocket bridge with token-store + per-user Docker container start/stop
- Read-only project mounts + read-write per-user scratch + post-turn copier to host-side output
- Session resumption via `--session-id` / `--resume`
- Bedrock auth passthrough + NExtSEEK credential reuse from the chat-UI login
- Image build pipeline with vendored `chat_nextseek` and pinned Claude Code version
- Full integration test of the chat_ws round-trip including the file-set diff publish path
- Manual smoke validating all 13 production-readiness rows on the developer machine

### Known production-blockers (do not deploy as-is)

- **AWS Bedrock token exposure** — the in-container agent can exfiltrate `AWS_BEARER_TOKEN_BEDROCK` from its env. A containment plan was aborted at Phase 0 spike 0.2 (2026-04-24); two surviving pivot options (Bedrock proxy + short-lived STS) are tracked in the (private) `.claude/known-issues/bedrock-token-exposure.md` working file. **Solo-developer POC use only until this is resolved.**

### What is intentionally out of scope for the POC

The following are explicitly **not** part of Plan A and should not be added without an explicit task spec:

- Container pooling (today: one container per user per session; cold start each time)
- Bedrock token rotation / refresh
- Institutional SSO (today: a JSON `DMAC_USERS` catalogue)
- Retention management (today: never auto-cleans `<output_root>/<user_id>/`)
- Network egress whitelisting from the agent container

---

## Contributing

This is an internal MIT BMC project. External contributions are not currently accepted, but the code is MIT-licensed (see [`LICENSE`](LICENSE)) so feel free to read, fork, and adapt.

### When making changes

- Read [`dmac-assistant-sds.md`](dmac-assistant-sds.md) and [`dmac-assistant-adrs.md`](dmac-assistant-adrs.md) before architecture changes.
- For repo-internal contributors: read the (private) `.claude/known-issues/` directory before changes that touch authentication, secret handling, or the container surface.
- Use `uv add` / `uv add --dev` for dependencies — never edit `pyproject.toml` by hand and never use pip / poetry.
- The bridge uses `docker-py`, not subprocess wrappers around the Docker CLI.
- The full pytest suite must pass with `--cov-fail-under=95`.

### Commit conventions

- Plan-driven work uses commit prefixes like `feat: complete task-NN-<slug> [coverage: NN.NN%]`.
- Sweep / retro-amendment work uses `chore: ...`.
- Reviews and plans are kept under the (private) `.claude/` working tree and referenced by commit messages.

---

## License

MIT. See [`LICENSE`](LICENSE).

---

## Acknowledgements

Built on top of [Claude Code](https://github.com/anthropics/claude-code) by Anthropic. The DMAC Assistant bridge contributes plumbing — Claude Code does the heavy lifting inside the container.
