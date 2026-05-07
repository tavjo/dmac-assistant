---
name: nextseek
description: >
  NExtSEEK data query workflow. Trigger whenever the user asks to query
  NExtSEEK, find/list/show samples or projects, count samples ("how many",
  "list all", "show me", "which mice/samples..."), retrieve a sample by UID,
  look up a sample tree, run a graph lineage query, refine a previous search
  ("which of those..."), recall results from earlier in the conversation
  ("what sample types were in those results"), or ask what NExtSEEK can do.
  Default path is one `nextseek-query` call that runs the entire chat_nextseek
  pipeline in a single Python invocation and returns a final user-facing reply.
  Do NOT trigger on general bioinformatics questions, code/file edits,
  non-NExtSEEK data sources, or pure file-system tasks. For explicit writes
  (create/update/delete), submission generation (GEO/SRA/nf-core/PRIDE), and
  pipeline-stage debugging, see the escape-hatch section.
disable-model-invocation: false
---

# nextseek

NExtSEEK query workflow. Read this entire file before taking any action.

---

## Default path: `nextseek-query` (use this for ~95% of questions)

For any natural-language NExtSEEK question, the default action is **one** call:

```bash
nextseek-query --query "<user's full question verbatim>"
```

`nextseek-query` runs the entire pipeline (entity extraction, parser, API/memory/reporter/graph routing, NExtSEEK REST/Neo4j calls, final-reply composition) in a single Python invocation and **prints only the user-facing reply text to stdout** — exactly what should be surfaced to the user. No JSON parsing, no field extraction.

**Take the stdout as the reply, surface it, and stop.** Do not call any other `nextseek-*` tool unless the routing rules below say to. Do not run `nextseek-entity-extract`, `nextseek-parse`, or `nextseek-plan` first — `nextseek-query` does all of that internally. Do not pipe the output through `jq`, `python3 -c`, `grep`, or any extractor — the shim already does it.

If you need the full structured dict (parser_plan, api_plan, bundle_id, artifacts, files) — for debug-ladder inspection or to drive a downstream tool — add `--json`:

```bash
nextseek-query --query "..." --json
```

Then the dict is:

```json
{
  "reply": "<final user-facing answer text — what the user should see>",
  "debug": {
    "mode": "new_search | refine_last_search | ask_about_last_results | reporter | graph_query | system_question | unsupported",
    "parser_plan": { ... },
    "api_plan": { ... }
  },
  "bundle_id": 42,            // int OR null when no bundle was created
  "artifacts": [ ... ],       // optional, present only if files were written
  "files": [ ... ]            // optional, present only if files were written
}
```

The `--json` form is rarely needed. Use it only when SKILL.md routing or escape-hatch §4 explicitly says to.

### Worked example (schematic — no real data)

When the user asks a NExtSEEK data question, your invocation pattern is:

```bash
nextseek-query --query "<the user's full question, verbatim, in double quotes>"
```

Stdout is plain text — a final user-facing reply that the pipeline composed. Surface it as-is. The shape will look something like:

```
Found <N> <sampletype> samples matching <criteria>.

<formatted result list, table, or summary the chatter agent produced>

<optional follow-up offer, e.g. "Would you like me to export to /data/scratch/?">
```

That's it. One tool call, one answer. Do not validate the count, fabricate UIDs, or fill in numbers from your own knowledge — surface only what `nextseek-query` returned. If the reply references a file path, translate it via `DMAC_PATH_MAPPINGS` per "Reply hygiene" below before sending.

### When to add `--planner`

Use `nextseek-query --query "..." --planner` only when the user asks a compound question that explicitly requires multi-step execution. The pattern is "do X, **then** do Y where Y depends on X's results" — e.g. "find <criterion>, then look up the lineage of those" or "list <kind> from <project> and compare against <published artifact>".

