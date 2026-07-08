# NExtSEEK Batch-Upload Payload-Builder Skill — Design Spec (V1)

**Status:** Design spec, authored 2026-06-30 via the superpowers brainstorming discipline.
This spec supersedes the prior superpowers task-plan
(`docs/superpowers/plans/2026-06-25-nextseek-batch-upload-skill.md`) and its build, which
diverged from intent (see the audit at
`docs/superpowers/plans/nextseek-batch-upload-skill-audit/CONSOLIDATED_FINDINGS.md`). No code
is written from this spec until the owner explicitly authorizes it. The spec + the
implementation plan derived from it are to be adversarially vetted for gameability before any
build.

**Revision R1 (2026-06-30, owner-approved during onboard review):** §7.5 and §9 step 2 (project_id
resolution) changed to *always confirm the project with the curator before use, never silently
auto-select*. The prior "one accessible project, use it" auto-select silently breaks for a
multi-project admin. No other decision changed.

**Revision R2 (2026-06-30, owner-approved + verified live against the deployed dev server):**
restore retrieve-on-update for visibility via `samples/advanced_search/` keyed by the UID list
(read-only; partial-safe stays; §3/§8/§9/§12); `Parent` described as a normal attribute (§9 step 6);
`checks` is a multipart form field, not a body field (§10/§12); assay study-disambiguation uses
single fetches (§7.6/§9 step 4); parse/serialize with `orjson` (§12/§15). The §12 contract is now
verified against `https://nextseek-dev.mit.edu` (the owner-designated source of truth), not on-disk
source.

**Revision R3 (2026-07-01, owner-approved, from re-vet):** §10 hard-gate rule made create-vs-update
and UID aware. The prior flat rule ("every `required==true`/`is_title` attribute is populated")
refused every valid sheet: `UID` is `required==true` AND the only `is_title==true` attribute yet is
blank on create (server auto-generates it), and update rows carry only changed attributes (omitted
required attrs are server-preserved). Corrected per the spec's own §3 create/update semantics; §7.2
aligned.

**Revision R4 (2026-07-01, owner scope-correction):** the §10 create-vs-update classification is
**per row by UID presence** (blank = new sample, populated = existing sample); `update_existing` is
an **upload-request parameter, not a sheet field**, so the skill (which builds the sheet, never
uploads) neither carries nor gates on it. §9 step 7 corrected to drop "+ `update_existing=true`".
The new-sample-row rule refuses a blank non-UID required attribute (no unverifiable "explicit-blank"
exception; optional attributes may be blank).

**Revision R5 (2026-07-01, owner-directed + verified live; assay-resolution mechanics superseded by
R8):** assay resolution uses **ONE accessible-assays `title → [IDs]` map from `GET /assays/`** with
**`GET /projects/{id}/` as the collision tie-break set** (see R8 and §7.6), superseding the R2
per-assay `GET /assays/{id}/` fetches (§7.6). **Assay updates are SET/REPLACE** (server
`smart_merge_assay_assets` deletes omitted assays), so update rows must **carry forward the sample's
current assay set ∪ additions** (§7.10); current assays come from the `advanced_search` `assays`
titles field (§12). A blank `assay_ids` on an update **wipes** all the sample's assays, so the gate
guards it (§10).

**Revision R6 (2026-07-01, from re-vet; assay-map mechanics superseded by R8; guarantee-scope
corrected 2026-07-02):** the §10 assay guard upgraded from "blank → refuse" to
**"delivered `assay_ids` ⊇ the resolved current set → else refuse"** (per-UID current-assay manifest,
§7.10). **Scope of the guarantee (corrected):** the ⊇ check catches a delivered set that is
**incomplete relative to the RESOLVED current set** — a payload-builder under-population, a comma-split
error, or an unresolved title (all of which make the delivered set diverge from the manifest). It does
**NOT** catch a shared under-count where the retrieved `assays` TITLE string itself omits a genuine
current assay (GROUP_CONCAT truncation, or a current assay whose title is absent from the accessible
`/assays/` map): the manifest-current set and the delivered set both derive from the SAME `resolve()`
over the SAME title string, so the ⊇ check is structurally blind to a shortfall common to both. That
residual is covered by (i) a runtime **fail-closed truncation guard** (§10 — refuse any assay-touching
row whose raw `assays` string length is within a safety margin of the GROUP_CONCAT ceiling) and (ii)
the pre-merge live-fidelity confirmation (§14) that positively checks
`resolve(assays) == the sample's authoritative DB assay-link ID set` for a duplicate-title sample. The
guard is **not** a claim of DB-link-set completeness. Current-assay preservation resolves against the
**ONE accessible-assays `title → [IDs]` map from `GET /assays/`** with `GET /projects/{id}/` as the
collision tie-break (R8 and §7.10); `assays` titles are parsed by **longest-match** (comma-safe);
metadata-only updates also carry forward the current set.

