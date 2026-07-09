# Phase 1 — Constraints notes: batch-upload skill, driven through the chat UI, output to Dropbox

**Scout run:** 2026-07-09 · **Repo:** dmac_assistant @ `main` (`6809ca6`)
**Goal:** demo-day dry run — exercise the NExtSEEK batch-upload skill end to end through the
browser chat UI, screenshot the whole flow, land a valid upload sheet in the operator's Dropbox
`example-project` folder.

> Internal working notes. The user-facing deliverable is
> `docs/research/batch_upload_ui_demo_findings_and_decisions.html`.
> A separate, unrelated `phase1_constraints_notes.md` (2026-06-16 stack-merge scout) exists in this
> directory and was deliberately not overwritten.

## 1. What this demo is trying to accomplish

Two chat turns in the browser UI at `http://127.0.0.1:8000/`:

1. An NExtSEEK-routed question retrieving samples + attributes for one scientist.
2. A Claude-Code-routed follow-up asking the assistant to build a batch-upload sheet that sets
   `Scientist = Jane Doe` on all of those UIDs.

Deliverable: the generated workbook, published to Dropbox, opened and confirmed valid.

## 2. Confirmed architecture (code-anchored)

- Chat UI: `src/dmac_assistant/static/index.html`, served at `GET /` (`app.py:30-33`).
  Login `#user_id` / `#password` / `#login-btn` → `POST /auth/login` (`auth.py:131-148`).
  Chat `#msg` / `#send-btn` / `#transcript`; WebSocket `/ws/chat` (`ws.py:419`) authenticated by
  the `dmac.bearer` subprotocol pair (`index.html:628`, `ws.py:104,142-156`).
- Bridge start: `PYTHONPATH=src uv run uvicorn dmac_assistant.app:app --host 127.0.0.1 --port 8000`.
  There is **no** make target for the bridge.
- Routing: BAML `RouteQuery` (`baml_src/router.baml:21-25`) → `nextseek_query` | `container_cc` |
  `unrelated`. Router is **ON by default** (`ws.py:830-844`, `DMAC_ROUTER_ENABLED` defaults `"1"`).
  There is **no supported way to force a route**.
- Bedrock: agent holds **no** AWS token; it calls the proxy by Docker DNS at
  `http://bedrock-proxy:8080` (`config.py:26,69`; `containers.py:370-379`). Token lives only in the
  proxy sidecar (`containers.py:390-393`).
- Network: `dmac-nextseek-net` is created by the **sidecar** compose (`sidecar/docker-compose.yml:55-58`);
  the proxy compose joins it as `external: true` (`bedrock-proxy/docker-compose.yml:32-37`).
  The bridge refuses to start any container if the network is absent (`containers.py:496-510`).
- Output: post-turn copier `copy_files()` writes `output_root/<user_id>/<rel>`
  (`copier.py:57-58,72`), fired at `ws.py:510` (legacy) / `ws.py:957` (router-on).

## 3. The output-path situation (settled — do not relitigate)

`.claude/reports/2026-05-28-dropbox-publish-path-redesign-decisions.md` records operator-locked
decisions, **build deferred** ("launch demo now, redesign after"):

- Target layout: `dropbox_root/<project>/<user_id>/<session>/{raw/, artifacts/<turn-n>/}`.
- `<project>` = `identity.projects[0]`.
- **Decision 5:** retire `DMAC_OUTPUT_ROOT` as a user-facing var; output derives from
  `DMAC_DROPBOX_ROOT` (already in `.env:26`).

Because that build was deferred, the running code still reads `DMAC_OUTPUT_ROOT`
(`config.py:215-218`). It is set in **no** env file, so it falls back to
`_DEV_DEFAULT_OUTPUT_ROOT = ~/dmac-dev/output` (`config.py:19`). That fallback was never chosen by
the operator. A prior vetting round already flagged this: *"[MEDIUM] 2A-4 — Delivery output path is
not pinned; 'Dropbox' is a simplification of what the copier does"*
(`docs/superpowers/plans/nextseek-batch-upload-skill-vet/pass-1/reviewer-findings.md:63`).

**For this demo (env-only, no code change):** launch the bridge with
`DMAC_OUTPUT_ROOT=$DMAC_DROPBOX_ROOT/example-project`, so the copier writes
`…/DMAC_Data/example-project/demo/<rel>` — matching the operator's existing folder.
The full `<session>/{raw,artifacts}` hierarchy remains the deferred build, and is already
implemented correctly in the integrated NExtSEEK version (operator, 2026-07-09).

## 4. The skill (code-anchored)

- `build_context/plugins/nextseek/skills/nextseek-batch-upload/SKILL.md`.
- Deliverable is an xlsx (`_batch_upload_payload.py:65,206-208`, sheet `Samples`,
  `payload_flat.xlsx`). The skill **never** uploads; every shim hard-refuses
  `--start|--upload|--confirmed-write` with exit 3, and `SKILL.md:73-77` forbids
  `POST .../batch-upload/start/`.
- Create vs update: `_is_update(row)` is `bool(row["UID"].strip())` (`_batch_upload_runner.py:87-88`).
  Blank UID creates; populated UID updates.
