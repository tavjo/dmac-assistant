# NExtSEEK Docs Ingestion Stabilization
**Plan slug**: nextseek-doc-ingest-stabilization  
**Created**: 2026-05-04  
**Status**: Approved for sequential execution on `task/nextseek-doc-ingest-stabilization`

## Goal Statement

Replace the nondeterministic GitBook PDF/`markitdown` ingestion path with a stable GitBook `site-index` plus per-page Markdown ingestion path, regenerate committed NExtSEEK docs from the new source, and preserve fail-closed behavior for true source instability or parser failure.

## Design Decisions

- **DD-01**: Use GitBook `~gitbook/site-index` as the canonical page manifest.
- **DD-02**: Fetch per-page Markdown, not PDF exports, for normal ingestion.
- **DD-03**: Resolve root page Markdown via title-slug fallback (`overview.md`) when the root pathname plus `.md` returns GitBook app HTML.
- **DD-04**: Preserve site-index order as generated docs order.
- **DD-05**: Strip repeated trailing GitBook `Agent Instructions: Querying This Documentation` boilerplate from every generated page.
- **DD-06**: Require 3x live stability proof for site-index and every resolved Markdown page before clearance.
- **DD-07**: Remove `markitdown[all]` from `build_tools` once the normal ingest path no longer uses it.
- **DD-08**: Keep artifacts under `.codex/`; do not mutate active plugin `.claude` plan artifacts as part of this fix.

## Task List

| ID | Summary | Wave | Coverage Target | Dependencies | Status |
|----|---------|------|----------------|--------------|--------|
| task-docs-01 | Live diagnose site-index + per-page Markdown stability | 1 | N/A | none | pending |
| task-docs-02 | Implement site-index Markdown loader and pipeline tests | 2 | 95% | task-docs-01 | pending |
| task-docs-03 | Remove markitdown dependency and stale contracts | 3 | 95% | task-docs-02 | pending |
| task-docs-04 | Live regenerate docs and final evaluation | 4 | 95% | task-docs-03 | pending |

## Dependency Graph

```text
task-docs-01 -> task-docs-02 -> task-docs-03 -> task-docs-04
```

## Key Files

- `build_tools/ingest_nextseek_docs/constants.py`
- `build_tools/ingest_nextseek_docs/fetch.py`
- `build_tools/ingest_nextseek_docs/__main__.py`
- `build_tools/tests/unit/test_fetch.py`
- `build_tools/tests/unit/test_main.py`
- `build_tools/tests/integration/test_end_to_end.py`
- `build_tools/pyproject.toml`
- `build_tools/uv.lock`
- `docs/nextseek/`
- `container/CLAUDE.md`

## Permissions Required

- Live HTTPS reads from `https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/`.
- `uv run` inside `build_tools/` with `UV_CACHE_DIR=/tmp/uv-cache`.
- `uv lock` for the `build_tools` project after dependency removal.
- No Docker build is required for this plan.

## Task Specs Manifest

| Spec File | Task | Wave | Coverage Target | Vetted | Coverage Exception |
|-----------|------|------|----------------|--------|--------------------|
| `.codex/tasks/task-docs-01-live-diagnosis.md` | task-docs-01 | 1 | N/A | yes | no executable code |
| `.codex/tasks/task-docs-02-markdown-page-loader.md` | task-docs-02 | 2 | 95% | yes | none |
| `.codex/tasks/task-docs-03-remove-markitdown.md` | task-docs-03 | 3 | 95% | yes | none |
| `.codex/tasks/task-docs-04-live-regeneration-evaluation.md` | task-docs-04 | 4 | 95% | yes | none |

## Coverage Exceptions

- `task-docs-01`: no executable code changes; live diagnosis/report only.

## Execution Log

- 2026-05-04: Plan created from approved user plan. Execution branch: `task/nextseek-doc-ingest-stabilization`.
- 2026-05-04: `task-docs-01` complete. Live diagnosis passed for site-index plus all 10 page Markdown resources; report persisted.
- 2026-05-04: `task-docs-02` complete. Implemented dynamic site-index loader, root-title fallback, boilerplate stripping, one-section-per-page normalization, and fail-closed tests.
- 2026-05-04: `task-docs-03` complete. Removed `markitdown[all]` from build_tools and refreshed `build_tools/uv.lock`.
- 2026-05-04: `task-docs-04` complete. Live regeneration produced 10 site-index-ordered docs; second run was no-op; evaluation report persisted.
