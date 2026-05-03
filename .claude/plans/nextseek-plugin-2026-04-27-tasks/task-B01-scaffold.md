# task-B01-scaffold — Plugin scaffold + `plugin.json`

> **Plan**: `nextseek-plugin-2026-04-27.md` (Plan B, Revision 3 — APPROVED 2026-05-01)
> **Wave**: 1 (sole task in Wave 1; B2 cannot start until B1 merges)
> **Status**: **LOCKED 2026-05-01** (Phase 4 APPROVE-with-micro-fixes → focused re-review APPROVE-with-micro-fixes → NEW-1 §9.2 fix applied → Phase 5 user-confirmed). See `## LOCKED` section at end of file.

## 1. Overview

Create the on-disk skeleton for the new `nextseek` plugin. After this task:

- `build_context/plugins/nextseek/.claude-plugin/plugin.json` exists with the canonical metadata Container-Claude reads at plugin discovery time.
- `build_context/plugins/nextseek/README.md` exists as a one-line pointer to the eventual `skills/nextseek/SKILL.md` (authored in B10).
- One commit on the integration branch: `nextseek-plugin: scaffold plugin.json + README` with body `Plan B · T1.`

**Key invariants:**
- `plugin.json` schema mirrors the existing `nextseek-api` plugin's exactly (same field shape: `name`, `version`, `description`, `author.name`, `keywords`). Plan A's `nextseek-api` is the precedent — see `build_context/plugins/nextseek-api/.claude-plugin/plugin.json`.
- No `bin/`, `skills/`, `commands/`, or `scripts/` directories are created by this task — those land in B2, B3-B9, B10, B11, B12 respectively. B1 must not pre-emptively create empty subdirs.
- Nothing in this task touches the `Dockerfile`, `Makefile`, or `container/` — that's B14/B13/B15/B16.

## 2. Dependencies

- **Predecessor tasks**: none (Wave 1 origin)
- **Plan A prerequisites** (already merged to `main` at `33e21f6`):
  - Python 3.14 pinned, `chat_nextseek` importable in `dmac-assistant:poc` image.
  - `DMAC_PATH_MAPPINGS` injection live; `/data/output/` mount live.
  - `nextseek-api` plugin still present on disk (it gets removed from the image only at B14 — its on-disk preservation is intentional per plan goal statement).
- **Artifacts consumed**: none.
- **External packages**: none.
- **Tooling required**: `git`. No Python, no Docker, no Make for this task.

## 3. Key Design Decisions

- **D1 (plan goal)**: "After Plan B merges: image v3 ships only the new `nextseek` plugin at `/app/plugins/nextseek/`." — *Constraint*: the new plugin's source-of-truth path is `build_context/plugins/nextseek/`, mirroring the `build_context/plugins/nextseek-api/` precedent. Do not place the plugin elsewhere.
- **D14 (preamble)**: SKILL.md preamble is authored later (B10). — *Constraint*: B1's `README.md` must be a stub pointer ("See `skills/nextseek/SKILL.md`"), not the user-facing instructions themselves. The eventual `skills/nextseek/SKILL.md` does not exist after B1; that is expected.
- **D29 (no `uv run --with` in shims)**: Plan B uses plain `python` and bash for shims, not `uv run --with`. — *Constraint*: `plugin.json` does not declare any runtime, sub-runner, or `dependencies` field. Container-Claude's plugin discovery reads only the documented manifest schema; extra keys are ignored but should not be added.
- **Plan B "File Structure" table row**: `build_context/plugins/nextseek/.claude-plugin/plugin.json` (create) and an additional README (create). — *Constraint*: exact filenames and casing as listed; the `.claude-plugin` dir name is load-bearing.

## 4. TDD Implementation Order

**Coverage target**: **N/A — declared coverage exception.** B1 produces only a JSON config file (`plugin.json`) and a static markdown README. There is no executable code path under test. The exception is justified per the ultraplan "Coverage Floor" rule under "Justified exceptions… (1) declare an alternative target, (2) name the exact uncoverable paths and why, (3) be approved during Phase 4 vetting." The uncoverable paths are: every line of `plugin.json` and every line of `README.md` — both are static data, not code. **Phase 4 vetting must approve this exception.**

