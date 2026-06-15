# DMAC Assistant

A lab-aware Claude Code agent for the [MIT BioMicro Center (BMC)](https://biomicro.mit.edu/). DMAC Assistant wraps a containerized [`claude`](https://github.com/anthropics/claude-code) CLI behind a thin FastAPI bridge so lab users can chat with an agent that knows their projects, their NExtSEEK sample catalog, and their pipelines — without ever opening a terminal.

> **Status**: Proof-of-concept. Plan A (containerized POC + bridge) and the Plan B `nextseek` plugin swap-in are complete; the remaining Plan B work (core production hardening + multi-user pooling) is the next milestone. See [Project Status](#project-status) for the full state.

---

## What this is

DMAC Assistant is **not** a custom agent framework. It is a deliberately small bridge around four load-bearing pieces:

1. **A FastAPI bridge** (`src/dmac_assistant/`) that authenticates lab users, resolves the project directories they're authorized to read, starts a per-user Docker container, and relays chat messages between a browser UI and Claude Code's `stream-json` output.
2. **A Docker image** (`dmac-assistant:poc`) that contains Claude Code, [`uv`](https://github.com/astral-sh/uv), the `nextseek` plugin, and the in-container agent instructions.
3. **Plugin and documentation surfaces** that the in-container Claude runtime reads from fixed paths inside the image — most importantly the NExtSEEK API documentation and the `nextseek` plugin (SKILL.md, CLI tools, and cached catalogs). The plugin reaches `chat_nextseek` over the network (via the sidecar / NExtSEEK); `chat_nextseek` is no longer installed inside the image.
4. **An offline reliability-analysis pipeline** (`src/dmac_assistant/eval/hibayes_runtime_reliability/`) that consumes the HiBayes-ready CSV emitted by `tools/hibayes/exporter.py` and produces per-task-family Bayesian posterior estimates of agent success probability, plus a self-contained HTML report. Runs inside a sibling Docker image (`hibayes-runtime-reliability:dev`) — see [Reliability analysis pipeline](#reliability-analysis-pipeline) below.

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
                                            │ │   --permission-mode       │ │
                                            │ │   auto                    │ │
                                            │ └─────────┬─────────────────┘ │
                                            │           │                   │
                                            │ Plugins:  ▼                   │
                                            │   nextseek (thin client)      │
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

Optional (bridge/sidecar-side only — **not forwarded to the agent container**): `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`. **`GCP_API_KEY` is required when the LLM router is on — which is now the default** (`DMAC_ROUTER_ENABLED` defaults to on; set it to a falsy value like `0` to fall back to the legacy single-path bridge, which makes `GCP_API_KEY` optional). The router uses Gemini Pro via BAML for route decisions; it is likewise not forwarded to the agent container. The shared backend credentials (`GCP_API_KEY`, `NEO4J_*`, `MYSQL_*`) live server-side on NExtSEEK; the agent reaches NExtSEEK through the sidecar, and `GCP_API_KEY` is needed only on the bridge host (for the router's BAML route decisions). See [LLM router](#llm-router).

---

## Repository layout

```
dmac-assistant/
├── baml_src/                  # Shared BAML source (router + e2e judges; dual codegen)
│   ├── clients.baml           # GCPReasoner client (gemini-3.1-pro-preview)
│   ├── generators.baml        # router_target + e2e_target codegen blocks
│   ├── router.baml            # RouteQuery function + route enums
│   ├── judge_router.baml      # JudgeRouterAnswer (router E2E harness)
│   └── judge_ui.baml          # JudgeUITranscript (UI walkthrough E2E)
├── src/dmac_assistant/        # FastAPI bridge
│   ├── app.py                 # Application factory + static UI mount
│   ├── auth.py                # Token store + identity model
│   ├── config.py              # Env-driven BridgeConfig
│   ├── containers.py          # docker-py wrapper, mount contract, env injection
│   ├── ws.py                  # /ws/chat WebSocket route + relay loop (+ router dispatch)
│   ├── run_tracker.py         # Per-turn scratch file-set snapshot
│   ├── copier.py              # scratch → output publish (M2-safe)
│   ├── streamjson.py          # claude stream-json parser
│   ├── sessions.py            # Most-recent-session lookup for --resume
│   ├── ns_adapter.py          # chat_nextseek JSONL → WS frame translator
│   ├── router/                # LLM router subsystem (flag: DMAC_ROUTER_ENABLED)
│   │   ├── agent.py           # RouterAgent (BAML wrapper, fallback policy)
│   │   ├── capabilities.py    # build_context/route_capabilities.json loader
│   │   ├── models.py          # model_class → Bedrock model-ID resolver
│   │   └── baml_client/       # Generated BAML Python client (coverage-excluded)
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
├── tools/                     # Non-shipping evidence/eval helpers (NOT in image)
│   └── hibayes/               # report.html → 14-column HiBayes-ready CSV exporter
├── vendor/                    # Pinned chat_nextseek source (gitignored)
├── docs/                      # Bridge protocol notes, ADRs, SDS
├── src/dmac_assistant/eval/   # Offline reliability-analysis pipeline (in-container)
│   └── hibayes_runtime_reliability/
│       ├── models.py          # Pydantic models + ReliabilityBand enum
│       ├── load_csv.py        # CSV → validated RuntimeEvalRow list
│       ├── process_runtime_reliability.py  # row list → per-family aggregates
│       ├── run_hibayes.py     # HiBayes inference + CLI entrypoint
│       ├── render_report.py   # Jinja2 → self-contained HTML report
│       ├── config/            # Default thresholds YAML
│       ├── templates/         # Jinja2 report template
│       └── README.md          # Pipeline usage + interpretation guide
├── Dockerfile.hibayes-eval    # Builds hibayes-runtime-reliability:dev image
├── scripts/run_hibayes_eval.sh  # Wrapper around `docker run hibayes-runtime-reliability:dev`
├── .coveragerc.in-container   # In-container coverage config (no eval omit)
├── dmac-assistant-sds.md      # Software Design Specification
├── dmac-assistant-adrs.md     # Architecture Decision Records
└── Makefile                   # image-build, image-stage, sync-vendor-deps, ingest-nextseek-docs, hibayes-eval-build, ...
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

Bridge coverage runs consistently above the 95% gate. At Plan A T12 closure (2026-05-01) the bridge subtree was at **98.89%**; subsequent additions (HiBayes runtime-reliability pipeline, LLM router subsystem, iter-02 residual-debt fixes) hold that bar via per-task `--cov-fail-under` checks at merge time. Two acknowledged low-priority gaps remain in `run_tracker.py` (an `OSError` race-condition guard for files that vanish between `os.walk` and `stat()`) and `copier.py` (an empty-string lexical guard in `_is_safe_relpath` that's unreachable from snapshot output). Both are unreachable in normal flow and tracked for follow-up. A few load-bearing router-subsystem surfaces (`ws.py::_chat_ws_router_on`, `ws.py::_get_router_agent`) carry explicit `# pragma: no cover` exceptions justified by their integration-test-only nature; see plan `## Coverage Exceptions` for the formal list.

The `build_tools/` sibling project has its own `pyproject.toml` and is run separately:

```sh
cd build_tools && uv run pytest
```

**Split-coverage model for `src/dmac_assistant/eval/`**. The reliability-analysis pipeline modules live under `src/dmac_assistant/eval/hibayes_runtime_reliability/` but their runtime dependencies (HiBayes, NumPyro, ArviZ, pandas, Jinja2, Matplotlib) live exclusively in the `hibayes-runtime-reliability:dev` image — they are not installed in the host bridge venv. Eval test files therefore use `pytest.importorskip` to skip cleanly on host. `pyproject.toml` carries `[tool.coverage.run] omit = ["src/dmac_assistant/eval/*"]` so the host-side gate measures the bridge subtree only. The eval modules are measured by an in-container gate that uses a separate config (`.coveragerc.in-container`, no omit) — see [Reliability analysis pipeline](#reliability-analysis-pipeline). Together the two gates cover the full `src/dmac_assistant/` tree without overlap.

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

The image is named `dmac-assistant:poc` (~1.35 GB; specific SHA rotates with each build — run `docker image inspect dmac-assistant:poc --format '{{.Id}}'` for the current digest). It is `linux/amd64` and contains Python 3.14, `uv`, Claude Code (Node-based with native-binary wrapper), the `nextseek` plugin (now a thin WebSocket/HTTP client), and the BAML-generated router client. `chat_nextseek` and `torch` are **no longer installed in this image** — they were removed (~3.6 GB saved, down from ~4.95 GB) when execution moved out of the agent container to the NExtSEEK sidecar; `vendor/chat_nextseek` is retained in the repo only for the bridge's host-side model-catalog default, not installed into the image.

```sh
make sync-vendor-deps    # clone chat_nextseek pinned source into vendor/ (HTTPS, uses GH Keychain auth)
make image-build         # builds with Buildx, runs the drift guard, pins claude-code version
make image-stage         # stages plugin + docs into build_context/ (used by image-build)
```

The Dockerfile installs all Python deps with `uv sync --locked` into an on-PATH venv (`/opt/dmac-venv`); the thin-client deps the runner needs (`websockets`, `httpx`) arrive that way. **`--system` must NOT appear anywhere in the Dockerfile** (a drift guard test catches re-introduction). The agent image no longer installs `chat_nextseek` — the plugin runner reaches it over the network via the sidecar (see [LLM router](#llm-router)); `make sync-vendor-deps` still clones the pinned source into `vendor/` for the bridge's host-side model catalog.

See [`docs/bridge/`](docs/bridge/) for protocol-level documentation of the WebSocket contract and the `stream-json` event shape.

---

## LLM router

A per-turn LLM router is inserted between the WebSocket bridge and Claude. For each user message, the router picks one of two execution routes:

- `nextseek_query` - dispatches the message to a thin in-image NExtSEEK runner that calls NExtSEEK's assistant API over the network; the deterministic `chat_nextseek` orchestrator pipeline runs server-side on NExtSEEK, not inside the agent container. Used for catalog/sample/study/lineage queries against NExtSEEK. Selected when the router classifies the message as a structured query.
- `container_cc` - runs Claude Code inside the same container with a router-chosen model class (`"opus"`, `"sonnet"`, or `"haiku"`). Used for everything else.

The router is controlled by **`DMAC_ROUTER_ENABLED`** and is **ON by default** (opt-out) as of 2026-06-15. Set `DMAC_ROUTER_ENABLED` to a falsy value (`0`/`false`/`no`/`off`/empty) to fall back to the legacy single-path bridge — byte-identical to the pre-router build (no router agent invocation, no `route_decided` frame, no per-turn exec - turns go to the long-lived Claude attach socket as before).

When the flag is on, the bridge emits one new optional WebSocket frame to the client BEFORE any `session_started` frame:

```json
{"type":"route_decided","route":"nextseek_query","model_class":null}
```

`model_class` is `null` when `route` is `"nextseek_query"`; for `"container_cc"` it is one of `"opus"`, `"sonnet"`, or `"haiku"`. The frame is OPTIONAL - it is emitted only when the router decides a route. The frame deliberately carries no `session_id` field (the routing decision is taken before any Claude session is started). See [`docs/bridge/ws-protocol.md`](docs/bridge/ws-protocol.md) for the full frame schema.

The router itself is a BAML Gemini Pro call (currently `gemini-3.1-pro-preview`) via `b.RouteQuery(...)` and needs a `GCP_API_KEY` environment value on the bridge host. When the router is disabled or the call fails, the bridge falls back to `route=container_cc, model_class=sonnet`.

An operator-facing E2E harness at [`tools/e2e/run_router_e2e.py`](tools/e2e/run_router_e2e.py) runs a 5-query routing-discriminator suite (pure-NS, pure-CC, ambiguous) against a locally-running bridge and emits a per-run manifest under `evidence/router-e2e/<run_id>/`.

For full design rationale and the locked architecture (10 design decisions, 16 task specs across 6 waves), see the LLM router specification at [`docs/superpowers/specs/2026-05-13-llm-router-design.md`](docs/superpowers/specs/2026-05-13-llm-router-design.md).

---

## Reliability analysis pipeline

An offline analysis tool, completely separate from the bridge runtime. It answers one question: **for each task family the headless agent ran, what is the posterior probability of runtime success, and how confident are we in that estimate?**

Inputs:
- A HiBayes-ready CSV produced by `tools/hibayes/exporter.py` from an evidence-aggregator `report.html` (one row per agent run, 14 fixed columns).

Outputs (all under `out/hibayes_runtime_reliability/`):
- `report.html` — self-contained HTML report with per-family posterior charts, HDI bars, observed-vs-posterior comparison, failure-mode counts, filterable results table.
- `task_family_aggregates.csv` — per-family observed counts and rates.
- `posterior_task_family_reliability.csv` — per-family posterior mean / median / 80% & 95% HDI / P(<0.90) / P(<0.80) / reliability band.
- `diagnostics.json` — HiBayes diagnostic suite (r_hat, ess_bulk, ess_tail, etc.).
- `config.resolved.yaml` — the thresholds + priors actually used.

```sh
# Build the eval image (one-time per HiBayes sha bump)
make hibayes-eval-build

# Generate the input CSV from an existing evidence-aggregator report
uv run --group tools python tools/hibayes/exporter.py \
    evidence/headless/<run>/report.html data/hibayes_eval_rows.csv

# Run the pipeline (wrapper handles the docker mounts)
scripts/run_hibayes_eval.sh python -m dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes \
    --input /work/data/hibayes_eval_rows.csv \
    --out /work/out/hibayes_runtime_reliability
```

See [`src/dmac_assistant/eval/hibayes_runtime_reliability/README.md`](src/dmac_assistant/eval/hibayes_runtime_reliability/README.md) for the full interpretation guide (what the posterior means, what the bands mean, how to extend with `tool_calls_total` / `cost_usd` / `is_opus` / `image` predictors later).

The pipeline is opt-in. Bridge users do not need it; reliability-evaluation operators do.

---

## HiBayes Evaluator Axes (2026-05)

The DMAC Assistant evaluation pipeline ships three new evaluation axes alongside the existing runtime-reliability axis. All four axes share a common HiBayes posterior schema (5-key wrapper + 9-field per-stratum) and render into a single combined HTML report.

### Pipeline

```
manifest.json
    │
    ├── Stage A (host) ──► hibayes_artifact_validity.csv
    ├── Stage B (host) ──► hibayes_functional_eval_inputs.csv (joins Stage A + runtime axis CSV)
    └── Stage C (host, BAML) ──► hibayes_functional_usefulness.csv + hibayes_review_sidecar.csv

Then:
    Stage D in-image fits (one per axis):
        runtime, artifact, functional → posterior.json files
    Then:
        combined HTML report
```

### Usage

```bash
make hibayes-axes
# Produces: 3 CSVs + 1 sidecar + 3 posterior.json + 1 combined.html
```

Individual stages are also addressable:

```bash
make hibayes-stage-a
make hibayes-stage-b
make hibayes-stage-c
make hibayes-eval-artifact
make hibayes-eval-functional
make hibayes-runtime-posterior-json
make hibayes-combined-report
```

### Stage A: tempdir-mode-vs-fixed-scratch manifest caveat (DD-25)

The Stage A CLI `--help` text and module docstring carry a verbatim warning (the canonical source is `DD25_TEMPDIR_WARNING` in `tools/hibayes/artifact_validator.py`). The README reproduces it byte-for-byte so the pinning test `test_readme_contains_verbatim_dd25_tempdir_warning` can enforce it:

> WARNING (locked DD-25): Running Stage A against a manifest emitted without `--scratch-dir` (tempdir-mode) will produce a `hibayes_artifact_validity.csv` in which every expected-artifact row is `Missing`, indistinguishable from real failure. Stage A cannot detect tempdir-mode-vs-fixed-scratch-mode from the manifest itself. Verify the upstream run used `--scratch-dir` before drawing inferences from a 100%-Missing Stage A CSV.

Important: the warning text inside the blockquote above MUST match `DD25_TEMPDIR_WARNING` character-for-character (no bold/italic, no smart quotes, plain backticks around `--scratch-dir`, `hibayes_artifact_validity.csv`, and `Missing`). If T1.1 ever edits the constant, this section must be updated in lockstep — the pinning test will fail otherwise.

See also: `tools/hibayes/` — `artifact_count` semantics caveat in [`.claude/CLAUDE.md`](.claude/CLAUDE.md) for the analogous warning on the runtime axis exporter.

### Stage A smoke gate

```bash
make hibayes-stage-a-smoke
```

Runs Stage A end-to-end inside `hibayes-runtime-reliability:dev` against the reference fixture (Linux base, no macOS Keychain).

### Live Stage C tests

The live test against `gemini-3.1-pro-preview` is gated behind `@pytest.mark.live`:

```bash
uv run pytest tools/e2e/tests/test_functional_evaluator_live.py -m live \
    --enable-socket \
    --override-ini="addopts=" \
    --override-ini="testpaths=tools/e2e/tests"
```

Cost envelope: ~9 API calls per local run; ~$0.001–$0.01 per run on the paid tier.

---

## Project status

| Plan | Status | Notes |
|------|--------|-------|
| **Plan A** — POC bridge + container + plugin shims | ✅ **Complete** (2026-05-01) | All 12 tasks merged + T11 manual smoke 13/13 ✅ |
| **HiBayes runtime-reliability pipeline** — offline posterior reliability analysis | ✅ **Complete** (2026-05-13) | All 8 tasks merged; Phase 7 round-4 reviewer PASS; split-coverage model formalized as Amendment 7 |
| **LLM router** — per-turn route selection between `chat_nextseek` and Container-CC | ✅ **Complete** (2026-05-18) | All 16 tasks merged (Wave 0–6); iter-02 independent Phase 7 reviewer PASS; controlled by `DMAC_ROUTER_ENABLED` (default ON as of 2026-06-15 — set falsy for the byte-identical legacy bridge); iter-02 residual debt closed in `fix/llm-router-residual-debt` (`dd34d6e`) |
| **HiBayes evaluator 2-axis expansion** — Stage A (artifact validity, deterministic) + Stage B (functional eval input CSV, deterministic) + Stage C (functional usefulness via BAML/Gemini-3.1-pro-preview) + combined tabbed HTML report | ✅ **Complete** (2026-05-27) | All 16 originally-planned tasks merged + 5 Phase-4 remediation tasks + task-17 combined-report rebuild + AM-001/AM-002/AM-003 amendments + 7 Phase-7 follow-up commits; both adversarial post-merge reviewer passes PROCEED; live Stage C green against gemini-3.1-pro-preview (103-query corpus, ~$1–10 per run); §8.3 Playwright MCP smoke green (3 tabs, 0 console errors, 8 plot PNGs + 6 Chart.js charts); locked design spec `hibayes-evaluator-expansion-design-2026-05-14.md` |
| **Plan B (nextseek plugin)** — swap `nextseek-api` → new `nextseek` plugin + D19 host-path reporting consumer | ✅ **Complete** (2026-05-06) | All waves merged to `main` (`adb54aa`); tasks B01–B17c closed (entity/parse/plan/api/graph/submission/report agents, SKILL.md, `/nextseek` command, permission allowlist, catalog snapshot, Dockerfile swap `5c517b5`, image-binding gate, B17c cred-leak mitigation); post-merge adversarial review ALL-PASS; SKILL.md consumes `DMAC_PATH_MAPPINGS` for container→host path translation |
| **NExtSEEK shared-credential sidecar** — move `chat_nextseek` execution + shared backend creds out of per-user agent containers | ✅ **Complete** (2026-06-14) | All tasks T0a–T18 + Amendments A-1…A-5 + T14 merged to local `main` (`6c89ca7`); Phase 7 independent cold-context adversarial reviewer PASS; hermetic suite 98.56%. Shared backend creds (`GCP_API_KEY`, `NEO4J_*`, `MYSQL_*`, `SESSION_DB_*`) now live server-side on NExtSEEK; agent containers no longer hold them. Agent image 4.95 GB → 1.35 GB; thin-client sidecar image 210 MB. The separate `AWS_BEARER_TOKEN_BEDROCK` exposure is unaffected and still open. Plan `nextseek-sidecar-build-2026-06-09` |
| **Plan B (remaining)** — core production hardening + multi-user pooling | ⏳ Not started | Two pieces remain: (1) AWS Bedrock token containment + output scrubber — B17c shipped only a stopgap cred-masking layer, the architectural fix is still open (see production-blockers below); (2) multi-user container pooling (today: one container per user per session). The NExtSEEK shared-credential exposure (a separate hardening item) is now contained — see the row above. |

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
