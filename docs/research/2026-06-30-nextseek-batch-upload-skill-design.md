# NExtSEEK Batch-Upload Payload-Builder Skill — Design Spec (V1)

**Status:** Design spec, authored 2026-06-30 via the superpowers brainstorming discipline.
This spec supersedes the prior superpowers task-plan
(`docs/superpowers/plans/2026-06-25-nextseek-batch-upload-skill.md`) and its build, which
diverged from intent (see the audit at
`docs/superpowers/plans/nextseek-batch-upload-skill-audit/CONSOLIDATED_FINDINGS.md`). No code
is written from this spec until the owner explicitly authorizes it. The spec + the
implementation plan derived from it are to be adversarially vetted for gameability before any
build.

## 0. Provenance — where the requirements come from

This spec is grounded only in primary sources, not paraphrase:

- The owner's **verbatim original `/scout` ask** (transcript `23b9d63a`, 2026-06-25): *"create a
  skill for container CC to use the batch upload code and all of its endpoints… build the
  necessary payloads… submit these back to the user for inspection… invoking validate endpoint
  (which is read-only) before returning payload… Doing the upload/update itself should remain
  explicitly forbidden… EVERYTHING should be completely wired in and LIVE… preliminary steps…
  must include Read-only API calls to get the attribute list of the sample type(s)… rules about
  leaving UID blank if new samples and including the UID if updating… What this isn't is a full
  curation skill."*
- The owner's **decisions this session** (brainstorming dialogue, 2026-06-30), recorded in §2–§7.
- The **live OpenAPI spec** pulled from the running stack (`GET /nextseek_api/schema/?format=yaml`).
- The **NExtSEEK batch-upload server code** (integration worktree
  `work/BMC/nextseek-worktrees/dmac-integration/nextseek_api/batch_upload/`).
- The **canonical curation model docs** named by BMC `CLAUDE.md` "Required reading before any
  curation work": `DMAC_docs/assay_association_model.md`, `curation_conceptual_flow.md`,
  `curation_operational_flow.md`, and the realized LinVo flat example
  (`SRP/LinVo/scripts/build_flat_upload.py`).
- The phase-1 notes + scout decision JSONs in `docs/research/`.

The GitBook `DMAC_docs/gitbook/03-uploading.md` is **not** authoritative for code/schema/enforcement
(it predates the new batch-upload code); it is useful only for the *logical* provenance model.

## 1. Goal & scope

An in-container ("container CC") Claude Code skill that turns a curator's request — chat plus
files in the mounted Dropbox project directory — into a **validated NExtSEEK batch-upload sheet**
and returns it for the curator to upload. It is a **payload builder**, not a curation tool.

**In scope (the batch-upload step, conceptual-flow steps 5–7):** build the flat upload sheet for
new and/or existing samples, fetch the real attribute schema, resolve `project_id` and assay IDs,
populate values, validate the produced file against the read-only validate endpoint, and deliver
the validated sheet.

**Invocation context.** The skill ships as a baked plugin skill (the `nextseek` plugin's `SKILL.md`
read by the in-container Claude) and is reached on the existing `container_cc` route (LLM router →
container CC `docker exec`). The design below is independent of that routing; the only bridge-side
change this spec requires is the exact-cost relay (§13).

**Explicit non-goals:**
- **Never uploads or updates the database.** The `start/` endpoint is structurally absent from the
  skill's client. Only read-only API calls (`validate`, the `GET` lookups) are made.
- **Not a full curation skill.** It does not define the sample tree, choose sample types, decide
  repository tiering, or deposit data files.
- **Does not derive or police the lineage graph.** In particular it does not compute the
  per-instance assay associations (the "shared assay on both endpoints" rule, §4) — it builds each
  row's `assay_ids` from the assay titles the curator supplies for that row. Getting the
  associations right is the curator's modeling responsibility. *(Boundary item B-1: a future
  enhancement could warn on a likely-un-annotated edge; out of scope for V1 unless the owner asks.)*
