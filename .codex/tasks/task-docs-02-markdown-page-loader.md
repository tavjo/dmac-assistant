# task-docs-02-markdown-page-loader

## 1. Overview

Implement the site-index plus per-page Markdown loader and wire ingestion to consume a stable Markdown corpus instead of repeated PDF fetch/parse attempts.

## 2. Dependencies

- **Predecessor tasks**: `task-docs-01-live-diagnosis`
- **Artifacts consumed**: diagnosis report proving live page stability
- **External packages**: existing `httpx`

## 3. Key Design Decisions

- **DD-01/DD-02**: Normal ingest source is site-index plus page Markdown.
- **DD-03**: Root path needs title-slug fallback.
- **DD-04**: Site-index order is canonical.
- **DD-05**: Strip repeated trailing GitBook agent-query boilerplate.
- **DD-06**: Fail closed if the corpus does not stabilize.

## 4. TDD Implementation Order

**Coverage target**: 95%

1. Add failing unit tests for site-index parsing, page URL resolution, root fallback, boilerplate stripping, HTML refusal, zero-page refusal, corpus stabilization, and no-write failure.
2. Implement loader helpers in `build_tools/ingest_nextseek_docs/fetch.py`.
3. Update `build_tools/ingest_nextseek_docs/__main__.py` so `ingest()` accepts a `loader` dependency and hashes stabilized section snapshots.
4. Update end-to-end tests to inject deterministic Markdown corpus loader outputs.
5. Verify from `build_tools/`:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

## 5. Success Conditions

- Build-tools suite passes with coverage >=95%.
- Generated block hermetic regression remains non-empty.
- No production writes occur when source loading or stabilization fails.

## 6. Worktree & Branch

- **Branch**: `task/nextseek-doc-ingest-stabilization`
- **Merge condition**: all Section 5 checks pass.
