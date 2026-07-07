# Porting the batch-upload skill to the integrated dmac-assistant-on-NExtSEEK stack — gap list

**Status: DEFERRED — do not start until the batch-upload skill is proven working here (T10 live paid
E2E green) and `feat/nextseek-batch-upload-skill` has merged.** This document exists so a later
session can execute the port without re-deriving the analysis. All claims below were grounded
2026-07-07 by read-only scouts against the integrated stack at
`~/step7d-greenfield/NExtSEEK` (branch `feat/dmac-assistant-full-integration`, HEAD `f093325`);
re-verify file:line anchors against that repo's current state before acting — it moves.

## What is being ported

The `nextseek-batch-upload` skill from this repo's `build_context/plugins/nextseek/`:
`skills/nextseek-batch-upload/SKILL.md`, the six shims (`nextseek-project-resolve`,
`nextseek-sampletype-attrs`, `nextseek-sample-search`, `nextseek-assay-resolve`,
`nextseek-build-payload`, `nextseek-validate-upload`), and the four modules
(`_batch_upload_runner.py`, `_batch_upload_client.py`, `_batch_upload_payload.py`,
`_batch_upload_extract.py`). Target: the integrated stack's agent image built from
`docker/cc-runtime/Dockerfile`, whose plugin tree is the git-tracked snapshot
`docker/cc-runtime/build_context/plugins/nextseek/`.

**Sequencing trap:** that snapshot was ported verbatim from an OLD dmac commit (`a429f13`,
`Dockerfile:1-16`). Cut the port from THIS branch's `build_context` **after** T10 passes and the
branch merges — otherwise you port a pre-hardening version of the skill.

## What ports with zero change (verified against their code)

- **Env contract matches exactly.** Their agent gets the user's own login per-request as
  `NEXTSEEK_USERNAME`/`NEXTSEEK_PASSWORD` AND `API_USER`/`API_PASS` (`cc_engine.py:266-272`, their
  I-9 rule — the agent is NOT fully de-credentialed), plus `NEXTSEEK_URL`/`NEXTSEEK_BASE_URL`
  loopback-rewritten to `http://nextseek_nginx` (`cc_engine.py:219-281`). Our
  `BatchUploadClient.from_env` reads exactly those names with the same NEXTSEEK-first precedence
  (DD-09). Works unmodified.
- **API surface is native there.** `POST /nextseek_api/batch-upload/validate/` (multipart file
  mode, `checks` ⊆ {structure,name_check,dag}, `batch_upload/views.py:405-434`) is confirmed
  side-effect-free in their code (`mutate_project_links=False`, pipeline stops before INSERT —
  `validation.py:179-190`, `orchestrator.py:183-184`). advanced_search, `/assays/`,
  `/projects/{id}/`, sample_types: same routes our client already calls. The agent's dual-homed
  nginx is its one route into NExtSEEK and covers all of them.
- **Workbook delivery is free.** Their CC turn path diffs the agent's `/data/scratch` after each
  turn and publishes any non-`raw/` file to `output/artifacts/<turn_id>/`, downloadable via the
  authenticated `GET /nextseek_api/cc-assistant/artifacts/{session}/download?key=...`
  (`cc_engine.py:871-938`, `services/cc_assistant.py:578-621`). Our runner promotes the workbook to
  `/data/scratch` — same contract, no server-side change needed. (The ChatSession bundle-registration
  mechanism is NOT needed and NOT reachable from the CC path; it serves only the two chat_nextseek
  ops.)
- **Write-safety + permission posture.** The SKILL.md Forbidden-Actions contract (never
  `batch-upload/start/`) travels with the files; their turns run the same `--permission-mode auto`
  with a trusted-NS-API `autoMode.environment` entry (`cc_engine.py:307-335`).

## The gaps (the actual port work)

1. **Image Python deps — the one hard gap.** Their agent image (deps from
   `docker/cc-runtime/pyproject.toml` + `uv.lock`, installed via `uv sync --locked
   --no-install-project`, `Dockerfile:92-95`) has `httpx` but **no `orjson`, `polars`, `fastexcel`,
   or `xlsxwriter`** (absent from `uv.lock` entirely; the `tools` group holding openpyxl/pandas is
   not installed by default either). Our four modules need all four. Fix: add them to that
   pyproject, `uv lock`, rebuild. This is the only image-level change.
2. **Plugin files + three config surfaces.** Copy the skill dir, six shims, and four modules into
   `docker/cc-runtime/build_context/plugins/nextseek/`; then update (a)
   `.claude-plugin/plugin.json` (currently describes only the 8 chat ops), (b) the baked
   `/app/CLAUDE.md` instruction surface (`container/CLAUDE.md` there), and (c) — easy to miss —
   the **L1 allowlist `scripts/setup.sh`** their `entrypoint.sh` runs at boot: without adding the
   six new shim commands, auto-mode will prompt/deny every batch-upload Bash call.
3. **Routing.** No batch-upload route exists. Their router is dmac's BAML `RouterAgent`
   (`cc_assistant/router.py:175`, BAML-first with a keyword `_heuristic` fallback at `:105-130`).
   "Prepare a batch upload sheet" would *plausibly* classify `container_cc` (the agentic/file-I/O
   route per `route_capabilities.json`), but the heuristic fallback has no "upload"/"sheet"
   patterns and NS keywords ("samples", "project") could pull it to the NS route. Options: add
   batch-upload phrasing to `route_capabilities.json`, extend the heuristic CC patterns, or drive
   via the force-CC endpoint (`cc/query/async/` → `_start_task(force_cc=True)`,
   `services/cc_assistant.py:456`).
4. **Per-turn limits are tighter there — verify before relying on the fused step.** Defaults:
   `NEXTSEEK_CC_MAX_BUDGET_USD` = **$2.00** (vs our $10 bridge default / $5 T10 cap) and a
   **hard-capped 180s wall clock** (`_TIMEOUT_HARD_MAX`, `cc_engine.py:70-74`; watchdog
   force-removes the container). The skill is naturally multi-turn (confirmation flow), so most
   turns are short, but the fused build-validate step paginates the full assay map (~47 pages on
   their data) — the 180s ceiling is the thing to load-test; raising it is a code change, not an
   env var.
5. **Acceptance rigor (optional but recommended).** Their step7d per-op harness takes a new op
   cleanly (a `BIN_OPS` entry + a locked `OP_QUERIES` question in
   `nextseek_api/cc_assistant/scripts/step7_gate3d_per_op.py`); our hermetic unit tests + the
   pinned-fixture/pin-registry gates would need adapting into their test tree to carry the same
   non-gameable guarantees. Largest optional chunk.
6. **Transport uniformity (deliberate divergence, not a defect).** Their 7 chat ops route
   agent → WS sidecar (`nextseek-sidecar:8765`, creds inside frames); our batch-upload client does
   direct REST with the user's own env creds. Direct-REST is architecturally sanctioned there
   (I-9; their plan/query path also does direct HTTP from the agent), so keep it as-is for the
   port. If they later want sidecar uniformity, that's a separate redesign — do not fold it into
   the port.

## Estimated size

S/M: items 1–2 are a focused day with their build; 3–4 are small but need their owner's judgment;
5 scales with how much of the rigor you want to carry over.
