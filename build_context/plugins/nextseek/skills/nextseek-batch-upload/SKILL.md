---
name: nextseek-batch-upload
description: >
  Build (never submit) a NExtSEEK batch-upload payload to create or update samples.
  Use when the user asks to prepare/build/validate an upload or update sheet/payload
  for NExtSEEK samples, or to add/update sample metadata, from chat info or files in
  /data/projects. Triggers on: "build an upload", "prepare a batch upload", "validate
  an upload payload", "add sample metadata", "update sample metadata", "create upload
  workbook", "prepare update payload". Read-only: validates via the API but never
  uploads.
---

# NExtSEEK Batch-Upload Payload Builder

You build a NExtSEEK batch-upload **create/update payload** and validate it. You NEVER upload it.
`POST .../batch-upload/start/` is **FORBIDDEN**; you have no tool for it, so do not attempt it.

## Procedure (follow in order)

1. **Understand the request.** New samples, updates, or both? Which sample type(s)? Which project?
   Source = the user's message and/or files under `/data/projects/<project>/` (read-only).

2. **Resolve the project id.** Use `nextseek-sampletype-attrs --list` and a projects lookup; if
   ambiguous, ask the user.

3. **Fetch the attribute list (MANDATORY, first).** For EACH sample type:
   `nextseek-sampletype-attrs --type <TYPE>`. Use ONLY these attribute names; never invent them.
   Save the fetched titles per sample type into a JSON object
   `{"<TYPE>": ["<title>", ...], ...}` (e.g. `/data/scratch/<user>/<run>/known_attrs.json`)
   and pass it as `--known-attrs` in steps 7–8, so the tools reject any invented attribute name
   deterministically.

4. **Read unstructured inputs if provided.** For a protocol, PDF, or docx the user points at:
   `nextseek-extract-text --file /data/projects/<...>` and read the missing/changed values from
   the text.

5. **For UPDATES, fetch the existing sample and MERGE.** `nextseek-sample-read --uid <UID>` for
   each updated sample. Save each sample's current attribute map into a JSON object keyed by UID
   `{"<UID>": {<title>: <value>, ...}, ...}` (e.g.
   `/data/scratch/<user>/<run>/existing.json`) and pass it as `--merge-existing` in steps 7–8;
   the tools deterministically carry forward ALL current attributes and overlay your changes, so
   the payload has the FULL attribute set. NExtSEEK silently removes attributes you omit on an
   update, so the full merge is mandatory.

6. **Apply the UID rule.** New sample → leave `UID` blank. Update → set `UID` to the existing
   sample's UID. The UID column must equal `json_metadata.UID`.

7. **Build the payload.** Write a rows JSON, one object per sample:
   ```json
   {"UID": "<blank-for-new or existing-UID-for-update>",
    "SampleType": "<TYPE>",
    "attributes": {"<title>": "<value>", ...},
    "assay_ids": [...]}
   ```
   (The tools normalize it into NExtSEEK `json_metadata` rows; do not hand-build `json_metadata`.)

   Then run:
   ```
   nextseek-build-payload \
     --rows <rows.json> \
     --known-attrs <known_attrs.json> \
     [--merge-existing <existing.json>] \
     --out /data/scratch/<user>/<run>
   ```

   Always pass `--known-attrs`. Pass `--merge-existing` for any update. Omit `--format` to use
   the default: single sample type → 4-sheet workbook; multiple types → flat single-sheet xlsx.
   Never output JSON unless the user explicitly asks for the programmatic JSON rows.

8. **Validate (MANDATORY, before returning).** Run:
   ```
   nextseek-validate-upload \
     --rows <rows.json> \
     --project-id <id> \
     [--update-existing] \
     --known-attrs <known_attrs.json> \
     [--merge-existing <existing.json>] \
     --out /data/scratch/<user>/<run>
   ```

   Validation always runs all three checks (`structure`, `name_check`, `dag`). If `valid` is
   false, fix the rows per `errors[]` and re-validate.

   **For UPDATES** (you passed `--update-existing` with a populated UID): a `name_check` finding
   that the Name "already exists" or is a duplicate is EXPECTED and is NOT a real problem. You are
   updating an existing sample, so its Name legitimately already exists. The `name_check` check
   flags already-existing Names to catch accidental CREATE duplicates, which does not apply to a
   deliberate update. Do NOT drop `name_check` to avoid it; instead, when you report the verdict
   in step 9, tell the user that on an update an "already exists" `name_check` finding is the
   normal/expected signal, so a `valid:false` driven only by that `name_check` finding on an
   update is not alarming.

9. **Return for inspection.** Tell the user the validation verdict and the artifact path(s). The
   files you wrote to `/data/scratch/<user>/<run>` are delivered to their Dropbox folder
   automatically by the bridge copier. NEVER upload. `POST .../batch-upload/start/` is
   **FORBIDDEN** — there is no tool for it and you must not attempt it.