**Revision R7 (2026-07-01, from re-vet):** the §10 assay guard **fails closed on manifest
incompleteness** (a missing/empty/degraded per-UID current-assay entry REFUSES before the ⊇ check —
`⊇ ∅` is vacuous); retrieve-failure fatality broadened to **any update row** (metadata-only
included), a null `assays` field is a retrieve failure not a zero-assay sample; `--confirm-clear-assays`
is **per-UID scoped** (never a global disable) and must be tested. Current-assay preservation uses the
**ONE accessible-assays `title → [IDs]` map from `GET /assays/`** with `GET /projects/{id}/` as the
collision tie-break (clarified/superseded in R8; the earlier "FULL `/assays/` map vs project-scoped
map" framing is retired).

**Revision R8 (2026-07-01, owner-confirmed + live-verified on nextseek-dev.mit.edu; propagated from
the build plan's assay-model correction, NOT a new design choice):** the assay-resolution model is
**ONE accessible-assays `title → [IDs]` map from `GET /assays/`** (list items are
`{id, type:"assays", attributes:{title}, links}` only, with **NO project/study id**, verified live)
that resolves **BOTH** the curator's NEW-addition titles **AND** each sample's CURRENT assay titles
(from the `advanced_search` `assays` string, §12). Assay titles are **NOT unique across studies within
a project** (verified live: 48 duplicate titles on dev, e.g. "Comet Chip Analysis - Data Attached" →
assay 351 [study 34] + 260 [study 36], both project 1), so a title may map to MULTIPLE IDs.
**`GET /projects/{id}/` (`relationships.assays.data[].id`) is the collision TIE-BREAK set**, applied
ONLY when a title maps to >1 ID. A **NEW-addition** title still ambiguous (0 or >1 candidates) after
the tie-break **FAILS CLOSED** (ask/refuse; the reverse map does not apply because the new assay is
not yet linked to the sample). A **CURRENT** (carry-forward) title still ambiguous instead triggers a
**two-path TARGETED reverse-map fallback**: **Path 1** resolves via the map + tie-break and collects
the ambiguous titles together with their candidate IDs; **Path 2** (only on ambiguity) fetches the
samples relationship (`GET /assays/{id}/` → `relationships.samples.data[]`) for **ONLY** the ambiguous
candidate IDs (deduped across ambiguous titles; **NEVER** all project assays, **NEVER** per-sample) and
keeps the candidate ID(s) whose sample list **contains** the sample (present in more than one means the
sample genuinely has both, carry both forward). Fail-closed for a current title is the last resort
only: a retrieve failure, a candidate samples-list that cannot be fetched, or the sample in none of its
candidate lists. This **supersedes** the R5 "2-call project-scoped title↔id map" and the R6/R7 "FULL
`/assays/` map" framing (the old "project-scoped map vs FULL map" split no longer exists). Publishing
creates new official assays under a new study, so the same title now maps to >1 SAME-project ID and the
project tie-break cannot disambiguate; Path 2's samples-list membership is what recovers the sample's
actual current assay (general/comprehensive published-study duplication handling is DEFERRED to V2).
**Scaling invariant (absolute):** NO per-sample/per-UID API call anywhere in the production resolution
path; `GET /samples/{uid}/` is FORBIDDEN in every non-T9.5 code path; total assay-resolution cost is
`GET /assays/` (paginated once) + `GET /projects/{id}/`
(once) + Path 2's per-ambiguous-candidate-ID samples fetches (ONLY on ambiguity, ONLY the ambiguous
candidate IDs) = O(1) in the number of samples. §7.6, §7.10, §8, §9 (steps 4–5), and §12 below are
written to this model.
**Owner-approved carve-out (2026-07-02), T9.5 keystone probe ONLY:** the pre-merge live-fidelity probe
(§12 / build-plan T9.5) MAY call `GET /samples/{uid}/` → `relationships.assays.data[]` for the SINGLE
probed sample to obtain the authoritative DB assay-link set as an INDEPENDENT source of truth (without it
the probe's `resolve(titles) == DB-link-set` assert is a tautology). This is a one-shot, O(1),
owner-gated, pre-merge read on ONE sample, NOT the production resolver, which stays bulk `advanced_search`
only. The absolute invariant above is otherwise unchanged: `GET /samples/{uid}/` remains FORBIDDEN in
every path except this single keystone probe.

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
- The **NExtSEEK batch-upload server code**
  `work/BMC/NExtSEEK/nextseek_api/batch_upload/` (the live dev spec remains authoritative for
  contract questions per the standing memory; the on-disk tree is corroborating only).
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
the server. **The skill performs no client-side merge** (the server deep-merges). It does, however,
**retrieve existing sample metadata for visibility** on an update: read-only, via
`samples/advanced_search/` keyed by the UID list (§8/§9/§12), so the curator can see current values
and the full resulting sample. This deletes the client-side *merge* subsystem the prior build added
(`merge_attributes`, `--merge-existing`, `--as-merge-map`), but **not** the read capability;
retrieval is for visibility, never for an on-the-wire merge.

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
**titles the curator supplies for that row** (resolved to assay IDs via the §7.6/§9 map). It trusts the
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
`openpyxl`; `json_metadata` is serialized with `orjson.dumps(...).decode()` (a string, per §12).

## 7. Confirmed decisions (this session)

- **§7.1 Update flow:** partial-safe; submit UID + changed attributes + `update_existing=true`;
  server deep-merges. No client-side merge; but the skill does retrieve existing metadata for
  visibility (read-only, via advanced_search by UID list, §8/§12). *(Owner-confirmed: "Preserved
  (partial is safe)"; retrieve restored R2 2026-06-30: "advanced_search literally works fine... pass
  in the list of UIDs as the filter search text.")*
- **§7.2 Missing values:** **ask the curator, then hard-gate (create-vs-update aware, §10).** After
  fetching the attribute schema, the model identifies the **non-UID** `required` attributes it has no
  value for and asks the curator before building; a
  deterministic gate then refuses any empty sheet, any create row missing a non-UID required
  attribute, and any update row with a present-but-blank attribute. `UID` is blank by design on
  create; omitted attributes on an update are server-preserved (not required). *(Owner-confirmed;
  create/update/UID-aware per R3.)*
- **§7.3 Scale:** no caps, no feasibility second-guessing. *(Owner directive.)*
- **§7.4 Ontology/controlled-vocab:** out of scope V1 (free-text). *(Owner-confirmed.)*
- **§7.5 `project_id`:** resolved interactively, **never silently auto-selected.** The skill always
  calls `GET /projects/` (projects accessible to the current user) + `GET /people/current/` first,
  then confirms which project to use with the curator before proceeding: if the curator named a
  project in chat, match it against the accessible list and confirm (resolve name → ID via the API,
  never trust a typed ID); otherwise present the accessible-projects list and ask which to use.
  **Even a single accessible project is surfaced for confirmation, not used silently** (silent
  auto-select breaks for multi-project admins). The confirmed project scopes assay resolution
  (§7.6). *(Owner directive, revised 2026-06-30: "ask user directly for project name... model does
  lookup first to pull all projects user has access to, asks the user to confirm which one should be
  used to filter assays by.")*
- **§7.6 Assays (R5/R8, verified live):** resolve assay titles ↔ IDs via **ONE accessible-assays
  `title → [IDs]` map from `GET /assays/`** (`{id, title}` for all accessible assays; list items carry
  **NO project/study id**), with **`GET /projects/{id}/`** (`relationships.assays.data[].id` = the
  confirmed project's assay IDs) as the **collision TIE-BREAK** set applied ONLY when a title maps to
  >1 ID. This **supersedes** the per-assay `GET /assays/{id}/` study-disambiguation (N calls → O(1),
  scales). The one map resolves (a) the curator's NEW-addition assay titles → IDs (still ambiguous
  after the tie-break, i.e. 0 or >1 candidates → **FAIL CLOSED**, ask/refuse) and (b) each sample's
  CURRENT assay titles (from `advanced_search`, §12) → IDs, where residual ambiguity instead triggers
  the two-path targeted reverse-map fallback (§7.10, R8): **Path 2** fetches `GET /assays/{id}/` →
  `relationships.samples.data[]` for ONLY the ambiguous candidate IDs and resolves by samples-list
  membership. **NO per-sample `GET /samples/{uid}/` call** in this production resolution path (O(N),
  forbidden; the single T9.5 keystone-probe carve-out noted under the Scaling invariant above is the sole
  exception, and is not part of Path 2). *(Owner directive,
  corrected R8: one `GET /assays/` map + `GET /projects/{id}/` tie-break; advanced_search returns
  assay associations as titles.)*
- **§7.7 Output:** flat `InputRowModel` sheet (not the 4-sheet workbook). *(Owner-confirmed
  rethink of the earlier Q-101 default.)*
- **§7.8 Divergence handling:** `json_metadata` authoritative; materialized columns review-only;
  edits go through the skill, not the sheet. *(Owner-confirmed.)*
- **§7.9 Model correctness:** the per-instance assay-association model (§4) is confirmed correct by
  the owner.
- **§7.10 Assay updates are SET/REPLACE, not deep-merge (R5, verified in `batch_upload/update.py`).**
  On an update, the row's `assay_ids` is the **complete desired set**: the server's
  `smart_merge_assay_assets` computes `to_remove = existing_assays − new_set` and **DELETEs** the
  omitted ones (docstring: "add new, remove unlisted"; `update.py:117`, `:431-444`). It runs on
  **every** update row, so a blank `assay_ids` on an update **WIPES all of that sample's assays**
  (`json_metadata`, by contrast, is deep-merged/partial-safe). Therefore for every update row the
  skill **carries forward the sample's current assay set ∪ the curator's additions** (current assays
  come from the `advanced_search` `assays` titles field, §5/§12, resolved to IDs via the §7.6 map);
  removing an assay happens only when the curator explicitly asks. Assay-only updates (changing only
  `assay_ids`) are **in V1 scope**. **Deterministic safety (R6):** during build the skill persists a
  per-UID **current-assay manifest** (a gate-readable sidecar, NOT shipped in the sheet); the §10
  superset-guard verifies the delivered `assay_ids ⊇ manifest-current` (unless a per-UID clear
  opt-in). **The ⊇ guarantee is scoped to resolution-completeness relative to the retrieved titles,
  NOT to DB-link truth** (R6): manifest-current and delivered `assay_ids` derive from the same
  `resolve()` over the same `assays` string, so the ⊇ check is blind to a shortfall common to both
  (a title the string omits via GROUP_CONCAT truncation or an out-of-map title). That residual is
  covered by a **runtime fail-closed truncation guard** — refuse any assay-touching row whose raw
  `assays` string length is within a safety margin of the GROUP_CONCAT ceiling (observed dev max = 387
  chars / 9 titles vs a ~1024 ceiling; refuse at >= 900 chars) — plus the §14 pre-merge live-fidelity
  confirmation. **Carry-both-forward (materialization rule):** when a single CURRENT title resolves to
  MULTIPLE same-project IDs (the sample is in more than one candidate's sample list, e.g.
  "Comet Chip Analysis - Data Attached" → {351, 260}), the row carries `assay_ids=[351,260]` AND a
  PARALLEL `assay_titles` list (the title materialized **once per resolved ID**, so
  `len(assay_titles) == len(assay_ids)` always holds and the server's length-consistency validator
  `models.py` does not reject a legitimate multi-membership update). **Preservation resolves each
  sample's current titles→IDs through the SAME ONE
  accessible-assays `title → [IDs]` map (§7.6/R8); on a same-project duplicate title the project
  tie-break cannot disambiguate, so the two-path targeted reverse-map fallback resolves it: Path 2
  fetches `GET /assays/{id}/` → `relationships.samples.data[]` for ONLY the ambiguous candidate IDs
  and keeps the candidate whose sample list contains the sample (NEVER all project assays, NEVER
  per-sample); a current title still unresolvable after Path 2 fails closed (§10/§11).**
  **Comma-in-title:**
  parse the `assays` titles by **longest-match membership** against the known assay title set, not
  `str.split(",")`; fail closed (refuse/ask) on an unresolvable token. **A metadata-only update
  still carries the current assay set forward** (the server diffs assays on every update row).
  *(Owner-confirmed; replace behavior verified in `update.py`; superset-guard from re-vet.)*

## 8. Components (and what changes vs. the broken build)

- **`_batch_upload_client.py`** — read-only HTTP client (HTTP Basic via `NEXTSEEK_USERNAME`/
  `NEXTSEEK_PASSWORD`, falling back to the legacy `API_USER`/`API_PASS` only when the NEXTSEEK_* pair
  is unset — owner-decided precedence 2026-07-02, both pairs set in the container env today;
  **`orjson` for all parse/serialize**, not stdlib `json`). Methods:
  `list_projects()` (`GET /projects/`, returns `{id, title}` per project);
  `project_assays(id)` (`GET /projects/{id}/`, `relationships.assays.data[].id` = the confirmed
  project's assay IDs, the collision TIE-BREAK set); `current_person()` (`GET /people/current/`);
  `sample_type_attributes(uid)` (`GET /sample_types/{uid}/`, full attribute objects);
  `list_assays()` (`GET /assays/`, `{id, title}`, list items carry NO project/study id) — builds the
  **ONE accessible-assays `title → [IDs]` map** (§7.6/R8; **replaces** the per-assay `assay_study`
  single-fetch); `assay_samples(candidate_ids)` (`GET /assays/{id}/` → `relationships.samples.data[]`,
  the **Path-2** reverse-map, called ONLY with ambiguous current-title candidate IDs, never all project
  assays, never per-sample, to resolve a current title by samples-list membership, §7.10/R8);
  **`search_samples_by_uid(uids)` (new): `POST /samples/advanced_search/` with
  `{filter_searchText: uids, searchText_logic: "OR", filter_matchType: "EXACT"}` (no `attribute`),
  paged at `page_size <= 1000`, client-side filtered by `json_metadata.UID`; returns per sample the
  `json_metadata` attrs AND the current **assay titles** (the row's `assays` comma-separated field,
  §12) — the read-only retrieve for update-visibility AND assay carry-forward (§3/§7.10)**;
  **`validate_file(xlsx, project_id, checks)` (new): `POST /batch-upload/validate/`, multipart
  file mode, `checks` as a multipart form field**. **Deleted:** the per-UID `read_samples()` GET
  loop and the entire client-side merge/read-back path. No `start()`/`upload()`; structurally
  absent.
- **`_batch_upload_payload.py`** — flat-sheet builder: `json_metadata` (authoritative, includes
  `Parent`) + per-row `assay_ids`/`assay_titles` + materialized review columns; enforces exact DB
  attribute names, the create-vs-update/UID-aware required-attr population (§10), and non-emptiness.
  **Deleted:**
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
2. **Resolve `project_id` from identity, then confirm:** `GET /projects/` + `GET /people/current/`
   to pull every project the user can access; confirm the project with the curator before
   proceeding (match a curator-named project against the list, else present the list and ask);
   never silently auto-select, even when only one project is accessible; **refuse to proceed
   without a confirmed `project_id`** (validate requires it). The confirmed project scopes the
   assay-title resolution in step 4.
3. **Fetch the exact attribute schema** per sample type: `GET /sample_types/{uid}/` → full attribute
   objects (`title`, `required`, `is_title`, `base_type`). Persist the **structured** objects (not
   titles-only).
4. **Build the ONE accessible-assays `title → [IDs]` map (R5/R8):** `GET /assays/` (`{id, title}`, NO
   project/study id) → a `title → [IDs]` map; `GET /projects/{id}/` (`relationships.assays.data[].id`)
   is the collision TIE-BREAK set applied only when a title maps to >1 ID. Resolve the curator's
   NEW-addition assay titles → IDs via this map (still ambiguous after the tie-break → ask/refuse, fail
   closed); never guess an `assay_id`. (O(1) calls; supersedes per-assay fetches.)
5. **For updates, retrieve existing state (read-only):** call `search_samples_by_uid()`
   (advanced_search by the UID list, §8), client-side filtered to the requested UIDs. Two uses:
   (a) **visibility** — show current attribute values + the resulting overlay; (b) **assay
   carry-forward (LOAD-BEARING, §7.10)** — each row's `assays` titles → IDs (via the §7.6 map, with the
   Path-2 reverse-map fallback for same-project duplicate titles, R8) are the sample's current assay
   set, which the update row must carry forward (∪ additions) or the server WIPES it. For (a) `json_metadata` is partial-safe so a retrieve failure is non-fatal
   (§11); for (b) a retrieve failure means the skill must NOT emit a blank-assay update (it would
   wipe) — refuse or ask (§10/§11).
6. **Populate values** from the curator's info into the **exact DB attribute names** (the only keys
   allowed in `json_metadata`). `Parent` is one of those attributes like any other; its *value* is
   the parent's UID or Name. **Ask the curator** for any missing required/`is_title` value or any
   unresolved assay/parent; never invent, never guess DB-specific values.
7. **Build rows:** UID blank for a new sample / the existing NExtSEEK UID for an update
   (`update_existing` is an upload-request parameter, not a sheet field, so the sheet carries only
   the UID). Per-row `assay_ids`/`assay_titles`: for an **update**, `assay_ids` = the sample's
   current set (step 5) ∪ the curator's additions (SET/REPLACE, §7.10) — never blank on an update
   unless the curator explicitly clears; for a **new sample**, the curator-provided assays. The flat
   sheet with materialized review columns (§6). No scale cap.
8. **Validate the produced `.xlsx`** via `validate_file` (multipart **file mode**, the way it
   uploads), all three checks (`structure,name_check,dag`), passing `checks` as a **multipart form
   field** and asserting `checks_run` contains all three.
9. **Hard delivery gate** (§10).
10. **Deliver** to `/data/scratch/<user>/…` (the post-turn copier publishes to Dropbox); return the
    verdict + path + a per-type row summary. **Never upload.**

## 10. Validation & hard delivery gate (the data-safety core)

The skill validates the **artifact it delivers** (the `.xlsx`, file mode → server `convert.py`
traditional/flat parse + ontology), **not** internal JSON rows (rows mode bypasses Excel parsing).
The gate derives each row's attribute set and values by **orjson-parsing that row's `json_metadata`
cell** (the authoritative payload) and MUST ignore the flat `REVIEW_ONLY__` materialized columns for
every present/required/non-blank determination.

Deliver **only if all hold**. Create vs update is determined **per row by UID presence** (blank UID
= new sample; populated UID = existing sample being updated); `update_existing` is an upload-request
parameter, not a sheet field, so it is not part of this gate:
- `valid == true` and `errors[]` empty, **and**
- every row has ≥ 1 real (non-UID) `json_metadata` attribute **or** (for an update) a changed
  `assay_ids` set — an assay-only update satisfies non-emptiness (§7.10), **and**
- **new-sample rows (blank UID):** every **non-UID** `required==true` attribute is populated (`UID`
  is blank by design, the server auto-generates it; a blank non-UID required attribute REFUSES;
  optional attributes may be blank), **and**
- **update rows (populated UID):** every `json_metadata` attribute **present in the row** is
  non-blank; omitted required attributes are NOT required (the server deep-merge preserves them);
  `UID` is the identifier, **and**
- **assay superset-guard (update rows, R6/R7/§7.10):** for every assay-touching update row the
  per-UID current-assay manifest MUST have a **fresh, retrieve-verified entry**; a missing, empty
  (unless the retrieve *positively confirmed* zero assays), or retrieve-degraded entry **FAILS CLOSED
  (REFUSE) BEFORE the superset check** — because `delivered ⊇ ∅` is vacuously true, so
  manifest-completeness is verified first. **Truncation guard (fail-closed, before the superset
  check):** refuse any assay-touching row whose raw `assays` title string length is within a safety
  margin of the GROUP_CONCAT ceiling (concrete conservative threshold: refuse at raw length
  >= 900 chars; observed dev max = 387 chars / 9 titles vs a ~1024 ceiling), because a truncated title
  string silently under-resolves the current set and the ⊇ check cannot see it. Given a verified,
  non-truncated entry, the delivered `assay_ids` must be a **superset of the manifest-current set**,
  else REFUSE (the server SET/REPLACE deletes the missing ones). The only shrink path is an explicit
  **per-UID** `--confirm-clear-assays <UID…>` opt-in (no default; scoped to the named UIDs, never a
  global guard-disable). This catches a blank OR delivered-vs-resolved-incomplete set AND a soft
  retrieve gap AND a truncation-suspect row; it does NOT catch a title genuinely absent from the
  retrieved string below the truncation threshold (a documented low-likelihood residual on the dev
  evidence, covered by the §14 pre-merge live-fidelity confirmation), **and**
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
- **Retrieve (advanced_search) failure on an update:** non-fatal for `json_metadata` **visibility**
  (partial-safe; surface a degraded-visibility note and proceed), but **fatal for ANY update row**
  (metadata-only included — the server diffs assays on every update row) — without the verified
  current assay set the skill cannot carry it forward, so it must REFUSE or ask, never emit an
  assay-losing update. A **null/absent `assays` field on a matched row is treated as a retrieve
  failure, NOT an empty current set** (only a positively-confirmed empty result is a real zero-assay
  sample); pagination must be complete before any assay-touching update is built.
- **Validate endpoint error / non-200:** surface verbatim; do not deliver.

## 12. API contract (verified against the deployed dev OpenAPI spec, 2026-06-30)

All calls use **HTTP Basic** (`NEXTSEEK_USERNAME`/`NEXTSEEK_PASSWORD`, with `API_USER`/`API_PASS` as
the legacy fallback when the NEXTSEEK_* pair is unset — owner-decided precedence 2026-07-02), the only
scheme accepted across every endpoint in this flow. Parse/serialize with **`orjson`**.

- `POST /nextseek_api/batch-upload/validate/` — synchronous, **side-effect-free** (runs TRANSFORM,
  stops before INSERT). Two input modes: `application/json` body `BatchUploadStartRequest` (`rows[]`)
  or `multipart/form-data` with the `.xlsx` under the `file` key (if both, rows wins). `project_id`
  is **required** (the only required field). **`checks` is a multipart FORM field** (`type: string`,
  default `structure`; comma-separated subset of `structure,name_check,dag`), not a JSON body field;
  the `?checks=` query form appears only in prose, so the form field is authoritative (verify query
  support live if ever needed). Response `ValidationResult` (200): required `[totals, valid, summary,
  checks_run]`; `valid` true iff `errors[]` empty and `totals.error` null;
  `totals.{processed,success,skipped,failed}`; `checks_run[]`; `job_id`/`summary_path` always null.
  200 MB upload cap → 413 (file mode). **The skill uses file mode** and passes `checks` as a form
  field.
- `POST /nextseek_api/samples/advanced_search/` — the read-only retrieve for update-visibility.
  Request `SampleAdvancedSearchRequest`: `filter_searchText` (string **or list**, required),
  `searchText_logic` (`AND`/`OR`), `filter_matchType` (`PARTIAL`/`EXACT`), optional
  `attribute`/`sampletype`. To fetch a known UID set: `{filter_searchText: [<UIDs>],
  searchText_logic: "OR", filter_matchType: "EXACT"}` with **no `attribute`** (verified live: adding
  `attribute:"UID"` to a list+OR query returns 0 rows). Query params `page` (1-based), `page_size`
  (default 100, max 1000). Response `SampleAdvancedSearchResult` `{total, rows[]}`; each
  `SampleAdvancedSearchRow` (additionalProperties; real fields verified live) carries `json_metadata`
  (the full attribute object — use it, **not** the HTML `attributeValue`/`uid`/`idlink` fields);
  `title` and `uuid` = the clean UID string (also `json_metadata.UID`); a **top-level numeric SEEK
  `id`** = the sample's numeric SEEK row id, DISTINCT from the `json_metadata.UID`/`uuid`/`title` UID
  strings, used as the Path-2 samples-list membership JOIN KEY (build-plan DD-13). *(VERIFIED live
  against nextseek-dev 2026-07-02 — evidence
  `evidence/batch-upload-path2-probe/20260702/advanced_search_row_shape.json`: the row for
  `D.IMG-230913ENG-1757-PUB` carried top-level `id`=324503. It is an **INT**, whereas the assay
  `relationships.samples.data[].id` values are **STRINGS** (JSON:API resource ids), so the Path-2
  membership join MUST normalize both sides to the same type (`str==str` or int==int), NEVER `int==str`
  — an `int == str` compare is always False, so the sample matches no candidate and the SET/REPLACE
  update silently wipes the sample's assays (build-plan DD-13 / T1 / T3 gate). Owner-resolved
  2026-07-02; W0 re-captures it as a belt-and-suspenders build-time confirmation against the
  then-current data.)* And **`assays` = a
  COMMA-SEPARATED STRING of the sample's current assay TITLES** (e.g. `"Tissue Collection -
  Metadata,Flow Cytometry - Data Linked"`) — the assay carry-forward source (§7.10), resolved to IDs
  via the §7.6/R8 one accessible-assays map (with the Path-2 reverse-map fallback for same-project
  duplicate titles). Client-side filter rows to `json_metadata.UID` in the requested
  set (an EXACT free-text UID can also hit a sample referencing it as `Parent`). *Robustness: if a
  project assay title can contain a comma, match tokens against the known project title set rather
  than a naive split (verify at build time).* *Verified live on dev 2026-06-30.*
- `GET /nextseek_api/sample_types/` (list) and `GET /nextseek_api/sample_types/{uid}/` (`{uid}` =
  type code e.g. `TIS` **or** numeric SEEK id). The latter returns `data.attributes.
  sample_attributes[]`; each attribute object carries **top-level `required` and `is_title`
  booleans**, `pos`, `unit`, `sample_attribute_type.base_type` (nested: `Text`/`Float`/`Integer`/
  `Date`), and `sample_controlled_vocab_id` (null = free-text). *(Verified live: TIS has 90
  attributes; `Parent` is `sample_attributes[5]`, required=false, Text.)*
- `GET /nextseek_api/projects/` (list, `{id, title}`) and `GET /nextseek_api/assays/` (list, all
  accessible assays as `{id, title}` — 324 on dev; list items carry NO project/study id). **Assay
  resolution (R5/R8) builds ONE `title → [IDs]` map from `GET /assays/`** and uses
  **`GET /projects/{id}/` → `relationships.assays.data[].id`** (the confirmed project's assay IDs) only
  as the collision **TIE-BREAK** set — **NOT** a per-assay `GET /assays/{id}/` fetch for resolution
  (superseded, §7.6). For a CURRENT title left ambiguous after the tie-break, **Path 2** fetches
  `GET /assays/{id}/` → `relationships.samples.data[]` for ONLY the ambiguous candidate IDs (never all
  project assays, never per-sample) and resolves by samples-list membership (§7.10/R8).
  `GET /nextseek_api/people/current/` — the logged-in person (`data.id` = caller's SEEK person id).
- `InputRowModel` required fields: `SampleType`, **`json_metadata` (a required JSON STRING**, built
  with `orjson.dumps(...).decode()`). Present-but-optional: `UID`, `assay_ids`, `assay_titles`,
  `project_id`. `additionalProperties: true` (materialized review columns ride alongside and are
  dropped server-side).
- **Build-time live re-checks still owed:** deep-merge null/removal semantics on `update_existing`;
  the `update_existing` match key (UID vs Name); advanced_search pagination at real scale; the
  runtime metadata key shape under load.

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
- **REQUIRED pre-merge live-fidelity confirmation ($0, read-only, owner-gated; not the paid live
  E2E):** a read-only `advanced_search` + authoritative-assay-link probe of a **duplicate-title**
  sample (e.g. `D.IMG-230913ENG-1757-PUB` / "Comet Chip Analysis - Data Attached" → {351, 260})
  positively confirms `resolve(advanced_search.assays) == the sample's authoritative DB assay-link ID
  set` and that the committed fixture's `assays` parse matches live; it persists an evidence artifact
  and exits non-zero on mismatch, and **merge is gated on it** (it is the backstop for the assay
  under-resolution residual R6/§7.10 documents, since the paid live E2E is held indefinitely). This is
  a mechanized gate, not a prose obligation (the build plan owns it as a numbered task).
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
  `fastexcel`), **write** via `xlsxwriter` (`polars.write_excel`); never `openpyxl`. **JSON parse/
  serialize via `orjson`** (host + image), never stdlib `json`: NExtSEEK responses are large (the
  TIS schema alone is ~411 KB) and stdlib `json` is too slow.
- The skill targets the **deployed dev-server** NExtSEEK contract (`https://nextseek-dev.mit.edu`),
  the owner-designated source of truth, verified live 2026-06-30, not read from on-disk source
  (which may have drifted from deploy).

## 16. Open boundary items (explicit, for the owner)

- **B-1:** the skill trusts the curator's per-row assay associations and does not compute/enforce
  the both-endpoints union (§4). A warn-on-likely-un-annotated-edge feature is a possible future
  enhancement, out of V1 scope unless the owner asks.
- **B-2:** controlled-vocabulary/Ontology handling is out of V1 (§7.4).
