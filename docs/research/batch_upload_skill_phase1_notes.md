# Phase 1 — Constraints notes: NExtSEEK batch-upload payload-builder skill

> scout Part 1 / Phase 1 internal working notes. Read-only research; no project file mutated.
> Date: 2026-06-25. Author target repo: `dmac_assistant`. Companion HTML report:
> `docs/research/nextseek_batch_upload_skill_findings_and_decisions.html`.
> (Distinct from the unrelated `phase1_constraints_notes.md` left by the stack-merge scout.)

## 0. The ask (verbatim intent, distilled)

Build a **skill for the in-container Claude Code agent ("container CC")** that:
- Uses the NExtSEEK **batch-upload** code/endpoints to **build create/update payloads** for samples.
- Must **NOT** write/update records in the DB. Doing the upload/update (`start/`) is **explicitly forbidden**.
- **MUST** call the read-only **`validate`** endpoint before returning the payload to the user.
- Preliminary steps **MUST** include read-only API calls to fetch the **attribute list of the sample type(s)**.
- Must encode the **UID rule**: leave UID **blank** for new samples; **include** UID when updating an existing one.
- Inputs come from **the user** (chat) **or** the **mounted Dropbox directory**.
- Is **NOT a full curation skill** — a simple payload-builder.
- Ends fully **wired in and LIVE** with **live E2E tests via the bridge against the dev server** — "no gotchas."

## 1. Confirmed project goals (this project = dmac_assistant)

- dmac_assistant wraps Claude Code as the agent runtime for MIT BioMicro Center lab users. Thin FastAPI bridge
  → per-user Docker container running `claude` → relays stream-json. (`.claude/CLAUDE.md`)
- Per-turn LLM router chooses an in-container route:
  - `container_cc` — general agent work; CC runs with the baked `nextseek` plugin. **The new skill rides here.**
  - `nextseek_query` — thin server-side read-only NExtSEEK query pipeline (`runner_ns.py` → assistant API).
  - `unrelated` — canned reply, no container.

## 2. Confirmed architecture (as built)

- **In-container skill mechanism**: ONE plugin baked into image `dmac-assistant:poc` = `nextseek`, at
  `/app/plugins/nextseek/` (Dockerfile:40 `COPY build_context/plugins/nextseek/ /app/plugins/nextseek/`).
  `container/entrypoint.sh:78-88` symlinks `/app/plugins/*` → `~/.claude/plugins/local/*` so CC auto-discovers
  `skills/<name>/SKILL.md`. **No marketplace.json / enabledPlugins / settings edits needed** — a new skill =
  new `skills/<name>/SKILL.md` (+ optional `bin/`) under `build_context/plugins/nextseek/`.
- **bin tools on PATH** via Dockerfile:118 `ENV PATH="/app/plugins/nextseek/bin:${PATH}"`. Existing tools:
  `nextseek-query`, `nextseek-api-read`, `nextseek-api-write`, `nextseek-entity-extract`, `nextseek-parse`,
  `nextseek-plan`, `nextseek-graph`, `nextseek-report`, `nextseek-generate-submission` (+ shared `_*.py` libs).
  **No batch-upload / validate / sample-type-attribute tool exists yet.**
- **Read-only API tool precedent**: `nextseek-api-read` is allowlist-gated by `assistant/read_safe_endpoints.json`.
  Allowlist = `samples/advanced_search` (POST), `samples/ experiments/ projects/ sample_types/ assays/` (GET).
  It **permits `sample_types/` (GET)** but NOT `sample_types/{uid}/` (the attribute-bearing retrieve) and NOT
  `batch-upload/validate/`.
- **Write-safety model** (3-layer, `nextseek` SKILL.md:139-216): CC permission allowlist + internal denylist +
  behavioral confirmation gate. `nextseek-api-write` requires strict-boolean confirmation; write-gate runs
  server-side in the sidecar (`sidecar/app/write_gate.py`).
- **Containment background (load-bearing)**: agent container holds only the user's NExtSEEK login + Bedrock token;
  shared backend creds are server-side on NExtSEEK. Per-turn CC runs under `--permission-mode auto`. Bedrock-token
  exfil (OI-3) is the standing production-blocker (deferred for solo-dev POC). New skill must not regress containment.

## 3. The NExtSEEK API surface ("batch upload code and all its endpoints")

> Source: `work/BMC/NExtSEEK` (`origin/dev` CONFIRMED has `validate`) + integration worktree
> `work/BMC/nextseek-worktrees/dmac-integration` (`integration/dmac-assistant`, HEAD `5fb3635`, 2026-06-25).
> All routes under `/nextseek_api/`.

