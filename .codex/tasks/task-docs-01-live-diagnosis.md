# task-docs-01-live-diagnosis

## 1. Overview

Prove the replacement GitBook source is stable before implementation. This task writes only a diagnostic report under `.codex/reports/`.

## 2. Dependencies

- **Predecessor tasks**: none
- **Artifacts consumed**: `.codex/reports/nextseek-doc-ingest-stabilization-2026-05-04.md`
- **External endpoints**: `https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/`

## 3. Behavioral Contract

- Fetch `~gitbook/site-index`.
- Resolve each page to a Markdown URL.
- Root page fallback: `Overview` resolves to `/overview.md`.
- Fetch site-index and every resolved Markdown page 3 times.
- Record SHA-256 and byte counts for every fetch.
- Stop the whole plan if any resource is unstable, returns GitBook app HTML, returns no H1, or fails HTTP status.

## 4. Verification

```bash
# live diagnostic; exact implementation may be an inline script or small helper
python -c '<diagnostic>'
```

Success requires `.codex/reports/nextseek-doc-ingest-markdown-pages-diagnosis-2026-05-04.md` to state that every resource is 3x stable and Markdown-valid.

## 5. Worktree & Branch

- **Branch**: `task/nextseek-doc-ingest-stabilization`
- **Merge target**: current plugin integration branch after the stabilization fix is accepted
