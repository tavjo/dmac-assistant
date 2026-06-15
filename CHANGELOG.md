# Changelog

All notable changes to this project are documented here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is pre-release so versions are dated rather than semver-numbered.

## [Unreleased]

### Changed — 2026-06-15 — LLM router enabled by default (opt-out)

The per-turn LLM router now defaults to **ON**. `ws._router_enabled()` returns true when `DMAC_ROUTER_ENABLED` is unset (opt-out); set `DMAC_ROUTER_ENABLED` to a falsy value (`0`/`false`/`no`/`off`/empty) to restore the legacy single-path bridge. This supersedes the original default-off behavior documented in the 2026-05-16 router entry below.

Rationale: with the router off, the bridge dispatched every turn through the legacy long-lived Claude attach socket, which runs Claude Code's **unpinned default model** (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`). After OI-3, that model is rejected by the Bedrock proxy allowlist (which permits only `us.anthropic.claude-opus-4-8`) with `403 path not permitted`, so no turn could complete; and the OI-4 `unrelated` route plus OI-5 `opus`-class pinning only take effect on the router path. Verified end-to-end through the chat UI: all three routes (`nextseek_query`, `container_cc`, `unrelated`) work with the router on (Container-CC runs the `opus`-class model `us.anthropic.claude-opus-4-8` through the proxy, all calls HTTP 200).