- **Create AND update = one endpoint**: `POST /nextseek_api/batch-upload/start/` (`batch_upload/views.py:160`).
  JSON `{rows:[InputRowModel], project_id, update_existing, neo4j_only, person_id, config_overrides}` OR multipart
  `.xlsx`. Async (Celery) → `202 {job_id, status:"queued"}`. **FORBIDDEN for the skill.**
- **VALIDATE (read-only) = `POST /nextseek_api/batch-upload/validate/`** (`batch_upload/views.py:405`, CONFIRMED
  on `origin/dev`). Runs through TRANSFORM, **stops before INSERT**, no Celery, no DB write.
  - Request: same two modes (`rows` wins) + `project_id` (**required**) + `checks` (⊆ `{structure,name_check,dag}`,
    default `structure`).
  - Response `ValidationResult` (`batch_upload/models.py:843-866`): `{valid:bool, summary:str, errors:[...],
    error_groups:[...], totals:{...}, checks_run:[...], checks_skipped:[...], job_id:null, summary_path:null}`.
  - `BatchUploadError` = `{type, message, row, uid}`. `valid = (no errors) and (totals.error is None)`.
  - Checks: `structure` = every `json_metadata` key is a defined attribute for the SampleType; `name_check` =
    flags rows whose Name already exists (accidental duplicate creation); `dag` = parent-reference cycles.
- **Sample-type attributes (read-only)**: list = `GET /nextseek_api/sample_types/` (`services/sample_types.py:88`);
  one type **with attributes** = `GET /nextseek_api/sample_types/{uid}/` (`services/sample_types.py:114`),
  `data.attributes` carries SEEK `sample_attributes` (title/base_type/required/pos/unit/is_title). Internal source
  for the validate `structure` check is a DB query `prefetch_sample_type_attributes` (`batch_upload/prefetch.py:211`).
- **Auth**: Token / CSRF-exempt-session / HTTP-Basic; `IsAuthenticated`.
- **Assistant native ops** (`services/assistant.py`): `entity/parse/graph/api-read/api-write/report/
  generate-submission`. **NONE wrap batch-upload/validate.** `generate-submission` = **publication** submissions
  (GEO/SRA/PRIDE) — a DIFFERENT artifact from sample batch-upload payloads. Do NOT conflate (memory warns).

## 4. The UID rule + payload format (documented in work/BMC)

- **UID field is literally `UID`** (Samples-sheet col 0; `UID` key in `json_metadata`; `SampleType::UID` in
  Instructions). Blank/whitespace → `None` → NEW (server auto-generates `{PREFIX}-{YYMMDD}{LAB}-{n}`). Present →
  UPDATE iff `update_existing=true`, else SKIP. UID col must equal `json_metadata.UID` (`InputRowModel`
  validator, `batch_upload/models.py:227-244`).
  - Docs: `DMAC_docs/gitbook/03-uploading.md:38-43`; `dmac-curation-tools/docs/curation-reference.md` Rule 4.3
    (716-720): blank for new, populated for existing, UID column must be first.
  - **Update data-loss caveat** (`03-uploading.md:41`): updating via a **Sample/Assay sheet** requires **ALL**
    attributes — omitted ones are **removed**. The flat-row API path supports partial "UID-only update"
    (`wave3_update_mode.xlsx` fixture). So partial-vs-full hinges on the chosen format → a real decision.
- **Two payload shapes** (validate/start accept both): **4-sheet workbook** (`Instructions/Samples/Ontology/Assay`
  — the human "Sample Sheet" BMC uploads via the NExtSEEK UI, UID col first), and **flat rows** → `InputRowModel`
  (`{UID, SampleType, json_metadata(JSON string), assay_ids[], project_id, study_*}` — the programmatic shape).
- **Parent field**: UID if parent already uploaded, else Name; multiple parents semicolon-separated.
- **Attributes are DB-defined per type — NEVER invent** (curation-reference Rule 4.2, 703-705). Fetch them.

## 5. Existing toolkit (reuse candidate) — dmac-curation-tools

- `work/BMC/dmac-curation-tools/src/dmac_curation/` has a COMPLETE payload toolkit: `workbook.py`,
  `attributes.py` (`get_sampletypes`/`save_attributes`), `uid_propagation.py`, `schemas/sample_types.py`, plus
  Claude skills `validate-workbooks`, `propagate-uids`. BUT it runs **host-side against a direct DB connection**,
  not in-container against the HTTP API, and is a **separate repo**. User wants a **simple** skill, NOT full
  curation → reuse is a decision. Most valuable as a *rules reference*, less so as code to vendor.

