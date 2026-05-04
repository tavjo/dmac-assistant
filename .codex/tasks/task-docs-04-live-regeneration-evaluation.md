# task-docs-04-live-regeneration-evaluation

## 1. Overview

Regenerate committed docs from the new stable source and clear the fix with live proof plus tests.

## 2. Dependencies

- **Predecessor tasks**: `task-docs-03-remove-markitdown`

## 3. Required Checks

1. Re-run 3x live stability proof across site-index and every page.
2. Run `make ingest-nextseek-docs`.
3. Run `make ingest-nextseek-docs` a second time and require no-op exit behavior.
4. Verify generated docs use site-index order.
5. Verify generated docs contain no repeated `Agent Instructions: Querying This Documentation` boilerplate.
6. Write `.codex/reports/nextseek-doc-ingest-stabilization-evaluation-2026-05-04.md`.

## 4. Success Conditions

- First live ingest exits `0` or `2`; if `2`, changed docs are intentional generated output.
- Second live ingest exits `0` and prints `no changes`.
- `docs/nextseek/README.md` source points at the site-index source, not the old PDF URL.
- Build-tools suite passes with coverage >=95%.
- Relevant root tests for Makefile, container docs, and markitdown drift guards pass.

## 5. Worktree & Branch

- **Branch**: `task/nextseek-doc-ingest-stabilization`
- **Merge condition**: final evaluation report records all checks green.
