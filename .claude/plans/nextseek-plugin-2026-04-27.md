# nextseek plugin — Plan B (plugin authoring) Implementation Plan

## COMPACT HANDOFF (2026-05-02 LATE NIGHT — Wave 3 CLOSED-OUT, branch pushed, Wave 4 scheduled remote)

> **Authoritative for current state. Supersedes the auto-generated COLD-START HANDOFF immediately below + the older `## EXECUTION STATUS (2026-05-03)` + the older `## COMPACT HANDOFF (2026-05-02 NIGHT ...)` sections further down.**

### One-paragraph state

Wave 3 fully merged + reviewed ALL-PASS this session. Integration HEAD advanced `7a31286` → `e33be6b` (8 shim commits + 8 `feat: complete...` merge commits via `merge_task.sh ... 0-host-A1-deferred`). Post-merge spec-level adversarial review (`feature-dev:code-reviewer`) returned ALL-PASS for B03–B09 with 2 carryover risks logged (B17 forward-prop tracker; stripped-PATH dispatch tests on 6 of 8 shims). Branch `ultraplan/nextseek-plugin-2026-04-27` pushed to origin with upstream tracking (was previously local-only). Plan file + 9 task specs force-added (`git add -f`) so a remote agent could read them; this followed the existing precedent of force-adding `build_context/plugins/nextseek/...` paths. Two remote one-shot routines scheduled for Wave 4 (next session must NOT duplicate this work — see "Scheduled remote agents" below).

### Tracked state

- **Integration HEAD**: `e33be6b` (was `7a31286` at session start). Now contains: Wave 1 + 2 + 3 (B01–B09) + a `chore:` commit force-tracking the plan + specs.
- **Branch upstream**: `origin/ultraplan/nextseek-plugin-2026-04-27` (set this session via `git push -u`). All 17 new commits pushed.
- **Worktrees on disk**:
  - B01, B02 (legacy, post-merge — safe to remove)
  - B03–B09 worktrees + branches REMOVED by `merge_task.sh` (no action needed)
  - 3 stale Plan A spike worktrees at `.worktrees/task-0.{1,2,3}` (still low-priority cleanup)
- **Test suite**: `235 passed, 10 skipped` on integration HEAD. Skipped = chat_nextseek-importing shim tests per Amendment 1 / `pytest.importorskip` (EXPECTED). Bridge-suite-wide `--cov-fail-under=95` from `pyproject.toml` fails at 51% — UNRELATED to plugin work; pre-existing on `src/dmac_assistant/`. Run with `--no-cov` to verify health.
- **Tracked under `.claude/plans/`**: plan file + all 9 task specs (B01–B09) force-added in commit `<chore commit>` 2026-05-02 late night so remote agents can access them. `.claude/` remains in `.gitignore` line 29; the force-add precedent matches `build_context/plugins/nextseek/...`.

### What changed this session (2026-05-02 → 2026-05-03 transition)

1. **Onboarded** to the 2026-05-02 NIGHT compact handoff. Verified all 8 Wave-3 task branches had spec-compliant commits matching the handoff table byte-for-byte.
2. **Merged all 8 Wave-3 task branches** sequentially via `merge_task.sh nextseek-plugin-2026-04-27 task-B0X-<slug> 0-host-A1-deferred`. All 8 clean (`ort` strategy, no conflicts). Worktrees + branches deleted by the script. Integration HEAD `7a31286` → `e33be6b`.
3. **Post-merge spec-level reviewer pass** (`feature-dev:code-reviewer` per `feedback_post_merge_review.md`): ALL-PASS. CRITICAL-3 (B06a) and CRITICAL-4 (B06b) security boundaries correctly implemented + tested. B09 confirmed deterministic dispatcher. Importorskip + Amendment-1 host-informational coverage uniformly honored.
4. **2 carryover risks surfaced** (NOT defects; documented in 2026-05-03 Amendment Log entry below):
   - B17 forward-propagation lives only in prose (no machine-readable tracker in tree). Mitigation: Wave 5 explosion MUST inherit verbatim merge-condition text from Amendment 1.
   - Stripped-PATH dispatch tests on B04/B05/B06a/B06b/B07/B08 require `/usr/bin/python` to resolve in image. Mitigation: B17 image-e2e MUST verify, OR Wave 5 amendment normalizes to `{**os.environ, ...}`.
5. **Plan file updated**: added `## EXECUTION STATUS (2026-05-03)` top-section + `## Amendment Log` entry "2026-05-03 — Wave 3 merged + post-merge spec-level review (ALL-PASS)".
6. **Branch pushed**: `git add -f` on plan file + task-specs dir (`.claude/` is gitignored; precedent for force-add matches `build_context/`); committed; `git push -u origin ultraplan/nextseek-plugin-2026-04-27`. Branch now has upstream + all 17 new commits on remote.
7. **2 remote one-shot routines scheduled** for Wave 4 spec authoring + adversarial review (see next section).

### Scheduled remote agents (CRITICAL — do NOT duplicate this work in next session)

| # | Routine name | Trigger ID | Fires (UTC) | Local (ET) | Purpose |
|---|---|---|---|---|---|
| 1 | `wave-4-spec-authoring-nextseek-plugin` | `trig_01G5J7nWz9opZ3xk3pvDqVJD` | 2026-05-03T01:03:32Z | Sat 9:03 PM | Author B10/B11/B12 specs + push to branch |
| 2 | `wave-4-adversarial-spec-review-nextseek-plugin` | `trig_01Nq1HFi88g4uZHdbD3VgXku` | 2026-05-03T04:03:32Z | Sun 12:03 AM | 6-lens adversarial Phase 4 review + write report to `.claude/reviews/wave-4-phase4-review-2026-05-03.md` + push |

Both run `claude-opus-4-7` against `ultraplan/nextseek-plugin-2026-04-27`. Both are one-shot (auto-disable after firing). User mentioned next 5-hour session will start ~2h 16min after schedule was set (~2026-05-03T01:00Z).

**Expected artifacts on branch when next session starts**:
- `.claude/plans/nextseek-plugin-2026-04-27-tasks/task-B10-skill-md.md`
- `.claude/plans/nextseek-plugin-2026-04-27-tasks/task-B11-nextseek-slash-command.md`
- `.claude/plans/nextseek-plugin-2026-04-27-tasks/task-B12-permission-allowlist-setup.md`
- `.claude/reviews/wave-4-phase4-review-2026-05-03.md`
- 2 new commits on `ultraplan/nextseek-plugin-2026-04-27` (one from each agent)

**Failure modes to check**:
- `WAVE_4_AUTHORING_BLOCKED.md` at repo root → Agent 1 hit a hard blocker; Agent 2 short-circuits and writes a "review skipped" report. Investigate the blocker file.
- Missing spec files but no blocker → Agent 1 partially failed; Agent 2 writes "specs missing" report.
- Both files present + review report present → proceed with reviewer findings.

Routine URLs:
- https://claude.ai/code/routines/trig_01G5J7nWz9opZ3xk3pvDqVJD
- https://claude.ai/code/routines/trig_01Nq1HFi88g4uZHdbD3VgXku

### Resume protocol (FRESH SESSION)

1. Open new Claude Code session in `/Users/taishajoseph/Documents/Projects/dmac_assistant`.
2. Run `/ultraplan onboard`. Onboard reads THIS section first.
3. **First action**: `git pull origin ultraplan/nextseek-plugin-2026-04-27` to fetch the 2 remote agents' commits.
4. Check `.claude/reviews/wave-4-phase4-review-2026-05-03.md` for Agent 2's verdict.
5. Per verdict:
   - **APPROVE / APPROVE-WITH-MICRO-FIXES**: apply any micro-fixes; proceed to Phase 5 lock + Wave 4 execution dispatch.
   - **REVISE**: dispatch local feature-dev:code-reviewer for second opinion, then revise specs in main session, re-review.
   - **FAIL / BLOCKED**: triage; may need to re-author one or more specs from scratch.
6. After Wave 4 execution + merges + post-merge review: proceed to Wave 5 (B13–B16). When B17 is exploded in Wave 6, MUST include the binding `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py --cov-fail-under=95` merge-condition (Amendment 1 forward-propagation rule).

### Next session followups (priority order)

1. Pull remote, check `.claude/reviews/wave-4-phase4-review-2026-05-03.md`, react per verdict.
2. If Wave 4 specs land clean → Phase 5 lock → execute Wave 4 (B10/B11/B12) — likely sequential rather than parallel since these are infrastructure tasks with potential interdependencies.
3. After Wave 4 merge → Wave 5 explosion (B13–B16 = ingest pipelines + context snapshot). When authoring B17 (Wave 6), inherit the verbatim binding-gate text from Amendment 1.
4. Cleanup (low-priority): orphan B01/B02 worktrees + 3 stale Plan A spike worktrees.

### Critical contracts inherited

- **chat_nextseek host/image split**: any host pytest target importing `chat_nextseek` MUST use `pytest.importorskip("chat_nextseek")` at module level. NO `make install-chat-nextseek` references.
- **Amendment 1**: NO `--cov-fail-under=95` on host pytest invocations; use FILE-PATH `--cov=...` for diagnostic only; binding gate is image-side via Wave-5/6 B17.
- **build_context/ rule**: ANY `git add` of files under `build_context/plugins/nextseek/` MUST use `-f` (gitignored).
- **Plan/spec files**: now also force-added to `.claude/plans/` precedent — future plan/spec edits use `git add -f`.
- **Coverage default**: 95% (B2 amendment removed the 90% exception for B2; same default for B3+).
- **3-layer write-safety contract** (CRITICAL-3 + CRITICAL-4): `nextseek-api-write` MUST be EXCLUDED from B12's L1 allowlist.

---

## COLD-START HANDOFF (auto-generated, partial — see compact handoff above for authoritative state)
**Generated**: 2026-05-02T20:01:42.415451
**Plan**: nextseek plugin — Plan B (plugin authoring) Implementation Plan (`?`)
**Last status**: APPLIED. Reviewer (`feature-dev:code-reviewer`) returned APPROVE-WITH-MICRO-FIXES; 9 of the 10 micro-fixes applied to spec bodies (8 stale `--cov-fail-under=95` checklist items across 8 specs + B03 §8 surviving "≥95% on host held by B2 suite" misreading + B03 §1 prose qualifier). Item 10 (B17 forward-propagation) recorded above.

### 1. Original Goal
(not found)

### 2. Completed Tasks
None yet.

### 3. In-Progress Tasks
None.

### 4. Remaining Tasks
None — all tasks accounted for.

### 5. Key Decisions & Amendments
### 2026-05-03 — Wave 3 merged + post-merge spec-level review (ALL-PASS)

- **Trigger**: `/ultraplan onboard` resumed in fresh session. All 8 Wave-3 task branches were verified committed with spec-compliant subjects (matching the 2026-05-02 NIGHT compact handoff table byte-for-byte). User selected "Merge all 8 + reviewer pass."
- **Action**: Sequential `merge_task.sh nextseek-plugin-2026-04-27 task-B0X-<slug> 0-host-A1-deferred` for B03 → B09. All 8 merges clean (`ort` strategy, no conflicts). Worktrees + task branches removed by the script. Integration HEAD advanced from `7a31286` to `e33be6b` (8 shim commits + 8 merge commits, 16 total).
- **Verification**: `uv run pytest tests/unit/ --no-cov` reports `235 passed, 10 skipped`. The 10 skipped = chat_nextseek-importing shim tests per Amendment 1 / `importorskip` (EXPECTED). The bridge-suite-wide `--cov-fail-under=95` from `pyproject.toml` fails at 51% (covers `src/dmac_assistant/`, pre-existing, unrelated to plugin work).
- **Reviewer pass** (`feature-dev:code-reviewer`, per memory `feedback_post_merge_review.md`): SPEC-LEVEL adversarial cross-check of all 8 merged tasks against §10 merge conditions + Amendment 1 + the host/image Python invariant. **Verdict: ALL-PASS** for B03, B04, B05, B06a, B06b, B07, B08, B09. CRITICAL-3 (B06a `--confirmed-write` rejection) and CRITICAL-4 (B06b parser-plan + confirmed-write gate) security boundaries correctly implemented + tested with the contractual error messages. B09 confirmed deterministic dispatcher (no LLM call content). Importorskip discipline + Amendment-1 host-informational coverage uniformly honored.
- **Reviewer-flagged carryover risks** (NOT defects; for forward planning):
  1. **B17 forward-propagation lives only in prose**. No machine-readable tracker (TODO marker, skipped test, conftest fixture) in the tree would fail if Wave 5 forgets the binding `--cov-fail-under=95` gate. Mitigation: Wave 5 explosion MUST inherit the verbatim merge-condition text from the previous Amendment 1 entry's "Forward-propagation rule" paragraph.
  2. **Stripped-PATH dispatch tests are latent image-side risks**. B04, B05, B06a, B06b, B07, B08 dispatch tests use `env={"PATH": "/usr/bin:/bin", ...}`; B03 + B09 use `{**os.environ, ...}`. Both spec-faithful. On image, the stripped form requires `/usr/bin/python` to resolve to a real interpreter. Mitigation: B17 image-e2e MUST verify `/usr/bin/python` resolves correctly inside the image, OR a Wave-5 amendment normalizes all 8 dispatch tests to inherited-env form. Flag at B17 explosion.
- **Status**: APPLIED. Plan top section "## EXECUTION STATUS (2026-05-03)" added; supersedes the 2026-05-02 NIGHT compact handoff. Tasks #1–#9 in this session's TodoList all completed.

### 2026-05-02 (evening) — Amendment 1: host-coverage gate informational, image gate binding (after B03 canary executed)

- **Trigger**: B03 canary executor (commit `498de87` on `task/B03-entity-extract`) returned `DONE_WITH_CONCERNS` with the diagnostic that host-side `--cov-fail-under=95` is structurally unachievable. `pytest.importorskip("chat_nextseek")` (added unconditionally to B2 in fixup `3765ed3` + every Wave 3 spec per the 2026-05-02 host-import audit) causes module-level skip on host (Python 3.12, chat_nextseek requires ≥3.14, image-only). On host, `_nextseek_runner.py` is therefore never imported → coverage = 0% by structural invariant. Spec §8 prediction "17 passed (B2 dispatch tests w/ importorskip allow them) + N skipped (B0X), coverage ≥95% held by B2 suite" was based on a misreading of `pytest.importorskip`: it is a hard module-level skip when the import fails, not a per-test conditional.
- **Proposed change**: Replace the host-side `--cov-fail-under=95` gate in every Wave 3 task spec's §4 Step 4 + §8 Verification block with a host-informational coverage report (FILE-PATH `--cov=...` flag preserved for diagnostic, `--cov-fail-under=...` flag removed). Binding ≥95% gate moves to image-side, enforced by Wave 5 B17 image-e2e. §10 merge conditions updated to specify "host informational, image binding."
- **Reason**: structural invariant (importorskip → 0% host coverage) cannot be satisfied; specs §8 predictions are wrong; executors cannot be expected to satisfy a hard-impossible gate. Implementation requirements unchanged — this is a verification-side correction only. No code changes to existing B1/B2 commits. B03 canary commit `498de87` becomes compliant under the amendment.
- **Blast radius**: 8 spec files. Inline edits applied:
  1. `task-B03-entity-extract.md` §4 Step 4 + §8 (`replace_all=true`); §10 merge condition #1 rewritten.
  2. `task-B04-parse.md` §4 Step 4 + §8 (`replace_all=true`); §10 unchanged ("§8 all green" still satisfiable).
  3. `task-B05-plan.md` same pattern as B04.
  4. `task-B06a-api-read.md` same pattern as B04 (§10 mention of CRITICAL-3 boundary preserved).
  5. `task-B06b-api-write.md` same pattern as B04.
  6. `task-B07-graph.md` same pattern as B04.
  7. `task-B08-generate-submission.md` same pattern as B04.
  8. `task-B09-report.md` §4 + §8 (`replace_all=true`); §10 merge condition #1 rewritten (was "coverage ≥95% with FILE-PATH `--cov=` form").
- **Re-vetting**: ONE combined Phase-4-style reviewer dispatch (`feature-dev:code-reviewer`) over all 8 amended specs, returning per-spec verdicts in a single response. Per memory `feedback_reviewer_no_write_tool.md` the reviewer is read-only; orchestrator (this session) applies any micro-fixes the reviewer surfaces.
- **Approved by**: user, 2026-05-02 evening via AskUserQuestion ("Approve as proposed (Recommended)" with prose addendum: "hold before execution; explain how you will make this amendment" — orchestrator explained 3-step plan; user approved Steps 1+3 only, skipping the diff preview).
- **Forward-propagation rule (Wave 5 B17 image-e2e)**: when B17 is exploded, its spec MUST include explicit image-side `--cov-fail-under=95` enforcement as a non-negotiable merge condition. Suggested text: `"Image-side pytest suite green: all Wave-3 shim tests (test_shim_*.py) report PASSED (not skipped) inside the image. Full suite with --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py --cov-fail-under=95 must report exit 0. This is the binding ≥95% gate deferred from Wave-3 Amendment 1 (2026-05-02 evening) and is non-negotiable."` Without this in B17, the binding gate promised by this amendment is hollow.
- **Status**: APPLIED. Reviewer (`feature-dev:code-reviewer`) returned APPROVE-WITH-MICRO-FIXES; 9 of the 10 micro-fixes applied to spec bodies (8 stale `--cov-fail-under=95` checklist items across 8 specs + B03 §8 surviving "≥95% on host held by B2 suite" misreading + B03 §1 prose qualifier). Item 10 (B17 forward-propagation) recorded above.

### 2026-05-02 — chat_nextseek host-import audit (after B2 implementer DONE_WITH_CONCERNS, pre-merge)