- **No controlled-vocabulary / Ontology handling in V1.** All attributes are treated as free-text;
  the skill does not build an Ontology sheet or validate vocab terms. *(Decision §7.4.)*

## 2. Governance & safety invariants (binding)

1. **Read-only.** The skill performs only read-only NExtSEEK API calls. It cannot upload.
2. **Never guess DB-specific values.** Sample-type IDs, **assay IDs**, exact attribute names,
   protocol UIDs, parents — all come from the DB/API or the curator, never invented. A mislabeled
   attribute name is **silently dropped on upload** (the largest "looks-fine-is-wrong" vector), so
   exact DB attribute names are enforced.
3. **Modeling decisions are the curator's, never the researcher's.** The skill consumes the
   curator's modeling (sample types, parents, assay titles, attribute values). It must never punt a
   modeling decision to a researcher.
4. **No scale caps, no feasibility second-guessing.** The NExtSEEK batch-upload backend is designed
   to populate 50k+ samples in minutes. A request to build thousands of rows is built in full
   (subject only to the curator's actual access). The skill never refuses or caps a large request
   on the belief it "won't work."
5. **Build-then-validate-then-gate.** Nothing is delivered unless it passes the hard gate (§10).

## 3. Create vs. update semantics (grounded in the real schema)

`validate` and `start` take the **same** request shape, `BatchUploadStartRequest`:
`{rows: [InputRowModel] OR a multipart .xlsx file, project_id (required, integer),
update_existing (bool, default false), …}`. There is **no separate create vs. update path**. The
only differences are:

- **UID:** blank (the `UID` column **and** `json_metadata.UID`) for a new sample — the server
  auto-generates it. Populated with the NExtSEEK-assigned UID for an existing sample.
  - Server consistency guard (`batch_upload/models.py`): UID column empty but `json_metadata.UID`
    set → error; both set and mismatched → error. The skill keeps them consistent.
- **`update_existing`:** `false` for create (existing samples are skipped); `true` for update
  (existing samples, matched by UUID or Name, are updated).

**Partial updates are safe — the server merges.** Confirmed in `batch_upload/insert.py`
(`update_existing=true` → `rows_to_update`) → `batch_upload/update.py`
(`load_existing_sample_details()` → `deep_merge_metadata()` = *"New keys overwrite, old preserved"*
→ `UPDATE samples SET json_metadata = merged`). Therefore an update sheet carries **only the
changed attributes** (plus the UID + `update_existing=true`); omitted attributes are preserved by
the server. **The skill performs no client-side merge, no fetch-existing, and no batch read-back of
samples.** (This deletes the entire merge subsystem the prior build wrongly added.)

## 4. The provenance model (context the skill consumes, does not derive)

From `DMAC_docs/assay_association_model.md` (canonical):

- Two levels: a **sample type** is schema (a node in the type-level tree, edges = assays); a
  **sample** is an instance (a workbook row). The type-level tree says a transition is *possible*;
  a row's `assay_ids` records what *actually happened to that one sample*.
- An assay association is a triple `(parent_sample, assay, child_sample)`. The `Parent` field gives
  the parent and child; the assay is the one **shared by both endpoints** (parent ∩ child) — that
  shared assay annotates the edge.
- A sample's `assay_ids` is the **union of the assays it shares with its parents (incoming edges)
  and its children (outgoing edges)**; a mid-lineage sample carries ≥ 2. Both endpoints of an edge
  must carry the shared assay or the edge is un-annotated. `assay_ids` is **per-instance, never
  uniform-per-type** (uniform assignment fabricates provenance).

**The skill's relationship to this model:** it builds each row's `assay_ids` from the assay
**titles the curator supplies for that row** (resolved to study-scoped IDs, §6/§9). It trusts the
curator's per-instance associations and does **not** compute the union or enforce the
both-endpoints rule (boundary B-1, §1).

## 5. Inputs

- **Chat:** the curator describes the samples (type, attributes, parents, assay titles, project
  context) in the conversation.
- **Mounted Dropbox files** under `/data/projects/<…>` (read-only): structured spreadsheets/CSVs
  read via the **calamine stack** (`polars` `engine="calamine"` / `fastexcel`) — **never
  `openpyxl`**; unstructured protocols/PDFs/DOCX via **`markitdown`** to extract attribute values.
  - `markitdown` is image-only (the agent container), with the documented `onnxruntime>=1.24.1`
    floor for the cp314 wheel; a pure-python fallback (e.g. `pdfplumber`/`python-docx`) is named for
    the install-fail escalation. The skill never silently substitutes the extractor.

## 6. Output format

Produce the **flat single-sheet `InputRowModel` xlsx** (the legacy 4-sheet workbook is dropped;
it is kept by NExtSEEK only for backwards compatibility / readability). Realized example:
`SRP/LinVo/scripts/build_flat_upload.py` + `outputs/batch_update/flat_upload_364_samples.xlsx`.

**Authoritative columns** (what the server ingests): `UID`, `SampleType`, `json_metadata` (a JSON
string holding all attributes, **including `Parent`**), `assay_ids` (list-repr string, e.g.
`"[9,2]"`), `assay_titles`.

**Readability via materialized review columns.** Each `json_metadata` field is also written as its
own column (and `assay_titles` as the human-readable assay view). These extra columns are **silently
dropped by the server** (so they don't affect the upload) and exist only for the curator to read.

**`json_metadata` is the single source of truth.** Decision §7.8: the materialized columns are
**review-only and clearly marked**; the server uploads only `json_metadata`, so a column edit that
does not reach `json_metadata` would be silently lost. Therefore **the curator does not hand-edit
the sheet — to change a value, the curator tells the skill, which rebuilds `json_metadata` and
re-materializes the columns.** Excel writing uses `xlsxwriter` (via `polars.write_excel`), never
`openpyxl`.

## 7. Confirmed decisions (this session)

- **§7.1 Update flow:** partial-safe; submit UID + changed attributes + `update_existing=true`;
  server deep-merges. No client merge/fetch/read-back. *(Owner-confirmed: "Preserved (partial is
  safe).")*
- **§7.2 Missing values:** **ask the curator, then hard-gate.** After fetching the attribute
  schema, the model identifies attributes (esp. `required`/`is_title`) it has no value for and asks
  the curator (or for explicit-blank confirmation) before building; a deterministic gate then
  refuses any sheet that is empty or missing a required attribute. *(Owner-confirmed.)*
- **§7.3 Scale:** no caps, no feasibility second-guessing. *(Owner directive.)*
- **§7.4 Ontology/controlled-vocab:** out of scope V1 (free-text). *(Owner-confirmed.)*
- **§7.5 `project_id`:** derived from the logged-in user — `GET /projects/` (scoped to the current
  user) + `GET /people/current/`; one accessible project → use it, several → resolve from the
  study/sample context or ask. Not asked by name. *(Owner directive: "obtain project_id based on who
  is currently logged in.")*
- **§7.6 Assays:** the curator provides assay **titles**; the skill resolves title → real
  `assay_id`, **disambiguated by study** (the same title can exist in multiple studies). *(Owner
  directive.)*
- **§7.7 Output:** flat `InputRowModel` sheet (not the 4-sheet workbook). *(Owner-confirmed
  rethink of the earlier Q-101 default.)*
- **§7.8 Divergence handling:** `json_metadata` authoritative; materialized columns review-only;
  edits go through the skill, not the sheet. *(Owner-confirmed.)*
- **§7.9 Model correctness:** the per-instance assay-association model (§4) is confirmed correct by
  the owner.

## 8. Components (and what changes vs. the broken build)

- **`_batch_upload_client.py`** — read-only HTTP client. Methods: `list_projects()`
  (`GET /projects/`), `current_person()` (`GET /people/current/`), `sample_type_attributes(uid)`
  (`GET /sample_types/{uid}/`, full attribute objects), **`list_assays()` (new — `GET /assays/`,
  returns title + id + linked study for title→id study-scoped resolution)**, **`validate_file(xlsx,
  project_id, checks)` (new — multipart **file mode**)**. **Deleted:** the per-UID
  `read_samples()` loop and the entire merge/read-back path. No `start()`/`upload()` — structurally
  absent.
- **`_batch_upload_payload.py`** — flat-sheet builder: `json_metadata` (authoritative, includes
  `Parent`) + per-row `assay_ids`/`assay_titles` + materialized review columns; enforces exact DB
  attribute names, required/`is_title` population, and non-emptiness. **Deleted:**
  `merge_attributes`, `--merge-existing`, `--as-merge-map`.
- **`_batch_upload_runner.py`** — orchestration + the **hard delivery gate** (non-zero exit on
  fail; stage-then-promote).
- **`SKILL.md`** — rewritten flow (§9): resolve project + assays from the API, fetch the real
  schema, populate values, ask-on-missing, validate the produced file, STOP on failure.
- **`ws.py`** (bridge) — relay `usage` + `total_cost_usd` from the CC stream-json `result` frame so
  cost is captured **exactly**, not fabricated (§13).

## 9. The end-to-end flow (the skill's steps)

1. **Parse the request:** create vs. update; which sample type(s); the source data (chat and/or
   mounted Dropbox files via the calamine stack / `markitdown`).
2. **Resolve `project_id` from identity:** `GET /projects/` + `GET /people/current/`; one → use,
   several → resolve from context or ask; **refuse to proceed without a resolved `project_id`**
   (validate requires it).
3. **Fetch the exact attribute schema** per sample type: `GET /sample_types/{uid}/` → full attribute
   objects (`title`, `required`, `is_title`, `base_type`). Persist the **structured** objects (not
   titles-only).
4. **Resolve assay titles → study-scoped `assay_id`s:** `GET /assays/`; match the curator's titles,
   disambiguate by the project's study.
5. **Populate values** from the curator's info into the **exact DB attribute names**; set `Parent`
   (UID or Name) inside `json_metadata`. **Ask the curator** for any missing required/`is_title`
   value or any unresolved assay/parent — never invent, never guess DB-specific values.
6. **Build rows:** UID blank for create / NExtSEEK UID + `update_existing=true` for update; per-row
   `assay_ids`/`assay_titles`; the flat sheet with materialized review columns (§6). No scale cap.
7. **Validate the produced `.xlsx`** via `validate_file` (multipart **file mode** — the way it
   uploads), all three checks (`structure,name_check,dag`), passing `checks` as the spec-defined
   query/form param and asserting `checks_run` contains all three.
8. **Hard delivery gate** (§10).
9. **Deliver** to `/data/scratch/<user>/…` (the post-turn copier publishes to Dropbox); return the
   verdict + path + a per-type row summary. **Never upload.**

## 10. Validation & hard delivery gate (the data-safety core)

The skill validates the **artifact it delivers** (the `.xlsx`, file mode → server `convert.py`
traditional/flat parse + ontology), **not** internal JSON rows (rows mode bypasses Excel parsing).

Deliver **only if all hold**:
- `valid == true` and `errors[]` empty, **and**
- every row has ≥ 1 real (non-UID) attribute, **and**
- every `required==true` / `is_title` attribute is populated, **and**
- `totals.processed == produced row count`, **and**
- `checks_run` contains `structure`, `name_check`, `dag`.

Otherwise: **refuse**, surface `errors[]` + exactly which fields/rows are missing, and ship
nothing. Implementation: **stage to a tmp dir, promote into `/data/scratch` only on pass** (or write
a `FAILED` marker the copier honors) so the auto-publish copier (`copier.py`, `ws.py`) cannot ship a
failed sheet. The runner returns **non-zero** on any gate failure; `SKILL.md` instructs the agent to
STOP and report on failure. The guarantee lives in the skill, not only in a test.

## 11. Error handling

- **Missing values:** ask the curator (§7.2), then hard-gate.
- **Unresolved DB-specific value** (assay title not found, project ambiguous, sample type unknown):
  surface and ask; never fabricate.
- **`markitdown` install failure:** fail-fast and escalate the named pure-python fallback to the
  curator; do not silently switch extractors.
- **Validate endpoint error / non-200:** surface verbatim; do not deliver.

## 12. API contract (grounded in the live OpenAPI spec)

- `POST /nextseek_api/batch-upload/validate/` — body `BatchUploadStartRequest`
  (`rows` *or* multipart `.xlsx` file; `project_id` required; `update_existing`); `checks` is a
  query/form param (not a body field). Returns a verdict with `valid`, `errors[]`,
  `totals.processed`, `checks_run`. **The skill uses file mode.**
- `GET /nextseek_api/sample_types/` (list) and `GET /nextseek_api/sample_types/{uid}/` (full
  attribute objects).
- `GET /nextseek_api/projects/` — projects accessible to the current user (IDs + linked studies).
- `GET /nextseek_api/people/current/` — the logged-in person.
- `GET /nextseek_api/assays/` — assays accessible to the current user (titles, types, IDs, linked
  studies) for title→id study-scoped resolution.
- `InputRowModel` required fields: `SampleType`, `json_metadata`. Present-but-optional: `UID`,
  `assay_ids`, `assay_titles`, `project_id`, `study_*`, `sop_id`.
- **Exact line refs and any leniency (e.g. `checks` body-vs-query) must be re-verified against the
  live spec + `convert.py` at build time before pinning literals.**

## 13. Exact-cost capture (bridge change)

The CC stream-json terminal `result` event carries exact per-turn `usage` and usually
`total_cost_usd`. The bridge currently collapses `result` into a `session_ended` frame and **drops**
`usage`/`total_cost_usd`. Fix: `ws.py` attaches `usage` + `total_cost_usd` to the `session_ended`
frame (backward-compatible); the E2E harness records the **exact** relayed values (no hardcoded
token literals). Gemini/BAML cost is captured honestly or flagged, never fabricated.

## 14. Acceptance & testing (ALL paid/live runs HELD until the owner authorizes)

- **$0 host-cost regression (the C8 reproduction), required green before any paid run:** a
  create-from-free-text request with **no attribute values** must drive the skill to **refuse**
  (ask-then-gate), asserting the non-empty + required-attribute + file-mode validate gates **fail
  fast** at host cost — never emitting an empty/header-only sheet.
- **Unit coverage** of: project/assay resolution, attribute-schema fetch + structured persistence,
  flat-sheet build + materialized columns + `json_metadata` authority, the hard gate, the
  create-vs-update UID/`update_existing` logic.
- **Live E2E via the bridge stays halted.** When the owner authorizes it: the bridge relays and the
  harness records **exact** Bedrock/Gemini cost from `result.usage`/`total_cost_usd`; the run
  exercises the **real** validate endpoint against the dev/local stack with real attribute schemas.

## 15. Process constraints (binding on the build that follows)

- **No code is written until the owner explicitly authorizes it.** This spec + the implementation
  plan derived from it are adversarially vetted for gameability (reduced plan-vetting discipline)
  first.
- Work stays on a branch (`feat/nextseek-batch-upload-skill` or a successor); commit + push to the
  branch; **hold merge until the owner approves.**
- Python deps via `uv add`; Excel **read** via the calamine stack (`polars` `engine="calamine"` /
  `fastexcel`), **write** via `xlsxwriter` (`polars.write_excel`); never `openpyxl`.
- The skill targets the **integration-worktree / live** NExtSEEK contract (which has the `validate`
  endpoint), not a stale checkout.

## 16. Open boundary items (explicit, for the owner)

- **B-1:** the skill trusts the curator's per-row assay associations and does not compute/enforce
  the both-endpoints union (§4). A warn-on-likely-un-annotated-edge feature is a possible future
  enhancement, out of V1 scope unless the owner asks.
- **B-2:** controlled-vocabulary/Ontology handling is out of V1 (§7.4).
