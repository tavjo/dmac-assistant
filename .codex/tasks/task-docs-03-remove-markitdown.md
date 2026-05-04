# task-docs-03-remove-markitdown

## 1. Overview

Remove the now-unused `markitdown[all]` dependency from the build-tools project and replace stale PDF/markitdown tests and prose.

## 2. Dependencies

- **Predecessor tasks**: `task-docs-02-markdown-page-loader`
- **Artifacts consumed**: implemented site-index Markdown loader

## 3. Implementation Order

1. Remove `markitdown[all]` from `build_tools/pyproject.toml`.
2. Refresh `build_tools/uv.lock`.
3. Delete or replace `build_tools/tests/integration/test_markitdown_contract.py`.
4. Remove stale `markitdown` stubs/comments from root tests if no longer needed.
5. Update comments/docstrings that describe the active ingest path as PDF/markitdown-driven.

## 4. Success Conditions

```bash
cd build_tools
UV_CACHE_DIR=/tmp/uv-cache uv run pytest
```

- Build-tools coverage remains >=95%.
- `rg -n "markitdown" build_tools` finds no active dependency/import/test contract.
- Root bridge `pyproject.toml`, root `uv.lock`, Dockerfile, and runtime image dependency guards remain unchanged or passing.

## 5. Worktree & Branch

- **Branch**: `task/nextseek-doc-ingest-stabilization`
- **Merge condition**: all Section 4 checks pass.