- **Trigger**: B2 implementer reported 17/17 green at SHA `6fb90618` but only after silently bumping the worktree's `.python-version` to 3.14 (uncommitted). When the main session reverted it to integration's pinned `3.12` and re-ran, `tests/unit/test_nextseek_runner.py::test_runner_emits_structured_error_on_missing_creds` failed (`AssertionError: 'IMPORT_FAILED' == 'CONFIG_MISSING'`) because the subprocess `_nextseek_runner.py` invocation hit `from chat_nextseek.config import ChatConfig` first and exited 2 before reaching the cred-missing check. chat_nextseek requires Python ≥3.14; host pins 3.12; chat_nextseek is image-only by Plan A T7's PATH_B decision (`pyproject.toml` closing comment). Six prior reviewers (B1, B2, cross-task, B1 re-review, B2 re-review, the 2026-05-01 onboard cross-reference) missed it because the misreading lived in parenthetical notes about a pre-flight that doesn't actually verify host import.
- **Audit (2026-05-02)**: a full sweep of plan body + B1 spec + B2 spec for chat_nextseek host-vs-image touchpoints identified 5 CRITICAL defects (plan body line 891 referencing a non-existent `make install-chat-nextseek` target and a non-existent host-import pre-flight; B2 spec line 33's "AND in the dev environment" clause; B2 spec line 170's "importable in dev" clause; B2 spec line 1061's false claim that pyproject.toml ought to include chat_nextseek; B2 spec §5.1 missing `pytest.importorskip`); 1 CRITICAL propagation risk to Wave 3 task bodies B3.3 and B9.3 (re-run the broken baseline test, plus a layered defect on dotted-module `--cov=` form); 2 HIGH documentation defects on plan lines 98 and 160 (no host/image qualifier on "chat_nextseek importable").
- **Resolution (10 items, all applied 2026-05-02)**:
  1. Plan body line ~891 rewritten to delete the non-existent `make install-chat-nextseek` reference and the false pre-flight claim; replaced with mandatory unconditional `importorskip` rule + cross-reference to the new `## Host vs Image Python Environment` section.
  2. B2 spec §1/§2 line ~33: removed the "AND in the dev environment" clause; explicit "image-only".
  3. B2 spec §5.2 line ~170: rewritten as unconditional `importorskip` instruction; struck the "in dev" clause.
  4. B2 spec §9.3 line ~1061: deleted "the repo's pyproject.toml ought to include chat_nextseek"; replaced with pointer to `pyproject.toml`'s `T7 path-decision: PATH_B image-only` comment.
  5. B2 spec §5.1 baseline test: added `pytest.importorskip("chat_nextseek")` at top of file with rationale comment.
  6. **Fixup commit** on `task/B02-shared-runner` applies the same one-line `pytest.importorskip` to the actual `tests/unit/test_nextseek_runner.py` so the integration tree is green on host post-merge.
  7. Forward-propagation rule recorded in this entry: **every Wave 3-7 task spec MUST inherit (a) `importorskip` discipline on any host pytest target that imports chat_nextseek, (b) FILE-PATH `--cov` form not dotted-module form, (c) `--cov-fail-under=95`, (d) no `make install-chat-nextseek` references.** Plan body lines ~1334-1338 (B3.3) and ~1499-1503 (B9.3) carry both defects (host-import + dotted-cov) — they will be corrected when those waves are exploded; until then this Amendment Log entry is authoritative.
  8. Plan body lines 98 and 160 (compact handoff + Dependency banner) updated with explicit "image-only" qualifiers.
  9. **New section `## Host vs Image Python Environment`** added (between `## Pre-flight` and `## Tool surface`) — authoritative front-and-center reference for the host/image split + 5 numbered rules for test discipline.
  10. **Memory file** `feedback_chat_nextseek_host_image_split.md` saved + indexed in `MEMORY.md` so this lesson survives across sessions and projects.
- **Re-vetting**: ONE combined post-merge review (adversarial + per-item checklist verification) dispatched after fixup commit + B2 → integration merge. Reviewer must confirm each of the 10 items at the cited file/line.
- **Approved by**: user, 2026-05-02 via AskUserQuestion ("All right, approved. But make sure when you are done, you have a checklist...").
- **Status**: APPLIED.

### 2026-05-01 (late evening) — build_context git-add -f (after Phase 5.7, pre-B1 dispatch)

- **Trigger**: Phase 5.7 onboard cross-reference caught that `.gitignore` line 13 (`build_context/`) ignores the entire tree the locked B1 + B2 specs were committing into. Five Phase 4 reviewers had missed it. Documented in the late-evening compact handoff under "CRITICAL pre-dispatch find — `build_context/` gitignored".
- **Proposed change** (path A from the handoff): add `-f` to the `git add` invocations that target `build_context/...` paths in B1 §4 Step 2 and B2 §4 Step 7; document the requirement in B1 §9.2 Gotchas, B2 §9.3 Gotchas, and a callout above the plan's File Structure table; record a forward-propagation rule for Wave 3-7.
- **Reason**: plain `git add build_context/...` silently no-ops on a gitignored path; the subsequent `git commit -m '...'` either fails ("nothing to commit") or commits an empty change. Verified: `git ls-files build_context/` returns exactly one path (`build_context/plugins/nextseek-api/skills/nextseek-api/SKILL.md`) — historically force-added with `-f`. Path B (whitelist `build_context/plugins/nextseek/**` in `.gitignore`) was rejected because anything else that drops files into `build_context/plugins/` (e.g. `make image-stage`) could start tracking unexpectedly.
- **Blast radius**:
  - `task-B01-scaffold.md` §4 Step 2 (`git add` → `git add -f`); §9.2 Gotchas (new bullet)
  - `task-B02-shared-runner.md` §4 Step 7 (split into two `git add` calls — one with `-f` for the two `build_context/...` paths, one plain for the two `tests/unit/...` paths); §9.3 Gotchas (new bullet)
  - Plan `## File Structure` (new note above the table)
  - This `## Amendment Log` entry
  - The late-evening compact handoff "CRITICAL pre-dispatch find" callout — annotated as RESOLVED below the original text
- **Forward-propagation rule (per `feedback_amendments_must_propagate_to_task_bodies.md`)**: every Wave 3-7 task that creates files under `build_context/plugins/nextseek/` MUST use `git add -f` in its commit step. This includes B3-B9 (shims under `bin/`), B10 (`skills/nextseek/SKILL.md`), B11 (`commands/nextseek.md`), B12 (`scripts/setup.sh`), B13 (`context/` snapshot pipeline output). Wave 3 explosion MUST inherit this and bake `-f` into every authored Step 7-equivalent commit block; failure to do so is a defect to be caught at Phase 4. The exception: pure tests/docs/Makefile/Dockerfile commits remain plain `git add` because those paths are NOT under `build_context/`.
- **Re-vetting**: skipped per user directive (option "Approve — apply, skip re-vet"). Mechanical one-flag change; reviewers had already validated the surrounding §4 Step semantics. Future Wave 3 specs DO still get full Phase 4 review on first authoring, where `-f` presence becomes a checklist item.
- **Approved by**: user, 2026-05-01 (late evening) via AskUserQuestion under `/ultraplan amend` protocol.
- **Status**: APPLIED.

### 2026-05-01 — Coverage bump B2 90% → 95% (during Phase 3 Wave 1+2 task spec authoring)

- **Trigger**: User pushed back during Phase 3 spec authoring: "Isn't coverage target supposed to 95%?"
- **Proposed change**: Raise B2's coverage target on `build_context/plugins/nextseek/bin/_nextseek_runner.py` from the plan-locked 90% to the ultraplan default 95%. Withdraw the B2 coverage exception. Add three new tests to `tests/unit/test_nextseek_runner_dispatch.py` covering the previously-excepted branches: `_load_config` ImportError path (exit 2 / `IMPORT_FAILED`), `_load_read_safe_endpoints` OSError path (exit 6 / `CONFIG_ERROR`), and `main()` broad-except clause (exit 4 / `AGENT_FAILED`).
- **Reason**: On review, those three "uncoverable" branches are reachable via standard `monkeypatch` (sys.modules injection, builtins.open replacement, _DISPATCH table substitution). They do not qualify as architectural uncoverability under the ultraplan rule "It's hard is not a justification — only genuine architectural uncoverability qualifies." The 90% target inherited from Rev 2 NEW-7 was a borderline call; bumping to 95% removes a Phase 4 vetting risk and adds three small monkeypatch tests.
- **Blast radius**:
  - `task-B02-shared-runner.md` §1 status header, §4 Coverage target prose, §5.2 (3 new tests added), §4 Step 5 cov-fail-under arg, §8 Verification cov-fail-under arg + expected test count + expected coverage, §9.4 (rewritten as "no exception"), §9.5 self-review, §10 merge condition #1
  - Plan compact handoff §"Plan B execution context" Coverage gate line (line ~32)
  - Plan body Task B2 step B2.4 (verification command + expected test count)
  - Plan `## Task Specs Manifest` row for B02 (target + exception flag)
  - Plan `## Coverage Exceptions` B2 sub-section (withdrawn)
  - This `## Amendment Log` entry
- **Spec impact on tasks other than B2**: B3-B18 task specs have not yet been exploded (Phase 3 ran wave-by-wave; Wave 1+2 only). Future Wave 3+ specs MUST inherit the corrected default-95% expectation. Note: the plan body still contains stale `--cov-fail-under=90` lines in B3.3 (line ~1252) and B9.3 (line ~1417) inside the inline shim-test invocations. These lines were left untouched by this amendment because (a) they live in not-yet-exploded task bodies and (b) the user explicitly scoped this amendment to B2. **When Wave 3 (B3-B9) is exploded, the explosion process MUST raise those floors to 95% to match B2.** A forward-pointer to this amendment should appear in the B3-B9 spec headers.
- **Approved by**: user, 2026-05-01 via AskUserQuestion (option "Bump B2 to 95%, add 3 extra tests").
- **Status**: PROPAGATED to all enumerated locations.

---

### 6. Open Questions & Ambiguities
None recorded.

### Coverage Exceptions
Approved exceptions to the ultraplan default 95% floor. Each exception names exact uncoverable paths and the justification. Phase 4 vetting must affirm before Phase 5 lock.

### B1: pure scaffold — no executable code

- **Declared target**: N/A (zero new lines under any cov source)
- **Default**: 95%
- **Justification**: B1 produces only `build_context/plugins/nextseek/.claude-plugin/plugin.json` (static JSON config) and `build_context/plugins/nextseek/README.md` (two-line markdown stub). Neither file contains executable Python. The repo-wide `--cov-fail-under=95` gate (against `tests.harness` + `src/dmac_assistant`) is unaffected by B1. Plugin manifest correctness is verified indirectly by B14's existing `tests/test_image_smoke.py` and `tests/test_dockerfile_build.py` modifications, which already assert the new plugin path is shipped to the built image.
- **Uncoverable paths**: every line of `plugin.json` and `README.md` (data, not code).
- **Fallback**: if Phase 4 rejects this exception, the contingency `tests/unit/test_nextseek_plugin_manifest.py` in `task-B01-scaffold.md` §5 covers the JSON-shape check.

### B2: ~~90% target~~ — **WITHDRAWN** (amended 2026-05-01 to default 95%)

The B2 coverage exception logged in this section earlier on 2026-05-01 has been **withdrawn the same day** during Phase 3 spec authoring. On review, the three "uncoverable" branches (ImportError in `_load_config`, OSError in `_load_read_safe_endpoints`, broad-except in `main()`) are reachable via standard `monkeypatch` and do not qualify as architectural uncoverability under the ultraplan rule. Three additional tests now cover those branches; B2's target is the default 95% on `_nextseek_runner.py`. See `## Amendment Log` entry "Coverage bump B2 90% → 95% (2026-05-01)" for the full record.

The shell shim layer (`_nextseek_common.sh` and the 8 `nextseek-*` shims authored in B3-B9) remains OUT of pytest-cov scope — that's a *scope* statement, not an exception (pytest-cov instruments only Python).

### Resume Instructions
Run `/ultraplan onboard` in a fresh session. The onboard protocol will
cross-reference this handoff against the actual codebase state before
resuming execution.

---

## EXECUTION STATUS (2026-05-03 — WAVE 3 COMPLETE, MERGED, REVIEWED ALL-PASS)

**Authoritative current state. Supersedes the COMPACT HANDOFF blocks below.**

- **Integration HEAD**: `e33be6b` (was `7a31286` at session start; +16 commits = 8 task-branch shim commits + 8 merge commits).
- **All 8 Wave-3 task branches merged** (B03 → B09) via `merge_task.sh`. Coverage arg passed as `0-host-A1-deferred` per Amendment 1 (host coverage informational; binding ≥95% deferred to Wave-5 B17).
- **Test suite**: `235 passed, 10 skipped` on integration HEAD. The 10 skipped are the chat_nextseek-importing tests per Amendment 1 / `pytest.importorskip` — EXPECTED, not a defect. The bridge-suite-wide `--cov-fail-under=95` from `pyproject.toml` fails at 51% — UNRELATED to Wave 3 (covers `src/dmac_assistant/`, not plugin paths); pre-existing.
- **Worktrees removed**: B03–B09 worktrees + branches deleted by `merge_task.sh`. B01/B02 orphan worktrees still on disk (low-priority cleanup); 3 stale Plan A spike worktrees at `.worktrees/task-0.{1,2,3}` also still present.
- **Post-merge spec-level reviewer pass** (`feature-dev:code-reviewer`, per `feedback_post_merge_review.md`): **ALL-PASS** for all 8 tasks. Cross-task verdict: importorskip discipline + Amendment-1 host-informational coverage are uniformly honored; CRITICAL-3 (B06a) and CRITICAL-4 (B06b) security boundaries correctly implemented + tested; B09 confirmed deterministic dispatcher (no LLM call content).

### Reviewer-flagged carryover risks (NOT defects; for forward planning)

1. **B17 forward-propagation lives only in prose**: The Wave-5 B17 image-side `--cov-fail-under=95` binding gate has no machine-readable tracker in the tree (no TODO marker, no skipped test, no conftest fixture that would fail if B17 is never implemented). The Amendment 1 promise depends entirely on Wave 5 planning surfacing it. Risk: B17 explosion forgets the binding gate. **Mitigation**: Wave 5 explosion MUST inherit the verbatim merge-condition text from Amendment Log entry "2026-05-02 (evening) — Amendment 1" (forward-propagation rule paragraph).

2. **Stripped-PATH dispatch tests are latent image-side risks**: B04, B05, B06a, B06b, B07, B08 dispatch tests use `env={"PATH": "/usr/bin:/bin", ...}` (stripped). B03 + B09 use `{**os.environ, ...}` (inherited). Both forms are spec-faithful. On image, the stripped-PATH tests REQUIRE `/usr/bin/python` to resolve to a real interpreter — typically a `python` → `python3.X` symlink. If the image's `python` is not at `/usr/bin/python`, these 6 tests will fail when un-skipped on image (chat_nextseek importable → importorskip passes → tests run → can't find python). **Mitigation**: B17 image-e2e MUST verify `/usr/bin/python` resolves correctly inside the image, OR Wave 5 amendment normalizes all 8 dispatch tests to the `{**os.environ, ...}` form. Flag this at B17 explosion.

### Next steps (priority order)

