# NExtSEEK Docs Ingestion Stabilization Evaluation — 2026-05-04

## Verdict

**PASS.** The docs ingestion pipeline now uses GitBook `site-index` plus per-page Markdown instead of the nondeterministic PDF/`markitdown` export path.

## Live Proof

- Final 3x stability proof passed for the site-index and all 10 resolved Markdown pages.
- First corrected live regeneration:
  - `UV_CACHE_DIR=/tmp/uv-cache make ingest-nextseek-docs`
  - result: exit `2`, `changes written: 10 section files, README, container/CLAUDE.md`
- Second live regeneration:
  - `UV_CACHE_DIR=/tmp/uv-cache make ingest-nextseek-docs`
  - result: exit `0`, `no changes`

## Generated Output Checks

- Generated section files are exactly the dynamic site-index order:
  1. `01-overview.md`
  2. `02-using-seek-and-nextseek.md`
  3. `03-uploading.md`
  4. `04-searching-downloading.md`
  5. `05-admin-pages.md`
  6. `06-useful-links.md`
  7. `07-installation.md`
  8. `08-seek.md`
  9. `09-nextseek.md`
  10. `10-contact-staff.md`
- `docs/nextseek/README.md` source is now `https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/site-index`.
- `rg "Agent Instructions: Querying This Documentation" docs/nextseek container/CLAUDE.md` returned no matches.

## Test Evidence

- `cd build_tools && UV_CACHE_DIR=/tmp/uv-cache uv run pytest`
  - `81 passed, 2 warnings`
  - total coverage `97.29%`
- Targeted root checks:
  - `UV_CACHE_DIR=/tmp/uv-cache uv run pytest tests/integration/test_makefile.py tests/unit/test_container_claude_md_plugin_section.py tests/test_dockerfile_build.py::test_dockerfile_uses_uv_sync_locked tests/test_dockerfile_build.py::test_plugin_discovery_survives_ingestion -q --no-cov`
  - `11 passed`

## Residual Notes

- No Docker build was run; this fix changes host-side build tooling and generated docs only.
- Pre-existing `.claude/CLAUDE.md` and `.claude/plans/nextseek-plugin-2026-04-27.md` modifications were not part of this stabilization fix and should not be staged with it.
