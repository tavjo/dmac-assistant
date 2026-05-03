---
name: nextseek
description: >
  Modular NExtSEEK query workflow. Trigger whenever the user types /nextseek,
  asks to query NExtSEEK, find a sample, look up a project, run a graph
  lineage query, or generate a GEO/SRA/nf-core/PRIDE submission. This skill
  orchestrates 8 plugin tools (entity-extract, parse, plan, api-read,
  api-write, graph, report, generate-submission) backed by chat_nextseek
  (pinned). The skill's
  job is routing — Container-Claude reads cached catalogs, picks tools, and
  writes the user-facing reply. The plugin's job is execution.
disable-model-invocation: false
---

# nextseek

Modular NExtSEEK query workflow. Read this entire file before taking any action.

---

## Always-first preamble

For every `/nextseek <text>` invocation, FIRST run:

```bash
nextseek-entity-extract --query "<user's full question>"
```

Returns: `{ "sampletypes": [...], "assays": [...], "keywords": [...], "projects": [...] }`. This grounds every subsequent tool call. **Never skip.** Even system-y questions ("what can I ask?") run entity-extract first — the cost is small and the grounding signal is the whole point.

## Catalog access

Read these files via the Read tool to ground routing decisions:

- `/app/plugins/nextseek/context/min_api_endpoints_enriched.json` — endpoint catalog (pick the operation_id).
- `/app/plugins/nextseek/context/min_sampletypes_db.json` — sampletype vocabulary.
- `/app/plugins/nextseek/context/min_assays_db.json` — assay vocabulary.
- `/app/plugins/nextseek/context/projects_db.json` — project list.
- `/app/plugins/nextseek/context/neo4j_schema.json` — Neo4j schema for graph queries.
- `/app/plugins/nextseek/context/capabilities.md` — user-facing capability doc.

Prefer reading the cached catalogs over running tools to "describe capabilities."

## Tool catalog

| Tool | Use when |
|---|---|
| `nextseek-entity-extract` | ALWAYS, first thing. |
| `nextseek-parse` | Single-shot routing — you want one mode + filters for a quick query. |
| `nextseek-plan` | Multi-step query — returns a structured plan you execute by calling the other tools yourself. |
| `nextseek-api-read` | Run an audited read-safe API request from a parser plan. |
| `nextseek-api-write` | Run an explicit write-class API request after L1/L2/L3 confirmation. |
| `nextseek-graph` | Lineage / structural queries (NL → Cypher → Neo4j). |
| `nextseek-report --mode <samples\|protocols\|published\|rppr> --project <NAME>` | Project summary reports. |
| `nextseek-generate-submission --type <GEO\|SRA\|NFCORE_RNASEQ\|NFCORE_SCRNASEQ\|PRIDE> --uids <csv>` | Generate a submission file. |

## Routing decision tree

1. If the user's question matches "what can I ask / what do you have / what's a sampletype / what are the assays" — answer from the catalogs directly. No tool call needed beyond entity-extract.
2. Single-shot data lookup ("find me X", "how many Y in Z") → `nextseek-parse` then `nextseek-api-read` when the parser plan resolves to a read-safe endpoint (or `nextseek-graph` if structural).
3. Multi-step ("find samples X then look up their lineage") → `nextseek-plan` for the plan; execute each step yourself with the other tools.
4. Project summary → `nextseek-report`.
5. Submission generation → `nextseek-generate-submission` (heavy; only on explicit user ask).

## Reply hygiene

After tool runs:
- Quote the **host-side path** of any artifact produced. Read `DMAC_PATH_MAPPINGS` from the
  environment to translate container paths to host paths. The format is a JSON object mapping
  container roots to host roots (e.g., `{"/data/scratch": "/persistent/scratch/alice"}`). If
  `DMAC_PATH_MAPPINGS` is absent or unparseable, report the container path and note that the host
  mapping was unavailable.
- Do not dump raw JSON unless the user asks.
- Surface what the user asked, not what the tool returned verbatim.

## Write safety — 3 layers

Most NExtSEEK calls are read-only (GET). For non-GET operations:

- **Layer 1 (mechanical):** Claude Code's permission allowlist permits `nextseek-api-read` only. `nextseek-api-write` and any command containing `--confirmed-write` are not allowlisted, so the user sees a permission prompt CC cannot bypass.
- **Layer 2 (mechanical):** the `nextseek-api-write` shim refuses execution unless `--confirmed-write` is explicitly passed.
- **Layer 3 (behavioral, this skill):** **NEVER** call `AskUserQuestion` (`container/CLAUDE.md` forbids it; the chat UI doesn't render the widget). Instead, write plain text:

> "About to execute a WRITE-classified operation. Method: POST. Endpoint: /samples/<...>/. Body: {...}. **Confirm?**"

Then wait for the user's next message. If the user responds "yes" / "go ahead" / similar, invoke `nextseek-api-write` with `--confirmed-write`. If anything else, abort and acknowledge.

## Errors

The runner emits structured errors as one-line JSON to stderr with these codes:
- `CONFIG_MISSING` (exit 2): API_USER / API_PASS not set. Tell the user; do not retry.
- `IMPORT_FAILED` (exit 2): chat_nextseek not installed in the image. Surface a deploy-side message.
- `VALIDATION` (exit 3): bad CLI args. Fix the call.
- `AGENT_FAILED` (exit 4): LLM / network failure. Retry once; if still failing, surface to user.
- `WRITE_BLOCKED` (exit 5): write shim invoked without `--confirmed-write` or read shim received a non-read-safe endpoint. Apply L3 prompt only for true writes; otherwise fix routing.
- `CONFIG_ERROR` (exit 6): plugin context file (e.g., `read_safe_endpoints.json`) missing in image. This is a deploy-side issue; surface to the user as "plugin misconfiguration, please rebuild image."