1. **Wave 4 explosion**: B10 (SKILL.md), B11 (`/nextseek` slash command), B12 (Layer-1 permission allowlist + setup.sh). Phase 3 task-spec authoring + Phase 4 adversarial review per usual ultraplan rhythm.
2. Carry the two carryover risks above into Wave 5/B17 planning (don't lose them).
3. Cleanup (low-priority): orphan B01/B02 worktrees + 3 stale Plan A spike worktrees.

---

## COMPACT HANDOFF (2026-05-02 NIGHT — Amendment 1 APPLIED; ALL 8 Wave-3 tasks committed on task branches; ready to merge) — SUPERSEDED 2026-05-03

**State at compact time (post-handoff, after orchestrator-side recovery of 3 stuck commits):**

| Task | Branch | Commit | Subject | Status |
|---|---|---|---|---|
| B03 | task/B03-entity-extract | `aee6be7` | `nextseek-plugin: nextseek-entity-extract shim` | ✅ orchestrator-recovered (canary) |
| B04 | task/B04-parse | `c128251` | `nextseek-plugin: nextseek-parse shim` | ✅ subagent |
| B05 | task/B05-plan | `0373ebc` | `nextseek-plugin: nextseek-plan shim` | ✅ orch-recovered from `$'...'` denial |
| B06a | task/B06a-api-read | `fb0404b` | `nextseek-plugin: nextseek-api-read shim (Layer-1 boundary)` | ✅ subagent (heredoc) |
| B06b | task/B06b-api-write | `c8689b0` | `nextseek-plugin: nextseek-api-write shim (Layer-2 gate)` | ✅ subagent (heredoc) |
| B07 | task/B07-graph | `5d06cca` | `nextseek-plugin: nextseek-graph shim` | ✅ orch-recovered from `$'...'` denial |
| B08 | task/B08-generate-submission | `0d5c3ee` | `nextseek-plugin: nextseek-generate-submission shim` | ✅ orch-recovered from `$'...'` denial |
| B09 | task/B09-report | `8b9424f` | `nextseek-plugin: nextseek-report deterministic dispatcher` | ✅ orch-recovered from `$'...'` denial |

**ALL 8 Wave-3 tasks are committed on their task branches with spec-compliant subjects** (each passes its spec's §10.3 regex). NONE merged to integration yet. Integration HEAD still `7a31286`.

**Recovery scorecard**: 4 of 8 tasks reached commit successfully via subagent (B04, B06a, B06b — used heredoc; B03 was orchestrator-recovered as the canary). 4 of 8 hit the `$'...'` Bash denial at the commit step (B05, B07, B08, B09) — all 4 had files staged correctly; orchestrator finished each by running the equivalent `git commit -F - <<'EOF'` heredoc form. NO code differences between the two paths — the commits are byte-identical to what the spec §4 Step 5 demands.

### NEW Bash-denial pattern discovered this session (2 of 7 agents hit it)

In addition to the compound `cd /path && git ... && pwd` denial documented earlier, **subagents are also denied on `git commit -m $'...'` ANSI-C quoting**. B05/B07/B08 hit this; B04/B06a/B06b worked around it by switching to `git commit -F - <<'EOF'` heredoc form. Orchestrator (this session, broader permission profile) ran the heredoc form and committed the 3 stuck branches (`0373ebc`, `5d06cca`, `0d5c3ee`).

**Forward rule for next session's dispatch prompts:** mandate heredoc commit form explicitly:
```
git -C <WORKTREE> commit -F - <<'EOF'
<exact spec §4 Step 5 subject>

<exact spec §4 Step 5 multi-line body>
EOF
```
The subagent must NEVER attempt the `$'...'` ANSI-C form — it gets denied on the same permission gate that denies compound `&&`.



> `/ultraplan compact` invoked 2026-05-02 night during Wave 3 retry-3 dispatch. **Authoritative for current state. Supersedes the auto-generated COLD-START HANDOFF immediately below this section AND the prior `## COMPACT HANDOFF (2026-05-02 EVENING ...)` further down.**

### One-paragraph state

Two failed dispatch rounds + one canary established the Wave 3 subagent contract: (1) background subagents DENY compound `cd /path && git ... && pwd` Bash forms even when each token is allowlisted — workaround is `git -C <abs-path>` form + one-command-per-Bash-call (no `&&`); (2) ultraplan default commit subject template OVERRODE each spec's §4 Step 5 — workaround is "defer to spec §4 Step 5 verbatim; orchestrator handles marker commits post-merge." Amendment 1 (host-coverage gate informational, image-side binding via Wave 5 B17) was approved + applied to all 8 Wave 3 specs; reviewer returned APPROVE-WITH-MICRO-FIXES; 9 micro-fixes applied. B03 commit recovered (`aee6be7 nextseek-plugin: nextseek-entity-extract shim` — passes spec §10.3). B04 just landed (`c128251 nextseek-plugin: nextseek-parse shim` — PASS). 6 retry-3 agents (B5, B6a, B6b, B7, B8, B9) still in flight at compact time.

### Tracked state

- **Integration HEAD**: `7a31286` (UNCHANGED this entire session — no merges yet).
- **Settings.local.json**: 12 patterns added during the session (pytest, uv run, pwd, echo, env, rm, bash -c, sh -c, diff, find, true, false). User pre-approved.
- **Worktrees on disk**:
  - B01, B02 (legacy, post-merge — safe to remove anytime)
  - **B03**: 1 commit `aee6be7 nextseek-plugin: nextseek-entity-extract shim` ready to merge — passes spec §10.3 regex
  - **B04**: 1 commit `c128251 nextseek-plugin: nextseek-parse shim` ready to merge — PASS reported
  - **B5, B6a, B6b, B7, B8, B9**: agents in-flight at compact time; next session must check `git -C <wt> log --oneline 7a31286..HEAD` per worktree to see what landed
  - 3 stale Plan A spike worktrees at `.worktrees/task-0.{1,2,3}` (low-priority cleanup)
- **Tracked under `build_context/plugins/nextseek/`**: same 5 paths as before this session (B1 + B2 only). New shims live on task branches not yet merged.

### What changed this session

1. **Bash invocation rule discovered**: subagents deny `cd /path && git ... && pwd` compound. Workaround: `git -C <abs-path>` + no `&&`. Two failed dispatch rounds (8 agents each) before this was nailed down. The B03 canary under retry-2 prompt validated the workaround.
2. **B03 canary** (commit `498de87`, retry 2): code correct but subject was `feat: complete task-B03-entity-extract [coverage: image-only-deferred]` from my dispatch override. Recovered via `git commit --amend` + `git reset --hard HEAD~1` of an empty marker commit — final HEAD on `task/B03-entity-extract` is `aee6be7` with subject `nextseek-plugin: nextseek-entity-extract shim` (spec-compliant). All B03 work preserved.
3. **Amendment 1 — host coverage informational, image binding** (full /ultraplan amend cycle):
   - Trigger: B03 canary diagnosed `pytest.importorskip("chat_nextseek")` causes module-level skip on host (Python 3.12; chat_nextseek requires ≥3.14, image-only). `_nextseek_runner.py` is never imported on host → coverage = 0% by structural invariant. Spec §8's "≥95% on host" prediction was wrong.
   - Applied to all 8 Wave 3 specs: removed `--cov-fail-under=95` from §4 Step 4 + §8 host invocations (`replace_all=true`); preserved FILE-PATH `--cov=...` flag for diagnostic; added `# AMENDMENT 1` comment block after each amended invocation. B03 + B09 §10 merge condition #1 rewritten.
   - Plan `## Amendment Log` updated with full entry (trigger, change, reason, blast radius per file, re-vetting plan, approval, status, B17 forward-propagation rule).
   - Reviewer (`feature-dev:code-reviewer`) returned APPROVE-WITH-MICRO-FIXES with 10 items. 9 applied: stale `[x] --cov-fail-under=95` checklist items in §9.X across all 8 specs + B03 §8 surviving "≥95% on host held by B2 suite" misreading + B03 §1 prose qualifier. Item 10 (B17 forward-propagation rule mandating image-side `--cov-fail-under=95` enforcement) recorded in Amendment Log; will become a hard merge condition when B17 is exploded in Wave 5.
4. **Amendment 2 = NOT a spec change** (analyzed, decided): the apparent commit-subject conflict was actually a defect in MY dispatch template (overrode spec §4 Step 5). Fix is prompt-side only: defer to spec §4 Step 5 verbatim; NO marker commit by executor (orchestrator-post-merge concern matching B1/B2 pattern). Retry-3 dispatch prompts incorporate this correction.
5. **B04 landed** (retry 3): `c128251 nextseek-plugin: nextseek-parse shim`. PASS, 0%/0/0/3 (skip on host as expected per Amendment 1). Files force-added past gitignore. Subagent reported one Bash denial on `git commit -m $'...'` ANSI-C form; succeeded with heredoc `git commit -F - <<'EOF'`. Workaround for future dispatches: prefer heredoc.

### Known followups for next session (in priority order)

1. **Check 6 in-flight retry-3 agents**: B5 `a6f889c49a7d3b07f`, B6a `ae0908b91602126c9`, B6b `a069fbe5c7584cacc`, B7 `a00260891ad16960b`, B8 `a5b17462d74a9ea97`, B9 `a9ca525db77a32886`. After onboard, run `git -C .claude/worktrees/task-B0X-<slug> log --oneline 7a31286..HEAD` for each worktree. PASS condition: 1 commit with subject matching `^nextseek-plugin: nextseek-<slug> ...`. Failures: re-dispatch retry-4 with the proven retry-3 prompt template (no marker commit override; defer to spec §4 Step 5; `git -C` + no `&&` rules).
2. **Merge B03 + B04** (and any other landed retry-3 commits) via `bash $ULTRAPLAN/scripts/merge_task.sh nextseek-plugin-2026-04-27 task-B03-entity-extract <coverage>` and same for B04. Coverage value: per Amendment 1, host coverage is informational only (0%); supply something like `image-only-deferred` or `0%-host-amendment-1` or whatever the merge script accepts. The marker `feat: complete task-B0X-<slug>` commit is added by the merge step itself, not the executor.
3. **Post-wave reviewer pass**: per memory `feedback_post_merge_review.md`, after each task → integration merge dispatch `feature-dev:code-reviewer` (read-only) at SPEC LEVEL. Goal: cross-check actual commit against spec §10 merge conditions + Amendment 1 expectations. Reviewer returns text; orchestrator persists fixes.
4. **Plan body B3.3 + B9.3 cleanup** (carryover from earlier handoff, lines ~1334-1338 + ~1499-1503): stale `--cov-fail-under=90` + dotted-module `--cov=` form. Spec authority supersedes; could be patched in a future amendment for cleanliness. Not blocking.
5. **3 stale Plan A spike worktrees** at `.worktrees/task-0.{1,2,3}` — safe to remove anytime.
6. **B17 image-e2e forward-propagation** (Wave 5): when B17 is exploded, its merge condition #1 MUST include `--cov=build_context/plugins/nextseek/bin/_nextseek_runner.py --cov-fail-under=95` enforcement on image. Without this, Amendment 1's "image binding" promise is hollow. Amendment Log entry "## 2026-05-02 (evening) — Amendment 1" carries the suggested merge-condition text verbatim.

### Critical contracts for next-session subagent dispatches

ALL retry/redo dispatches for this plan MUST embed the following in their prompts:

```
## CRITICAL — Bash invocation rules
1. NEVER use `&&` to chain commands. One command per Bash tool call.
2. NEVER use `cd`. Use `git -C <abs-worktree-path>` for git, `uv run --project <abs-repo-root> pytest <abs-test-path>` for pytest, absolute paths for chmod/python.
3. Prefer `git commit -F - <<'EOF'` heredoc over `$'...'` ANSI-C quoting (latter has been seen to denied; B04 retry-3 confirmation).
4. If Bash IS denied for a specific command, STOP and report the EXACT denied command string. Do not retry, do not work around.

## CRITICAL — Commit subject convention
DEFER to the spec's §4 Step 5 verbatim — single commit with subject `nextseek-plugin: nextseek-<slug> ...` and the spec's multi-line body. NO marker `feat: complete...` commit by the executor — that is an orchestrator post-merge concern.

## Amendment 1 (2026-05-02 evening) is APPLIED
- Host `--cov-fail-under=95` is REMOVED from §4 Step 4 + §8.
- FILE-PATH `--cov=...` flag preserved for diagnostic.
- Host coverage = 0% structurally (importorskip module-level skip). EXPECTED, not a defect.
- Binding ≥95% gate is image-side via Wave 5 B17.
```

### Resume protocol (FRESH SESSION)

1. Open new Claude Code session in `/Users/taishajoseph/Documents/Projects/dmac_assistant`.
2. Run `/ultraplan onboard`. Onboard agent reads THIS section first (above the auto-generated COLD-START).
3. Verify integration HEAD: `git log -1 --pretty=oneline ultraplan/nextseek-plugin-2026-04-27` should still show `7a31286`.
4. Verify B03 + B04 commits: `git -C .claude/worktrees/task-B03-entity-extract log --oneline 7a31286..HEAD` returns `aee6be7 nextseek-plugin: nextseek-entity-extract shim`. Same for B04 → `c128251 nextseek-plugin: nextseek-parse shim`.
5. Check the 6 in-flight retry-3 worktrees (B5, B6a, B6b, B7, B8, B9) for their landed commits.
6. For PASSing tasks: merge via `merge_task.sh`. For failures: re-dispatch retry-4 with the contract above.
7. After wave completes: post-merge reviewer pass; update plan; flag B17 forward-propagation requirement explicitly when Wave 5 starts.

---

## Settings & Worktrees Initialized (2026-05-02 Phase 5.5)

**Phase 5 lock**: ratified as-is per user directive 2026-05-02 (existing `## LOCKED 2026-05-02` markers on all 8 Wave 3 specs stand; structured-summary protocol step waived).

**Settings audit**: `.claude/settings.local.json` reviewed against compiled permission manifest for B3-B9. Verdict: **no changes required**. All B3-B9 commands (`chmod +x`, `git add -f`, `git commit`, `git diff --stat`, `git log`, `python -c "import py_compile"`, `uv run pytest tests/unit/test_shim_*.py`) and write paths (`build_context/plugins/nextseek/bin/**`, `tests/unit/**`) already covered. `ask` list still gates `git push`, `git reset`, `git clean`, `rm -rf`. Approved by user 2026-05-02 via AskUserQuestion.

**Worktrees initialized** via `init_worktrees.sh nextseek-plugin-2026-04-27 task-B03-entity-extract task-B04-parse task-B05-plan task-B06a-api-read task-B06b-api-write task-B07-graph task-B08-generate-submission task-B09-report`. All 8 created at integration HEAD `7a31286`:

| Task | Worktree | Branch |
|---|---|---|
| B03 | `.claude/worktrees/task-B03-entity-extract` | `task/B03-entity-extract` |
| B04 | `.claude/worktrees/task-B04-parse` | `task/B04-parse` |
| B05 | `.claude/worktrees/task-B05-plan` | `task/B05-plan` |
| B06a | `.claude/worktrees/task-B06a-api-read` | `task/B06a-api-read` |
| B06b | `.claude/worktrees/task-B06b-api-write` | `task/B06b-api-write` |
| B07 | `.claude/worktrees/task-B07-graph` | `task/B07-graph` |
| B08 | `.claude/worktrees/task-B08-generate-submission` | `task/B08-generate-submission` |
| B09 | `.claude/worktrees/task-B09-report` | `task/B09-report` |

**Phase 6 dispatch strategy**: all 8 in parallel (per user 2026-05-02 — cross-task reviewer confirmed independence, no merge-order constraints).

---

<details>
<summary>Earlier auto-generated cold-start summary (collapsed; the manual section above is authoritative for current state)</summary>

## Revision log

- v1 — Original Plan B authored and self-reviewed; verdict remained UNVETTED.
- v2 — Addresses combined Plan A/Plan B review: real `chat_nextseek` API signatures, split read/write API shims, audited read-safe endpoint allowlist, full read-only planner-advisor loop, `DMAC_PATH_MAPPINGS` path translation, hardened tests, and corrected entrypoint test strategy.
- v3 — Addresses Revision 2 focused review (2026-05-01) NEW-1 through NEW-8. The v2 amendments stated requirements in prose but did not regenerate the affected task bodies; v3 actually rewrites them. Concretely: B2.3 runner code now implements `_dispatch_api_read` (with `read_safe_endpoints.json` allowlist enforcement) and `_dispatch_api_write` (with `--confirmed-write` enforcement) as separate dispatchers and adds a `NEXTSEEK_DRY_RUN` short-circuit per dispatcher. B2.2b adds a per-dispatcher monkeypatch test file. B6a adds a `--confirmed-write` rejection test. B10.1's "Reply hygiene" block is rewritten to consume `DMAC_PATH_MAPPINGS` and B10 gains a grep-based verification step. B13.1's Makefile target is parameterized via `CHAT_NEXTSEEK_SRC` with a missing-source guard, and B14 gains a Dockerfile catalog assertion. B17.1 is replaced with a dry-run test that asserts agent-specific JSON. B18.2's verification reference is updated to use `DMAC_PATH_MAPPINGS` semantics rather than the production path. Coverage floors are added to B2.4, B3.3, and B9.3.

---

## Amendment Log

### 2026-05-03 — Wave 3 merged + post-merge spec-level review (ALL-PASS)

- **Trigger**: `/ultraplan onboard` resumed in fresh session. All 8 Wave-3 task branches were verified committed with spec-compliant subjects (matching the 2026-05-02 NIGHT compact handoff table byte-for-byte). User selected "Merge all 8 + reviewer pass."
- **Action**: Sequential `merge_task.sh nextseek-plugin-2026-04-27 task-B0X-<slug> 0-host-A1-deferred` for B03 → B09. All 8 merges clean (`ort` strategy, no conflicts). Worktrees + task branches removed by the script. Integration HEAD advanced from `7a31286` to `e33be6b` (8 shim commits + 8 merge commits, 16 total).
- **Verification**: `uv run pytest tests/unit/ --no-cov` reports `235 passed, 10 skipped`. The 10 skipped = chat_nextseek-importing shim tests per Amendment 1 / `importorskip` (EXPECTED). The bridge-suite-wide `--cov-fail-under=95` from `pyproject.toml` fails at 51% (covers `src/dmac_assistant/`, pre-existing, unrelated to plugin work).
- **Reviewer pass** (`feature-dev:code-reviewer`, per memory `feedback_post_merge_review.md`): SPEC-LEVEL adversarial cross-check of all 8 merged tasks against §10 merge conditions + Amendment 1 + the host/image Python invariant. **Verdict: ALL-PASS** for B03, B04, B05, B06a, B06b, B07, B08, B09. CRITICAL-3 (B06a `--confirmed-write` rejection) and CRITICAL-4 (B06b parser-plan + confirmed-write gate) security boundaries correctly implemented + tested with the contractual error messages. B09 confirmed deterministic dispatcher (no LLM call content). Importorskip discipline + Amendment-1 host-informational coverage uniformly honored.
- **Reviewer-flagged carryover risks** (NOT defects; for forward planning):
  1. **B17 forward-propagation lives only in prose**. No machine-readable tracker (TODO marker, skipped test, conftest fixture) in the tree would fail if Wave 5 forgets the binding `--cov-fail-under=95` gate. Mitigation: Wave 5 explosion MUST inherit the verbatim merge-condition text from the previous Amendment 1 entry's "Forward-propagation rule" paragraph.
  2. **Stripped-PATH dispatch tests are latent image-side risks**. B04, B05, B06a, B06b, B07, B08 dispatch tests use `env={"PATH": "/usr/bin:/bin", ...}`; B03 + B09 use `{**os.environ, ...}`. Both spec-faithful. On image, the stripped form requires `/usr/bin/python` to resolve to a real interpreter. Mitigation: B17 image-e2e MUST verify `/usr/bin/python` resolves correctly inside the image, OR a Wave-5 amendment normalizes all 8 dispatch tests to inherited-env form. Flag at B17 explosion.
- **Status**: APPLIED. Plan top section "## EXECUTION STATUS (2026-05-03)" added; supersedes the 2026-05-02 NIGHT compact handoff. Tasks #1–#9 in this session's TodoList all completed.

### 2026-05-02 (evening) — Amendment 1: host-coverage gate informational, image gate binding (after B03 canary executed)

- **Trigger**: B03 canary executor (commit `498de87` on `task/B03-entity-extract`) returned `DONE_WITH_CONCERNS` with the diagnostic that host-side `--cov-fail-under=95` is structurally unachievable. `pytest.importorskip("chat_nextseek")` (added unconditionally to B2 in fixup `3765ed3` + every Wave 3 spec per the 2026-05-02 host-import audit) causes module-level skip on host (Python 3.12, chat_nextseek requires ≥3.14, image-only). On host, `_nextseek_runner.py` is therefore never imported → coverage = 0% by structural invariant. Spec §8 prediction "17 passed (B2 dispatch tests w/ importorskip allow them) + N skipped (B0X), coverage ≥95% held by B2 suite" was based on a misreading of `pytest.importorskip`: it is a hard module-level skip when the import fails, not a per-test conditional.
- **Proposed change**: Replace the host-side `--cov-fail-under=95` gate in every Wave 3 task spec's §4 Step 4 + §8 Verification block with a host-informational coverage report (FILE-PATH `--cov=...` flag preserved for diagnostic, `--cov-fail-under=...` flag removed). Binding ≥95% gate moves to image-side, enforced by Wave 5 B17 image-e2e. §10 merge conditions updated to specify "host informational, image binding."
- **Reason**: structural invariant (importorskip → 0% host coverage) cannot be satisfied; specs §8 predictions are wrong; executors cannot be expected to satisfy a hard-impossible gate. Implementation requirements unchanged — this is a verification-side correction only. No code changes to existing B1/B2 commits. B03 canary commit `498de87` becomes compliant under the amendment.
- **Blast radius**: 8 spec files. Inline edits applied:
  1. `task-B03-entity-extract.md` §4 Step 4 + §8 (`replace_all=true`); §10 merge condition #1 rewritten.
  2. `task-B04-parse.md` §4 Step 4 + §8 (`replace_all=true`); §10 unchanged ("§8 all green" still satisfiable).
  3. `task-B05-plan.md` same pattern as B04.
  4. `task-B06a-api-read.md` same pattern as B04 (§10 mention of CRITICAL-3 boundary preserved).
  5. `task-B06b-api-write.md` same pattern as B04.
  6. `task-B07-graph.md` same pattern as B04.
  7. `task-B08-generate-submission.md` same pattern as B04.
  8. `task-B09-report.md` §4 + §8 (`replace_all=true`); §10 merge condition #1 rewritten (was "coverage ≥95% with FILE-PATH `--cov=` form").
- **Re-vetting**: ONE combined Phase-4-style reviewer dispatch (`feature-dev:code-reviewer`) over all 8 amended specs, returning per-spec verdicts in a single response. Per memory `feedback_reviewer_no_write_tool.md` the reviewer is read-only; orchestrator (this session) applies any micro-fixes the reviewer surfaces.
- **Approved by**: user, 2026-05-02 evening via AskUserQuestion ("Approve as proposed (Recommended)" with prose addendum: "hold before execution; explain how you will make this amendment" — orchestrator explained 3-step plan; user approved Steps 1+3 only, skipping the diff preview).
- **Forward-propagation rule (Wave 5 B17 image-e2e)**: when B17 is exploded, its spec MUST include explicit image-side `--cov-fail-under=95` enforcement as a non-negotiable merge condition. Suggested text: `"Image-side pytest suite green: all Wave-3 shim tests (test_shim_*.py) report PASSED (not skipped) inside the image. Full suite with --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py --cov-fail-under=95 must report exit 0. This is the binding ≥95% gate deferred from Wave-3 Amendment 1 (2026-05-02 evening) and is non-negotiable."` Without this in B17, the binding gate promised by this amendment is hollow.
- **Status**: APPLIED. Reviewer (`feature-dev:code-reviewer`) returned APPROVE-WITH-MICRO-FIXES; 9 of the 10 micro-fixes applied to spec bodies (8 stale `--cov-fail-under=95` checklist items across 8 specs + B03 §8 surviving "≥95% on host held by B2 suite" misreading + B03 §1 prose qualifier). Item 10 (B17 forward-propagation) recorded above.

### 2026-05-02 — chat_nextseek host-import audit (after B2 implementer DONE_WITH_CONCERNS, pre-merge)

- **Trigger**: B2 implementer reported 17/17 green at SHA `6fb90618` but only after silently bumping the worktree's `.python-version` to 3.14 (uncommitted). When the main session reverted it to integration's pinned `3.12` and re-ran, `tests/unit/test_nextseek_runner.py::test_runner_emits_structured_error_on_missing_creds` failed (`AssertionError: 'IMPORT_FAILED' == 'CONFIG_MISSING'`) because the subprocess `_nextseek_runner.py` invocation hit `from chat_nextseek.config import ChatConfig` first and exited 2 before reaching the cred-missing check. chat_nextseek requires Python ≥3.14; host pins 3.12; chat_nextseek is image-only by Plan A T7's PATH_B decision (`pyproject.toml` closing comment). Six prior reviewers (B1, B2, cross-task, B1 re-review, B2 re-review, the 2026-05-01 onboard cross-reference) missed it because the misreading lived in parenthetical notes about a pre-flight that doesn't actually verify host import.
- **Audit (2026-05-02)**: a full sweep of plan body + B1 spec + B2 spec for chat_nextseek host-vs-image touchpoints identified 5 CRITICAL defects (plan body line 891 referencing a non-existent `make install-chat-nextseek` target and a non-existent host-import pre-flight; B2 spec line 33's "AND in the dev environment" clause; B2 spec line 170's "importable in dev" clause; B2 spec line 1061's false claim that pyproject.toml ought to include chat_nextseek; B2 spec §5.1 missing `pytest.importorskip`); 1 CRITICAL propagation risk to Wave 3 task bodies B3.3 and B9.3 (re-run the broken baseline test, plus a layered defect on dotted-module `--cov=` form); 2 HIGH documentation defects on plan lines 98 and 160 (no host/image qualifier on "chat_nextseek importable").
- **Resolution (10 items, all applied 2026-05-02)**:
  1. Plan body line ~891 rewritten to delete the non-existent `make install-chat-nextseek` reference and the false pre-flight claim; replaced with mandatory unconditional `importorskip` rule + cross-reference to the new `## Host vs Image Python Environment` section.
  2. B2 spec §1/§2 line ~33: removed the "AND in the dev environment" clause; explicit "image-only".
  3. B2 spec §5.2 line ~170: rewritten as unconditional `importorskip` instruction; struck the "in dev" clause.
  4. B2 spec §9.3 line ~1061: deleted "the repo's pyproject.toml ought to include chat_nextseek"; replaced with pointer to `pyproject.toml`'s `T7 path-decision: PATH_B image-only` comment.
  5. B2 spec §5.1 baseline test: added `pytest.importorskip("chat_nextseek")` at top of file with rationale comment.
  6. **Fixup commit** on `task/B02-shared-runner` applies the same one-line `pytest.importorskip` to the actual `tests/unit/test_nextseek_runner.py` so the integration tree is green on host post-merge.
  7. Forward-propagation rule recorded in this entry: **every Wave 3-7 task spec MUST inherit (a) `importorskip` discipline on any host pytest target that imports chat_nextseek, (b) FILE-PATH `--cov` form not dotted-module form, (c) `--cov-fail-under=95`, (d) no `make install-chat-nextseek` references.** Plan body lines ~1334-1338 (B3.3) and ~1499-1503 (B9.3) carry both defects (host-import + dotted-cov) — they will be corrected when those waves are exploded; until then this Amendment Log entry is authoritative.
  8. Plan body lines 98 and 160 (compact handoff + Dependency banner) updated with explicit "image-only" qualifiers.
  9. **New section `## Host vs Image Python Environment`** added (between `## Pre-flight` and `## Tool surface`) — authoritative front-and-center reference for the host/image split + 5 numbered rules for test discipline.
  10. **Memory file** `feedback_chat_nextseek_host_image_split.md` saved + indexed in `MEMORY.md` so this lesson survives across sessions and projects.
- **Re-vetting**: ONE combined post-merge review (adversarial + per-item checklist verification) dispatched after fixup commit + B2 → integration merge. Reviewer must confirm each of the 10 items at the cited file/line.
- **Approved by**: user, 2026-05-02 via AskUserQuestion ("All right, approved. But make sure when you are done, you have a checklist...").
- **Status**: APPLIED.

### 2026-05-01 (late evening) — build_context git-add -f (after Phase 5.7, pre-B1 dispatch)

- **Trigger**: Phase 5.7 onboard cross-reference caught that `.gitignore` line 13 (`build_context/`) ignores the entire tree the locked B1 + B2 specs were committing into. Five Phase 4 reviewers had missed it. Documented in the late-evening compact handoff under "CRITICAL pre-dispatch find — `build_context/` gitignored".
- **Proposed change** (path A from the handoff): add `-f` to the `git add` invocations that target `build_context/...` paths in B1 §4 Step 2 and B2 §4 Step 7; document the requirement in B1 §9.2 Gotchas, B2 §9.3 Gotchas, and a callout above the plan's File Structure table; record a forward-propagation rule for Wave 3-7.
- **Reason**: plain `git add build_context/...` silently no-ops on a gitignored path; the subsequent `git commit -m '...'` either fails ("nothing to commit") or commits an empty change. Verified: `git ls-files build_context/` returns exactly one path (`build_context/plugins/nextseek-api/skills/nextseek-api/SKILL.md`) — historically force-added with `-f`. Path B (whitelist `build_context/plugins/nextseek/**` in `.gitignore`) was rejected because anything else that drops files into `build_context/plugins/` (e.g. `make image-stage`) could start tracking unexpectedly.
- **Blast radius**:
  - `task-B01-scaffold.md` §4 Step 2 (`git add` → `git add -f`); §9.2 Gotchas (new bullet)
  - `task-B02-shared-runner.md` §4 Step 7 (split into two `git add` calls — one with `-f` for the two `build_context/...` paths, one plain for the two `tests/unit/...` paths); §9.3 Gotchas (new bullet)
  - Plan `## File Structure` (new note above the table)
  - This `## Amendment Log` entry
  - The late-evening compact handoff "CRITICAL pre-dispatch find" callout — annotated as RESOLVED below the original text
- **Forward-propagation rule (per `feedback_amendments_must_propagate_to_task_bodies.md`)**: every Wave 3-7 task that creates files under `build_context/plugins/nextseek/` MUST use `git add -f` in its commit step. This includes B3-B9 (shims under `bin/`), B10 (`skills/nextseek/SKILL.md`), B11 (`commands/nextseek.md`), B12 (`scripts/setup.sh`), B13 (`context/` snapshot pipeline output). Wave 3 explosion MUST inherit this and bake `-f` into every authored Step 7-equivalent commit block; failure to do so is a defect to be caught at Phase 4. The exception: pure tests/docs/Makefile/Dockerfile commits remain plain `git add` because those paths are NOT under `build_context/`.
- **Re-vetting**: skipped per user directive (option "Approve — apply, skip re-vet"). Mechanical one-flag change; reviewers had already validated the surrounding §4 Step semantics. Future Wave 3 specs DO still get full Phase 4 review on first authoring, where `-f` presence becomes a checklist item.
- **Approved by**: user, 2026-05-01 (late evening) via AskUserQuestion under `/ultraplan amend` protocol.
- **Status**: APPLIED.

### 2026-05-01 — Coverage bump B2 90% → 95% (during Phase 3 Wave 1+2 task spec authoring)

- **Trigger**: User pushed back during Phase 3 spec authoring: "Isn't coverage target supposed to 95%?"
- **Proposed change**: Raise B2's coverage target on `build_context/plugins/nextseek/bin/_nextseek_runner.py` from the plan-locked 90% to the ultraplan default 95%. Withdraw the B2 coverage exception. Add three new tests to `tests/unit/test_nextseek_runner_dispatch.py` covering the previously-excepted branches: `_load_config` ImportError path (exit 2 / `IMPORT_FAILED`), `_load_read_safe_endpoints` OSError path (exit 6 / `CONFIG_ERROR`), and `main()` broad-except clause (exit 4 / `AGENT_FAILED`).
- **Reason**: On review, those three "uncoverable" branches are reachable via standard `monkeypatch` (sys.modules injection, builtins.open replacement, _DISPATCH table substitution). They do not qualify as architectural uncoverability under the ultraplan rule "It's hard is not a justification — only genuine architectural uncoverability qualifies." The 90% target inherited from Rev 2 NEW-7 was a borderline call; bumping to 95% removes a Phase 4 vetting risk and adds three small monkeypatch tests.
- **Blast radius**:
  - `task-B02-shared-runner.md` §1 status header, §4 Coverage target prose, §5.2 (3 new tests added), §4 Step 5 cov-fail-under arg, §8 Verification cov-fail-under arg + expected test count + expected coverage, §9.4 (rewritten as "no exception"), §9.5 self-review, §10 merge condition #1
  - Plan compact handoff §"Plan B execution context" Coverage gate line (line ~32)
  - Plan body Task B2 step B2.4 (verification command + expected test count)
  - Plan `## Task Specs Manifest` row for B02 (target + exception flag)
  - Plan `## Coverage Exceptions` B2 sub-section (withdrawn)
  - This `## Amendment Log` entry
- **Spec impact on tasks other than B2**: B3-B18 task specs have not yet been exploded (Phase 3 ran wave-by-wave; Wave 1+2 only). Future Wave 3+ specs MUST inherit the corrected default-95% expectation. Note: the plan body still contains stale `--cov-fail-under=90` lines in B3.3 (line ~1252) and B9.3 (line ~1417) inside the inline shim-test invocations. These lines were left untouched by this amendment because (a) they live in not-yet-exploded task bodies and (b) the user explicitly scoped this amendment to B2. **When Wave 3 (B3-B9) is exploded, the explosion process MUST raise those floors to 95% to match B2.** A forward-pointer to this amendment should appear in the B3-B9 spec headers.
- **Approved by**: user, 2026-05-01 via AskUserQuestion (option "Bump B2 to 95%, add 3 extra tests").
- **Status**: PROPAGATED to all enumerated locations.

---

## Host vs Image Python Environment

> **Authoritative reference for every Plan B test, spec, and verification step. Added 2026-05-02 by the chat_nextseek host-import audit. Read this before authoring any Wave 3+ task spec or critiquing any host-side test.**

| Property | Host (where you run `uv run pytest`) | Image (`dmac-assistant:plan-a` / `:poc`) |
|---|---|---|
| Python | 3.12 (`.python-version`; `pyproject.toml` `requires-python = ">=3.12"`) | 3.14 (Dockerfile lines 20-30, `DMAC_PYTHON=/usr/local/bin/python3.14`) |
| `chat_nextseek` package | **NOT installed; cannot install** (`chat_nextseek/pyproject.toml` declares `requires-python = ">=3.14"`; `uv.lock` has zero entries; `pyproject.toml` closing comment is `# T7 path-decision: PATH_B image-only — chat_nextseek install deferred to T8 (R4-NEW-5)`) | Installed once at image build via `COPY vendor/chat_nextseek /tmp/chat_nextseek` + `RUN uv pip install /tmp/chat_nextseek` (Plan A T8 Amendment 4 vendored-source) |
| `chat_nextseek` source | Reachable on host as a sibling git checkout at `/Users/taishajoseph/Documents/Projects/work/chat_nextseek/` (used by Plan B's pre-flight `grep` over `agents.py`/`helpers.py`) and as the gitignored `vendor/chat_nextseek/` clone produced by `make sync-vendor-deps`. **Source-reachable ≠ import-installable.** | Same vendored source becomes the installed package |

**Rule 1 — host-side test discipline.** Every host-side test file that does `import chat_nextseek`, `from chat_nextseek...`, or transitively triggers chat_nextseek import (e.g. by spawning a subprocess that runs `_nextseek_runner.py`) MUST begin with `pytest.importorskip("chat_nextseek")` after stdlib imports. This is unconditional, not conditional on a "dev environment that lacks chat_nextseek" — chat_nextseek is **never** present on the host venv. Tests that need true end-to-end chat_nextseek behavior belong in the image surface (B17 dry-run e2e, B18 manual smoke), not on host.

**Rule 2 — runner-code import order is correct.** `_nextseek_runner.py`'s `_load_config()` does `from chat_nextseek.config import ChatConfig` at the top of the function. In production (image) chat_nextseek is always present so this is fine; if it ever vanishes the runner exits with `IMPORT_FAILED` (exit 2), which is the right behavior. Do **not** reorder this to "check creds before importing chat_nextseek" — that would mask a deploy-time regression.

**Rule 3 — pre-flight semantics.** Plan B's pre-flight at lines ~258-267 only `grep`s the chat_nextseek source files for function signatures; it does NOT verify host-side importability. The B0 pre-flight at line ~105/276 (`docker run --rm dmac-assistant:plan-a python -c "..."`) verifies importability inside the image. **Neither pre-flight verifies host-side import** — the host never has chat_nextseek installed.

**Rule 4 — pyproject.toml does NOT carry chat_nextseek.** Future task specs MUST NOT instruct executors to add chat_nextseek to `[project] dependencies` or `[dependency-groups] dev`. The closing comment in `pyproject.toml` documents this decision. If a future plan ever needs to revisit it, it must amend Plan A T7 directly and address the Python-version incompatibility (3.12 host vs 3.14 chat_nextseek requirement) and the Linux/Darwin ABI mismatch flagged in Plan A Amendment 4.

**Rule 5 — Wave 3+ spec authoring checklist.** Before any Wave 3-7 task spec is locked, verify (a) every host pytest invocation that includes `tests/unit/test_nextseek_runner.py` or any chat_nextseek-dependent file is matched by an `importorskip` at the top of that file; (b) any `--cov=...` flag uses the FILE-PATH form (`build_context/plugins/nextseek/bin/_nextseek_runner.py`), not the dotted module form, because `bin/` lacks `__init__.py`; (c) the coverage floor is `--cov-fail-under=95` (per the 2026-05-01 amendment); (d) no spec text references a non-existent `make install-chat-nextseek` target.

References: `feedback_chat_nextseek_vendor.md` (memory); Plan A `nextseek-plugin-infra-2026-04-27.md` Amendment 4 line 337; `pyproject.toml` closing comment.

---

## Tool surface (Plan B builds these)

| Shim | Underlying call | Type | Invoked by |
|---|---|---|---|
| `nextseek-entity-extract` | `entity_agent(...)` | LLM (GCP) | Slash-command preamble (always first) |
| `nextseek-parse` | `parser_agent(...)` | LLM (GCP) | CC for single-shot routing |
| `nextseek-plan` | Full read-only planner advisor: `multi_parser_agent(...)` + `planner_agent(...)` + read-safe API/graph execution + context engineering + evaluator critique | LLM (GCP) + read-only execution | CC for multi-step advice |
| `nextseek-api-read` | `api_agent_build_request(...)` + audited read-safe endpoint execution | LLM (GCP) → REST | CC for read-safe API queries |
| `nextseek-api-write` | `api_agent_build_request(...)` + write execution; requires L1 prompt + `--confirmed-write` + L3 plain-text confirm | LLM (GCP) → REST | CC for explicit writes only |
| `nextseek-graph` | `graph_agent(...)` (with auto-retry) | LLM (GCP) → Neo4j | CC for lineage / structural queries |
| `nextseek-report` | `helpers.run_reporter_summary(...)` (deterministic dispatcher) with `--mode samples\|protocols\|published\|rppr` | Deterministic | CC for project reports |
| `nextseek-generate-submission` | `report_writer_agent(...)` | LLM heavy (Opus-class via GCP pro) | CC on user request |

`nextseek-plan` is still an advisor, not an unbounded executor. It may internally execute **only** read-safe API calls and graph queries so context engineering and evaluator critique have real outputs. It must not execute reports, submission generation, or any write-class operation. Write/report/submission steps are returned as skipped recommendations for CC to execute explicitly through the other tools.

---

## File Structure

> **Note (Amendment 2026-05-01 "build_context git-add -f"):** every path under `build_context/` is matched by `.gitignore` line 13 (`build_context/`) and is therefore IGNORED by git unless force-added. Any task step that commits a `build_context/plugins/nextseek/...` path MUST use `git add -f`. This applies to B1, B2, and every Wave 3-7 task that authors files under that tree (B3-B9 shims, B10 SKILL.md, B11 commands/, B12 setup.sh, B13 context/ catalog snapshots). Plain `git add` silently no-ops on these paths and produces empty commits.

| File | Disposition | Responsibility |
|---|---|---|
| `build_context/plugins/nextseek/.claude-plugin/plugin.json` | create | Plugin metadata. |
| `build_context/plugins/nextseek/bin/_nextseek_common.sh` | create | Shared shim helpers: cred translation, `NEXTSEEK_MODE=gcp`, log-dir, error formatting. |
| `build_context/plugins/nextseek/bin/_nextseek_runner.py` | create | Shared Python helper: load `ChatConfig`, lazy-init session, `--json` output mode, structured error → exit code mapping. |
| `build_context/plugins/nextseek/bin/nextseek-entity-extract` | create | Shim → `entity_agent`. Always-first by skill preamble (D14). |
| `build_context/plugins/nextseek/bin/nextseek-parse` | create | Shim → `parser_agent`. |
| `build_context/plugins/nextseek/bin/nextseek-plan` | create | Full read-only planner-advisor loop; returns planner output, executed read results, context outputs, evaluator critique, skipped steps, recommended CC actions. |
| `build_context/plugins/nextseek/bin/nextseek-api-read` | create | Shim → `api_agent_build_request` + read-safe execution only. Allowlisted by Layer 1. |
| `build_context/plugins/nextseek/bin/nextseek-api-write` | create | Shim → `api_agent_build_request` + write execution. Not allowlisted; requires `--confirmed-write`. |
| `build_context/plugins/nextseek/bin/nextseek-graph` | create | Shim → `graph_agent` with auto-retry. |
| `build_context/plugins/nextseek/bin/nextseek-report` | create | Deterministic dispatcher; `--mode samples\|protocols\|published\|rppr`. |
| `build_context/plugins/nextseek/bin/nextseek-generate-submission` | create | Shim → `report_writer_agent`. `--type GEO\|SRA\|NFCORE_RNASEQ\|NFCORE_SCRNASEQ\|PRIDE`. |
| `build_context/plugins/nextseek/skills/nextseek/SKILL.md` | create | Preamble (entity-extract first), tool catalog, L3 plain-text write-safety prompt. |
| `build_context/plugins/nextseek/commands/nextseek.md` | create | `/nextseek` slash command. |
| `build_context/plugins/nextseek/scripts/setup.sh` | create | Layer-1 permissions allowlist installer (idempotent). |
| `build_context/plugins/nextseek/context/` | create (build-time) | Snapshotted catalogs from chat_nextseek's `src/chat_nextseek/context/`. |
| `build_context/plugins/nextseek/context/read_safe_endpoints.json` | create | Audited read-safe endpoint/method allowlist, including explicit POST-search exceptions. |
| `Makefile` | modify | New `make snapshot-nextseek-catalogs` target; updated `make ingest-nextseek-docs`. |
| `Dockerfile` | modify | Replace `COPY build_context/plugins/` with `COPY build_context/plugins/nextseek/ /app/plugins/nextseek/`. Drop the `nextseek-api` PATH entry; add `nextseek` PATH entry. |
| `container/entrypoint.sh` | modify | Remove legacy `SEEK_USER`/`SEEK_PASSWORD`/`NEXTSEEK_BASE_URL` aliasing (was for nextseek-api). Add new aliasing: `NEXTSEEK_USERNAME → API_USER`, `NEXTSEEK_PASSWORD → API_PASS`, set `NEXTSEEK_MODE=gcp`. Keep the symlink-into-`~/.claude/plugins/local/` machinery. |
| `container/CLAUDE.md` | modify | Re-point auto-doc block at `/app/plugins/nextseek/`. Update Clarification policy reference. |
| `tests/unit/test_plugin_shims_invoke.py` | create | Each shim invokes the right chat_nextseek function with the expected args; uses `monkeypatch` to stub LLM calls. |
| `tests/integration/test_plugin_e2e.py` | modify | Add tests against the new plugin (image v3). Existing tests stay. |
| `tests/test_image_smoke.py` | modify | Assert old plugin path is GONE; new plugin path PRESENT; PATH includes `nextseek/bin/`. |
| `tests/test_dockerfile_build.py` | modify | Assert COPY targets new plugin only. |

---

## Pre-flight (executor runs once)

- [ ] **Read chat_nextseek's API surface to confirm import paths**

```bash
grep -n "^def entity_agent\|^def parser_agent\|^def multi_parser_agent\|^def planner_agent\|^def context_engineer_step\|^def plan_evaluator_agent\|^def api_agent_build_request\|^def graph_agent\|^def report_writer_agent" \
  /Users/taishajoseph/Documents/Projects/work/chat_nextseek/src/chat_nextseek/agents.py
grep -n "^def run_reporter_summary\|^def tool_nextseek_api_request" \
  /Users/taishajoseph/Documents/Projects/work/chat_nextseek/src/chat_nextseek/helpers.py
grep -n "^class ReporterPlan\|^class ReportWriterPlan" \
  /Users/taishajoseph/Documents/Projects/work/chat_nextseek/src/chat_nextseek/schemas/chat.py
```

Confirm the call signatures match the Revision 2 runner contract below. If chat_nextseek refactored a public function, surface to the user before proceeding — Plan B's shim contracts depend on these.

- [ ] **Confirm Plan A merged**

```bash
docker run --rm dmac-assistant:plan-a python -c "from chat_nextseek.orchestrator import run_query; print('ok')"
```

Expected: prints `ok`. If not, Plan A has not landed and Plan B cannot start.

---

## Revision 2 Mandatory Amendments

These amendments supersede conflicting text in B2, B4-B8, B10, B12, B15, and B17. Do not execute Plan B from the older task text alone.

### Runner contract: use the real `chat_nextseek` APIs

The shared runner must use these real signatures from the pinned `chat_nextseek` source:

- `entity_agent(config, user_query, sampletypes=None, assays=None, projects=None)`
- `parser_agent(session, config, user_query, entity_result)`
- `multi_parser_agent(session, config, user_query, entity_result)`
- `planner_agent(session, config, user_query, entity_result, parser_plan=None, retry_feedback=None)`
- `context_engineer_step(config, step, tool_output, next_step=None)`
- `plan_evaluator_agent(config, user_query, planner_output, step_results, step_summary, final_reply=None, stop_reason=None)`
- `api_agent_build_request(config, plan)`
- `helpers.tool_nextseek_api_request(config, endpoint, method, requestBody=None, queryParameters=None)`
- `graph_agent(config, user_query, entity_result, parser_plan=None, retry_context=None)`
- `helpers.run_reporter_summary(config, ReporterPlan(...), log_dir)`
- `report_writer_agent(config, user_query, ReportWriterPlan(...), template=None)`

The runner must import `ReporterPlan` and `ReportWriterPlan` from `chat_nextseek.schemas.chat`; it must not fabricate duck-typed reporter objects.

### Read-safe endpoint allowlist

Create `build_context/plugins/nextseek/context/read_safe_endpoints.json` as a plan-authored, reviewed artifact. It is the only source of truth for whether non-GET operations are read-safe.

Minimum shape:

```json
[
  {
    "endpoint": "/nextseek_api/samples/advanced_search/",
    "methods": ["POST"],
    "source": "min_api_endpoints_enriched.json",
    "rationale": "Search endpoint; returns data and does not mutate NExtSEEK state."
  }
]
```

Rules:

- GET endpoints are read-safe only when present in the allowlist or generated into it during the catalog snapshot step.
- POST endpoints are read-safe only when explicitly audited in this file.
- Missing endpoint/method pairs fail closed and must be routed to `nextseek-api-write`.
- Tests must assert POST search succeeds only when listed and fails closed when removed from the fixture allowlist.

### Split API shims and write safety

Replace `nextseek-api-call` with:

- `nextseek-api-read --parser-plan <json>`: allowlisted; refuses any endpoint/method not present in `read_safe_endpoints.json`; never accepts `--confirmed-write`.
- `nextseek-api-write --parser-plan <json> --confirmed-write`: not allowlisted by setup.sh; refuses execution without `--confirmed-write`.

Layer 1 must not include any pattern that can match `nextseek-api-write` or any command containing `--confirmed-write`.

### Full planner-advisor loop

`nextseek-plan` must return one JSON object with:

- `entity`: entity output,
- `multi_parser`: multi-parser output,
- `planner_output`: planner output,
- `executed_read_steps`: read-safe API and graph step results executed internally,
- `context_engineer_outputs`: context outputs for steps that had real read outputs,
- `evaluator`: evaluator critique over the actual read outputs and skipped-step summary,
- `skipped_steps`: write/report/submission or not-read-safe steps that were not executed,
- `recommended_next_actions`: instructions for CC to continue via `nextseek-api-write`, `nextseek-report`, or `nextseek-generate-submission` when needed.

Planner-advisor constraints:

- May execute read-safe API calls and graph queries only.
- Must never execute writes, reports, or submission generation.
- Must use `read_safe_endpoints.json` before any internal API execution.
- If a planned step is not read-safe, it records a skipped step rather than trying to work around the safety model.

### D19 path translation in SKILL.md

SKILL.md must read `DMAC_PATH_MAPPINGS` and translate artifact paths by replacing known container roots with host roots. It must not hard-code `/persistent/output/{user_id}`. If `DMAC_PATH_MAPPINGS` is absent or invalid, CC should report the container path and clearly say the host mapping was unavailable.

### Test hardening

- Add monkeypatched unit tests for each runner dispatcher path, asserting the exact imported `chat_nextseek` function is called with the expected argument order.
- Replace B17's permissive "no ImportError" image test with a stub/dry-run image test that must return agent-specific JSON for at least `nextseek-entity-extract`, `nextseek-api-read`, and `nextseek-plan`.
- Fix B15's bats test: execute `container/entrypoint.sh sh -c 'env'` and assert exported variables from output; do not source a script that ends with `exec "$@"`.

---

## Revision 3 Mandatory Amendments

Revision 3 supersedes Revision 2 wherever they conflict. Where Revision 2 stated requirements only in prose, Revision 3 has rewritten the affected task bodies so an executor following the task text literally produces correct code. Affected tasks: **B2.3** (runner code), **B2.2b** (new step), **B6a** (new shim test), **B10.1** (SKILL.md "Reply hygiene"), **B10** (new grep verification step), **B13.1** (Makefile target), **B14.1** (new Dockerfile assertion), **B17.1** (image dry-run test), **B18.2** (verification text), and coverage requirements added to **B2.4**, **B3.3**, **B9.3**.

If a Revision 2 amendment and a Revision 3 amendment conflict, Revision 3 wins. Cross-check the task body before executing — Revision 2's failure mode was that amendments at the top did not propagate into task bodies. Revision 3 was authored specifically to close that gap.

### NEW-1 — Runner dispatcher split (`api-read` / `api-write`)

**Closes:** NEW-1 in `plan-B-revision-2-focused-review-2026-05-01.md`.

**What changed in the task body:** B2.3's full `_nextseek_runner.py` code block has been rewritten. The single `_dispatch_api_call` is replaced by two distinct dispatchers:

- `_dispatch_api_read(args, config, session)` — loads `read_safe_endpoints.json` (path overridable via `NEXTSEEK_READ_SAFE_ENDPOINTS_PATH`), parses `--parser-plan`, refuses `(endpoint, method)` pairs absent from the allowlist with exit code 5 (`WRITE_BLOCKED`), then executes the request via `helpers.tool_nextseek_api_request`.
- `_dispatch_api_write(args, config, session)` — refuses execution unless `--confirmed-write` is set (exit code 5), does NOT consult the allowlist, executes via `helpers.tool_nextseek_api_request`.

`_DISPATCH` keys are now `entity`, `parse`, `plan`, `api-read`, `api-write`, `graph`, `report`, `generate-submission`. The `--agent` argparse `choices=sorted(_DISPATCH)` clause picks them up automatically.

Additionally, `NEXTSEEK_DRY_RUN=1` short-circuits each dispatcher to a minimal valid typed-JSON response so B17.1's dry-run test can pass without GCP/NExtSEEK credentials.

**Where to look:** B2.3 code block (now rewritten end-to-end).

### NEW-2 — Per-dispatcher monkeypatched tests

**Closes:** NEW-2.

**What changed in the task body:** A new step **B2.2b** sits between B2.2 and B2.3 and creates `tests/unit/test_nextseek_runner_dispatch.py`. The step specifies:

- One test per dispatcher: `entity`, `parse`, `plan`, `api-read`, `api-write`, `graph`, `report`, `generate-submission`.
- Each test uses `importlib.util.spec_from_file_location` to import `_nextseek_runner` (it is a script, not a package).
- Each test monkeypatches the corresponding `chat_nextseek.agents.<fn>` or `chat_nextseek.helpers.<fn>` with a `MagicMock` and asserts a single call with the expected positional args in the documented argument order.
- A reference test (`test_dispatch_entity_calls_entity_agent_with_config_and_query`) is provided in full so the remaining seven tests can be authored from the template without follow-up.

The new test file is added to B2.5's `git add` line and runs in B2.4.

**Where to look:** new B2.2b step; B2.4 pytest invocation; B2.5 commit step.

### NEW-3 — SKILL.md "Reply hygiene" rewrite + grep guard

**Closes:** NEW-3 (D19 host-path reporting).

**What changed in the task body:** B10.1's "Reply hygiene" subsection no longer references `/persistent/output/{user_id}/`. It now instructs the in-container Claude runtime to read `DMAC_PATH_MAPPINGS` (a JSON object mapping container roots to host roots — see `src/dmac_assistant/containers.py`) and translate paths at reply time. A new B10.3 verification step greps the committed SKILL.md for the forbidden literal and fails if found. The grep is wired into the B10 commit gate.

**Where to look:** B10.1 SKILL.md block, "Reply hygiene" subsection; new B10.3 verification step; B10.4 commit step (formerly B10.2) now runs the grep before committing.

### NEW-4 — B17.1 dry-run image test

**Closes:** NEW-4.

**What changed in the task body:** B17.1's test text has been replaced. The new test sets `NEXTSEEK_DRY_RUN=1`, runs `nextseek-entity-extract`, `nextseek-api-read`, and `nextseek-plan` inside the image, and asserts each returns exit code 0 with agent-specific top-level JSON keys. The test depends on NEW-1's `NEXTSEEK_DRY_RUN` runner support.

**Where to look:** B17.1 test code block (now rewritten).

### NEW-5 — `read_safe_endpoints.json` allowlist enforcement

**Closes:** NEW-5.

**What changed in the task body:** Subsumed by NEW-1's runner rewrite. `_load_read_safe_endpoints()` is a helper inside `_nextseek_runner.py` that:

- Resolves the path from `NEXTSEEK_READ_SAFE_ENDPOINTS_PATH` (default `/app/plugins/nextseek/context/read_safe_endpoints.json`).
- Parses the JSON list and returns a set of `(endpoint, method.upper())` tuples.
- Exits with code 6 (`CONFIG_ERROR`) and a message naming the missing file if the file is absent and no override is set.

A new `CONFIG_ERROR` exit code is documented in the runner docstring and in B10.1's "Errors" subsection.

**Where to look:** B2.3 runner code (`_load_read_safe_endpoints` helper, `_dispatch_api_read` body); B10.1 "Errors" list.

### NEW-6 — `CHAT_NEXTSEEK_SRC` Makefile parameterization + Dockerfile catalog assertion

**Closes:** NEW-6.

**What changed in the task body:** B13.1's Makefile target is parameterized (`CHAT_NEXTSEEK_SRC ?= /Users/taishajoseph/Documents/Projects/work/chat_nextseek`) with a `test -d` guard that exits with a clear error message if the source path is missing. B14 gains a `RUN test ...` line in the Dockerfile, immediately after the COPY of plugin context, that fails the build if no `min_*.json` files exist in the image's plugin context dir.

**Where to look:** B13.1 Makefile block; B14.1 Dockerfile diff (new line after COPY).

### NEW-7 — Coverage floor

**Closes:** NEW-7.

**What changed in the task body:** B2.4, B3.3, and B9.3 pytest invocations now pass `--cov=build_context.plugins.nextseek.bin._nextseek_runner --cov-fail-under=90 -v`. The coverage scope is intentionally narrowed to the Python runner module rather than the whole `bin/` dir because `bin/` contains shell shim scripts that pytest-cov cannot measure; trying for `--cov=build_context/plugins/nextseek/bin` at 90% would either be unenforceable or require a mocked-up `bash`-coverage tool. The runner is the security-critical module, and 90% on it is the meaningful gate.

**Where to look:** B2.4, B3.3, B9.3 pytest invocations.

### NEW-8 — B18.2 path verification text

**Closes:** NEW-8.

**What changed in the task body:** B18.2's verification bullet no longer hard-codes `~/persistent/output/<user_id>/<run-id>/`. It now reads "the reply quotes a host-side artifact path consistent with the `DMAC_PATH_MAPPINGS` env var injected into the session (in dev: `~/dmac-dev/output/demo/`; in prod: per the configured `output_root`)."

**Where to look:** B18.2 verification list.

### Residual NEW: B6a `--confirmed-write` rejection test

**Closes:** CRITICAL-3 residual risk.

**What changed in the task body:** B6a's test step gains `test_read_shim_rejects_confirmed_write`. The test invokes the read shim with `--confirmed-write` and asserts a non-zero exit. This guards the boundary the L1 allowlist depends on: an LLM cannot smuggle a write through the allowlisted read shim by appending `--confirmed-write`.

**Where to look:** B6a test step (within the B4–B8 task block).

---

## Task B1: Plugin scaffold + `plugin.json`

**Files:**
- Create: `build_context/plugins/nextseek/.claude-plugin/plugin.json`
- Create: `build_context/plugins/nextseek/README.md` (one-pager pointing at SKILL.md)

- [ ] **Step B1.1: Create the plugin.json**

```json
{
  "name": "nextseek",
  "version": "0.1.0",
  "description": "Modular NExtSEEK query workflow for Container-Claude. Wraps the chat_nextseek multi-agent pipeline as discrete plugin tools (entity-extract, parse, plan, api-read, api-write, graph, report, generate-submission) so CC orchestrates routing/planning natively while chat_nextseek owns deterministic execution.",
  "author": {"name": "BMC"},
  "keywords": ["nextseek", "chat_nextseek", "bmc", "metadata", "graph"]
}
```

- [ ] **Step B1.2: Create a one-line README**

```markdown
# nextseek plugin
See `skills/nextseek/SKILL.md`. Replaces the demo-grade `nextseek-api` plugin.
```

- [ ] **Step B1.3: Commit**

```bash
git add build_context/plugins/nextseek/.claude-plugin/plugin.json \
        build_context/plugins/nextseek/README.md
git commit -m "nextseek-plugin: scaffold plugin.json + README

Plan B · T1."
```

---

## Task B2: Shared shim helpers — `_nextseek_common.sh` + `_nextseek_runner.py`

**Files:**
- Create: `build_context/plugins/nextseek/bin/_nextseek_common.sh`
- Create: `build_context/plugins/nextseek/bin/_nextseek_runner.py`
- Create: `tests/unit/test_nextseek_runner.py`

**Findings addressed:** none new; foundational reuse for B3–B9.

**Revision 2 note:** Step B2.3's original runner code is superseded by the "Runner contract" in Revision 2 Mandatory Amendments. Use the exact real `chat_nextseek` signatures listed there; do not copy the old `run_api_request` / duck-typed ReporterPlan implementation.

- [ ] **Step B2.1: Write `_nextseek_common.sh` (sourced by every shim)**

```bash
#!/bin/sh
# Sourced by every nextseek-* shim. Translates env vars chat_nextseek expects.

# D20: re-export env names chat_nextseek's ChatConfig reads.
: "${API_USER:=${NEXTSEEK_USERNAME:-}}"
: "${API_PASS:=${NEXTSEEK_PASSWORD:-}}"
: "${NEXTSEEK_BASE_URL:=${NEXTSEEK_URL:-}}"
export API_USER API_PASS NEXTSEEK_BASE_URL

# D23: force GCP profile.
: "${NEXTSEEK_MODE:=gcp}"
export NEXTSEEK_MODE

# Default outputs land under /data/scratch/<user>/<run-id>/ (chat_nextseek
# orchestrator creates per-run subdirs). The bridge-side copier (Plan A T5)
# discovers them by scratch-listing diff and publishes to /data/output/.
: "${NEXTSEEK_OUTPUTS_DIR:=/data/scratch/${API_USER:-anon}}"
export NEXTSEEK_OUTPUTS_DIR

# Quiet config-load logs by default.
: "${CHAT_NEXTSEEK_CONFIG_VERBOSE:=false}"
export CHAT_NEXTSEEK_CONFIG_VERBOSE

# nextseek_die <code> <message>: structured error -> stderr + exit
nextseek_die() {
  printf 'nextseek-error: %s\n' "$2" >&2
  exit "$1"
}
```

- [ ] **Step B2.2: Write the runner failing test**

Create `tests/unit/test_nextseek_runner.py`:

```python
"""Plan B · T2: shared runner produces structured JSON output."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

RUNNER = Path(
    "build_context/plugins/nextseek/bin/_nextseek_runner.py"
).resolve()


def test_runner_emits_structured_error_on_missing_creds(tmp_path, monkeypatch):
    monkeypatch.delenv("API_USER", raising=False)
    monkeypatch.delenv("API_PASS", raising=False)
    result = subprocess.run(
        ["python", str(RUNNER), "--agent", "entity", "--query", "x"],
        capture_output=True, text=True, env={"PATH": "/usr/bin:/bin"},
    )
    assert result.returncode != 0
    payload = json.loads(result.stderr.strip().splitlines()[-1])
    assert payload["error"]["code"] == "CONFIG_MISSING"
```

- [ ] **Step B2.2b: Write per-dispatcher monkeypatched tests (NEW-2)**

Create `tests/unit/test_nextseek_runner_dispatch.py`. There must be one test per dispatcher key in `_DISPATCH`: `entity`, `parse`, `plan`, `api-read`, `api-write`, `graph`, `report`, `generate-submission`. Each test loads `_nextseek_runner.py` as a module via `importlib.util.spec_from_file_location` (the runner is a script, not an installed package). Each test monkeypatches the corresponding `chat_nextseek` import target with a `unittest.mock.MagicMock`, calls the dispatcher with a minimal `argparse.Namespace`, and asserts the mock was called once with the documented positional arguments in the documented order.

The reference test (entity) is fully written below; author the remaining seven by analogy. Argument order per dispatcher:

- `entity`: `entity_agent(config, args.query)` — verify positional args are `(config, "...query...")`.
- `parse`: calls `entity_agent(config, args.query)` then `parser_agent(session, config, args.query, entity_out)` — assert `parser_agent` called with `(session, config, query, entity_out)` in that order.
- `plan`: calls `entity_agent`, `multi_parser_agent(session, config, args.query, entity_out)`, `planner_agent(session, config, args.query, entity_out, multi)` — assert `planner_agent` positional args `(session, config, query, entity_out, multi)`.
- `api-read`: pre-stub `_load_read_safe_endpoints` to return a set containing `(endpoint, method)`; assert `helpers.tool_nextseek_api_request(config, endpoint, method, requestBody=..., queryParameters=...)` is invoked.
- `api-write`: with `args.confirmed_write=True`; assert `helpers.tool_nextseek_api_request` invoked with the parsed plan; with `args.confirmed_write=False`, assert `SystemExit` with exit code 5.
- `graph`: `graph_agent(config, args.query, entity_out)` — assert positional args.
- `report`: `helpers.run_reporter_summary(config, ReporterPlan(...), log_dir)` — assert called once with a `ReporterPlan` instance whose `summary_mode` matches the input mode.
- `generate-submission`: `report_writer_agent(config, args.query or "", ReportWriterPlan(...))` — assert called with a `ReportWriterPlan` whose `report_type` matches.

Reference template (use literally for the entity test, adapt for the others):

```python
"""Plan B · T2 · B2.2b: per-dispatcher monkeypatch tests for _nextseek_runner."""
from __future__ import annotations

import argparse
import importlib.util
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

RUNNER_PATH = Path(
    "build_context/plugins/nextseek/bin/_nextseek_runner.py"
).resolve()


def _load_runner():
    """Load _nextseek_runner.py as a module (it's a script, not a package)."""
    spec = importlib.util.spec_from_file_location("_nextseek_runner", RUNNER_PATH)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_nextseek_runner"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def runner():
    return _load_runner()


def test_dispatch_entity_calls_entity_agent_with_config_and_query(runner, monkeypatch):
    """entity_agent must be called with (config, query) in that order."""
    fake_entity_agent = MagicMock(return_value=MagicMock(model_dump=lambda: {"sampletypes": []}))
    # chat_nextseek.agents is imported INSIDE _dispatch_entity; patch the module attr.
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)

    args = argparse.Namespace(query="find samples")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_entity(args, config, session)

    fake_entity_agent.assert_called_once()
    call_args, call_kwargs = fake_entity_agent.call_args
    # Positional argument order matters: (config, query).
    assert call_args[0] is config, f"first positional arg should be config, got {call_args[0]!r}"
    assert call_args[1] == "find samples", f"second positional arg should be query, got {call_args[1]!r}"
    assert result == {"sampletypes": []}


def test_dispatch_parse_calls_parser_agent_with_session_config_query_entity(runner, monkeypatch):
    """parser_agent must be called with (session, config, query, entity_out)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_parser_agent = MagicMock(
        return_value=MagicMock(model_dump=lambda: {"mode": "new_search"})
    )
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "parser_agent", fake_parser_agent)

    args = argparse.Namespace(query="find samples")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_parse(args, config, session)

    fake_entity_agent.assert_called_once()
    ent_args, _ = fake_entity_agent.call_args
    assert ent_args[0] is config
    assert ent_args[1] == "find samples"

    fake_parser_agent.assert_called_once()
    p_args, _ = fake_parser_agent.call_args
    assert p_args[0] is session, f"parser_agent arg0 should be session, got {p_args[0]!r}"
    assert p_args[1] is config, f"parser_agent arg1 should be config, got {p_args[1]!r}"
    assert p_args[2] == "find samples", f"parser_agent arg2 should be query, got {p_args[2]!r}"
    assert p_args[3] is fake_entity_out, f"parser_agent arg3 should be entity_out, got {p_args[3]!r}"
    assert result == {"mode": "new_search"}


def test_dispatch_plan_calls_planner_agent_with_full_positional_chain(runner, monkeypatch):
    """planner_agent must be called with (session, config, query, entity_out, multi)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_multi = MagicMock(name="multi_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_multi_parser_agent = MagicMock(return_value=fake_multi)
    fake_planner_agent = MagicMock(
        return_value=MagicMock(model_dump=lambda: {"plan": []})
    )
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "multi_parser_agent", fake_multi_parser_agent)
    monkeypatch.setattr(agents_mod, "planner_agent", fake_planner_agent)

    args = argparse.Namespace(query="find samples then lineage")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_plan(args, config, session)

    fake_multi_parser_agent.assert_called_once()
    mp_args, _ = fake_multi_parser_agent.call_args
    assert mp_args[0] is session
    assert mp_args[1] is config
    assert mp_args[2] == "find samples then lineage"
    assert mp_args[3] is fake_entity_out

    fake_planner_agent.assert_called_once()
    pl_args, _ = fake_planner_agent.call_args
    assert pl_args[0] is session, f"planner_agent arg0 should be session, got {pl_args[0]!r}"
    assert pl_args[1] is config, f"planner_agent arg1 should be config, got {pl_args[1]!r}"
    assert pl_args[2] == "find samples then lineage"
    assert pl_args[3] is fake_entity_out, f"planner_agent arg3 should be entity_out"
    assert pl_args[4] is fake_multi, f"planner_agent arg4 should be multi, got {pl_args[4]!r}"
    assert result == {"plan": []}


def test_dispatch_api_read_calls_helpers_tool_nextseek_api_request(runner, monkeypatch, tmp_path):
    """api-read: build_request → allowlist check → helpers.tool_nextseek_api_request."""
    # Build a fake api_plan returned by api_agent_build_request.
    fake_api_plan = MagicMock(name="api_plan")
    fake_api_plan.endpoint = "/samples/"
    fake_api_plan.method = "GET"
    fake_api_plan.requestBody = None
    fake_api_plan.queryParameters = {"project": "X"}
    fake_api_plan.model_dump = lambda: {"endpoint": "/samples/", "method": "GET"}

    fake_build_request = MagicMock(return_value=fake_api_plan)
    fake_tool_request = MagicMock(return_value={"results": []})

    import chat_nextseek.agents as agents_mod
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(agents_mod, "api_agent_build_request", fake_build_request)
    monkeypatch.setattr(helpers_mod, "tool_nextseek_api_request", fake_tool_request)
    # Force the allowlist to admit our (endpoint, method) pair.
    monkeypatch.setattr(
        runner, "_load_read_safe_endpoints",
        lambda: {("/samples/", "GET")},
    )

    args = argparse.Namespace(
        parser_plan='{"mode": "new_search"}',
        confirmed_write=False,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_api_read(args, config, session)

    fake_build_request.assert_called_once()
    br_args, _ = fake_build_request.call_args
    assert br_args[0] is config, f"api_agent_build_request arg0 should be config"
    assert br_args[1] == {"mode": "new_search"}, f"arg1 should be parsed plan dict"

    fake_tool_request.assert_called_once()
    tr_args, tr_kwargs = fake_tool_request.call_args
    assert tr_args[0] is config, f"tool_nextseek_api_request arg0 should be config"
    assert tr_args[1] == "/samples/", f"arg1 should be endpoint"
    assert tr_args[2] == "GET", f"arg2 should be method"
    assert tr_kwargs.get("requestBody") is None
    assert tr_kwargs.get("queryParameters") == {"project": "X"}
    assert result["endpoint"] == "/samples/"
    assert result["method"] == "GET"
    assert result["response"] == {"results": []}


def test_dispatch_api_write_with_confirmed_write_calls_helpers_tool_nextseek_api_request(
    runner, monkeypatch
):
    """api-write with --confirmed-write: passes through to helpers.tool_nextseek_api_request."""
    fake_api_plan = MagicMock(name="api_plan")
    fake_api_plan.endpoint = "/samples/"
    fake_api_plan.method = "POST"
    fake_api_plan.requestBody = {"name": "S1"}
    fake_api_plan.queryParameters = None
    fake_api_plan.model_dump = lambda: {"endpoint": "/samples/", "method": "POST"}

    fake_build_request = MagicMock(return_value=fake_api_plan)
    fake_tool_request = MagicMock(return_value={"created": True})

    import chat_nextseek.agents as agents_mod
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(agents_mod, "api_agent_build_request", fake_build_request)
    monkeypatch.setattr(helpers_mod, "tool_nextseek_api_request", fake_tool_request)

    args = argparse.Namespace(
        parser_plan='{"mode": "create"}',
        confirmed_write=True,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_api_write(args, config, session)

    fake_tool_request.assert_called_once()
    tr_args, tr_kwargs = fake_tool_request.call_args
    assert tr_args[0] is config
    assert tr_args[1] == "/samples/"
    assert tr_args[2] == "POST"
    assert tr_kwargs.get("requestBody") == {"name": "S1"}
    assert tr_kwargs.get("queryParameters") is None
    assert result["endpoint"] == "/samples/"
    assert result["method"] == "POST"


def test_dispatch_api_write_without_confirmed_write_exits_5(runner, monkeypatch):
    """api-write without --confirmed-write must SystemExit with code 5 (Layer-2 block)."""
    args = argparse.Namespace(
        parser_plan='{"mode": "create"}',
        confirmed_write=False,
    )
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    with pytest.raises(SystemExit) as exc_info:
        runner._dispatch_api_write(args, config, session)
    assert exc_info.value.code == 5, f"expected exit 5 (WRITE_BLOCKED), got {exc_info.value.code}"


def test_dispatch_graph_calls_graph_agent_with_config_query_entity(runner, monkeypatch):
    """graph_agent must be called with (config, query, entity_out)."""
    fake_entity_out = MagicMock(name="entity_out")
    fake_entity_agent = MagicMock(return_value=fake_entity_out)
    fake_graph_agent = MagicMock(return_value={"cypher": "MATCH (n) RETURN n", "result": []})
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "entity_agent", fake_entity_agent)
    monkeypatch.setattr(agents_mod, "graph_agent", fake_graph_agent)

    args = argparse.Namespace(query="lineage of S1")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_graph(args, config, session)

    fake_graph_agent.assert_called_once()
    g_args, _ = fake_graph_agent.call_args
    assert g_args[0] is config, f"graph_agent arg0 should be config"
    assert g_args[1] == "lineage of S1", f"graph_agent arg1 should be query"
    assert g_args[2] is fake_entity_out, f"graph_agent arg2 should be entity_out"
    assert result == {"cypher": "MATCH (n) RETURN n", "result": []}


def test_dispatch_report_calls_run_reporter_summary_with_reporter_plan(runner, monkeypatch):
    """run_reporter_summary must be called with (config, ReporterPlan, log_dir)."""
    fake_run_reporter = MagicMock(return_value=([{"row": 1}], ["/tmp/out.csv"], "summary text"))
    from chat_nextseek import helpers as helpers_mod
    monkeypatch.setattr(helpers_mod, "run_reporter_summary", fake_run_reporter)
    monkeypatch.setenv("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")

    args = argparse.Namespace(mode="samples", project="ProjectA", query=None)
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_report(args, config, session)

    fake_run_reporter.assert_called_once()
    r_args, _ = fake_run_reporter.call_args
    assert r_args[0] is config, f"run_reporter_summary arg0 should be config"
    # arg1 is a ReporterPlan instance — verify summary_mode matches input mode.
    rp = r_args[1]
    assert rp.project == "ProjectA"
    assert rp.summary_mode == "samples", f"summary_mode should be 'samples', got {rp.summary_mode!r}"
    assert r_args[2] == "/tmp/nextseek", f"arg2 should be log_dir"
    assert result["summary"] == "summary text"
    assert result["saved_files"] == ["/tmp/out.csv"]


def test_dispatch_generate_submission_calls_report_writer_agent_with_plan(runner, monkeypatch):
    """report_writer_agent must be called with (config, query_str, ReportWriterPlan)."""
    fake_report = MagicMock()
    fake_report.model_dump = lambda: {"report": "text", "type": "GEO"}
    fake_writer = MagicMock(return_value=fake_report)
    import chat_nextseek.agents as agents_mod
    monkeypatch.setattr(agents_mod, "report_writer_agent", fake_writer)

    args = argparse.Namespace(type="GEO", uids="S1,S2", query="generate GEO")
    config = MagicMock(name="config")
    session = MagicMock(name="session")

    result = runner._dispatch_generate_submission(args, config, session)

    fake_writer.assert_called_once()
    w_args, _ = fake_writer.call_args
    assert w_args[0] is config, f"report_writer_agent arg0 should be config"
    assert w_args[1] == "generate GEO", f"arg1 should be query string"
    plan = w_args[2]
    assert plan.report_type == "GEO", f"report_type should be 'GEO', got {plan.report_type!r}"
    assert plan.reporter_context == {"uids": ["S1", "S2"]}
    assert result == {"report": "text", "type": "GEO"}
```

**`pytest.importorskip("chat_nextseek")` is mandatory at the top of every host-side test file that imports chat_nextseek, including the §5.1 baseline subprocess test.** chat_nextseek is **never** installed on the host venv per Plan A T7's PATH_B image-only decision (see `pyproject.toml` closing comment `# T7 path-decision: PATH_B image-only — chat_nextseek install deferred to T8 (R4-NEW-5)` and the new `## Host vs Image Python Environment` section). The host runs Python 3.12 and chat_nextseek's own `pyproject.toml` declares `requires-python = ">=3.14"`, so it physically cannot install on host. There is **no** `make install-chat-nextseek` Makefile target — earlier wording in this plan that referenced one was a defect (revised 2026-05-02; see `## Amendment Log` entry "chat_nextseek host-import audit"). The B0 pre-flight at line 105/276 verifies importability **only inside the `dmac-assistant:plan-a` image**, not on the host. On the host, every chat_nextseek-dependent test must either skip via `importorskip` or run inside the image (B17/B18 surface).

- [ ] **Step B2.3: Implement the runner**

Create `build_context/plugins/nextseek/bin/_nextseek_runner.py`:

```python
#!/usr/bin/env python
"""Shared entry point for nextseek-* shims.

Loads chat_nextseek's ChatConfig once, dispatches to the requested agent,
emits one of:
  - stdout: result JSON (one line)
  - stderr (last line): structured error JSON, exit code != 0

Exit codes:
  0  ok
  2  config / env missing
  3  validation (bad args)
  4  agent failure (LLM error, network, etc.)
  5  write blocked (Layer-2 --confirmed-write missing OR endpoint not in
     read_safe_endpoints.json on api-read path)
  6  config error (read_safe_endpoints.json missing in production)

Dry-run mode: when NEXTSEEK_DRY_RUN=1, each dispatcher returns a minimal
valid typed JSON response without invoking any LLM, REST, or Neo4j call.
This is what B17.1's image dry-run test exercises to prove wiring without
needing live GCP/NExtSEEK credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import sys


READ_SAFE_ENDPOINTS_DEFAULT = "/app/plugins/nextseek/context/read_safe_endpoints.json"


def _err(code: str, message: str, exit_code: int) -> None:
    payload = {"error": {"code": code, "message": message}}
    sys.stderr.write(json.dumps(payload) + "\n")
    sys.exit(exit_code)


def _dry_run() -> bool:
    return os.environ.get("NEXTSEEK_DRY_RUN") == "1"


def _load_config():
    try:
        from chat_nextseek.config import ChatConfig
    except ImportError as exc:
        _err("IMPORT_FAILED", f"chat_nextseek not importable: {exc}", 2)
    if not os.environ.get("API_USER") or not os.environ.get("API_PASS"):
        _err("CONFIG_MISSING", "API_USER / API_PASS not set", 2)
    return ChatConfig({})


def _make_session(config):
    from chat_nextseek.session import SQLiteSessionState
    user = os.environ.get("API_USER", "anon")
    return SQLiteSessionState(config.SESSION_DB_PATH, user)


def _load_read_safe_endpoints():
    """Return set of (endpoint, METHOD) tuples from read_safe_endpoints.json.

    Path resolution:
      - If NEXTSEEK_READ_SAFE_ENDPOINTS_PATH is set, use that (test override).
      - Else default to /app/plugins/nextseek/context/read_safe_endpoints.json.

    If the file is missing, exit with code 6 (CONFIG_ERROR) naming the path.
    """
    path = os.environ.get("NEXTSEEK_READ_SAFE_ENDPOINTS_PATH",
                          READ_SAFE_ENDPOINTS_DEFAULT)
    if not os.path.exists(path):
        _err("CONFIG_ERROR",
             f"read_safe_endpoints.json missing at {path}; set "
             "NEXTSEEK_READ_SAFE_ENDPOINTS_PATH or rebuild the image",
             6)
    try:
        with open(path) as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError) as exc:
        _err("CONFIG_ERROR",
             f"failed to load {path}: {type(exc).__name__}: {exc}",
             6)
    allowlist = set()
    for entry in data:
        ep = entry.get("endpoint")
        for m in entry.get("methods", []):
            allowlist.add((ep, m.upper()))
    return allowlist


# ---------------------------------------------------------------- dispatchers

def _dispatch_entity(args, config, session):
    if _dry_run():
        return {"sampletypes": [], "assays": [], "keywords": [], "projects": []}
    from chat_nextseek.agents import entity_agent
    out = entity_agent(config, args.query)
    return out.model_dump() if hasattr(out, "model_dump") else out


def _dispatch_parse(args, config, session):
    if _dry_run():
        return {"mode": "new_search", "target_endpoint": None}
    from chat_nextseek.agents import parser_agent, entity_agent
    entity_out = entity_agent(config, args.query)
    plan = parser_agent(session, config, args.query, entity_out)
    return plan.model_dump() if hasattr(plan, "model_dump") else plan


def _dispatch_plan(args, config, session):
    """multi_parser + planner advisor. Read-only execution per Rev 2 D2.

    Full advisor loop (executed_read_steps, context_engineer_outputs,
    evaluator critique, skipped_steps, recommended_next_actions) is
    elaborated by `nextseek-plan` shim's runner path; the runner returns
    the planner output and any executed read-only step results.
    """
    if _dry_run():
        return {
            "plan": [],
            "executed_read_steps": [],
            "context_engineer_outputs": [],
            "evaluator": None,
            "skipped_steps": [],
            "recommended_next_actions": [],
        }
    from chat_nextseek.agents import (
        entity_agent, multi_parser_agent, planner_agent,
    )
    entity_out = entity_agent(config, args.query)
    multi = multi_parser_agent(session, config, args.query, entity_out)
    plan = planner_agent(session, config, args.query, entity_out, multi)
    return plan.model_dump() if hasattr(plan, "model_dump") else plan


def _dispatch_api_read(args, config, session):
    """Read-only API dispatch. Refuses non-allowlisted (endpoint, method) pairs.

    NEW-1 + NEW-5: read_safe_endpoints.json is the only source of truth for
    which (endpoint, method) pairs are read-safe. Anything else → exit 5.
    The shim must NOT pass --confirmed-write here; the read shim itself
    rejects it (B6a test_read_shim_rejects_confirmed_write).
    """
    if not args.parser_plan:
        _err("VALIDATION", "--parser-plan required", 3)
    if args.confirmed_write:
        _err("VALIDATION",
             "--confirmed-write is not valid on api-read; use api-write", 3)

    if _dry_run():
        return {"endpoint": "/dry-run/", "method": "GET", "response": {}}

    try:
        plan_dict = json.loads(args.parser_plan)
    except json.JSONDecodeError as exc:
        _err("VALIDATION", f"--parser-plan is not valid JSON: {exc}", 3)

    from chat_nextseek.agents import api_agent_build_request
    api_plan = api_agent_build_request(config, plan_dict)
    endpoint = api_plan.endpoint
    method = api_plan.method.upper()

    allowlist = _load_read_safe_endpoints()
    if (endpoint, method) not in allowlist:
        _err("WRITE_BLOCKED",
             f"endpoint {endpoint!r} method {method!r} not in "
             "read_safe_endpoints.json; route via nextseek-api-write if "
             "this is an intentional write",
             5)

    from chat_nextseek import helpers
    result = helpers.tool_nextseek_api_request(
        config,
        endpoint,
        method,
        requestBody=api_plan.requestBody,
        queryParameters=api_plan.queryParameters,
    )
    return {
        "endpoint": endpoint,
        "method": method,
        "api_plan": api_plan.model_dump() if hasattr(api_plan, "model_dump") else api_plan,
        "response": result,
    }


def _dispatch_api_write(args, config, session):
    """Write-class API dispatch. Layer 2: refuses without --confirmed-write.

    No allowlist consultation: writes are gated by L1 (no allowlist entry
    for nextseek-api-write — Claude Code prompts the user) + L2 (this
    function's --confirmed-write check) + L3 (the SKILL.md plain-text
    confirmation prompt).
    """
    if not args.parser_plan:
        _err("VALIDATION", "--parser-plan required", 3)
    if not args.confirmed_write:
        _err("WRITE_BLOCKED",
             "nextseek-api-write requires --confirmed-write (Layer 2)", 5)

    if _dry_run():
        return {"endpoint": "/dry-run/", "method": "POST", "response": {}}

    try:
        plan_dict = json.loads(args.parser_plan)
    except json.JSONDecodeError as exc:
        _err("VALIDATION", f"--parser-plan is not valid JSON: {exc}", 3)

    from chat_nextseek.agents import api_agent_build_request
    api_plan = api_agent_build_request(config, plan_dict)
    from chat_nextseek import helpers
    result = helpers.tool_nextseek_api_request(
        config,
        api_plan.endpoint,
        api_plan.method,
        requestBody=api_plan.requestBody,
        queryParameters=api_plan.queryParameters,
    )
    return {
        "endpoint": api_plan.endpoint,
        "method": api_plan.method.upper(),
        "api_plan": api_plan.model_dump() if hasattr(api_plan, "model_dump") else api_plan,
        "response": result,
    }


def _dispatch_graph(args, config, session):
    if _dry_run():
        return {"cypher": "", "result": []}
    from chat_nextseek.agents import graph_agent, entity_agent
    entity_out = entity_agent(config, args.query)
    return graph_agent(config, args.query, entity_out)


def _dispatch_report(args, config, session):
    if args.mode not in ("samples", "protocols", "published", "rppr"):
        _err("VALIDATION",
             f"--mode must be samples|protocols|published|rppr, got {args.mode!r}",
             3)
    if not args.project:
        _err("VALIDATION", "--project required", 3)

    if _dry_run():
        return {"summary": "", "saved_files": [], "rows": []}

    from chat_nextseek import helpers
    from chat_nextseek.schemas.chat import ReporterPlan
    summary_mode = "RPPR" if args.mode == "rppr" else args.mode
    rp = ReporterPlan(project=args.project, reporter_mode="summary",
                      summary_mode=summary_mode)
    log_dir = os.environ.get("NEXTSEEK_OUTPUTS_DIR", "/tmp/nextseek")
    result, saved, summary = helpers.run_reporter_summary(config, rp, log_dir)
    return {"summary": summary, "saved_files": saved, "rows": result}


def _dispatch_generate_submission(args, config, session):
    if args.type not in ("GEO", "SRA", "NFCORE_RNASEQ", "NFCORE_SCRNASEQ", "PRIDE"):
        _err("VALIDATION", f"--type unsupported: {args.type!r}", 3)
    if not args.uids:
        _err("VALIDATION", "--uids required (comma-separated)", 3)

    if _dry_run():
        return {"report": "", "type": args.type}

    from chat_nextseek.agents import report_writer_agent
    from chat_nextseek.schemas.chat import ReportWriterPlan
    uids = [u.strip() for u in args.uids.split(",") if u.strip()]
    plan = ReportWriterPlan(report_type=args.type, reporter_context={"uids": uids})
    return report_writer_agent(config, args.query or "", plan).model_dump()


_DISPATCH = {
    "entity": _dispatch_entity,
    "parse": _dispatch_parse,
    "plan": _dispatch_plan,
    "api-read": _dispatch_api_read,
    "api-write": _dispatch_api_write,
    "graph": _dispatch_graph,
    "report": _dispatch_report,
    "generate-submission": _dispatch_generate_submission,
}


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--agent", required=True, choices=sorted(_DISPATCH))
    p.add_argument("--query")
    p.add_argument("--parser-plan")  # for api-read / api-write
    p.add_argument("--confirmed-write", action="store_true")
    p.add_argument("--mode")  # for report
    p.add_argument("--project")  # for report
    p.add_argument("--type")  # for generate-submission
    p.add_argument("--uids")  # for generate-submission
    args = p.parse_args()

    # In dry-run mode, skip ChatConfig + session bring-up entirely so the
    # image dry-run test (B17.1) passes without API_USER / API_PASS.
    if _dry_run():
        config = None
        session = None
    else:
        config = _load_config()
        session = _make_session(config)

    try:
        result = _DISPATCH[args.agent](args, config, session)
    except SystemExit:
        raise
    except Exception as exc:
        _err("AGENT_FAILED",
             f"{type(exc).__name__}: {exc}",
             4)
    sys.stdout.write(json.dumps(result, default=str) + "\n")


if __name__ == "__main__":
    main()
```

- [ ] **Step B2.4: Run runner + dispatcher tests with coverage floor (NEW-7)**

```bash
uv run pytest tests/unit/test_nextseek_runner.py tests/unit/test_nextseek_runner_dispatch.py \
  --cov=build_context/plugins/nextseek/bin/_nextseek_runner.py \
  --cov-fail-under=95 -v
```

Expected: B2.2 baseline test + all 8 B2.2b dispatcher tests + 1 api-write-exit-5 test + 3 amendment-2026-05-01 coverage-bump tests = **13 tests PASS**, coverage of `_nextseek_runner` ≥ **95%** (ultraplan default; amended 2026-05-01 from 90% — see `## Amendment Log`). The 3 amendment tests cover the previously-excepted `IMPORT_FAILED` (exit 2), `CONFIG_ERROR` (exit 6) and `AGENT_FAILED` (exit 4) branches. Coverage scope remains narrowed to the Python runner module — sourced shell shims under `bin/` are out of pytest-cov scope (scope, not exception); they're measured by their own bats/subprocess tests in B3-B9. The file-path form of `--cov` is preferred because `bin/` lacks `__init__.py`.

- [ ] **Step B2.5: Commit**

```bash
chmod +x build_context/plugins/nextseek/bin/_nextseek_runner.py
git add build_context/plugins/nextseek/bin/_nextseek_common.sh \
        build_context/plugins/nextseek/bin/_nextseek_runner.py \
        tests/unit/test_nextseek_runner.py \
        tests/unit/test_nextseek_runner_dispatch.py
git commit -m "nextseek-plugin: shared runner + cred-translation helper

Plan B · T2. Includes per-dispatcher monkeypatch tests (B2.2b)
that pin chat_nextseek call signatures."
```

---

## Task B3: `nextseek-entity-extract` shim (template for the others)

**Files:**
- Create: `build_context/plugins/nextseek/bin/nextseek-entity-extract`
- Create: `tests/unit/test_shim_entity_extract.py`

- [ ] **Step B3.1: Write the shim**

```bash
#!/bin/sh
# nextseek-entity-extract — extract sampletypes/assays/keywords/projects.
# Always invoked first by the slash-command preamble (D14).
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

QUERY=""
while [ $# -gt 0 ]; do
  case "$1" in
    --query) QUERY="$2"; shift 2 ;;
    --query=*) QUERY="${1#--query=}"; shift ;;
    --help) echo "Usage: nextseek-entity-extract --query \"<text>\""; exit 0 ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$QUERY" ] || nextseek_die 3 "missing --query"

exec python "$SCRIPT_DIR/_nextseek_runner.py" --agent entity --query "$QUERY"
```

- [ ] **Step B3.2: Write the failing test**

Create `tests/unit/test_shim_entity_extract.py`:

```python
"""Plan B · T3: nextseek-entity-extract shim."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

SHIM = (Path("build_context/plugins/nextseek/bin/nextseek-entity-extract")
        .resolve())


def test_help(monkeypatch):
    result = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert result.returncode == 0
    assert "Usage" in result.stdout


def test_missing_query_errors():
    result = subprocess.run([str(SHIM)], capture_output=True, text=True)
    assert result.returncode == 3
    assert "missing --query" in result.stderr


def test_runner_dispatched(monkeypatch, tmp_path):
    """Stub the runner so we don't hit the LLM. Confirm shim invokes the
    runner with the right --agent and --query."""
    fake_runner = tmp_path / "_nextseek_runner.py"
    fake_runner.write_text("""\
import sys, json
print(json.dumps({"called_with": sys.argv[1:]}))
""")
    fake_runner.chmod(0o755)
    # Symlink the shared common script next to the fake runner.
    (tmp_path / "_nextseek_common.sh").write_text(
        Path("build_context/plugins/nextseek/bin/_nextseek_common.sh")
        .read_text()
    )
    fake_shim = tmp_path / "nextseek-entity-extract"
    fake_shim.write_text(SHIM.read_text())
    fake_shim.chmod(0o755)
    result = subprocess.run(
        [str(fake_shim), "--query", "find samples"],
        capture_output=True, text=True,
        env={"PATH": "/usr/bin:/bin", "API_USER": "x", "API_PASS": "y"},
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout.strip())
    assert "--agent" in payload["called_with"]
    assert "entity" in payload["called_with"]
    assert "find samples" in payload["called_with"]
```

- [ ] **Step B3.3: Run, verify pass (with coverage floor — NEW-7)**

```bash
chmod +x build_context/plugins/nextseek/bin/nextseek-entity-extract
uv run pytest tests/unit/test_nextseek_runner.py \
  tests/unit/test_nextseek_runner_dispatch.py \
  tests/unit/test_shim_entity_extract.py \
  --cov=build_context.plugins.nextseek.bin._nextseek_runner \
  --cov-fail-under=90 -v
```

Expected: 3 shim tests PASS + B2 tests still PASS, runner coverage ≥ 90%. Same scope rationale as B2.4: shell shims are exercised via subprocess tests; only the Python runner is the security-critical, coverable surface.

- [ ] **Step B3.4: Commit**

```bash
git add build_context/plugins/nextseek/bin/nextseek-entity-extract \
        tests/unit/test_shim_entity_extract.py
git commit -m "nextseek-plugin: nextseek-entity-extract shim

Plan B · T3. Template for the other LLM shims (T4–T8)."
```

---

## Task B4–B8: LLM shims (parse, plan, api-call, graph, generate-submission)

**Pattern:** each shim mirrors `nextseek-entity-extract` (T3) but with different `--agent` value and arg parsing. The runner already dispatches all agents (T2 Step B2.3). Each shim is ~20 lines of bash + a small unit test.

**Revision 2 note:** this section's `api-call` references are superseded. Implement `nextseek-api-read` and `nextseek-api-write` as B6a/B6b. `nextseek-plan` is the full read-only advisor loop described in Revision 2 Mandatory Amendments, not just `PlannerOutput` emission.

For each shim listed below, follow the EXACT same TDD pattern as T3:
1. Write the shim (bash, sourcing `_nextseek_common.sh`, exec'ing the runner with the right `--agent`).
2. Write the failing test (mirror `test_shim_entity_extract.py` shape).
3. Run, verify pass.
4. Commit.

### Task B4: `nextseek-parse`
- Args: `--query <text>`. Validates non-empty. Exec: `--agent parse --query "$QUERY"`.

### Task B5: `nextseek-plan`
- Args: `--query <text>`. Validates non-empty. Exec: `--agent plan --query "$QUERY"`.
- The runner returns the PlannerOutput JSON. Tool description (for SKILL.md) emphasizes: "this tool gives you a plan but does NOT execute it. Use the steps to inform your own tool calls."

### Task B6a: `nextseek-api-read`
- Args: `--parser-plan <json>` (required). Exec: `--agent api-read --parser-plan "$PLAN_JSON"`.
- The runner must reject endpoint/method pairs missing from `read_safe_endpoints.json` (NEW-1 + NEW-5: implemented in B2.3 `_dispatch_api_read`).
- The shim must not accept or forward `--confirmed-write`. Implement this by having the shim's argparse-style loop fail with `nextseek_die 3 "--confirmed-write is not valid on nextseek-api-read; use nextseek-api-write"` if the flag is seen.
- **Test (CRITICAL-3 residual close):** in `tests/unit/test_shim_api_read.py`, add:

```python
import subprocess
from pathlib import Path

SHIM_DIR = Path("build_context/plugins/nextseek/bin").resolve()


def test_read_shim_rejects_confirmed_write():
    """nextseek-api-read must exit non-zero if --confirmed-write is passed."""
    r = subprocess.run(
        [str(SHIM_DIR / "nextseek-api-read"),
         "--query", "x", "--parser-plan", "{}", "--confirmed-write"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0, (
        f"read shim accepted --confirmed-write: stdout={r.stdout!r} "
        f"stderr={r.stderr!r}"
    )
```

This is the boundary test that prevents an LLM from smuggling a write through the L1-allowlisted read shim. Must be added to the B4-B8 commit batch.

### Task B6b: `nextseek-api-write`
- Args: `--parser-plan <json>` (required) and `--confirmed-write` (required).
- Exec: `--agent api-write --parser-plan "$PLAN_JSON" --confirmed-write`.
- The shim is not allowlisted by Layer 1; Layer 2 lives inside the runner and refuses missing `--confirmed-write`.

### Task B7: `nextseek-graph`
- Args: `--query <text>`. Exec: `--agent graph --query "$QUERY"`.

### Task B8: `nextseek-generate-submission`
- Args: `--type GEO|SRA|NFCORE_RNASEQ|NFCORE_SCRNASEQ|PRIDE` (required), `--uids <csv>` (required). Exec: `--agent generate-submission --type "$TYPE" --uids "$UIDS"`.

Each task gets its own commit:

```bash
git commit -m "nextseek-plugin: nextseek-<name> shim

Plan B · T<N>."
```

After T4–T8 are landed, run:

```bash
uv run pytest tests/unit/test_shim_*.py -v
```

Expected: all PASS.

---

## Task B9: Reporter dispatcher shim — `nextseek-report`

**Files:**
- Create: `build_context/plugins/nextseek/bin/nextseek-report`
- Create: `tests/unit/test_shim_report.py`

(Single shim with `--mode` switch — deterministic dispatcher per D8.)

- [ ] **Step B9.1: Write the shim**

```bash
#!/bin/sh
# nextseek-report — deterministic project-summary dispatcher.
# --mode samples|protocols|published|rppr (per chat_nextseek reporter sub-modes)
set -eu
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
. "$SCRIPT_DIR/_nextseek_common.sh"

MODE=""; PROJECT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --mode) MODE="$2"; shift 2 ;;
    --mode=*) MODE="${1#--mode=}"; shift ;;
    --project) PROJECT="$2"; shift 2 ;;
    --project=*) PROJECT="${1#--project=}"; shift ;;
    --help) echo "Usage: nextseek-report --mode <samples|protocols|published|rppr> --project <NAME>"; exit 0 ;;
    *) nextseek_die 3 "unknown arg: $1" ;;
  esac
done
[ -n "$MODE" ] || nextseek_die 3 "missing --mode"
[ -n "$PROJECT" ] || nextseek_die 3 "missing --project"

exec python "$SCRIPT_DIR/_nextseek_runner.py" \
  --agent report --mode "$MODE" --project "$PROJECT"
```

- [ ] **Step B9.2: Write the test (mirror T3.2 shape)**

```python
"""Plan B · T9: nextseek-report dispatcher."""
import subprocess
from pathlib import Path

SHIM = Path("build_context/plugins/nextseek/bin/nextseek-report").resolve()

def test_help():
    r = subprocess.run([str(SHIM), "--help"], capture_output=True, text=True)
    assert r.returncode == 0

def test_missing_mode():
    r = subprocess.run([str(SHIM), "--project", "X"], capture_output=True, text=True)
    assert r.returncode == 3
    assert "missing --mode" in r.stderr

def test_missing_project():
    r = subprocess.run([str(SHIM), "--mode", "samples"], capture_output=True, text=True)
    assert r.returncode == 3

def test_invalid_mode_fails_at_runner():
    """Runner enforces the enum (B2 Step B2.3 _dispatch_report)."""
    # End-to-end test verifies the runner's enum check fires.
    pass  # See test_nextseek_runner.py for runner-level coverage.
```

- [ ] **Step B9.3: Run, verify pass and commit (with coverage floor — NEW-7)**

```bash
chmod +x build_context/plugins/nextseek/bin/nextseek-report
uv run pytest tests/unit/test_nextseek_runner.py \
  tests/unit/test_nextseek_runner_dispatch.py \
  tests/unit/test_shim_*.py \
  --cov=build_context.plugins.nextseek.bin._nextseek_runner \
  --cov-fail-under=90 -v
git add build_context/plugins/nextseek/bin/nextseek-report \
        tests/unit/test_shim_report.py
git commit -m "nextseek-plugin: nextseek-report deterministic dispatcher

Plan B · T9. Single shim with --mode samples|protocols|published|rppr.
Runs the full B2-B9 unit suite under --cov-fail-under=90 on
_nextseek_runner."
```

Coverage scope is intentionally narrowed to `_nextseek_runner` (the Python module). Shim shell scripts are exercised via subprocess; pytest-cov cannot measure shell.

---

## Task B10: SKILL.md — preamble + tool catalog + L3 prompt

**Files:**
- Create: `build_context/plugins/nextseek/skills/nextseek/SKILL.md`

- [ ] **Step B10.1: Write the SKILL.md**

````markdown
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
````

- [ ] **Step B10.2: Verify SKILL.md does not hard-code `/persistent/output/{user_id}/` (NEW-3)**

Before committing, grep the file for the forbidden literal that Revision 2 review flagged:

```bash
! grep -q "/persistent/output/{user_id}/" build_context/plugins/nextseek/skills/nextseek/SKILL.md
```

The `!` makes the command exit 0 when grep finds NOTHING and exit 1 when it finds the string. Run this as a hard gate before B10.3 commits. If grep finds the string, fix the SKILL.md before continuing.

- [ ] **Step B10.3: Commit**

```bash
# Last guard — D19 hard-coded path must be absent.
if grep -q "/persistent/output/{user_id}/" build_context/plugins/nextseek/skills/nextseek/SKILL.md; then
  echo "ERROR: SKILL.md still contains forbidden hard-coded path /persistent/output/{user_id}/" >&2
  exit 1
fi
git add build_context/plugins/nextseek/skills/nextseek/SKILL.md
git commit -m "nextseek-plugin: SKILL.md (preamble + tool catalog + L3)

Plan B · T10. D14: entity-extract preamble. D19: Reply hygiene
reads DMAC_PATH_MAPPINGS rather than hard-coding paths. D22:
3-layer write safety with plain-text L3 (no AskUserQuestion)."
```

---

## Task B11: `/nextseek` slash command

**Files:**
- Create: `build_context/plugins/nextseek/commands/nextseek.md`

- [ ] **Step B11.1: Write the command**

```markdown
---
description: Modular NExtSEEK query workflow. Routes via the nextseek skill.
allowed-tools: Bash, Read
---

# /nextseek

You have been invoked via the `/nextseek` slash command. Use the `nextseek` skill (auto-loads from `skills/nextseek/SKILL.md`).

The user's question is below the `---`. Apply the skill's always-first preamble (`nextseek-entity-extract`) before any other action.

---

$ARGUMENTS
```

- [ ] **Step B11.2: Commit**

```bash
git add build_context/plugins/nextseek/commands/nextseek.md
git commit -m "nextseek-plugin: /nextseek slash command

Plan B · T11."
```

---

## Task B12: Layer-1 permission allowlist + setup.sh

**Files:**
- Create: `build_context/plugins/nextseek/scripts/setup.sh`
- Create: `tests/unit/test_setup_idempotent.py`

- [ ] **Step B12.1: Write setup.sh**

```bash
#!/bin/sh
# Layer 1 — install permission allowlist into ~/.claude/settings.json (idempotent).
# Pre-allows GET-only nextseek-* shims and structurally-safe shims.
# Anything outside the allowlist (including --confirmed-write) trips a
# Claude Code permission prompt CC cannot bypass.
set -eu

SETTINGS="${SETTINGS_FILE:-$HOME/.claude/settings.json}"
mkdir -p "$(dirname "$SETTINGS")"
[ -f "$SETTINGS" ] || echo '{}' > "$SETTINGS"

ALLOW='[
  "Bash(nextseek-entity-extract:*)",
  "Bash(nextseek-parse:*)",
  "Bash(nextseek-plan:*)",
  "Bash(nextseek-api-read --parser-plan*)",
  "Bash(nextseek-graph:*)",
  "Bash(nextseek-report --mode samples*)",
  "Bash(nextseek-report --mode protocols*)",
  "Bash(nextseek-report --mode published*)",
  "Bash(nextseek-report --mode rppr*)",
  "Bash(nextseek-generate-submission --type*)"
]'

jq --argjson new "$ALLOW" '
  .permissions //= {} |
  .permissions.allow //= [] |
  .permissions.allow = (.permissions.allow + $new | unique)
' "$SETTINGS" > "$SETTINGS.tmp" && mv "$SETTINGS.tmp" "$SETTINGS"

echo "nextseek allowlist installed at $SETTINGS"
```

- [ ] **Step B12.2: Write the test**

```python
"""Plan B · T12: setup.sh is idempotent and merges into existing allowlist."""
import json
import os
import subprocess
from pathlib import Path


def test_setup_idempotent(tmp_path):
    settings = tmp_path / "settings.json"
    settings.write_text(json.dumps({
        "permissions": {"allow": ["Bash(echo:*)"]}
    }))
    setup = Path("build_context/plugins/nextseek/scripts/setup.sh").resolve()
    env = {**os.environ, "SETTINGS_FILE": str(settings), "HOME": str(tmp_path)}
    # Run twice.
    for _ in range(2):
        r = subprocess.run(["sh", str(setup)], capture_output=True, text=True, env=env)
        assert r.returncode == 0, r.stderr
    data = json.loads(settings.read_text())
    allow = data["permissions"]["allow"]
    # Existing entry preserved.
    assert "Bash(echo:*)" in allow
    # No duplicates after second run.
    assert len(allow) == len(set(allow))
    # New nextseek entries present.
    assert any("nextseek-entity-extract" in a for a in allow)
```

- [ ] **Step B12.3: Run, verify pass, commit**

```bash
chmod +x build_context/plugins/nextseek/scripts/setup.sh
uv run pytest tests/unit/test_setup_idempotent.py -v
git add build_context/plugins/nextseek/scripts/setup.sh \
        tests/unit/test_setup_idempotent.py
git commit -m "nextseek-plugin: Layer-1 permission allowlist setup.sh

Plan B · T12. Idempotent — re-running merges without dupes."
```

---

## Task B13: Catalog snapshot pipeline (`make snapshot-nextseek-catalogs`)

**Files:**
- Modify: `Makefile`

- [ ] **Step B13.1: Add the Make target**

In `Makefile`, add (NEW-6 — parameterized + guarded):

```makefile
# NEW-6: parameterize the source path so other developers / CI can override.
CHAT_NEXTSEEK_SRC ?= /Users/taishajoseph/Documents/Projects/work/chat_nextseek

.PHONY: snapshot-nextseek-catalogs
snapshot-nextseek-catalogs:
	@test -d "$(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context" || \
		(echo "ERROR: CHAT_NEXTSEEK_SRC not found at $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context. Override via 'make snapshot-nextseek-catalogs CHAT_NEXTSEEK_SRC=/path/to/chat_nextseek'." && exit 1)
	@mkdir -p build_context/plugins/nextseek/context
	@cp $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context/min_*.json \
	    build_context/plugins/nextseek/context/
	@cp $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context/projects_db.json \
	    build_context/plugins/nextseek/context/
	@cp $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context/neo4j_schema.json \
	    build_context/plugins/nextseek/context/
	@cp $(CHAT_NEXTSEEK_SRC)/src/chat_nextseek/context/capabilities.md \
	    build_context/plugins/nextseek/context/
	@echo "Snapshotted catalogs to build_context/plugins/nextseek/context/ (from $(CHAT_NEXTSEEK_SRC))"
```

The default value matches the dev-machine layout. Other developers / CI override via `make snapshot-nextseek-catalogs CHAT_NEXTSEEK_SRC=/path/to/chat_nextseek`. The `test -d` guard fails the build with a clear message rather than silently producing an empty `build_context/plugins/nextseek/context/`.

- [ ] **Step B13.2: Run it**

```bash
make snapshot-nextseek-catalogs
```

Expected: catalog files appear under `build_context/plugins/nextseek/context/`.

- [ ] **Step B13.3: Commit**

```bash
git add Makefile build_context/plugins/nextseek/context/
git commit -m "nextseek-plugin: snapshot-nextseek-catalogs Make target

Plan B · T13. Captures min_* JSON catalogs + projects_db +
neo4j_schema + capabilities.md. CC reads these directly via
the Read tool (D15)."
```

---

## Task B14: Dockerfile swap

**Files:**
- Modify: `Dockerfile:22-23, 46`
- Modify: `tests/test_image_smoke.py`
- Modify: `tests/test_dockerfile_build.py`

- [ ] **Step B14.1: Update Dockerfile COPY**

Replace line 22:

```dockerfile
COPY build_context/plugins/ /app/plugins/
```

with:

```dockerfile
# Plan B · T14: ship only the new nextseek plugin in the image.
# The old nextseek-api plugin is preserved on disk under
# build_context/plugins/nextseek-api/ (host-side codebase) for reuse,
# but is NOT included in the image (D25 amended).
COPY build_context/plugins/nextseek/ /app/plugins/nextseek/

# NEW-6: fail the build if catalog files weren't snapshotted before
# `docker build`. Without this, an image can ship with an empty
# /app/plugins/nextseek/context/ and degrade silently at runtime.
RUN test -n "$(ls /app/plugins/nextseek/context/min_*.json 2>/dev/null)" || \
    (echo "ERROR: no min_*.json catalog files in /app/plugins/nextseek/context/; run 'make snapshot-nextseek-catalogs' before 'docker build'" >&2 && exit 1)
```

Replace line 46:

```dockerfile
ENV PATH="/app/plugins/nextseek-api/bin:${PATH}"
```

with:

```dockerfile
ENV PATH="/app/plugins/nextseek/bin:${PATH}"
```

- [ ] **Step B14.2: Update smoke test**

In `tests/test_image_smoke.py`, add:

```python
def test_old_plugin_path_absent(image_tag):
    """D25: nextseek-api is removed from the image."""
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", image_tag,
         "test", "-d", "/app/plugins/nextseek-api"],
        capture_output=True, text=True,
    )
    assert r.returncode != 0


def test_new_plugin_path_present(image_tag):
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", image_tag,
         "test", "-d", "/app/plugins/nextseek"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0


def test_new_plugin_bin_on_path(image_tag):
    import subprocess
    r = subprocess.run(
        ["docker", "run", "--rm", image_tag,
         "/bin/sh", "-c", "command -v nextseek-entity-extract"],
        capture_output=True, text=True,
    )
    assert r.returncode == 0
    assert "/app/plugins/nextseek/bin/nextseek-entity-extract" in r.stdout
```

- [ ] **Step B14.3: Update Dockerfile build test**

```python
def test_dockerfile_copies_only_new_plugin():
    text = Path("Dockerfile").read_text()
    assert "COPY build_context/plugins/nextseek/" in text
    assert "/app/plugins/nextseek-api" not in text
    assert "/app/plugins/nextseek/bin" in text
```

- [ ] **Step B14.4: Build, run smoke**

```bash
docker build --platform=linux/amd64 -t dmac-assistant:plan-b-t14 .
uv run pytest tests/test_image_smoke.py tests/test_dockerfile_build.py -v
```

Expected: PASS.

- [ ] **Step B14.5: Commit**

```bash
git add Dockerfile tests/test_image_smoke.py tests/test_dockerfile_build.py
git commit -m "dockerfile: swap nextseek-api -> nextseek plugin

Plan B · T14. D25: image v3 ships only the new plugin.
Old plugin codebase preserved under build_context/plugins/nextseek-api/
for reuse but NOT mounted into the image."
```

---

## Task B15: `container/entrypoint.sh` updates

**Files:**
- Modify: `container/entrypoint.sh:11-14`
- Modify: `tests/entrypoint.bats`

- [ ] **Step B15.1: Update the cred-translation block**

In `container/entrypoint.sh`, replace lines 11-14:

```bash
: "${SEEK_USER:=${NEXTSEEK_USERNAME:-}}"
: "${SEEK_PASSWORD:=${NEXTSEEK_PASSWORD:-}}"
: "${NEXTSEEK_BASE_URL:=${NEXTSEEK_URL:-}}"
export SEEK_USER SEEK_PASSWORD NEXTSEEK_BASE_URL
```

with:

```bash
# D20: chat_nextseek's ChatConfig reads API_USER / API_PASS.
: "${API_USER:=${NEXTSEEK_USERNAME:-}}"
: "${API_PASS:=${NEXTSEEK_PASSWORD:-}}"
: "${NEXTSEEK_BASE_URL:=${NEXTSEEK_URL:-}}"
# D23: GCP-only profile.
: "${NEXTSEEK_MODE:=gcp}"
export API_USER API_PASS NEXTSEEK_BASE_URL NEXTSEEK_MODE

# Backward compat: SEEK_USER / SEEK_PASSWORD still exported for any host-side
# tooling that grew up reading them. Removable post-Plan-B once nothing
# downstream depends on them.
: "${SEEK_USER:=$API_USER}"
: "${SEEK_PASSWORD:=$API_PASS}"
export SEEK_USER SEEK_PASSWORD
```

- [ ] **Step B15.2: Update bats**

In `tests/entrypoint.bats`, add:

```bash
@test "entrypoint exports API_USER and API_PASS for chat_nextseek" {
  NEXTSEEK_USERNAME="alice" NEXTSEEK_PASSWORD="pw" run sh -c '
    . container/entrypoint.sh true 2>/dev/null
    echo "API_USER=$API_USER"
    echo "API_PASS=$API_PASS"
    echo "NEXTSEEK_MODE=$NEXTSEEK_MODE"
  '
  [[ "$output" == *"API_USER=alice"* ]]
  [[ "$output" == *"API_PASS=pw"* ]]
  [[ "$output" == *"NEXTSEEK_MODE=gcp"* ]]
}
```

(If `tests/entrypoint.bats` cannot source the entrypoint without exec'ing, skip the source-style test and keep the existing exec-based bats pattern. Adapt to repo convention.)

- [ ] **Step B15.3: Run bats**

```bash
bats tests/entrypoint.bats
```

Expected: PASS.

- [ ] **Step B15.4: Commit**

```bash
git add container/entrypoint.sh tests/entrypoint.bats
git commit -m "entrypoint: chat_nextseek cred names + NEXTSEEK_MODE=gcp

Plan B · T15. Translates NEXTSEEK_USERNAME/PASSWORD -> API_USER/API_PASS
(D20). Sets NEXTSEEK_MODE=gcp (D23). Keeps SEEK_USER/SEEK_PASSWORD
exported for back-compat with host-side tooling."
```

---

## Task B16: `container/CLAUDE.md` auto-doc + `make ingest-nextseek-docs`

**Files:**
- Modify: `container/CLAUDE.md` (the auto-generated NEXTSEEK-DOCS block)
- Modify: `Makefile` (`ingest-nextseek-docs` target)

- [ ] **Step B16.1: Locate the auto-doc sentinel**

```bash
grep -n "BEGIN NEXTSEEK-DOCS\|END NEXTSEEK-DOCS\|nextseek-api" container/CLAUDE.md
```

The block is at:
```
<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->
<!-- END NEXTSEEK-DOCS (auto-generated) -->
```

- [ ] **Step B16.2: Update the human-authored references in container/CLAUDE.md**

Replace the existing plugin-pointer paragraph (currently mentions `nextseek-api`) with the new plugin's pointers. After the swap, the file's plugin block should read:

```markdown
## Plugins available in this image

The image ships one plugin, discoverable at fixed paths:

- **`nextseek`** — modular NExtSEEK query plugin.
  - Skill manifest: `/app/plugins/nextseek/skills/nextseek/SKILL.md`
  - Slash command: `/app/plugins/nextseek/commands/nextseek.md`
  - Code: `/app/plugins/nextseek/bin/`
  - Cached catalogs: `/app/plugins/nextseek/context/`

When a user asks about NExtSEEK data, read the SKILL.md first. The plugin's CLI tools are in `/app/plugins/nextseek/bin/` and read credentials from `NEXTSEEK_USERNAME` / `NEXTSEEK_PASSWORD` (translated to `API_USER` / `API_PASS` by the plugin shim).
```

- [ ] **Step B16.3: Update the Make target**

Update `make ingest-nextseek-docs` (locate via `grep -n "ingest-nextseek-docs" Makefile`) to ingest from the new plugin's docs and to inject between the existing `BEGIN NEXTSEEK-DOCS` / `END NEXTSEEK-DOCS` sentinels. The exact awk/sed pattern depends on the existing target's structure — preserve the sentinel-based replace approach.

- [ ] **Step B16.4: Run the ingest target**

```bash
make ingest-nextseek-docs
git diff container/CLAUDE.md
```

Expected: the auto-doc block updates with content sourced from the new plugin's SKILL.md / docs.

- [ ] **Step B16.5: Commit**

```bash
git add container/CLAUDE.md Makefile
git commit -m "container: re-point CLAUDE.md auto-doc at new plugin

Plan B · T16."
```

---

## Task B17: Integration test — end-to-end query through new plugin

**Files:**
- Modify: `tests/integration/test_plugin_e2e.py`

- [ ] **Step B17.1: Add a test that runs a full read-only query**

```python
import json
import subprocess


def test_image_dry_run_dispatchers_emit_typed_json(built_image):
    """NEW-4: each agent dispatcher returns minimal valid JSON when
    NEXTSEEK_DRY_RUN=1, proving wiring without needing GCP / NExtSEEK creds.

    `built_image` is the pytest fixture that yields the dmac-assistant image
    tag the rest of the integration suite already uses. If your suite uses a
    different fixture name (e.g. `image_tag`), substitute as appropriate;
    this test must run against the freshly-built Plan B image.
    """
    cases = [
        ("nextseek-entity-extract", ["--query", "test"], "sampletypes"),
        ("nextseek-api-read",
         ["--parser-plan", json.dumps({"endpoint": "/x/", "method": "GET"})],
         "endpoint"),
        ("nextseek-plan", ["--query", "test"], "plan"),
    ]
    for shim, extra_args, expected_key in cases:
        r = subprocess.run(
            [
                "docker", "run", "--rm",
                "-e", "NEXTSEEK_DRY_RUN=1",
                # API_USER / API_PASS still set so the runner does not exit
                # with CONFIG_MISSING before reaching the dry-run guard.
                # (The dry-run guard short-circuits before _load_config in
                #  the Rev 3 runner; if the executor moves it, set these
                #  anyway — it doesn't hurt.)
                "-e", "API_USER=dry",
                "-e", "API_PASS=dry",
                built_image,
                shim, *extra_args,
            ],
            capture_output=True, text=True, timeout=30,
        )
        assert r.returncode == 0, (
            f"{shim} exit={r.returncode} stderr={r.stderr!r} stdout={r.stdout!r}"
        )
        try:
            payload = json.loads(r.stdout)
        except json.JSONDecodeError as exc:
            raise AssertionError(
                f"{shim} did not emit JSON on stdout: {exc}; stdout={r.stdout!r}"
            )
        assert expected_key in payload, (
            f"{shim} dry-run JSON missing key {expected_key!r}; got {payload!r}"
        )
```

This test depends on the `NEXTSEEK_DRY_RUN` runner support added in Rev 3 B2.3. It distinguishes a correctly-wired plugin from one whose runner crashes at dispatch (because a broken dispatcher cannot return the agent-specific top-level key).

(Live end-to-end tests against the real chat_nextseek + GCP + NExtSEEK still go in the manual smoke task B18, not in this automated integration suite.)

- [ ] **Step B17.2: Run, verify pass, commit**

```bash
uv run pytest tests/integration/test_plugin_e2e.py -v
git add tests/integration/test_plugin_e2e.py
git commit -m "tests: end-to-end nextseek shim runs in image

Plan B · T17. Wiring test only — does not hit GCP/NExtSEEK live."
```

---

## Task B18: Manual end-to-end smoke

**Files:** none.

- [ ] **Step B18.1: Build the v3 image**

```bash
docker build --platform=linux/amd64 -t dmac-assistant:plan-b .
```

- [ ] **Step B18.2: Run a real query as a real user**

Start the bridge with the new image, log in with real NExtSEEK creds, dispatch:

> /nextseek find me three D.SEQ samples in SRP

Verify:
- `nextseek-entity-extract` runs first (skill preamble worked).
- A sub-tool runs (`nextseek-parse` + `nextseek-api-read` likely).
- The reply quotes a host-side artifact path consistent with the `DMAC_PATH_MAPPINGS` env var injected into the session (in dev: `~/dmac-dev/output/demo/`; in prod: per the configured `output_root`).
- The artifact actually exists on the host.

- [ ] **Step B18.3: Test write-safety L3**

Dispatch:

> /nextseek delete sample UID-1234

Verify:
- CC writes a plain-text "About to execute a WRITE-classified operation. Confirm?" message.
- No AskUserQuestion was invoked.
- If you reply "no", the call is aborted.

- [ ] **Step B18.4: Test graceful Neo4j degradation**

Run the bridge without `NEO4J_*` env vars set. Dispatch a graph query. Verify the user gets a clean "graph queries not configured" message, not a stack trace.

- [ ] **Step B18.5: Verify old plugin is gone**

```bash
docker run --rm dmac-assistant:plan-b /bin/sh -c 'command -v nextseek-init || echo "MISSING (expected)"'
docker run --rm dmac-assistant:plan-b /bin/sh -c 'ls /app/plugins/nextseek-api 2>&1 || echo "MISSING (expected)"'
```

Expected: both report MISSING.

---

## Self-review · Plan B

**Spec coverage:** D2 (B5 full read-only planner-advisor with context engineering + evaluator critique), D3 (B3 entity-first preamble in B10 SKILL.md), D4 (no chatter shim), D5 (B4 nextseek-parse + B5 nextseek-plan wraps it), D6 (B6a/B6b api-read/api-write), D7 (B7 graph), D8 (B9 single nextseek-report dispatcher), D9 (B8 generate-submission), D10/D11 (no memory/system shims — CC handles natively per skill prompt), D12 (single plugin), D13 (chat_nextseek pinned by Plan A under Python 3.14), D14 (B10 always-first preamble), D15 (B10 references catalog paths; B13 snapshots them at build), D19 (`DMAC_PATH_MAPPINGS` consumed in SKILL.md), D20 (B15 entrypoint cred translation), D21 (B11 single /nextseek), D22 (B10 SKILL.md L3 plain-text + B12 L1 allowlist; L2 in write shim), D23 (B15 NEXTSEEK_MODE=gcp), D25 (B14 swap; old plugin preserved under build_context/), D29 (B3-B9 shims invoke `python` directly).

**Placeholders:** none load-bearing. The Make target's hard-coded host path is intentional and documented.

**Type/name consistency:** runner agent names match shim args: `entity` ↔ `nextseek-entity-extract`, `parse` ↔ `nextseek-parse`, `plan` ↔ `nextseek-plan`, `api-read` ↔ `nextseek-api-read`, `api-write` ↔ `nextseek-api-write`, `graph` ↔ `nextseek-graph`, `report` ↔ `nextseek-report`, `generate-submission` ↔ `nextseek-generate-submission`. Reporter sub-modes match chat_nextseek's: `samples`, `protocols`, `published`, `rppr`. Submission types match chat_nextseek's `normalize_report_type()` canonicals: `GEO`, `SRA`, `NFCORE_RNASEQ`, `NFCORE_SCRNASEQ`, `PRIDE`.

**Anti-gaming:** the manual smoke (B18) explicitly tests L3 write-safety (real prompt + real abort), Neo4j graceful degradation, and old-plugin removal — none of these can pass-while-broken via mocked unit tests alone.

---

## Risk register · Plan B

| Risk | Where | Mitigation |
|---|---|---|
| chat_nextseek public API changes between pre-flight and image build | Pre-flight + B2.3 | Pin Plan A's chat_nextseek rev; bump deliberately. |
| Skill auto-loading fails when only SKILL.md is present (no plugin.json under skills/) | B10 | Verify the `disable-model-invocation: false` frontmatter is correct for this Claude Code version. Fall back to manual `Skill` invocation if not. |
| Layer-1 allowlist patterns don't match Claude Code's expected glob shape | B12 | The current `nextseek-api` plugin uses identical patterns; reuse those (D25 codebase-preserved means we can grep its setup.sh for reference). |
| Catalog snapshot is stale at deploy time | B13 | Manual rebuild required to refresh; document in B16 that bumping catalogs = rebuild image. |
| `nextseek-plan` executes too much internally | B5 + B10 | Runner may execute only read-safe API and graph steps. It must return write/report/submission steps as skipped recommendations. |
| Reporter `helpers.run_reporter_summary` expects a real ReporterPlan | B2.3 `_dispatch_report` | Use `chat_nextseek.schemas.chat.ReporterPlan`; duck-typed objects are forbidden by Revision 2. |
| Image v3 bin paths don't include `_nextseek_runner.py` (it's not on PATH but invoked from shims) | B14 | Shims use `$SCRIPT_DIR/_nextseek_runner.py`, which resolves correctly inside the image. |
| Old plugin's symlink-into-`.claude/plugins/local/` machinery in entrypoint.sh now points at non-existent `nextseek-api` dir | B15 | The existing entrypoint loops over `/app/plugins/*` — once `nextseek-api` is gone from `/app/plugins/`, the loop just operates on `nextseek/`. No code change needed. |

---

## Execution

Status: Revision 2 UNVETTED after combined adversarial review. The revised sections require focused re-review before execution.

Per writing-plans skill: after vetting, execution will use `superpowers:subagent-driven-development` (one fresh subagent per task with two-stage review between tasks).

Plan B depends on Plan A having merged. Execution order: Plan A revision → focused review → Plan A execution/merge → Plan B focused review → Plan B execution/merge.

---

## Settings & Worktrees Initialized — 2026-05-01

Phase 5.5 completed.

**Settings**: 10 entries appended to `.claude/settings.local.json` `permissions.allow` (4 Bash patterns: `git ls-files`, `python`, `sh -n`, `test`; 3 Write/3 Edit pairs for `build_context/plugins/nextseek/**`, `.claude/plans/**`, `.claude/reviews/**`). User-confirmed via AskUserQuestion.

**Integration branch**: `ultraplan/nextseek-plugin-2026-04-27` created from `main@33e21f6`. Main repo working tree now operates on this branch.

**Worktrees**:
- `.claude/worktrees/task-B01-scaffold/` on branch `task/B01-scaffold` — created 2026-05-01.
- `task-B02-shared-runner` worktree **deferred** until B1 merges to integration branch (per dependency rule "Tasks with dependencies wait for predecessor merge before worktree creation"). Will be initialized after B1 merge in Phase 6 wave handoff.

**Stale spike worktrees** at `.worktrees/task-0.{1,2,3}` (from Plan A spike work) are still present and untouched per user directive — unrelated to Plan B execution.

---

## Task Specs Manifest

Per-task spec files live under `.claude/plans/nextseek-plugin-2026-04-27-tasks/`. Phase 3 task spec explosion progress: Wave 1 + Wave 2 LOCKED 2026-05-01. **Wave 3 authored 2026-05-02 — UNVETTED, awaiting Phase 4 combined adversarial+checklist review.** Wave 4-7 specs not yet exploded.

| Spec file | Task | Wave | Depends on | Coverage target | Exception? | Status |
|---|---|---|---|---|---|---|
| `task-B01-scaffold.md` | B1: scaffold + plugin.json | 1 | (none — Wave 1 origin) | N/A — declared exception (no executable code) | Yes (§4 + §9) | **LOCKED 2026-05-01** (round 1 APPROVE-with-micro-fixes → re-review APPROVE-with-micro-fixes → all fixes applied → user-confirmed) |
| `task-B02-shared-runner.md` | B2: shared `_nextseek_common.sh` + `_nextseek_runner.py` + 17 tests | 2 | B1 merged | 95% on `_nextseek_runner.py` (ultraplan default) | No (amended 2026-05-01) | **LOCKED 2026-05-01** (round 1 REVISE → re-review APPROVE-with-micro-fixes → all fixes applied → user-confirmed) |
| `task-B03-entity-extract.md` | B3: `nextseek-entity-extract` shim (canonical Wave-3 template) | 3 | B1, B2 | 95% on `_nextseek_runner.py` (held by B2) | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B04-parse.md` | B4: `nextseek-parse` shim | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B05-plan.md` | B5: `nextseek-plan` shim (read-only advisor, Rev 2 D2) | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B06a-api-read.md` | B6a: `nextseek-api-read` shim (Layer-1 boundary, CRITICAL-3 close) | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B06b-api-write.md` | B6b: `nextseek-api-write` shim (Layer-2 gate; not in L1 allowlist) | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B07-graph.md` | B7: `nextseek-graph` shim | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B08-generate-submission.md` | B8: `nextseek-generate-submission` shim | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) |
| `task-B09-report.md` | B9: `nextseek-report` deterministic dispatcher (D8) | 3 | B1, B2 | 95% on `_nextseek_runner.py` | No | **LOCKED 2026-05-02** (Phase 4 APPROVE-with-micro-fixes → required fixes applied → user-confirmed) — corrects plan body B9.3 stale dotted-module `--cov=` + `--cov-fail-under=90` |

### Phase 4 reviews of record (Wave 3)

| File | Verdict |
|---|---|
| `.claude/reviews/plan-B-spec-B03-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (CRITICAL-1 stripped-PATH env + HIGH-1 RED guard fixed) |
| `.claude/reviews/plan-B-spec-B04-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (HIGH-2 git diff guard added) |
| `.claude/reviews/plan-B-spec-B05-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (Step 6 git diff guard added) |
| `.claude/reviews/plan-B-spec-B06a-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (H1 verbatim relabel + H2 §9.2a divergence note added) |
| `.claude/reviews/plan-B-spec-B06b-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (H1 `--confirmed-write=*` case branch + M1 grep if/else applied) |
| `.claude/reviews/plan-B-spec-B07-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (H2 git diff guard added) |
| `.claude/reviews/plan-B-spec-B08-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (H1 RED wording + cross-task A9.1 nextseek-error assertions added) |
| `.claude/reviews/plan-B-spec-B09-phase4-review-2026-05-02.md` | APPROVE-with-micro-fixes (H1 stripped-PATH env + cross-task A9.1 nextseek-error assertions added) |
| `.claude/reviews/plan-B-wave-3-cross-task-review-2026-05-02.md` | APPROVE-with-micro-fixes (5 inheritance rules pass uniformly; A9.1 + A9.2 propagated) |

(Future waves: B10–B18 specs NOT YET EXPLODED. Wave 4 = B10-B12; Wave 5 = B13-B16; Wave 6 = B17; Wave 7 = B18.)

Wave structure (suggested in compact handoff §10) is unchanged:
- Wave 1 = B1
- Wave 2 = B2
- Wave 3 = B3–B9 (8 shims, parallel)
- Wave 4 = B10–B12
- Wave 5 = B13–B16
- Wave 6 = B17 (dry-run image e2e)
- Wave 7 = B18 (manual smoke)

---

## Coverage Exceptions

Approved exceptions to the ultraplan default 95% floor. Each exception names exact uncoverable paths and the justification. Phase 4 vetting must affirm before Phase 5 lock.

### B1: pure scaffold — no executable code

- **Declared target**: N/A (zero new lines under any cov source)
- **Default**: 95%
- **Justification**: B1 produces only `build_context/plugins/nextseek/.claude-plugin/plugin.json` (static JSON config) and `build_context/plugins/nextseek/README.md` (two-line markdown stub). Neither file contains executable Python. The repo-wide `--cov-fail-under=95` gate (against `tests.harness` + `src/dmac_assistant`) is unaffected by B1. Plugin manifest correctness is verified indirectly by B14's existing `tests/test_image_smoke.py` and `tests/test_dockerfile_build.py` modifications, which already assert the new plugin path is shipped to the built image.
- **Uncoverable paths**: every line of `plugin.json` and `README.md` (data, not code).
- **Fallback**: if Phase 4 rejects this exception, the contingency `tests/unit/test_nextseek_plugin_manifest.py` in `task-B01-scaffold.md` §5 covers the JSON-shape check.

### B2: ~~90% target~~ — **WITHDRAWN** (amended 2026-05-01 to default 95%)

The B2 coverage exception logged in this section earlier on 2026-05-01 has been **withdrawn the same day** during Phase 3 spec authoring. On review, the three "uncoverable" branches (ImportError in `_load_config`, OSError in `_load_read_safe_endpoints`, broad-except in `main()`) are reachable via standard `monkeypatch` and do not qualify as architectural uncoverability under the ultraplan rule. Three additional tests now cover those branches; B2's target is the default 95% on `_nextseek_runner.py`. See `## Amendment Log` entry "Coverage bump B2 90% → 95% (2026-05-01)" for the full record.

The shell shim layer (`_nextseek_common.sh` and the 8 `nextseek-*` shims authored in B3-B9) remains OUT of pytest-cov scope — that's a *scope* statement, not an exception (pytest-cov instruments only Python).