`GCP_API_KEY` is therefore **required by default** now (the router's BAML route-decision call via the Google `gemini-3.1-pro-preview` model). The `route_decided` frame is emitted by default.

- `src/dmac_assistant/ws.py` — `_router_enabled()` default flipped off → on (`os.environ.get("DMAC_ROUTER_ENABLED", "1")`).
- `tests/conftest.py` — autouse fixture pins `DMAC_ROUTER_ENABLED=0` for the legacy-path suite; router tests opt back in with `=1`.

### Changed — 2026-06-14 — NExtSEEK shared-credential sidecar + thin-client rewire

Removed shared institutional credentials from per-user agent containers. The agent container previously held `GCP_API_KEY`, `NEO4J_*`, `MYSQL_*`, and `SESSION_DB_*` in its process environment (exfiltrable by the in-container agent); they now live only on the bridge host (the router) and **server-side on NExtSEEK**, never in the agent container. This closes the NExtSEEK shared-credential exposure vector. (The separate `AWS_BEARER_TOKEN_BEDROCK` exposure remains open — see [Project status](README.md#project-status) production-blockers.)

Architecture changes:

- **Agent image slimmed 4.95 GB → 1.35 GB** — `chat_nextseek` and its `torch` / `sentence-transformers` dependency tree were removed from the agent image. The in-image `nextseek` plugin runner and the NS-route runner (`container/runner_ns.py`) are now thin clients; neither imports `chat_nextseek` in-process.
- **`chat_nextseek` runs server-side on NExtSEEK.** NS-route queries (`run_query` / `run_query_plan`) go through the NExtSEEK assistant viewset over HTTP. The 7 granular plugin operations (entity, parse, graph, api-read, api-write, report, generate-submission) route through a docker-compose **sidecar** over WebSocket, which forwards to NExtSEEK's native HTTP endpoints.
- **Sidecar is a thin HTTP forwarder** (image 210 MB). It holds only `NEXTSEEK_BASE_URL` + a staging directory — no backend credentials, no `chat_nextseek` runtime, no session store. Per-request user credentials travel as Basic-auth arguments, never via `os.environ`, eliminating a cross-user credential-bleed race.
- **Report artifacts delivered over authenticated HTTP** — granular report / submission outputs are downloaded from NExtSEEK and staged for the bridge to publish to the per-user output root.
- **`NEXTSEEK_MODE` is no longer injected** into the agent container; the classifier work it steered now runs server-side.

New files:

- `sidecar/` — docker-compose sidecar service: `app/server.py` (WebSocket server), `app/ops.py` (7-op dispatch), `app/ns_client.py` (NExtSEEK granular HTTP client), `app/granular_models.py`, `app/write_gate.py`, `app/contract.py`, `app/config.py`, `app/exceptions.py`, `app/staging.py`, `app/healthcheck.py`, plus `Dockerfile`, `docker-compose.yml`, and Make targets `sidecar-build` / `sidecar-up` / `sidecar-down`.
- `src/dmac_assistant/staging_sweep.py` — bridge-side sweep of the sidecar staging directory before the post-turn output snapshot.

Env contract changes:

- The 16 shared-credential keys (`GCP_API_KEY`, `NEO4J_*`, `MYSQL_*`, `SESSION_DB_*`) are removed from `_build_environment`; only `DMAC_PATH_MAPPINGS` (plus the AWS / NEXTSEEK basics) are forwarded to the agent container.
- New bridge-side vars `DMAC_SIDECAR_NETWORK` and `DMAC_SIDECAR_STAGING_ROOT`. The bridge attaches each agent container to the sidecar network with a fail-fast if the network is absent — `make sidecar-up` is required before any bridge run.

Plan: `nextseek-sidecar-build-2026-06-09` (tasks T0a–T18 + Amendments A-1…A-5 + T14, 6 waves; Phase 7 independent adversarial reviewer PASS; hermetic suite 98.56%). Authoritative spec: [`docs/superpowers/specs/2026-06-08-nextseek-shared-cred-sidecar-design.md`](docs/superpowers/specs/2026-06-08-nextseek-shared-cred-sidecar-design.md).

### Changed — 2026-05-20 — Consolidated `baml_src/`

Merged the two host-side BAML source trees (`src/dmac_assistant/router/baml_src/` and `tools/e2e/baml_src/`) into a single top-level [`baml_src/`](baml_src/). Both existing generated-client paths are preserved via dual `generator` blocks in `baml_src/generators.baml`:

- `router_target` (async) → `src/dmac_assistant/router/baml_client/` (checked in; Python imports unchanged)
- `e2e_target` (sync) → `tools/e2e/baml_client/` (gitignored; regenerated at image build)

The duplicate `retry_policy Exponential` and the two per-tree LLM client definitions were collapsed to one `GCPReasoner` client (`gemini-3.1-pro-preview`) used by `RouteQuery`, `JudgeRouterAnswer`, and `JudgeUITranscript`. The Dockerfile now `COPY baml_src/` and runs `baml-cli generate --from /app/baml_src` (both generators; no selective-generator CLI flag exists). Vendor `chat_nextseek` `baml_src/` is untouched.

### Fixed — 2026-05-18 — LLM router iter-02 Phase 7 residual debt

iter-02 independent Phase 7 reviewer flagged 5 low-severity residual items against branch `ultraplan/llm-router-2026-05-14` at `c1f4f5b`. Item 5 (unpushed commits) was resolved by the `main`-merge push. The remaining four were addressed on `fix/llm-router-residual-debt` and merged to `main` as `dd34d6e` (fix commit `0dff3df`). Reviewer report: [`.codex/reports/llm-router-independent-final-evaluation-2026-05-18-iter02.md`](.codex/reports/llm-router-independent-final-evaluation-2026-05-18-iter02.md).

Changes shipped:

- **CC route happy-path lifecycle now pinned**: `tests/integration/test_router_cc_route_real.py` previously accepted any terminal frame (`session_ended` OR `error`) as sufficient evidence that the real CC turn completed. Tightened to require `session_started` precede `session_ended` on the happy path. Error-only outcomes are still accepted (transient Bedrock failures), but the success path now proves the bridge<->container<->Bedrock<->stream-json pipeline actually traversed the full session lifecycle. Verified live against `dmac-assistant:poc` + Bedrock in 13.3s.
- **NS / CC session state independence documented**: `docs/bridge/README.md` gains a new `### NS and CC session state independence` subsection under `## Routing and model selection`. NextSEEK-query turns and Container-CC turns share one container but have independent session scopes; an NS turn followed by a CC turn does NOT thread an NS session id into CC's `--resume`. By-design, but previously undocumented. Pinned by `test_ns_cc_session_independence_documented` in `tests/unit/test_docs_router_invariants.py`.
- **`router_decision` log-record visibility surfaced in Troubleshooting**: `docs/bridge/README.md` Troubleshooting section gains a bullet for operators searching for routing telemetry. The `router_decision` record is at INFO level on `dmac_assistant.router.agent`; uvicorn's default `--log-level error` (and the E2E harness) silences it. The bullet points to the `--log-level info` remediation. Pinned by `test_router_decision_visibility_in_troubleshooting`.

### Added — 2026-05-18 — `DMAC_E2E_PROJECT` env override

`tools/e2e/run_router_e2e.py` no longer hardcodes the synthetic-user project label `"proj-a"`. The new `_synthetic_project()` helper reads `DMAC_E2E_PROJECT` from the environment with `"proj-a"` as the default, so multi-user deployments where `proj-a` is not in the bridge project allowlist can override without editing the script. Empty-string env values fall back to the default (operator-typo defense). Pinned by 3 unit tests in `tests/unit/test_e2e_project_override.py`. Part of the iter-02 residual-debt closeout (see Fixed entry above).

### Added — 2026-05-18 — HiBayes evaluator expansion (Stages A/B/C/D + combined report)

Added three new HiBayes evaluator axes alongside the existing runtime-reliability axis. The four axes share a common posterior schema (DD-41 nested wrapper) and render into a single combined HTML report.

- **Stage A — Artifact Validity** (`tools/hibayes/artifact_validator.py`): deterministic GEO `.xlsx` / nf-core CSV / SVG validation against the locked DD-17/18/19/20 rule set. CLI `--help` carries the verbatim DD-25 tempdir-mode warning per DL-014.
- **Stage B — Functional Eval Input CSV** (`tools/hibayes/functional_inputs.py`): deterministic merge of manifest + runtime + Stage A artifact CSV + per-query record.json into a 12-column input CSV.
- **Stage C — Functional Usefulness** (`tools/e2e/functional_evaluator.py`): BAML/Gemini judge with three sequential calls per query and per-field aggregation; emits both the 12-column usefulness CSV and the 12-column review sidecar per DD-43.
- **Combined HTML Report** (`src/dmac_assistant/eval/hibayes_combined_report/`): page-level Jinja2 template `{% include %}`-ing each axis's section partial; partial-failure render on missing axis.

New Make targets: `hibayes-stage-a`, `hibayes-stage-b`, `hibayes-stage-c`, `hibayes-eval-artifact`, `hibayes-eval-functional`, `hibayes-runtime-posterior-json`, `hibayes-combined-report`, `hibayes-axes`, `hibayes-stage-a-smoke`.

Plan: [`.claude/plans/hibayes-evaluator-expansion-build-2026-05-15.md`](.claude/plans/hibayes-evaluator-expansion-build-2026-05-15.md).

### Added — 2026-05-16 — LLM router subsystem

Per-turn LLM router inserted into the WebSocket bridge. For each user message, the router picks one of two execution routes: `nextseek_query` (deterministic `chat_nextseek` pipeline running inside the long-lived `dmac-assistant:poc` container via `docker exec`) or `container_cc` (in-container Claude Code with a router-chosen model class — `"opus"`, `"sonnet"`, or `"haiku"`). The router is flag-gated by `DMAC_ROUTER_ENABLED`; with the flag unset or falsy, bridge behavior is byte-identical to the pre-router build. Plan: `llm-router-2026-05-14` (16 tasks, Wave 0–6, Phase 4 round-4 reviewer UA across all specs).

User-observable contract changes:

- **New optional WS frame `route_decided`** — emitted to the client BEFORE `session_started` whenever the router decides a route. Schema: `{type: "route_decided", route: "nextseek_query" | "container_cc", model_class: "opus" | "sonnet" | "haiku" | null}`. The frame carries NO `session_id` field (locked DD-09). `model_class` is `null` for the `nextseek_query` route. Clients that do not recognize the frame type render it harmlessly via the existing `default:` case in the frontend frame switch (T0.1 pinning test confirms this).
- **New `tool_use` namespace `ns:*`** — when the router picks `nextseek_query`, the chat_nextseek orchestrator's per-step events are surfaced as `{"type":"tool_use","tool":"ns:<agent>","input":...}` frames. Existing clients render the `tool` value verbatim with no allowlist.
- **New bridge-side env var `GCP_API_KEY`** — required when `DMAC_ROUTER_ENABLED=1`. Consumed by the BAML `GCPReasoner` client that drives the router's route-decision call (the Google `gemini-3.1-pro-preview` model).
- **New per-exec env contract for in-container runs** — the bridge now explicitly sets `API_USER`, `API_PASS`, `NEXTSEEK_BASE_URL` (and `NEXTSEEK_MODE=gcp` + `NEO4J_DATABASE` for the NS route only) when invoking `docker exec` for each turn. The entrypoint env-translation path is bypassed because per-turn exec does not run the entrypoint.
- **New container startup mode `DMAC_RUNTIME_MODE`** — supports `idle` (long-lived container, no Claude process running until a `docker exec` arrives) in addition to the legacy default (`agent`, container starts Claude immediately). The router uses idle mode by default since per-turn exec is the dispatch model.

New files:

- `src/dmac_assistant/router/` — bridge-side router package (BAML scaffold, `RouterAgent`, capability registry loader, model-class map).
- `src/dmac_assistant/router/baml_client/` — generated BAML Python client (Pydantic models + `RouteQuery` call site). Coverage-excluded per plan `## Coverage Exceptions` (generated code).
- `src/dmac_assistant/ns_adapter.py` — pure function `ns_event_to_frames(event, *, session_id, event_index)` that translates chat_nextseek JSONL events to WS frames.
- `container/runner_ns.py` — in-image Python sidecar that runs `chat_nextseek.orchestrator.run_query(...)` per NS turn and emits JSONL events on stdout.
- `build_context/route_capabilities.json` — per-route capability/task-family registry (loaded by `RouterAgent`).
- `build_context/router_model_class_map.json` — Bedrock model-ID resolution for the three Anthropic model classes (BAML enum aliases `"opus"`/`"sonnet"`/`"haiku"`).
- `tools/e2e/run_router_e2e.py` — operator-facing WS-client headless harness; runs a 5-query routing-discriminator suite (pure-NS, pure-CC, ambiguous) and emits a per-run manifest at `evidence/router-e2e/<run_id>/`.
- `tests/unit/router/`, `tests/unit/test_docs_router_invariants.py`, `tests/integration/test_router_*.py` — full test suite + this docs pinning suite.

Modified files:

- `pyproject.toml` — `baml-py` specifier changed from `>=0.222.0` to `~=0.222.0` (atomic `uv add` per plan DD-13).
- `src/dmac_assistant/ws.py` — `chat_ws` now performs per-turn dispatch when `DMAC_ROUTER_ENABLED=1`; emits the optional `route_decided` frame; dispatches to `_dispatch_cc_turn` or `_dispatch_ns_turn` depending on the route. Flag-off path is unchanged.
- `src/dmac_assistant/containers.py` — `BridgeAttachSocket` extended with `read_event_line()` for the per-turn exec stream.
- `container/entrypoint.sh` — adds the `DMAC_RUNTIME_MODE=idle` branch (legacy default unchanged).

BAML enum:

The router's route decision uses two BAML enums. The runtime contract on the wire is the lowercase `@alias` strings (`"nextseek_query"` / `"container_cc"` for `Route`; `"opus"` / `"sonnet"` / `"haiku"` for `ModelClass`); the BAML-generated Python enum identifiers (`NextseekQuery`, `ContainerCC`, `Opus`, `Sonnet`, `Haiku`) are internal to the router package.

CLI:
```sh
# Operator-facing E2E harness (5 routing-discriminator queries):
uv run python tools/e2e/run_router_e2e.py \
    --output-base evidence/router-e2e \
    --bridge-port 8001 \
    --queries tools/e2e/router_discriminators.json
```

Coverage:

- Host pytest gate: full unit + integration suite passes with `--cov-fail-under=95` on the `src/dmac_assistant/` subtree (router package included).
- Generated BAML client at `src/dmac_assistant/router/baml_client/` is excluded under plan `## Coverage Exceptions`.
- `tools/e2e/run_router_e2e.py` runs in a subprocess and is exercised by a wrapper test under `tests/integration/`; coverage on the tool itself is informational only (no `--cov-fail-under` threshold per T5.1 round-2 finding F-T5.1-2-1, which documented that pytest-cov 7.1.0 dropped auto-`.pth` subprocess instrumentation).

### Added — 2026-05-13 — HiBayes runtime-reliability analysis pipeline

Offline analysis tool that consumes the HiBayes-ready CSV emitted by `tools/hibayes/exporter.py` and produces per-task-family Bayesian posterior estimates of agent success probability. Output: self-contained HTML report plus CSV/JSON artifacts under `out/hibayes_runtime_reliability/`. Plan: `hibayes-runtime-reliability-2026-05-09` (8 tasks, Wave 1–5, Phase 7 round-4 reviewer PASS).

New files:
- `src/dmac_assistant/eval/hibayes_runtime_reliability/` — pipeline source (models, loader, aggregator, HiBayes runner + CLI, HTML renderer, packaged config + Jinja2 template, in-tree README).
- `Dockerfile.hibayes-eval` — builds the sibling `hibayes-runtime-reliability:dev` image (HiBayes installed via pinned git SHA).
- `scripts/run_hibayes_eval.sh` — wrapper around `docker run hibayes-runtime-reliability:dev` with the canonical mount contract.
- `.coveragerc.in-container` — in-container coverage config (no eval omit; used by §6.2/§6.3 task-07 gates).
- `tests/unit/eval/`, `tests/integration/test_hibayes_pipeline.py`, `tests/fixtures/hibayes_runtime_reliability/` — full test suite (98% in-container package coverage on the eval modules).
- `Makefile`: `hibayes-eval-build` target.

CLI:
```sh
uv run python -m dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes \
    --input <hibayes_eval_rows.csv> --out <output_dir>
```

### Changed — 2026-05-13 — Split-coverage model for the host pytest gate

`pyproject.toml` now carries `[tool.coverage.run] omit = ["src/dmac_assistant/eval/*"]` so the host-side coverage gate measures the bridge subtree only. The eval pipeline modules cannot be exercised on the host venv (their runtime deps live exclusively in the `hibayes-runtime-reliability:dev` image, per DD-13) — their `pytest.importorskip` guards make them skip cleanly host-side. Coverage for those modules is enforced inside the container at ≥95% via the §6.2/§6.3 gates referencing `.coveragerc.in-container`. Together the two gates cover the full `src/dmac_assistant/` tree without overlap. Formalized as plan Amendment 7.

Host-side gate (post-change): **98.84% on 1464 statements**, 624 passed.
In-container gate (post-change): **98% on 520 statements**, 122 passed, 0 failed.

### Notes

Plan A (POC bridge + container + plugin shims, completed 2026-05-01) is documented in the plan files under `.claude/plans/` (gitignored). The original Plan A merge predates this changelog; entries here begin with the 2026-05-13 hibayes pipeline merge.