## 6. The bridge + live E2E path

- Bridge `src/dmac_assistant/ws.py` `/ws/chat`; router ON by default (ws.py:822-836). `_dispatch_one_turn`
  (ws.py:1019-1106) → `container_cc` runs `exec_cc_turn` (CC agent + plugin).
- Routes: `baml_src/router.baml` (enum) + `build_context/route_capabilities.json` (registry the LLM sees —
  currently only `nextseek_query` + `container_cc`; `unrelated` is prompt-induced). Make payload-building reach
  `container_cc` by adding a task family there (no code/image change), and keep it out of `nextseek_query`.
- **Live E2E "via the bridge"** = `tools/e2e/run_router_e2e.py` (boots a real uvicorn bridge, talks WS like the
  UI; asserts route_match + BAML semantic judge). NS target precedence `DMAC_E2E_NS_URL` → `NEXTSEEK_URL` →
  `http://localhost:8000`; localhost → `host.docker.internal`. Dev server = `https://nextseek-dev.mit.edu`
  (`.env.dev:15`); back up 2026-06-25, may need VPN (`run_router_e2e.py:222-229`). `_check_ns_target_reachable`
  fails fast if dead. New case = `DISCRIMINATORS` tuple + corpus entry (or sidecar-level artifact harness).
- **Cost**: a live CC turn uses Bedrock (paid). `validate` itself is free/read-only. Paid-inference E2E needs
  explicit per-session authorization (standing rule) → surfaced as a decision.

## 7. What is already DECIDED (do NOT re-ask)

| Area | Decision | Source |
|---|---|---|
| Route | Skill rides `container_cc` (CC runs skills) | user prompt |
| Write safety | Upload/update (`start/`) FORBIDDEN; skill read-only toward DB | user prompt |
| Mandatory step | Skill MUST call `validate` before returning payload | user prompt |
| Mandatory step | Skill MUST fetch sample-type attribute list (read-only) first | user prompt |
| UID semantics | Blank UID = new; UID present = update | user prompt + curation-reference 4.3 |
| Scope | Simple payload-builder, NOT full curation | user prompt |
| Inputs | From the user (chat) OR the mounted Dropbox dir | user prompt |
| Acceptance | Live E2E via the bridge against the dev server; fully wired/LIVE | user prompt |
| Validate exists | `POST /nextseek_api/batch-upload/validate/` IS on `origin/dev` | git grep origin/dev views.py:405 |

## 8. What remains genuinely OPEN (→ MCQs in the report)

1. **Payload output format** (BLOCKER) — flat JSON rows vs 4-sheet xlsx vs flat xlsx vs both.
2. **Delivery channel** (BLOCKER) — chat inline vs scratch file vs Dropbox-publish. Collides with unbuilt copier.
3. **Read-only API-call mechanism** (BLOCKER, arch) — new read-only bin tools vs extend `nextseek-api-read`
   allowlist vs bake SchemaRAG `nextseek-api` plugin. `validate` is a read-only POST vs "POST=write=gated".
4. **Update-mode attribute handling** (BLOCKER, data-safety) — partial vs fetch+merge full. Coupled to Q1.
5. **Validate `checks` scope** (DEFAULTABLE) — `structure` only vs +`name_check` vs all three.
6. **Reuse dmac-curation-tools** vs fresh (DEFAULTABLE — user steered "simple").
7. **Live E2E target + paid-inference authorization** (BLOCKER for execution).
8. **Dropbox input format** the skill expects (DEFAULTABLE/LATER).

## 9. Known risks / contradictions

- **Dev-server deployment lag**: `validate` is on `origin/dev` *source*, but whether the running dev SERVER has it
  is UNVERIFIED (can't confirm without hitting it; may need VPN). Pre-execution gate.
- **Branch divergence**: local "primary" NExtSEEK checkout is on `ultraplan/nextseek-api-polish` (lacks validate);
  integration worktree + `origin/dev` have it. Build/test must target the right branch/deployment.
- **Router misclassification**: payload-building could be misrouted to read-only `nextseek_query` (can't run a skill).
- **Read-only-POST tension**: validate must run without a write-confirmation gate, yet it's a POST.
- **`sample_types/{uid}/` not in the read allowlist** (only the list endpoint is).
- **Conflation trap**: `generate-submission` (GEO/SRA publication) ≠ batch-upload sample payloads.