There is a behavioral assertion possible (the JSON parses; required fields are present), but it is intentionally deferred to B14's `tests/test_dockerfile_build.py` and `tests/test_image_smoke.py` modifications which already assert "new plugin path PRESENT" and indirectly exercise plugin manifest discovery. Adding a duplicate B1-only parse test would be vestigial coverage.

**Step 1 — VERIFY (no RED/GREEN, no test code)**: After writing both files, confirm. **All commands MUST run from the repo root** — anchor explicitly with `cd "$(git rev-parse --show-toplevel)"`:
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  python -c "import json, pathlib; \
    p = pathlib.Path('build_context/plugins/nextseek/.claude-plugin/plugin.json'); \
    d = json.loads(p.read_text()); \
    assert d['name'] == 'nextseek'; \
    assert d['version'] == '0.1.0'; \
    assert isinstance(d['author'], dict) and d['author']['name'] == 'BMC'; \
    print('plugin.json schema OK')"
  test -s build_context/plugins/nextseek/README.md && echo 'README.md non-empty'
  ```

**Step 2 — Commit** (use ANSI-C `$'...'` quoting, not HEREDOC, to avoid leading-whitespace pitfalls in the markdown-rendered code block — Phase 4 review HIGH-1):
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  git add -f build_context/plugins/nextseek/.claude-plugin/plugin.json \
             build_context/plugins/nextseek/README.md
  git commit -m $'nextseek-plugin: scaffold plugin.json + README\n\nPlan B · T1.'
  ```

**Step 3 — VERIFY commit landed on the task branch**:
  ```bash
  cd "$(git rev-parse --show-toplevel)"
  git log -1 --pretty=format:'%s' | grep -q '^nextseek-plugin: scaffold'
  ```

## 5. Behavioral Contract (Tests)

**No new tests are added by this task.** Per the coverage exception in Section 4, B1's correctness is verified by the manual python one-liner in Step 1 of Section 4 and indirectly by:

- `tests/test_image_smoke.py` (modified by B14, not B1): asserts `/app/plugins/nextseek/` is PRESENT in the built image.
- `tests/test_dockerfile_build.py` (modified by B14, not B1): asserts the `Dockerfile`'s `COPY` directive references the new plugin tree.

If the user's Phase 4 vetting rejects the no-test exception, the fallback test to add is:

```python
# tests/unit/test_nextseek_plugin_manifest.py — only if Phase 4 vetting requires it
"""B1 fallback — verifies plugin.json shape if Phase 4 disallows the no-test exception."""
from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_JSON = (
    REPO_ROOT / "build_context" / "plugins" / "nextseek"
    / ".claude-plugin" / "plugin.json"
)


def test_plugin_json_exists_and_parses():
    assert PLUGIN_JSON.exists(), f"missing {PLUGIN_JSON}"
    data = json.loads(PLUGIN_JSON.read_text())
    assert data["name"] == "nextseek"
    assert data["version"] == "0.1.0"
    assert isinstance(data["description"], str) and data["description"].strip()
    assert data["author"] == {"name": "BMC"}
    assert "keywords" in data and isinstance(data["keywords"], list)


def test_plugin_readme_exists_and_points_at_skill():
    readme = REPO_ROOT / "build_context" / "plugins" / "nextseek" / "README.md"
    assert readme.exists()
    text = readme.read_text()
    assert "SKILL.md" in text, "README must point at SKILL.md"
```

The default disposition is **no test** (exception approved). The fallback exists only as a contingency.

## 6. Reference Implementation

### 6.1 New file: `build_context/plugins/nextseek/.claude-plugin/plugin.json`

```json
{
  "name": "nextseek",
  "version": "0.1.0",
  "description": "Modular NExtSEEK query workflow for Container-Claude. Wraps the chat_nextseek multi-agent pipeline as discrete plugin tools (entity-extract, parse, plan, api-read, api-write, graph, report, generate-submission) so CC orchestrates routing/planning natively while chat_nextseek owns deterministic execution.",
  "author": {"name": "BMC"},
  "keywords": ["nextseek", "chat_nextseek", "bmc", "metadata", "graph"]
}
```

