---
name: nextseek-batch-upload
description: >
  Build and validate a read-only NExtSEEK batch-upload workbook for sample create
  or update work. Use when preparing sample metadata rows, resolving upload
  project and assay context, or validating a workbook before human inspection.
---

# NExtSEEK Batch Upload

You prepare a flat create/update workbook and validate it. You do not submit it.
The safe output is the workbook path plus the validation result.

## Required Flow

1. Resolve the project with `nextseek-project-resolve`.
   Run `nextseek-project-resolve --name '<project name>' --out <token path>` — it queries the
   live `/projects/` API and resolves the exact title against the accessible projects,
   returning their ids and titles. Resolve by name, not typed id. Get curator-confirmed
   selection before use, then re-run with `--confirmed` to mint the token (when the curator
   already confirmed the named project in their request, run with `--confirmed` directly).
   Never auto-select, even when exactly one project exists, and never derive a project id
   from the cached catalogs under `context/` (for example `projects_db.json`) — they are
   stale snapshots, not authoritative; only this tool's live answer counts. Do not use any
   other nextseek-* tool for project lookup. Keep the non-secret confirmation token and pass
   it to validation.

2. Fetch the structured schema with `nextseek-sampletype-attrs`.
   Do this for every SampleType. Persist the structured schema, not just title
   strings, and use it for value population. If a required value is missing or
   ambiguous, ask for the missing value instead of inventing it.

3. Retrieve on update with `nextseek-sample-search`.
   A populated UID means an update. Retrieve the visible current sample row before
   building so the hard gate can preserve current assay links and refuse missing
   or degraded current-assay evidence.

4. Resolve assay titles with `nextseek-assay-resolve`.
   Use the accessible `/assays/` map and the selected project's assay set as the
   project tie-break. Fail-closed on ambiguity or zero matches for curator-added
   assay titles. Ask the curator instead of guessing.

5. Build the rows JSON.
   Each row has `UID`, `SampleType`, `attributes`, and optional `assay_ids` or
   assay titles. Blank UID creates a sample. Populated UID updates a sample.
   Values belong in `attributes`; the tools build canonical `json_metadata`.

6. Build only staged payloads with `nextseek-build-payload`.
   Use a non-scratch staging directory for build-only inspection. Do not hand-edit
   the sheet. If the user changes values, update the rows JSON and
   rebuild from the source rows so schema and gate checks still apply.

7. Validate in file mode with `nextseek-validate-upload`.
   Pass `--project-id` and the matching `--project-confirmation` token. The
   validator builds, posts the workbook in file mode, requires
   `structure,name_check,dag`, and then applies the runner hard gate. The hard
   gate checks server verdict, processed row count, structured schema-required
   values, populated update fields, current-assay manifest completeness, and
   delivered-assay superset safety.

8. STOP on failure.
   Any validation failure, hard gate refusal, missing project confirmation,
   schema problem, retrieve problem, assay ambiguity, or promotion failure stops
   the workflow. Fix the source rows or ask the curator, then rebuild and
   validate again.

9. Return the artifact for inspection.
   Report the validation verdict and the generated workbook path. Warn that
   update rows require `update_existing=true` during any later human-run upload,
   because the server default skips populated-UID updates. Flag mixed create+update
   sheets so the curator knows that setting matters.

## Forbidden Actions

POST .../batch-upload/start/ is forbidden. Never submit a batch, trigger write
actions, or treat validation as permission to write. This skill builds and
validates only.
