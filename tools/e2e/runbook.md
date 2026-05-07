# DMAC Assistant E2E Walkthrough Runbook

**Plan**: `dmac-assistant-e2e-ui-test-2026-05-06`
**Task**: T6 (Phase 6) — agent-driven walkthrough of the dmac-assistant chat UI.
**Authored by**: T4.
**Run date (this runbook)**: `2026-05-07` — substitute today's date if running on a different day; all `evidence/run-2026-05-07/` paths below should be adjusted accordingly.
**Audience**: a Claude Code agent session with `mcp__plugin_playwright_playwright__*` tools loaded.

This runbook is the operational checklist a Phase 6 agent follows to drive the chat UI through the 10 chat_nextseek queries, capture per-query observability, and emit one `QueryRecord` JSON per query under `evidence/run-2026-05-07/`. The judge step (T7) consumes those JSONs later — this runbook does NOT invoke the judge; it only documents the contract T7 must use (Section 9).

---

## §0. Background you must read first

### 0.1 Corpus (10 queries, executed in this order)

| # | ID | Pipeline / what it exercises |
|---|---|---|
| 1 | `Search-Basic-1` | new_search — keyword + sampletype routing |
| 2 | `Search-Refine-1` | refine_last_search — depends on prior search state (session DB) |
| 3 | `Memory-1` | ask_about_last_results — analytical memory query (session DB) |
| 4 | `Retrieve-1` | direct sample retrieval by UID/identifier |
| 5 | `SampleTree-1` | NExtSEEK REST sample tree endpoint |
| 6 | `Graph-Lineage-1` | Neo4j graph lineage traversal |
| 7 | `Reporter-Summary-1` | MySQL aggregation via reporter |
| 8 | `Report-GEO-1` | MySQL + report_generation (GEO submission export) |
| 9 | `Write-Create-1` | NExtSEEK REST POST (write path) |
| 10 | `Unsupported-1` | negative control — refusal of off-topic query |

The exact `query_text` and `pass_criteria` for each ID come from `evidence/run-2026-05-07/queries.json` (produced by T1). Read that file at the start of the run; do NOT reproduce the prompts inline anywhere.

### 0.2 Dependency chain (load-bearing for crash handling)

