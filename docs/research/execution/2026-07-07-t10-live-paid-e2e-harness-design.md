# T10 — Live paid batch-upload E2E harness (design)

Authority: build plan `.claude/plans/nextseek-batch-upload-skill-build-2026-06-30.md`, task
`### T10 — Live paid E2E (Wave 8)`. This design records HOW T10 is built; the plan's Steps/Success
are the contract.

## System under test

The **local dmac-assistant stack**, NOT NExtSEEK. T10 drives the dmac bridge over the `/ws/chat`
WebSocket a lab user hits; the bridge spawns a real agent container (`dmac-assistant:poc`, which bakes
the batch-upload skill + the six `nextseek-*` shims — verified 2026-07-07) and runs a **paid Claude
Code turn** that reads the batch-upload `SKILL.md` and executes the shims to build + validate a
workbook. The batch-upload flow itself makes no paid inference; the money is the CC agent turn.

The NExtSEEK `step7d-greenfield` harness is a **rigor reference only** (owner directive 2026-07-07):
authoritative-cost-first ledger with `cost_source` provenance + estimate fallback, pre-call abort cap,
per-turn summary schema, committed reproduce command, "markdown is never proof", fresh-session +
invocation-proof checks. We mirror the discipline; we do not wire T10 to or test NExtSEEK.

Drive path (owner decision 2026-07-07): **through the bridge over WebSocket** (highest fidelity),
reusing the proven `tools/e2e/run_router_e2e.py` orchestration.

## Frame contract (what the WS surfaces — grounds every assert)

- `route_decided` `{type, route, model_class}` — the T10 turn must route `container_cc`.
- `tool_use` `{type, tool, input, id}` — the agent's tool calls; `tool=="Bash"` with
  `input.command` naming a `nextseek-*` shim is **invocation proof** the skill actually ran.
- `assistant_message` `{type, content}` — the reply (workbook path + validation verdict).
- `session_ended` `{type, session_id, usage, total_cost_usd}` — `total_cost_usd` is Claude Code's
  **authoritative** Bedrock cost (`cost_source="claude_code_result"`).

## Components (all committed)

1. `tools/e2e/batch_upload_live_evidence.py` — **pure logic, $0, hermetically unit-tested.** Route
   classification, `tool_use`→invocation extraction (basename-exact tokenization so `nextseek-api`
   never matches `nextseek-api-write`; skips `command -v`/`which`/`type`/`echo` argument-only
   mentions), cost extraction (authoritative `total_cost_usd` first; estimate fallback = aggregate
   `usage` × published Opus-4.8 rates, tagged `usage_estimate_on_timeout`, NEVER overriding a real
   >0 figure), reply extraction, fresh-session assertion, and `evaluate_turn` verdict taxonomy.
   Published rates + `PUBLISHED_RATE_TABLE_VERSION` stamp live here.
2. `tools/e2e/run_batch_upload_live_e2e.py` — **thin live driver, paid.** Reuses run_router_e2e's
   `_launch_bridge`/`_login`/`_wait_for_ready`/`_terminate_bridge`/`_build_child_env`; drives ONE
   batch-upload query over `/ws/chat`; `SpendLedger(session_cap_usd=cap)` with pre-call `reserve`
   (abort-before-exceed) then `record` from `session_ended.total_cost_usd`; writes the evidence
   bundle. Live-orchestration functions carry `# pragma: no cover` (plan's closed set only).
   `--paid` gate + `--cap 5.00` + host/stack preflight; refuses to spend without `--paid`.
3. `tools/e2e/verify_batch_upload_live.py` — **$0 committed verifier.** Recomputes the verdict + cost
   from the persisted transcript ONLY, confirms the summary matches, enforces "markdown is never
   proof" (bundle must carry the JSON transcript + ledger, not only prose), exits non-zero on any
   mismatch. This is the reproducible cross-session check.
4. `tools/e2e/test_batch_upload_live_evidence.py` — **hermetic tests, $0**, ≥95% coverage on the pure
   module + verifier (run with explicit `--cov=tools/e2e` per the CLAUDE.md `tools/` note).

## Evidence bundle → `evidence/batch-upload-e2e/<ts>/`

`live_e2e_transcript.json` (all WS frames + metadata), `per_turn_summary.json` (step7d-style verdict),
`ledger.jsonl` + `ledger_reconciliation.txt`, `SUMMARY.txt` (per-condition PASS/FAIL + cost block +
the verbatim reproduce command). The bundle dir is gitignored (plan convention); **durability comes
from the committed harness + verifier + reproduce command** — the ledger is re-derivable by re-running
the committed verifier over the transcript. (Open follow-up if the owner wants the bundle itself
committed: point `--evidence-root` at a tracked path.)

## Reproduce command (persisted in SUMMARY.txt)

```
# $0 hermetic self-tests (NOTE: dotted --cov module form — the slash/path form reports 0% under
# the repo's tools/ layout, per the CLAUDE.md tools-coverage gotcha):
env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tools/e2e/test_batch_upload_live_evidence.py \
  --override-ini "addopts=--disable-socket -q" \
  --cov=tools.e2e.batch_upload_live_evidence --cov=tools.e2e.verify_batch_upload_live \
  --cov-report=term-missing --cov-fail-under=95
# PAID live run (explicit per-session owner paid-API authorization + $5 cap):
uv run python tools/e2e/run_batch_upload_live_e2e.py --paid --cap 5.00
# $0 verify a persisted bundle:
uv run python tools/e2e/verify_batch_upload_live.py evidence/batch-upload-e2e/<ts>/live_e2e_transcript.json
```

## Live infra setup (deconflicted from the running NExtSEEK stack, 2026-07-07)

The dmac repo's `make proxy-up` hardcodes `container_name: dmac-bedrock-proxy`, which collides with a
running container of that name owned by the separate NExtSEEK integration stack
(`project=nextseek`, `~/step7d-greenfield/NExtSEEK`, image `nextseek-bedrock-proxy:latest`, on
`dmac-cc-net`). To avoid touching the running stack (owner directive), the T10 Bedrock proxy is a
distinctly-tagged image + distinctly-named container on its own network, carrying the `bedrock-proxy`
alias the bridge resolves:

```
docker build -f bedrock-proxy/Dockerfile -t dmac-bedrock-proxy:poc-t10 .
docker network create dmac-nextseek-net
docker run -d --name dmac-bedrock-proxy-t10 \
  --network dmac-nextseek-net --network-alias bedrock-proxy \
  --env-file bedrock-proxy/proxy-secret.env --restart unless-stopped \
  dmac-bedrock-proxy:poc-t10
# teardown:  docker rm -f dmac-bedrock-proxy-t10 && docker network rm dmac-nextseek-net
```

No image-name collision (dmac builds `:poc-t10`; the running proxy is `nextseek-bedrock-proxy:latest`).
The bridge attaches the agent to `dmac-nextseek-net` (config `sidecar_network` default) and injects
`ANTHROPIC_BEDROCK_BASE_URL=http://bedrock-proxy:8080` (config default), so the alias is what matters,
not the container name. The batch-upload skill does NOT use the NS shared-cred sidecar, so preflight
checks the Bedrock proxy on the network — not `_check_sidecar`'s NS-sidecar container.

## Sequence

Build (1)+(3)+(4) TDD ($0) → independent adversarial review → wire (2) → $0 preflight/dry-run to
resolve live stack wiring (agent→NS reachability for the validate call, router route) → **paid run
under $5 cap (confirm spend right before)** → independent Wave 8 review → merge decision.