Notes:
- Trailing newline at EOF (POSIX).
- 2-space indentation.
- `description` is a single string (no embedded newlines) so JSON parsers without lax-string mode read it cleanly. The description matches the plan's plugin.json block at lines 372-380 verbatim.
- The schema is intentionally minimal. No `runtime`, `entrypoint`, `commands`, `tools`, or `dependencies` keys. Container-Claude's plugin discovery does not require them and the manifest must not pre-declare components that don't exist yet (those land in B2-B12).

### 6.2 New file: `build_context/plugins/nextseek/README.md`

```markdown
# nextseek plugin
See `skills/nextseek/SKILL.md`. Replaces the demo-grade `nextseek-api` plugin.
```

Notes:
- Two-line file (heading + one-line body). Trailing newline.
- The body intentionally references a path (`skills/nextseek/SKILL.md`) that does not yet exist — B10 will create it. This is acceptable because the README is internal documentation aimed at developers reading the source tree, not user-facing runtime instructions. The reference becomes valid as soon as B10 merges.

## 7. Modified Files (exact diffs)

**None.** B1 only creates new files.

If B1 is run on a working tree that already has `build_context/plugins/nextseek/.claude-plugin/plugin.json` (e.g. partial prior attempt), abort the task and surface to the user via `AskUserQuestion` — do not silently overwrite. The plan is locked at Rev 3 and there is no preexisting Plan B work on `main` (`git log main` shows no nextseek-plugin commits past `33e21f6`).

## 8. Verification

```bash
# Run new tests only — N/A (no new tests; coverage exception)
# (If Phase 4 rejects the exception, the fallback test from §5 runs instead:)
#   uv run pytest tests/unit/test_nextseek_plugin_manifest.py -v

# Run full suite — must not regress
uv run pytest -q

# Coverage check — N/A (declared exception)
# B1 contributes no executable code to the cov sources declared in pyproject.toml
# (`tests.harness`, `src/dmac_assistant`). Repo-level cov-fail-under=95 still applies
# globally; B1 must not lower it.

# Manifest schema spot-check (manual; run from repo root)
cd "$(git rev-parse --show-toplevel)"
python -c "import json, pathlib; \
  d = json.loads(pathlib.Path('build_context/plugins/nextseek/.claude-plugin/plugin.json').read_text()); \
  assert d['name']=='nextseek' and d['version']=='0.1.0' and d['author']['name']=='BMC'; \
  print('OK')"

# Linter / type checker — no Python files added; nothing to lint for this task.
```

**Expected test count**: 0 new (default; or 2 new if Phase 4 rejects the exception).
**Expected coverage**: unchanged from pre-B1 baseline. Repo `--cov-fail-under=95` gate must continue to pass.

## 9. Implementation Notes

### 9.1 Plan-line and codebase citations