- Update-path fail-closed gates (unit-tested only): `manifest` (`:231-236`),
  `assay_superset` (`:237-239`), `present_blank` (`:219-222`).
- Six shims: `nextseek-project-resolve`, `nextseek-sampletype-attrs`, `nextseek-sample-search`,
  `nextseek-assay-resolve`, `nextseek-build-payload`, `nextseek-validate-upload`.
- Agent writes to `/data/scratch/<user>` (`_nextseek_common.sh:14-18`); `nextseek-build-payload`
  and `_promote` refuse an `--out` under `/data/scratch` for staging.

## 5. Live evidence status

- `evidence/batch-upload-e2e/` — 6 paid T10 turn bundles. Most authoritative pass:
  `20260707T231422Z` (name-only project resolution **through** the shim; route `container_cc`;
  `total_cost_usd 0.874748`, `cost_source claude_code_result`).
- **All six paid bundles are blank-UID create rows.** The update path has **never** been driven by a
  paid CC turn.
- `docs/superpowers/plans/evidence/e2e-local/20260630T192019Z.record.json` *did* run an update
  (`TIS-230206SAS-1-PUB`, `Scientist: Megan Proulx → E2E-updated`), but (a) its verdict was
  `ALL GATES: FAIL` (`run.txt`), and (b) it used `nextseek-sample-read --as-merge-map`, a shim that
  **no longer exists**. Treat it as historical, not as proof of the current skill.

## 6. Routing evidence (why turn 2 will land on container_cc)

The router prompt captured verbatim in `docs/superpowers/plans/evidence/e2e-local/run.txt` shows a
`container_cc` task family `upload_payload` whose example queries include *"Build an update payload
to fix the metadata on these existing samples,"* while `nextseek_query`'s capability text says it is
explicitly **NOT** for building/validating batch-upload payloads. All six paid T10 turns routed
`container_cc`. This is strong empirical support, not a guarantee.

## 7. Live NExtSEEK dev facts (probed 2026-07-09, read-only)

- `https://nextseek-dev.mit.edu` is up; valid TLS (`ssl_verify_result=0`).
- Auth is real: anonymous → 401, wrong creds → 401, `.env` creds → 200.
- API prefix `/nextseek_api` (`_batch_upload_client.py:13`); 49 paths in the OpenAPI 3.1.0 schema.
- `POST /nextseek_api/samples/advanced_search/` body:
  `{sampletype, attribute, filter_searchText (required), filter_matchType, attribute_logic, searchText_logic}`.
  Schema description: *"RETURNS: Paginated list of matching samples"* — read-only.
- One project: id `1`, title `Published Data`.
- **11,712 TIS samples; 25 distinct `Scientist` values.** Full fixture:
  `docs/research/fixtures/2026-07-09-dev-tis-scientists.json`.
  Small-N candidates: Lee Pribyl (2), Eddie Irvine (6), Owen Leddy (7), Lindsay Volk (8),
  Monet Norales (9). Data-quality note: `JoAnne Flynn` (6,949) and `Joanne Flynn` (325) coexist.

## 8. Environment prerequisites (verified 2026-07-09)

| Item | State |
|---|---|
| `dmac-assistant:poc` | PRESENT |
| `dmac-bedrock-proxy:poc` | **MISSING** — needs `make proxy-build` |
| `dmac-nextseek-sidecar:poc` | **MISSING** — needs `make sidecar-build` |
| `dmac-nextseek-net` | **ABSENT** — created by `make sidecar-up` |
| container name `dmac-bedrock-proxy` | freed 2026-07-09 (operator-authorized `docker rm` of the stopped NExtSEEK-stack container) |
| local NExtSEEK stack | brought DOWN 2026-07-09 (9 containers stopped, not removed); out of scope |
| `.env` `NEXTSEEK_URL` | `http://host.docker.internal:8000` → **must** be `https://nextseek-dev.mit.edu`; operator edits `.env` (three-layer protection) |

## 9. Known risks

1. **Update path is not live-proven** on the current skill. Three fail-closed gates have unit
   coverage only. It is *safe* (no writes ever), but it can fail-closed mid-demo.
2. **Routing is LLM-decided**; no override exists. Turn 2 wording matters.
3. `nextseek-api` skill cannot bootstrap — its SchemaRAG ingest against dev times out (operator:
   container-side issue). Workaround used here: fetch `/nextseek_api/schema/?format=yaml` directly.
4. The agent's `NEXTSEEK_URL` reaches dev over TLS with `verify=True` (no `verify=` override in
   `_assistant_client.py`) — a cert problem would surface as a typed transport failure.
5. `.env` holds live secrets but **is gitignored** (`.gitignore:18`). Do not stage it.

## 10. Contradictions found

- Project memory `project_dropbox_output_is_the_delivery_channel` says the Dropbox delivery is
  "BUILT & LIVE." The copier is built; its **destination** is `DMAC_OUTPUT_ROOT`, which is unset.
  The memory's own caveat ("verify exact publish path in code before asserting") is the correct
  reading. Memory needs correcting.
- `README.md:106` instructs launching with `DMAC_OUTPUT_ROOT=$HOME/dmac-dev/output`, which
  contradicts the 2026-05-28 locked decision. README is stale on this point.