Heuristic: if the user's question contains a sequencing conjunction ("then", "and then", "after that", "based on those results, …"), pass `--planner`. Otherwise omit it (the standard pipeline is faster).

`--planner` is read-class only — `run_query_plan` routes through the same read-only API surface as the standard pipeline (`nextseek-api-read`-equivalent calls), never `nextseek-api-write`. If the planner advises a write, the orchestrator stops and surfaces the proposed write in the `reply` for the user to confirm; you must then drop into `nextseek-api-write` with the L3 protocol below.

### Refinement and memory queries

`nextseek-query` reads session state from the SQLite session DB on every call. So follow-up questions that use demonstratives ("which of those …", "what … were in those results", "narrow that to …", "tell me more about #3") are **the same single tool call** — just pass the new question verbatim:

```bash
nextseek-query --query "<the user's follow-up question, verbatim>"
```

The parser routes this to `refine_last_search` or `ask_about_last_results` automatically because the prior `bundle_id` is in the session DB. Do NOT manually pass prior context — the pipeline handles it.

**Edge case — demonstrative without prior bundle**: if the user asks "which of those…" / "what sample types were in those results…" but there is no prior `bundle_id` in the session, `nextseek-query` will return `debug.mode == "unsupported"` (or an empty result). Do NOT silently retry with a guessed query; reply to the user with: "I don't have a prior search to refine — please run a fresh search first (e.g. 'Find me X')."

---

## When NOT to use `nextseek-query` — the four escape-hatch categories

Drop into a fine-grained tool only in these explicit cases:

### 1. Writes (POST/PUT/DELETE)

`nextseek-query` is read-only. For any operation that creates, updates, or deletes data on the NExtSEEK server, route through `nextseek-api-write` and apply the **3-layer write safety** below. Layer 1 (Claude Code permission allowlist) blocks `nextseek-api-write` unless explicitly approved by the user; Layer 2 (the shim) refuses without `--confirmed-write`; Layer 3 is the behavioral protocol in this file.

### 2. Submission generation

GEO / SRA / nf-core / PRIDE submission files are produced by `nextseek-generate-submission`. These are heavy, side-effecting operations the user must request explicitly:

```bash
nextseek-generate-submission --type <GEO|SRA|NFCORE_RNASEQ|NFCORE_SCRNASEQ|PRIDE> --uids <UID-1,UID-2,...>
```

### 3. Project summary reports

`nextseek-query` will route project summary asks through the reporter agent automatically. Use the standalone `nextseek-report` only when the user explicitly says "build me the report" with a known project name AND mode:

```bash
nextseek-report --mode samples --project IMPACT
nextseek-report --mode rppr --project IMPACT
```

Modes: `samples`, `protocols`, `published`, `rppr`.

### 4. Debugging / structured plan inspection

If `nextseek-query` returns a `reply` you don't trust (e.g. routing to `unsupported` when it shouldn't, or empty results that look wrong), THEN you may probe the pipeline stages individually:

| Tool | Purpose |
|---|---|
| `nextseek-entity-extract --query "<text>"` | See what sampletypes/assays/keywords were extracted |
| `nextseek-parse --query "<text>"` | See the parser plan (mode, target endpoint, filters) |
| `nextseek-plan --query "<text>"` | See the multi-step planner output. Executes read-only steps and returns advisor recommendations; never executes writes. |
| `nextseek-api-read --parser-plan '<json>'` | Manually execute a read-safe API call from a parser plan. Only endpoints in `read_safe_endpoints.json` are accepted; others exit `WRITE_BLOCKED` (5). |
| `nextseek-graph --query "<text>"` | Manually run a Neo4j Cypher lineage query |

Use these as a debugging ladder, not a default workflow.

---

## Catalog access (still relevant for capability questions)

For pure capability questions ("what can I ask?", "what sampletypes do you have?", "what assays are tracked?"), prefer reading the cached catalogs directly via the `Read` tool — no nextseek-* call needed:

- `/app/plugins/nextseek/context/min_api_endpoints_enriched.json` — endpoint catalog.
- `/app/plugins/nextseek/context/min_sampletypes_db.json` — sampletype vocabulary.
- `/app/plugins/nextseek/context/min_assays_db.json` — assay vocabulary.
- `/app/plugins/nextseek/context/projects_db.json` — project list.
- `/app/plugins/nextseek/context/neo4j_schema.json` — Neo4j schema.
- `/app/plugins/nextseek/context/capabilities.md` — user-facing capability doc.

For *data* questions ("find me mice with X", "how many Y in Z"), always use `nextseek-query` instead — the catalogs alone won't answer those.

---

## Reply hygiene

After any `nextseek-*` call:

- The user-facing answer is always the `reply` field (for `nextseek-query`) or composed by you from the tool's structured output (for fine-grained tools). Surface what the user asked for, not raw JSON.
- Quote the **host-side path** of any artifact produced (file written under `/data/scratch/`, submission file, report). Read `DMAC_PATH_MAPPINGS` from the environment to translate container paths to host paths. Format is a JSON object mapping container roots to host roots (e.g. `{"/data/scratch": "/persistent/scratch/alice"}`). If `DMAC_PATH_MAPPINGS` is absent or unparseable, report the container path and note that the host mapping was unavailable.
- Do not dump raw JSON unless the user explicitly asks ("show me the parser plan", "show me the API response").
- Do not narrate intermediate steps ("calling entity-extract... calling parser..."). The pipeline runs internally; the user sees one tool call and one answer.

---

## Write safety — 3 layers

For non-GET operations (`nextseek-api-write`, write-class endpoints):

- **Layer 1 (mechanical, deployment-dependent)**: a Claude Code permission allowlist that gates `nextseek-api-write`. **In the dmac-assistant bridge POC, the in-container Claude runs with `--dangerously-skip-permissions` (per the host bridge's launch command), so Layer 1 is BYPASSED here.** Layer 1 only applies in deployments that omit `--dangerously-skip-permissions` AND ship a `Bash(nextseek-api-write:*)` deny rule. Treat L1 as defense-in-depth, not as a guarantee — the load-bearing layers are L2 and L3.
- **Layer 2 (mechanical, always on)**: the `nextseek-api-write` shim refuses execution unless `--confirmed-write` is explicitly passed (`_nextseek_runner.py` line 179–181). Cannot be bypassed by the in-container agent.
- **Layer 3 (behavioral, this skill — load-bearing)**: NEVER call `AskUserQuestion` (`container/CLAUDE.md` forbids it; the chat UI doesn't render the widget). Instead, write plain text:

> "About to execute a WRITE-classified operation. Method: POST. Endpoint: /samples/<...>/. Body: {...}. **Confirm?**"

Then wait for the user's next message. If the user responds "yes" / "go ahead" / similar, invoke `nextseek-api-write` with `--confirmed-write`. If anything else, abort and acknowledge.

---

## Errors

The runner emits structured errors as one-line JSON to stderr with these codes (exit code in parens):

- `CONFIG_MISSING` (2): `API_USER` / `API_PASS` not set. Tell the user; do not retry.
- `IMPORT_FAILED` (2): `chat_nextseek` not installed in the image. Surface a deploy-side message.
- `VALIDATION` (3): bad CLI args. Fix the call.
- `AGENT_FAILED` (4): LLM / network failure. Retry **once** with the exact same call; if still failing, surface the error to the user with the structured payload.
- `WRITE_BLOCKED` (5): write shim invoked without `--confirmed-write`, OR `nextseek-api-read` received a non-read-safe endpoint. Apply the L3 prompt only for true writes; otherwise fix routing.
- `CONFIG_ERROR` (6): plugin context file (e.g. `read_safe_endpoints.json`) missing in image. Deploy-side issue; surface as "plugin misconfiguration, please rebuild image."