- Plan content: `nextseek-plugin-2026-04-27.md` lines 364-397 (Task B1 block).
- Schema precedent: `build_context/plugins/nextseek-api/.claude-plugin/plugin.json` (read this file before authoring B1's plugin.json to confirm the exact field set in the existing plugin).
- File-structure plan reference: `nextseek-plugin-2026-04-27.md` lines 124-125 (the row for `plugin.json` in the File Structure table).

### 9.2 Gotchas

- **Do not create empty subdirs.** Git does not track empty directories. `bin/`, `skills/`, `commands/`, `scripts/`, `context/` belong to B2/B10/B11/B12/B13 respectively. Creating them in B1 either (a) is silently dropped by git or (b) requires `.gitkeep` files which then have to be removed when those tasks land. Skip them entirely.
- **`.claude-plugin` is a literal directory name**, not a hidden dotfile-only convention. It must exist as a real directory under the plugin root and contain `plugin.json` directly.
- **Commit message body**: matches the plan's literal commit-message body at lines 393-397, including the trailing line `Plan B · T1.` Use ANSI-C `$'...'` quoting (as written in Step 2) to preserve the multi-line format without leading-whitespace pitfalls. Do not revert to a HEREDOC — indented HEREDOCs silently prepend leading spaces to the commit subject (Phase 4 re-review NEW-1).
- **README content is intentionally minimal.** Resist the urge to write fuller documentation here. The user-facing surface is `skills/nextseek/SKILL.md` (B10). A fuller README would (a) drift from B10 and (b) fork the source of truth.
- **No `pyproject.toml` or `uv.lock` for this plugin.** The existing `nextseek-api` plugin has its own `pyproject.toml` because it was a uv-installable subpackage. Plan B's `nextseek` plugin runs shell shims that invoke the system Python with `chat_nextseek` already importable (Plan A T7+T8). Adding a `pyproject.toml` at the new plugin root is out of scope for B1 and would conflict with D29.
- **Worktree cleanup**: if a prior abandoned attempt left files at `build_context/plugins/nextseek/`, escalate via `AskUserQuestion` — do not silently `rm -rf`. (See "Executing actions with care" in the harness rules.)
- **`build_context/` is gitignored — `git add -f` is mandatory.** `.gitignore` line 13 reads `build_context/`. Plain `git add build_context/...` silently no-ops, and the subsequent `git commit` either fails ("nothing to commit") or commits an empty change. Step 2 uses `git add -f`. The only file currently tracked under that tree is `build_context/plugins/nextseek-api/skills/nextseek-api/SKILL.md`, also force-added historically. Do not amend `.gitignore` to whitelist the subtree — the `-f` flag at commit time is the agreed resolution (see plan `## Amendment Log` entry "build_context git-add -f").

### 9.3 Self-review checklist (per Phase 3 spec)

- [ ] Tests fail before implementation? **N/A** — coverage exception declared (no tests).
- [ ] Tests pass after? **N/A** — same.
- [ ] No regressions? **Yes** — full suite must remain green; B1 adds no Python imports.
- [ ] Coverage meets declared target? **Yes** — declared target is "exception, no executable code"; default repo-wide `--cov-fail-under=95` continues to pass because B1 contributes zero new lines to cov sources.
- [ ] Exception justified if below 95%? **Yes** — JSON config + static markdown have no executable paths to cover; B14's existing image-smoke and dockerfile-build tests already verify the manifest is shipped to the built image.

## 10. Worktree & Branch

- **Branch**: `task/B01-scaffold` (cut from integration branch `ultraplan/nextseek-plugin-2026-04-27`)
- **Worktree**: `.claude/worktrees/task-B01-scaffold/` (created via `scripts/init_worktrees.sh nextseek-plugin-2026-04-27 B01-scaffold` per the ultraplan skill convention)
- **Merge target**: `ultraplan/nextseek-plugin-2026-04-27`
- **Merge condition**: `git status --porcelain` is empty after the commit; `uv run pytest -q` from the worktree exits 0; manual python schema spot-check from §8 prints `OK`. Coverage gate is "unchanged from baseline" — coverage of the cov sources in pyproject.toml is not reduced by this task.
- **Wave dependency**: B1 must complete and merge to the integration branch before B2 can start (Wave 2). No other Wave 1 tasks exist.

## LOCKED 2026-05-01

This spec is immutable as of 2026-05-01 after Phase 5 user confirmation.

- **Phase 4 verdict (round 1)**: APPROVE-with-micro-fixes (2 HIGH applied — see `.claude/reviews/plan-B-spec-B01-phase4-review-2026-05-01.md`).
- **Cross-task verdict**: APPROVE-with-micro-fixes (1 manifest cross-reference applied).
- **Phase 4 verdict (round 2 — focused re-review)**: APPROVE-with-micro-fixes (NEW-1 §9.2 Gotchas contradiction fixed — see `.claude/reviews/plan-B-spec-B01-phase4-rereview-2026-05-01.md`).
- **Coverage exception approved**: no-test exception (zero executable code; fallback contingency in §5 retained as backup, not active).
- **Lock effect**: any deviation from this spec during execution requires `/ultraplan amend`. Behavioral verification in §4 Step 1 is authoritative.
