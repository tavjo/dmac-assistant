# task-06-hashing

## 1. Overview

Implement SHA-256 content hashing and stored-hash I/O helpers in `build_tools/ingest_nextseek_docs/hashing.py`.

**Key invariants:**
- `compute_content_hash` returns the hex-encoded SHA-256 of UTF-8 bytes.
- `read_stored_hash` returns a stripped string or `None` if the file is missing.
- `write_stored_hash` writes `digest + "\n"` to the path, creating parent directories as needed.
- Module is stdlib-only (`hashlib`, `pathlib`).

## 2. Dependencies

- **Predecessor tasks**: T2 (package exists).
- **Artifacts consumed**: `build_tools/ingest_nextseek_docs/__init__.py` (empty).
- **External packages**: none.

## 3. Key Design Decisions

- **D14**: Hash-file written LAST in regeneration — *Constraint*: `write_stored_hash` is called only at the very end of `ingest()` in T7.
- **R7 resolution** (anti-circular test): Test asserts against the **externally known** SHA-256 of `"hello"`, not against `hashlib.sha256(...)` — test is a real contract, not a self-check.
- **Coverage floor**: 95%.

## 4. TDD Implementation Order

**Coverage target**: 100% (small, pure module).

**Step 1 — RED**: `test_compute_content_hash_known_digest` (import fails).
**Step 2 — GREEN**: implement `compute_content_hash`.

**Step 3 — RED**: `test_read_stored_hash_missing_file_returns_none`.
**Step 4 — GREEN**: implement `read_stored_hash`.

**Step 5 — RED**: `test_read_stored_hash_strips_whitespace`.
**Step 6 — GREEN**: strip-on-read.

**Step 7 — RED**: `test_write_stored_hash_creates_parent_dirs`.
**Step 8 — GREEN**: `parent.mkdir(parents=True, exist_ok=True)`.

**Step 9 — RED**: `test_write_stored_hash_appends_newline`.
**Step 10 — GREEN**: confirmed.

**Step 11 — VERIFY**:
  ```bash
  uv run pytest tests/unit/test_hashing.py -q
  uv run pytest --cov=build_tools.ingest_nextseek_docs.hashing \
      --cov-report=term-missing --cov-fail-under=95 tests/unit/test_hashing.py
  ```

## 5. Behavioral Contract (Tests)

### `tests/unit/test_hashing.py`

```python
"""Unit tests for build_tools.ingest_nextseek_docs.hashing."""
from __future__ import annotations

from pathlib import Path

from build_tools.ingest_nextseek_docs.hashing import (
    compute_content_hash,
    read_stored_hash,
    write_stored_hash,
)

# Well-known SHA-256 of the literal ASCII string "hello" (no newline).
# Pinned to a real external value, not re-derived from hashlib — prevents
# circular self-test.
SHA256_OF_HELLO = (
    "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
)


def test_compute_content_hash_matches_known_digest_for_hello() -> None:
    assert compute_content_hash("hello") == SHA256_OF_HELLO


def test_compute_content_hash_matches_known_digest_for_empty_string() -> None:
    # SHA-256 of empty bytes (well-known)
    assert compute_content_hash("") == (
        "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
    )


def test_compute_content_hash_distinguishes_different_inputs() -> None:
    assert compute_content_hash("a") != compute_content_hash("b")


def test_read_stored_hash_returns_none_when_file_missing(tmp_path: Path) -> None:
    assert read_stored_hash(tmp_path / "nope.txt") is None


def test_read_stored_hash_strips_trailing_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "hash.txt"
    p.write_text("  abc123\n")
    assert read_stored_hash(p) == "abc123"


def test_read_stored_hash_strips_leading_whitespace(tmp_path: Path) -> None:
    p = tmp_path / "hash.txt"
    p.write_text("   abc123")
    assert read_stored_hash(p) == "abc123"


def test_write_stored_hash_writes_digest_with_trailing_newline(tmp_path: Path) -> None:
    p = tmp_path / "hash.txt"
    write_stored_hash(p, "deadbeef")
    assert p.read_text() == "deadbeef\n"


def test_write_stored_hash_creates_missing_parent_dirs(tmp_path: Path) -> None:
    p = tmp_path / "deep" / "deeper" / "hash.txt"
    assert not p.parent.exists()
    write_stored_hash(p, "xyz")
    assert p.exists()
    assert p.parent.exists()
    assert p.read_text() == "xyz\n"


def test_write_stored_hash_overwrites_existing_file(tmp_path: Path) -> None:
    p = tmp_path / "hash.txt"
    p.write_text("old\n")
    write_stored_hash(p, "new")
    assert p.read_text() == "new\n"
```

## 6. Reference Implementation

### `build_tools/ingest_nextseek_docs/hashing.py` (new)

```python
"""SHA-256 content hashing and stored-hash I/O."""
from __future__ import annotations

import hashlib
from pathlib import Path


def compute_content_hash(text: str) -> str:
    """Return the hex-encoded SHA-256 digest of `text` encoded as UTF-8."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_stored_hash(path: Path) -> str | None:
    """Read and strip the stored hash file, or return None if the file is missing."""
    if not path.exists():
        return None
    return path.read_text().strip()


def write_stored_hash(path: Path, digest: str) -> None:
    """Write `digest` + newline to `path`, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(digest + "\n")
```

## 7. Modified Files (exact diffs)

None — new file only.

## 8. Verification

```bash
uv run pytest tests/unit/test_hashing.py -q

uv run pytest --cov=build_tools.ingest_nextseek_docs.hashing \
    --cov-report=term-missing --cov-fail-under=95 tests/unit/test_hashing.py

# Known-digest assertion actually present (grep for the specific hex string)
grep -F "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" \
    tests/unit/test_hashing.py

# Full suite
uv run pytest -q
```

**Expected test count**: 9 new tests.

**Expected coverage**: 100% for `hashing.py`.

## 9. Implementation Notes

- The SHA-256 of `"hello"` is `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824`; of empty bytes is `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855`. Both are trivially verifiable at `echo -n "hello" | sha256sum` / `echo -n "" | sha256sum`.
- Use `path.exists()` followed by `path.read_text()` rather than `try: path.read_text() except FileNotFoundError` because the semantics of the missing-file return value are a deliberate API contract, not an exception-handling concern.
- `mkdir(parents=True, exist_ok=True)` is idempotent — safe for re-runs.

## 10. Worktree & Branch

- **Branch**: `task/06-hashing`
- **Worktree**: `.claude/worktrees/task-06-hashing/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass; coverage ≥ 95% (targeting 100%).