`Search-Refine-1` (#2) and `Memory-1` (#3) BOTH require the session DB to contain results from a prior `new_search`. Concretely:

- #2 depends on #1.
- #3 depends on #2 having executed against the state #1 produced.

All 10 queries run **sequentially in a single chat session / single browser tab**. Do NOT open a second tab, do NOT log out and back in between queries (except as required by the crash-recovery rules in §8).

### 0.3 Run-directory layout (created by you as you go)

```
evidence/run-2026-05-07/
  queries.json                       # T1 output (read-only input here)
  query-01-Search-Basic-1.json       # one per query, written by you
  query-02-Search-Refine-1.json
  ...
  query-10-Unsupported-1.json
  transcripts/
    query-01.jsonl                   # the per-turn slice of session JSONL (or full session JSONL pointer)
    ...
  screenshots/
    query-01.png                     # browser_snapshot output
    ...
```

### 0.4 Mount contract (load-bearing for cost / tool-use capture in §5 and §6)

| Container path | Host path |
|---|---|
| `/data/projects/{name}` | `~/Library/CloudStorage/Dropbox/DMAC_Data/{name}` (`ro`) |
| `/data/scratch` | `/persistent/scratch/{user_id}` (`rw`) |
| `/home/user/.claude` | `/persistent/claude-users/{user_id}/.claude` (`rw`) |

Concretely for the demo user, the session JSONL the agent reads from the **host** is at:

```
/persistent/claude-users/demo/.claude/projects/<sid-dir>/<sid>.jsonl
```

The `<sid-dir>` directory name is discovered at runtime per §5.1.

---

## §1. Pre-flight: MCP tool sanity check (Step 1 — DO NOT SKIP)

Before doing anything else — before reading queries.json, before checking the bridge, before logging in — verify the playwright-mcp tool is actually loaded and responsive. (Mitigates Finding 8 / OP-2: a previous run wasted setup work because MCP wasn't available.)

```text
# Tool call:
mcp__plugin_playwright_playwright__browser_navigate
  url: about:blank
```

**If the call succeeds** (returns a snapshot or success indicator): proceed to §2.

**If the call fails** for any reason (tool not registered, error response, exception, timeout):

1. STOP. Do NOT attempt any other browser_* tool.
2. Surface the failure to the user with the exact error message returned. Suggested phrasing:
   > "MCP playwright pre-flight failed: `mcp__plugin_playwright_playwright__browser_navigate` against `about:blank` returned `<error>`. Cannot proceed with E2E walkthrough — MCP playwright server is not available in this session. Please check `.mcp.json` registration and restart Claude Code, then re-dispatch the runbook agent."
3. Do not attempt workarounds. Do not fall back to `subprocess` calls or other browser drivers — those are out of scope per §0 of the plan.

---

## §2. Pre-flight checklist (run after §1 succeeds)

Verify each item below before sending the first query. Treat any miss as an abort condition (see §10).

| # | Item | How to verify | Expected |
|---|---|---|---|
| 1 | Image present locally | `docker images dmac-assistant:e2e-2026-05-07 --format '{{.ID}}\t{{.CreatedAt}}'` | non-empty; image SHA recorded in plan execution log by T5 |
| 2 | Bridge URL responsive | `curl -sf http://127.0.0.1:8000/health` (or load `http://127.0.0.1:8000/` in browser) | HTTP 200 / login page renders |
| 3 | Port 8000 not held by something else | `lsof -i :8000` | the bridge process (uvicorn) is the only listener |
| 4 | Demo creds in `DMAC_USERS` | env var `DMAC_USERS` parses as JSON containing key `"demo"` with `password`, `nextseek_username`, `nextseek_password` | yes |
| 5 | T1 corpus file present | `test -f evidence/run-2026-05-07/queries.json` | exists; contains 10 entries |
| 6 | Run-output directories exist | `mkdir -p evidence/run-2026-05-07/transcripts evidence/run-2026-05-07/screenshots` | success |
| 7 | Host claude-users tree exists for demo | `test -d /persistent/claude-users/demo/.claude/projects/` | exists (will be populated after first query) |

Any missing item: HALT and report to user. Do NOT auto-create the bridge or rebuild the image — those are out of scope here.

**Image hash recording**: capture the output of step 1 and include it in the final report (T7 will read it from `evidence/run-2026-05-07/_meta.json` if you choose to write one — optional but recommended).

---

## §3. Per-query MCP tool sequence

For each query `N` in 1..10, in order, execute the following sequence. Each step lists the exact MCP tool name and the relevant inputs.

### 3.1 Navigate (only on query #1; subsequent queries reuse the same tab)

```text
mcp__plugin_playwright_playwright__browser_navigate
  url: http://127.0.0.1:8000
```

Then log in as `demo` using the credentials from `DMAC_USERS["demo"]` — fill the username/password fields with `browser_type` and click the submit button with `browser_click`. (Use `browser_snapshot` first to discover the actual form selector text — the bridge UI may evolve.)

After login, you should land on the chat view with an empty composer. Take a baseline `browser_snapshot` and store it as `evidence/run-2026-05-07/screenshots/00-baseline.png`.

### 3.2 Type the query

Read `query_text` for query #N from `evidence/run-2026-05-07/queries.json`. Then:

```text
mcp__plugin_playwright_playwright__browser_type
  element: <chat composer textbox>
  ref: <accessibility ref from latest snapshot>
  text: <query_text from queries.json[N-1]>
  submit: false                       # we press Enter ourselves so we control timing
```

### 3.3 Capture started_at, then send

**Capture wall clock immediately before pressing Enter** (used for `started_at` — §4):

```python
# Pseudocode for the agent's bookkeeping:
started_at = utcnow_iso8601()        # e.g. "2026-05-07T14:32:11.482Z"
```

```text
mcp__plugin_playwright_playwright__browser_press_key
  key: Enter
```

### 3.4 Wait for completion signal

Use `browser_wait_for` against a stable completion signal in the UI. The exact signal text/selector depends on the UI; common signatures to look for in the latest snapshot, in priority order:

1. The composer (textbox) becomes re-enabled after being disabled during streaming.
2. A "Stop" button disappears, OR a "Send" button reappears.
3. The last assistant message bubble is followed by an idle indicator (no spinner, no "Thinking…" text).

```text
mcp__plugin_playwright_playwright__browser_wait_for
  text: <stable completion text e.g. "Send">      # or a "textGone" criterion for "Thinking…"
  time: 30                                          # seconds; 30s is the abort threshold (§10)
```

If `browser_wait_for` times out → mark the query as crashed; record `error="completion-signal-timeout"`, `latency_seconds=null`, `ui_answer=null`, then apply the dependency-chain rules in §8.

### 3.5 Capture completed_at and snapshot

Immediately after `browser_wait_for` resolves:

```python
completed_at = utcnow_iso8601()
latency_seconds = (completed_at - started_at).total_seconds()
```

```text
mcp__plugin_playwright_playwright__browser_snapshot
```

Save the snapshot output (or a `browser_take_screenshot` PNG) to:

```
evidence/run-2026-05-07/screenshots/query-{N:02d}.png
```

Also extract the **user-visible final assistant reply text** from the snapshot (the text the user would read in the chat bubble). This becomes the `ui_answer` field. If the reply text is unrecoverable (crashed mid-stream, blank bubble), set `ui_answer=null` and populate `error`.

---

## §4. Latency capture

Already covered inline in §3.3 and §3.5, but re-stating for clarity:

- `started_at` = UTC ISO-8601 timestamp captured **immediately before** the `browser_press_key Enter` call (§3.3).
- `completed_at` = UTC ISO-8601 timestamp captured **immediately after** `browser_wait_for` resolves (§3.5).
- `latency_seconds` = `(completed_at - started_at).total_seconds()`.

Both are stored as ISO-8601 strings in the `QueryRecord`; `latency_seconds` is a non-negative float. For crashed queries, leave `started_at` populated, set `completed_at` to the time the timeout fired, and set `latency_seconds=null` (the schema allows `error` to be set instead — exactly one of the two must be populated).

Use `Z` (UTC) suffix; do not write local-time stamps.

---

## §5. Cost capture (sourced from session JSONL on host)

### 5.1 Discover `<sid-dir>` after the first query (one-time)

Cost data lives in the session JSONL written by the in-container Claude runtime. The directory name encodes the project the session attached to and is NOT predictable in advance — it must be discovered at runtime (Finding 9).

After query #1 completes (§3.5), shell out via the agent's normal Bash tool:

```bash
ls /persistent/claude-users/demo/.claude/projects/
```

Expected output: one or more directory names (typically one per active project). Pick the directory whose `mtime` is most recent — that is the session that just handled query #1. Record it once at the top of your bookkeeping for the rest of the run:

```python
sid_dir = "<the directory name picked>"
session_jsonl_dir = f"/persistent/claude-users/demo/.claude/projects/{sid_dir}"
```

If `ls` returns no entries, query #1 did not actually invoke Claude (likely a bridge failure) — mark query #1 as crashed and consult §8 for chain consequences.

### 5.2 Find the per-session JSONL file

Within `session_jsonl_dir`, list `.jsonl` files:

```bash
ls -t /persistent/claude-users/demo/.claude/projects/<sid-dir>/*.jsonl | head -1
```

The most-recently-modified file is the active session's transcript. Pin its path as `session_jsonl_path` for the rest of the run. **Do NOT switch to a new file mid-run** — if a new `.jsonl` appears later, that means a new session started, which only happens after a crash (§8).

### 5.3 Read `total_cost_usd` per query

Each query corresponds to one or more turns in the JSONL. The terminal `result` event for a turn includes `total_cost_usd`. Concretely, scan the JSONL for events shaped like:

```json
{"type": "result", ..., "total_cost_usd": <float>, "usage": {...}}
```

For each query #N, the per-query cost is the `total_cost_usd` from the `result` event whose turn corresponds to query #N's user message.

**Cumulative-vs-per-call disambiguation** (mandatory check on first two events): after query #2 completes, inspect the `total_cost_usd` values of the first two `result` events. Two cases:

- **Per-call**: the second value is roughly comparable in magnitude to the first (each is the cost of one turn). In this case `cost_usd = result_event.total_cost_usd` directly.
- **Cumulative**: the second value is strictly greater than the first AND approximately equals `first + (second_query_cost)`. In this case `cost_usd[N] = result_event[N].total_cost_usd - result_event[N-1].total_cost_usd` (for N ≥ 2; for N=1 the cumulative and per-call values coincide).

Pick the interpretation once based on the first two events and apply it consistently for queries #3 through #10.

### 5.4 IMPORTANT — verify event-name shape empirically before relying on it

The exact `result` event name and `total_cost_usd` field path are derived from Claude Code's `--output-format stream-json` documentation, but have NOT been verified against an actual dmac-assistant session JSONL by the author of this runbook. **The first thing the runbook agent should do after query #1 lands** is `head -50 <session_jsonl_path>` (or `jq` for one event of each `type`) and confirm:

1. The event with the cost field has `type == "result"` (and not e.g. `type == "turn_finished"`).
2. The cost field is named `total_cost_usd` (and not e.g. `cost_usd` at the top level or nested under `usage`).
3. `tool_use` events for §6 are top-level events with `type == "tool_use"` (and not nested inside an assistant message under `content[].type == "tool_use"`).

If the actual shape differs, **adjust the parsing and DOCUMENT the deviation in the run's `_meta.json`** so T7 / future runs know the canonical shape. Do not silently re-key the field — T3's aggregator and T7's report build on the same JSON structure.

If the cost field cannot be located at all, set `cost_usd=null` is NOT permitted by the schema — the field is `float >= 0`. In that case write `cost_usd=0.0` and add a note in `error` (e.g. `"cost-source-not-found-in-jsonl"`); T7 will surface this.

---

## §6. `tool_use_summary` capture (sourced from session JSONL — NOT from UI DOM)

The plan explicitly requires (Finding 12) that `tool_use_summary` is derived from the **same session JSONL** as the cost data, not from any UI DOM scrape. The UI DOM presentation of tool use is unverified and may be lossy or absent.

### 6.1 Per-turn slicing

For query #N, the relevant turn is bounded by:

- **Start**: the first event after the `user` message whose content matches `query_text[N]`.
- **End**: the next `result` event (the same one used for cost in §5.3).

Within that slice, count `tool_use` events. The exact event shape — top-level `type == "tool_use"` vs `assistant.content[].type == "tool_use"` — must be verified empirically per §5.4.

### 6.2 Aggregation shape

`tool_use_summary` is a `list[dict[str, Any]]` per the T2 `QueryRecord` schema. Aggregate the per-turn tool uses by tool name and emit one dict per distinct tool:

```json
[
  {"tool": "nextseek-api-read", "count": 2},
  {"tool": "Read", "count": 5},
  {"tool": "Bash", "count": 1}
]
```

The `tool` key holds the literal tool name as it appears in the JSONL (preserve plugin namespacing if present, e.g. `nextseek-api-read`, `mcp__nextseek-api-read`, etc.). `count` is the integer occurrence count within the per-query slice.

If no tool_use events exist in the slice (the assistant answered from prior context only), emit `[]`.

### 6.3 Plugin-fidelity is computed downstream — not here

Per DD-06, `plugin_fidelity` is a boolean computed by T3's aggregator from `tool_use_summary`. T6 (this runbook) does NOT compute `plugin_fidelity` — it just records the raw `tool_use_summary`. T6 sets `plugin_fidelity` to a placeholder (`true` is fine — T3 overwrites it during aggregation, OR T7 recomputes from `tool_use_summary` directly). If you prefer, leave `plugin_fidelity=False` as the conservative default — what matters is that `tool_use_summary` is faithful.

### 6.4 Per-query transcript file

After computing the slice, write the per-query slice (the raw JSONL events for that turn, one per line) to:

```
evidence/run-2026-05-07/transcripts/query-{N:02d}.jsonl
```

This is the value of `transcript_path` in the `QueryRecord` (relative to repo root or absolute — be consistent across all 10 records).

---

## §7. Per-query `QueryRecord` JSON write

Schema is `tools.e2e.schema.QueryRecord` (T2). 16 fields total: 13 walkthrough + 3 judge.

| Field | Type | Source |
|---|---|---|
| `query_id` | str | `queries.json[N-1].id` |
| `query_text` | str | `queries.json[N-1].query` |
| `started_at` | str (ISO-8601) | §3.3 |
| `completed_at` | str (ISO-8601) | §3.5 |
| `latency_seconds` | float ≥ 0 | §4 |
| `cost_usd` | float ≥ 0 | §5 |
| `answer_provided` | bool | true if assistant returned a non-empty user-visible message (incl. refusals); false if crashed/blank |
| `plugin_fidelity` | bool | placeholder (T3 / T7 recomputes); see §6.3 |
| `transcript_path` | str | §6.4 |
| `screenshot_path` | str | §3.5 |
| `tool_use_summary` | list[dict] | §6.2 |
| `error` | str \| None | null on success; descriptive string on crash |
| `ui_answer` | str \| None | §3.5 (final visible assistant text) |
| `judge_verdict` | enum \| None | leave `null` (T7 populates) |
| `judge_reasoning` | str \| None | leave `null` (T7 populates) |
| `judge_model` | str \| None | leave `null` (T7 populates) |

**Path convention for the per-query file**:

```
evidence/run-2026-05-07/query-{N:02d}-{query_id}.json
```

Example for query #1:

```
evidence/run-2026-05-07/query-01-Search-Basic-1.json
```

**Constraint enforced by schema**: at most one of `latency_seconds`/`error` may be null per record. Concretely, every record satisfies: NOT (`latency_seconds` is null AND `error` is null). The success criterion in T6's plan row is: "no record has both `latency_seconds=null` AND `error=null` (one of the two MUST be populated)" — enforce this before writing.

Write the file via the standard Python idiom:

```python
record = QueryRecord(...)             # validates via Pydantic
out_path = pathlib.Path(f"evidence/run-2026-05-07/query-{n:02d}-{qid}.json")
out_path.write_text(record.model_dump_json(indent=2) + "\n")
```

Write each record as soon as the query completes (or crashes) — do NOT batch writes at the end of the run, because a partial run (e.g. mid-run abort) must still leave a complete record set up to that point.

---

## §8. Crash and dependency-chain rules

The execution constraint from §0.2 is: queries #2 and #3 require the session-DB state from #1 (and #2 respectively). Crashes therefore break dependency chains and need explicit handling. (Finding 13.)

### 8.1 Query #1 crash

If `Search-Basic-1` crashes (timeout, error, blank reply, MCP failure mid-query):

1. Write the crash record for #1: `error="..."`, `latency_seconds=null`, `ui_answer=null`, `cost_usd=0.0`, `tool_use_summary=[]`.
2. Skip queries #2 and #3 entirely. Write skip records for both:
   ```json
   {
     "query_id": "Search-Refine-1",
     "error": "skipped-due-to-query-1-crash; dependency_chain_break=true",
     "latency_seconds": null,
     ...
   }
   ```
   (`dependency_chain_break=true` is encoded as a substring in `error`; the schema does not have a dedicated boolean field for it.)
3. **Start a fresh chat session for query #4** (`Retrieve-1`). Concretely:
   - Click the "New chat" or equivalent button in the UI (use `browser_snapshot` to find it).
   - If no new-chat affordance exists, log out and log back in.
   - The `<sid-dir>` from §5.1 may now be stale — re-discover after #4 lands and record the new one.
4. Continue with queries #4 through #10 normally.

### 8.2 Query #2 crash

If `Search-Refine-1` crashes:

1. Write the crash record for #2.
2. **Decision point for #3**: only attempt #3 if the session-DB state is "uncertain-but-readable" — concretely, if the chat UI is still responsive and you see any acknowledgement that #2's prior search context still applies. In practice this is rare; default to NOT attempting.
3. If you do NOT attempt #3: write a skip record for #3 with `error` containing `"dependency_chain_break=true"`, then continue with #4–#10.
4. If you DO attempt #3 anyway: run it normally; if it returns gibberish or a "no prior search" error, mark `answer_provided=false` and let T7's judge classify the verdict.

### 8.3 Query #3 crash

If `Memory-1` crashes: write the crash record and continue with #4–#10. Queries #4–#10 do not depend on #3.

### 8.4 Mid-run query crash (queries #4–#10)

For any single-query crash with no downstream dependency: write the crash record for that query and continue with the next. If five consecutive queries crash, abort per §10.

### 8.5 Bookkeeping — record `dependency_chain_break`

Whenever a query is skipped because of an upstream crash, the `error` field MUST contain the literal substring `dependency_chain_break=true`. T7 / T3 detect this substring when computing the success bar.

---

## §9. T7 judge-invocation contract (for documentation only; T6 does NOT execute this)

T7 (Phase 7) iterates over the `evidence/run-2026-05-07/query-*.json` files this runbook produced and invokes the BAML judge inside the e2e image. T6 must NOT run the judge — but the runbook agent SHOULD verify the contract surface is intact at the end of the run so T7 doesn't fail on a trivially missing piece.

### 9.1 Exact `docker run --rm` command shape

```bash
docker run --rm \
  --env GCP_API_KEY \
  --env NEXTSEEK_EVALUATOR_MODE=gcp \
  --mount type=bind,source="$(pwd)/evidence/run-2026-05-07",target=/evidence,readonly \
  --mount type=bind,source="$(pwd)/evidence/run-2026-05-07/judge-output",target=/judge-output \
  dmac-assistant:e2e-2026-05-07 \
  python -m tools.e2e.judge_runner \
    --record /evidence/query-01-Search-Basic-1.json \
    --output /judge-output/query-01-Search-Basic-1.judged.json
```

Key invariants:

- **Image tag**: `dmac-assistant:e2e-2026-05-07` (the T5-produced tag for this run date; format `e2e-YYYY-MM-DD`).
- **Env-var allowlist (EXACTLY these two; per OP-4)**: `GCP_API_KEY` (forwarded from host env) and `NEXTSEEK_EVALUATOR_MODE=gcp` (literal value).
- **NO `AWS_BEARER_TOKEN_BEDROCK`**, no `AWS_*`, no `NEXTSEEK_USERNAME`/`NEXTSEEK_PASSWORD`, no `DMAC_USERS`. The judge container must NOT have access to Bedrock — it uses GCP Gemini via `NEXTSEEK_EVALUATOR_MODE=gcp`.
- **Mounts**: evidence dir mounted **read-only** at `/evidence`; a separate writable host output dir (created by T7 — recommend `evidence/run-2026-05-07/judge-output/`) mounted at `/judge-output`.
- **`--rm`**: container is one-shot; no state carried between judge invocations. T7 invokes this command once per record (10 times total).

### 9.2 What T6 should verify before exiting

After all 10 records are written, the runbook agent should:

1. Confirm `docker images dmac-assistant:e2e-2026-05-07` is non-empty (T5 produced it).
2. Confirm `GCP_API_KEY` is present in the host env (`echo ${GCP_API_KEY:+set} | grep -q set`).
3. Confirm `evidence/run-2026-05-07/judge-output/` exists and is writable (`mkdir -p` + `touch`).

Any miss is non-fatal for T6 (the records have already been written) but should be flagged in the closing report so T7 doesn't surprise the user.

---

## §10. Abort conditions

The runbook agent MUST abort and surface to the user (do NOT continue silently) under any of:

1. **Bridge non-responsive ≥30s**: any `browser_navigate`, `browser_wait_for`, or HTTP probe of `http://127.0.0.1:8000` that does not return within 30 seconds. Snapshot whatever state exists, write a partial run summary, and stop.
2. **MCP playwright tool unavailable mid-run**: any `mcp__plugin_playwright_playwright__*` tool returning a "tool not found / not registered" error after §1 succeeded. Treat the same as a §1 pre-flight failure but mark all unwritten queries as `error="mcp-tool-disappeared-mid-run"`.
3. **More than 5 consecutive crashes**: if queries #N, #N+1, ..., #N+5 all crash (with `error` populated), abort. Six crashes in a row indicates a systemic failure; further attempts waste evidence-run setup.
4. **Fresh-session restart fails after a query #1 crash** (§8.1 step 3): if the new chat / re-login itself crashes, abort the whole run.
5. **Disk-full / permission-denied writing under `evidence/run-2026-05-07/`**: any `OSError` writing a record file — record what you have, surface the error, stop.

On abort: write a `_status` field somewhere visible (recommend `evidence/run-2026-05-07/_meta.json`) containing `{"status": "aborted", "reason": "<which condition>", "queries_completed": N}` so T7 knows the run is partial.

---

## §11. Closing checklist

Before exiting and signaling Phase 6 complete:

- [ ] All 10 query files exist at `evidence/run-2026-05-07/query-{NN}-{id}.json` (or have explicit skip records).
- [ ] Every record passes Pydantic validation against `tools.e2e.schema.QueryRecord`.
- [ ] No record has both `latency_seconds=null` AND `error=null`.
- [ ] All 10 transcript files exist at `evidence/run-2026-05-07/transcripts/query-NN.jsonl`.
- [ ] All 10 screenshot files exist at `evidence/run-2026-05-07/screenshots/query-NN.png`.
- [ ] §9.2 verifications surfaced (image present, GCP_API_KEY set, judge-output dir writable).
- [ ] Cumulative-vs-per-call cost interpretation chosen (§5.3) is documented in `_meta.json`.
- [ ] Empirical event-name verification (§5.4) is documented in `_meta.json`.

When the checklist is complete, T6 is done and T7 may dispatch.
