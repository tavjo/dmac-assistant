# Plan: NExtSEEK Docs Ingestion Tool

**Status:** `PHASE 3 COMPLETE — TASK SPECS READY — AWAITING PHASE 4 VETTING OR USER APPROVAL TO PROCEED` (no tasks started)
**Owner:** Taisha (human reviewer) + Claude Code (executor)
**Spec:** `docs/superpowers/specs/2026-04-13-nextseek-docs-ingestion-design.md` (revised 2026-04-13)
**Created:** 2026-04-13
**Last updated:** 2026-04-13 — plan revised after spike findings, dep cleanup, and adversarial-review hardening applied

---

## Goal

Ship the build-time ingestion tool described in the spec: `make ingest-nextseek-docs` fetches the NExtSEEK GitBook content, converts it to markdown via `markitdown[all]`, hash-compares against the prior ingestion, and on a hash mismatch regenerates `docs/nextseek/<ordinal>-<slug>.md`, `docs/nextseek/README.md`, and the auto-generated block inside `container/CLAUDE.md`. Every pure-function module has unit tests; the full pipeline has an integration test using an in-test synthetic HTML fixture (no live network).

## Constraints and Conventions (apply to every task)

- **Package management:** add every new dependency with `uv add <pkg>` (or `uv add --dev <pkg>` for dev-only). Never `pip install` and never hand-edit `pyproject.toml`.
- **All deps added in T1.** Parallel tasks must not touch `pyproject.toml` or `uv.lock`. This avoids lockfile races when T3–T6 run concurrently.
- **Testing discipline:** strict TDD. Red (failing test + proof it fails) → green (minimum impl) → refactor. No implementation code lands without a failing test that drove it.
- **No live network in tests.** Enforced by `pytest-socket` (auto-disabled via `pytest.ini_options.addopts = "--disable-socket"` in `pyproject.toml`). Integration tests use the synthetic-HTML fixture; unit tests use stubs passed via dependency injection.
- **Dependency injection over monkeypatching.** `ingest()` takes `fetcher` and `parser` as keyword arguments with production defaults. Tests pass stubs; no import-site monkeypatching, no drift risk.
- **Autouse production-path guard.** `tests/conftest.py` includes an autouse fixture that makes production default paths (`DEFAULT_DOCS_DIR`, `DEFAULT_CLAUDE_MD_PATH`) raise if accessed during a test. Any test that accidentally uses production defaults fails loudly instead of polluting the repo.
- **Spec is canonical.** If a task surfaces a divergence from the spec, amend the spec in the same commit as the task. Do not let code and spec drift.
- **Atomic write ordering in `__main__.ingest()`.** Section files → README → container/CLAUDE.md → **hash last**. A failure at any point leaves the hash stale and the next run self-heals.
- **Marker strings centralized.** `BEGIN_MARKER` and `END_MARKER` live in `build_tools/ingest_nextseek_docs/constants.py`. Nothing else hard-codes them; tests import them.
- **Logging contract.** Python `logging` to stderr at INFO. stdout reserved for the human-readable status line the Makefile greps. Error messages go to stderr on exit 1.
- **One concern per task.** If a task grows beyond its success criteria during execution, split it rather than expand it.
- **One commit per task.** Commit subject: `T<N>: <short>`. Body lists the task's success criteria as checkboxes with evidence (pytest run, file existence, etc.). Co-author trailer included per repo convention.
- **Plan file updated after every task.** On completion (pass/partial/fail), update the task's Status and Evidence, update the Status Dashboard, update Last-Updated in the header, and append any surprises to the Amendment Log.
- **Human checkpoints are gates.** Tasks marked `[HUMAN GATE]` do not auto-proceed. The executor pauses and waits for explicit approval.

## Decisions Log

| # | Decision | Rationale |
|---|---|---|
| D1 | Build-time tool, not a runtime plugin | ADR-008 reserves "plugin" for runtime CLI tools. Ingestion runs once on the dev machine; output is committed. |
| D2 | Use `markitdown[all]` (matches example projects) | Verified 2026-04-13 that `MarkItDown().convert(...)` on bytes fetched from `~gitbook/pdf?limit=100` returns ~71,200 chars of markdown with proper `#`/`##` headings preserved. |
| D3 | **Fetch returns HTML, not PDF.** markitdown auto-detects by content, not extension | Verified 2026-04-13 via verbatim port of smart-form-tool's `fetch_pdf_content`. The function name in example projects is misleading; markitdown handles HTML transparently. |
| D4 | Split by H1, one file per page | Matches GitBook page boundaries; natural user mental model. H2-sub-split deferred. |
| D5 | Per-section description = first paragraph after H1 (truncated ~140 chars); no LLM | Mechanical, free, deterministic. |
| D6 | CLAUDE.md summary prose = first paragraph of first H1; section list = auto-generated H1 titles | Fully mechanical, ~5-line budget, no LLM dep. |
| D7 | Injection target is `container/CLAUDE.md` (new file), NOT repo-root `CLAUDE.md` | Repo-root = dev-side guidance. container/CLAUDE.md = in-container agent instructions. Different audiences. |
| D8 | Fence-aware H1 splitter | Avoids false-positive section boundaries inside fenced code blocks where `#` lines may appear as shell comments. |
| D9 | **Synthetic HTML** fixture (pure string), not synthetic PDF | markitdown handles HTML directly, preserves `<h1>` as `#`. No `reportlab` dep needed. Deterministic bytes, no external tool in tests. |
| D10 | Dependency injection for `fetcher` and `parser` | Tests pass stubs; no monkeypatching at import-sites; no patch-target drift risk. |
| D11 | Exit codes: `0` no change, `1` error, `2` changes written | Lets Makefile target + future CI branch on result. |
| D12 | Manual trigger only for POC (no cron, no auto-rebuild) | Explicit POC scope boundary per SDS §1.2. |
| D13 | Linting / type-checking (ruff, mypy) deferred to a follow-up plan | Keep this plan tight. |
| D14 | Hash-file written LAST in the regeneration phase | Partial-write failure leaves hash stale; next run auto-heals. |

## Adversarial Review — Risk Disposition

From the pre-execution attack, 14 risks were identified. All are either resolved by design choices above or addressed by specific task hardening below.

| # | Risk | Resolved by |
|---|------|-------------|
| 1 | markitdown→source heading contract unvalidated | T1 includes an explicit markitdown contract test (`test_markitdown_contract.py`) asserting `<h1>` → `# ` on a synthetic HTML fixture. Fails fast if library behavior changes. |
| 2 | Marker string mismatch plan↔spec | Centralized in `constants.py` (D8). Every task references the constants; no string duplication. |
| 3 | Parallel uv.lock races | **All deps hoisted to T1.** T3–T6 never modify `pyproject.toml`. |
| 4 | Monkeypatch target drift | **Dependency injection** (D10). No monkeypatching at import sites anywhere. |
| 5 | Tests pollute real repo | **Autouse conftest fixture** raises if production defaults are used. Structural prevention, not convention. |
| 6 | Hash-write ordering | **Hash written LAST** (D14, codified in T7 success criteria). |
| 7 | Fixture non-determinism | N/A — synthetic HTML is pure string (D9). No timestamps, no font embedding, no binary artifacts. |
| 8 | Gameable success criteria | Every task below lists per-case assertions with specific expected outputs. No count-only criteria, no circular hash tests, no timing assertions. |
| 9 | Smart-form-tool imports leak in | T3 includes a `test_no_stale_imports.py` that greps `build_tools/` and fails if any of `baml`, `duckdb`, `leiden`, `smart_form_*`, `openai` are imported. |
| 10 | H1 regex matches `#` in code fences | Fence-aware splitter (D8), explicitly tested in T4 case F. |
| 11 | Logging/exit contract unspecified | Codified in spec §4.8 and applied in T7 success criteria. |
| 12 | markitdown version drift | Pinned to `markitdown[all]>=0.1.5`; the contract test (T1) fails fast on behavior regressions. |
| 13 | Makefile portability | T8 uses POSIX-compatible shell, explicit exit-code propagation, and a syntax-check in success criteria. |
| 14 | Commit discipline undefined | Per-task commit protocol codified in the Constants above. |

## Task Dependency Graph

```
T1 ─┬─► T2 ─┬─► T3 ─┐
    │       │       ├─► T7 ─► T8 ─► T9 ─► T10 [HUMAN GATE]
    │       ├─► T4 ─┤
    │       ├─► T5 ─┤
    │       └─► T6 ─┘
    └────────────────┘
```

- **Serial:** T1 → T2 (scaffolding). T7 waits on T3–T6. T8 waits on T7. T9 waits on T7.
- **Parallel after T2:** T3 (fetch), T4 (split), T5 (toc), T6 (hashing) — different modules, no shared state, no dep modifications. Can dispatch four sub-agents concurrently.
- **Final:** T10 is the human gate.

## Tasks

---

### T1 — Hoisted deps, pytest infra, markitdown contract test, autouse guard

**Status:** `pending`
**Agent:** general-purpose
**Prerequisites:** none

**Description:**
One task that does all the scaffolding so downstream tasks never touch `pyproject.toml`.

1. Run `uv add --dev pytest pytest-socket` (these are the only new dev deps). Existing production deps already include `httpx`, `markitdown[all]`, `pydantic`, `python-dotenv` from prior spike work.
2. Add to `pyproject.toml` under a new `[tool.pytest.ini_options]` section: `addopts = "--disable-socket -q"` and `testpaths = ["tests"]`.
3. Create directory tree: `tests/__init__.py`, `tests/conftest.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`.
4. In `tests/conftest.py`:
   - Export `make_synthetic_html(sections: list[tuple[str, str]]) -> bytes` per spec §6.
   - Export a `synthetic_html` pytest fixture returning a default 3-section HTML body.
   - **Autouse fixture** `_block_production_paths` that runs for every test. It imports `build_tools.ingest_nextseek_docs.constants` and monkeypatches `DEFAULT_DOCS_DIR` and `DEFAULT_CLAUDE_MD_PATH` to paths that raise `RuntimeError("test used production default path")` if any filesystem operation touches them. (Implementation: use `unittest.mock.PropertyMock` or a sentinel `Path`-like that raises on `__str__`/`__fspath__`.)
   - Note: since `build_tools/` doesn't yet exist at this point, the autouse fixture guards against the module being absent too — it tries the import and skips the guard gracefully if the module isn't there yet. It becomes active as soon as T7 creates `constants.py`.
5. Write `tests/integration/test_markitdown_contract.py` with one test: pass `make_synthetic_html([("Hello", "world")])` bytes through `MarkItDown().convert(...)` using a `NamedTemporaryFile(suffix=".pdf")` (matching the production call), assert the returned `text_content` contains `# Hello` on its own line and `world` in a following line. This test pins the assumption the entire plan rests on.

**Files created:** `pyproject.toml` (modified), `uv.lock` (modified), `tests/__init__.py`, `tests/conftest.py`, `tests/unit/__init__.py`, `tests/integration/__init__.py`, `tests/integration/test_markitdown_contract.py`.

**Observable success criteria:**
- `uv run pytest tests/integration/test_markitdown_contract.py -q` exits 0 with exactly 1 passing test.
- `uv run pytest -q --collect-only` includes `test_markitdown_contract` in its output.
- `grep -F "addopts" pyproject.toml` returns a line containing `--disable-socket`.
- `grep -Fq "pytest-socket" pyproject.toml` succeeds (dep present in dev group).
- The autouse fixture raises if a subsequent test attempts to use `DEFAULT_DOCS_DIR` — validated by a self-test in `test_autouse_guard.py` under `tests/unit/`.

**Evaluator:** run the pytest commands above; read `conftest.py` to confirm autouse guard logic; confirm the markitdown-contract test actually asserts `# Hello` (not some weaker property).

---

### T2 — Create `container/CLAUDE.md` skeleton + repo-root pointer

**Status:** `pending`
**Agent:** general-purpose
**Prerequisites:** T1

**Description:**
Create `container/CLAUDE.md` as the in-container agent's baseline instructions. Minimal, ~10 lines of human-written prose plus the empty marker block. The marker strings must be imported or hard-copied from the spec §4.7 verbatim; a follow-up task (T5) creates `constants.py` with canonical values, and T7 asserts the skeleton's marker strings match the constants exactly.

Skeleton content:

```markdown
# In-Container Agent Instructions

You are the DMAC assistant running inside a Docker container for a MIT BMC lab member. Project data is mounted read-only at `/data/projects/`. Write output files to `/data/scratch/`. NExtSEEK credentials are available via `NEXTSEEK_USERNAME` and `NEXTSEEK_PASSWORD` environment variables. **Never log, print, or write credentials to any file.** Confirm destructive NExtSEEK operations (POST/PUT/DELETE) with the user conversationally before executing them.

<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->
<!-- END NEXTSEEK-DOCS (auto-generated) -->
```

(The block between the markers is empty. The ingestion tool will populate it.)

Also add one line to repo-root `CLAUDE.md` in the "Repository Status" section pointing at `container/CLAUDE.md` and noting that its NExtSEEK block is auto-generated.

**Files touched:** `container/CLAUDE.md` (new), `CLAUDE.md` (repo root — one-line edit).

**Observable success criteria:**
- `container/CLAUDE.md` exists. `grep -Fc "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->" container/CLAUDE.md` returns exactly `1`. Same for END.
- `grep -F "container/CLAUDE.md" CLAUDE.md` (repo root) returns at least one match.
- `container/CLAUDE.md` contains the literal substring `Never log, print, or write credentials`.

**Evaluator:** run the greps above.

---

### T3 — TDD `fetch.py` (verbatim port from smart-form-tool) + stale-imports gate

**Status:** `pending`
**Agent:** general-purpose (sub-agent A)
**Prerequisites:** T2

**Description:**
Create `build_tools/__init__.py`, `build_tools/ingest_nextseek_docs/__init__.py`, and `build_tools/ingest_nextseek_docs/fetch.py`. Port `fetch_pdf_content` → rename to `fetch_source_bytes`, and `parse_pdf_with_markitdown` → rename to `parse_source_to_markdown`. Otherwise keep the implementations verbatim from `smart-form-tool/packages/core/src/smart_form_core/utils/nextseek_docs.py` lines 123–169.

**TDD order:**
1. `tests/unit/test_fetch.py::test_fetch_source_bytes_returns_response_content` — use `respx` to mock `httpx.Client.get`, returning a fake response with content `b"<!DOCTYPE html><body>hi</body>"`. Assert the function returns those exact bytes. (Add `respx` to dev deps as part of T1 if not already there — update T1 if so.)
   - Actually: since `pytest-socket` disables sockets, a raise-on-call stub is cleaner than `respx`. Use `monkeypatch.setattr("httpx.Client", lambda *a, **kw: ...)` with a stub client. Or more simply: since we're testing a small function, verify its behavior by passing a URL to a local test server? **Simpler:** patch `httpx.Client` at the `build_tools.ingest_nextseek_docs.fetch` module level with a stub context manager returning a response whose `.content` is a known bytes object. Write this test first, watch it fail (function doesn't exist), then implement.
2. `test_fetch_source_bytes_raises_on_http_error` — stub `response.raise_for_status()` to raise `httpx.HTTPStatusError`; assert the exception propagates. Red → green.
3. `test_parse_source_to_markdown_handles_html` — pass `make_synthetic_html([("Welcome", "Intro.")])` bytes; assert result contains `# Welcome` on a line and `Intro.` in the following section. Red → green.
4. `tests/unit/test_no_stale_imports.py::test_build_tools_has_no_forbidden_imports` — read every `.py` file under `build_tools/` and `re.search(r"^\s*(from|import)\s+(baml|duckdb|leiden|smart_form|openai)", flags=re.M)`. Assert no matches. Runs as a regular unit test so it catches drift in any future task.

**Files touched:** `build_tools/__init__.py`, `build_tools/ingest_nextseek_docs/__init__.py`, `build_tools/ingest_nextseek_docs/fetch.py`, `tests/unit/test_fetch.py`, `tests/unit/test_no_stale_imports.py`.

**Observable success criteria:**
- `uv run pytest tests/unit/test_fetch.py tests/unit/test_no_stale_imports.py -q` exits 0.
- `test_fetch.py` has exactly 3 test functions covering: returns-content, raises-on-error, parses-html-to-headings.
- `test_no_stale_imports.py::test_build_tools_has_no_forbidden_imports` passes; if the test file itself is ever inverted (made to unconditionally pass), CI catches it (this is a review concern, not a mechanical one).
- `grep -E "^(import|from) (baml|duckdb|leiden|smart_form|openai)" -r build_tools/` returns nothing.
- No test in `test_fetch.py` makes a real network call (enforced globally by `--disable-socket`).

**Evaluator:** run the pytest commands; run the grep; inspect the test file for assertion substance.

---

### T4 — TDD `split.py` (fence-aware H1 splitter)

**Status:** `pending`
**Agent:** general-purpose (sub-agent B)
**Prerequisites:** T2

**Description:**
Create `build_tools/ingest_nextseek_docs/split.py` with a `Section` dataclass (fields: `ordinal: int`, `title: str`, `slug: str`, `body: str`, `description: str`) and `split_by_h1(markdown: str) -> list[Section]`.

**TDD order — one test per case, each asserting specific behavior (not just "count ≥ N"):**
- Case A: empty markdown → returns `[]`.
- Case B: single H1 with body → returns `[Section(ordinal=1, title="Hello", slug="hello", body=..., description=...)]` — assert each field by exact equality (after normalizing whitespace in body).
- Case C: three H1s → returns 3 sections with ordinals `[1, 2, 3]`, titles `["A", "B", "C"]`, slugs `["a", "b", "c"]`.
- Case D: two H1s with colliding slugs (`"Hello World!"` and `"Hello World"`) → slugs are `["hello-world", "hello-world-2"]` (exact).
- Case E: H1 with no body before the next heading → description is exactly `"(section overview)"`.
- Case F: **fence-aware** — markdown with a fenced code block containing `# comment` lines, followed by a real H1. The code-fence `#` must NOT open a section; only the real H1 does. Assert the returned list has exactly 1 section whose `body` includes the full code block.
- Case G: H1 description of length 200 with a space at position 135 → truncated to the substring ending at position 135 + `"…"` (the word-boundary trim rule).

**Files touched:** `build_tools/ingest_nextseek_docs/split.py`, `tests/unit/test_split.py`.

**Observable success criteria:**
- `uv run pytest tests/unit/test_split.py -q` exits 0.
- `test_split.py` has exactly 7 test functions, named `test_split_empty`, `test_split_single_h1`, `test_split_three_h1s`, `test_split_slug_collision`, `test_split_empty_description`, `test_split_fence_aware`, `test_split_description_truncation`.
- `split.py` imports only from Python stdlib and `build_tools.ingest_nextseek_docs.*` (no `httpx`, `markitdown`, `pydantic` even).
- Running `grep -c "assert " tests/unit/test_split.py` returns ≥ 20 (each test makes multiple specific assertions).

**Evaluator:** run pytest; inspect test file for per-case assertion substance; run the grep for import hygiene.

---

### T5 — TDD `toc.py` + `constants.py`

**Status:** `pending`
**Agent:** general-purpose (sub-agent C)
**Prerequisites:** T2, T4 (imports `Section`)

**Description:**
Create `build_tools/ingest_nextseek_docs/constants.py` containing:

```python
BEGIN_MARKER = "<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->"
END_MARKER = "<!-- END NEXTSEEK-DOCS (auto-generated) -->"
DEFAULT_DOC_URL = "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/~gitbook/pdf?limit=100"
DEFAULT_DOCS_DIR = Path("docs/nextseek")
DEFAULT_CLAUDE_MD_PATH = Path("container/CLAUDE.md")
```

Create `build_tools/ingest_nextseek_docs/toc.py` with three functions per spec §4.6–4.7 and §5.

**TDD order:**
1. `test_render_readme_golden` — fixed 2-section input + source_url + content_hash → assert exact string match against a 20-line golden block defined in the test file.
2. `test_render_claude_md_block_golden` — fixed 3-section input + overview_paragraph → assert exact string match against a 6-line golden block.
3. `test_update_claude_md_happy_path` — `tmp_path` seeded with a file containing the markers; call `update_claude_md(path, "NEW\nCONTENT")`; assert the bytes between markers are now `"NEW\nCONTENT"`, nothing else changed.
4. `test_update_claude_md_missing_markers` — file without markers → `ValueError`, file bytes unchanged (assert byte-identical).
5. `test_update_claude_md_duplicate_markers` — file with two BEGIN markers → `ValueError`, file unchanged.
6. `test_update_claude_md_is_atomic` — monkeypatch `os.replace` to raise on first call; assert file unchanged on disk (no partial write visible).
7. `test_update_claude_md_idempotent` — call twice with the same block; second call produces a byte-identical file.
8. `test_constants_match_spec` — assert `BEGIN_MARKER` and `END_MARKER` equal the literal strings in the spec §4.7 (imported from a local test constant to avoid duplication, or directly asserted).

**Files touched:** `build_tools/ingest_nextseek_docs/constants.py`, `build_tools/ingest_nextseek_docs/toc.py`, `tests/unit/test_toc.py`.

**Observable success criteria:**
- `uv run pytest tests/unit/test_toc.py -q` exits 0 with exactly 8 tests.
- Golden strings do not contain any dynamic content (no timestamps, UUIDs, file paths beyond the ones passed as arguments).
- `update_claude_md` uses `os.replace` (verified by grep: `grep -F "os.replace" build_tools/ingest_nextseek_docs/toc.py`).
- `container/CLAUDE.md`'s current marker strings match `BEGIN_MARKER` and `END_MARKER` exactly (run `python -c "from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER; assert BEGIN_MARKER in open('container/CLAUDE.md').read(); assert END_MARKER in open('container/CLAUDE.md').read()"` — exit 0).

**Evaluator:** run the pytest; run the constant-consistency python -c; inspect golden strings for dynamic content.

---

### T6 — TDD `hashing.py`

**Status:** `pending`
**Agent:** general-purpose (sub-agent D)
**Prerequisites:** T2

**Description:**
Create `build_tools/ingest_nextseek_docs/hashing.py` with `compute_content_hash`, `read_stored_hash`, `write_stored_hash`.

**TDD order:**
1. `test_compute_content_hash_known_digest` — `assert compute_content_hash("hello") == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"`. This is the well-known SHA-256 of "hello" (lowercase, no newline); pinning against a real external digest (not `hashlib.sha256(...)`) prevents the test from being circular.
2. `test_read_stored_hash_missing_file` — `read_stored_hash(tmp_path / "nope")` returns `None`.
3. `test_read_stored_hash_strips_whitespace` — write `"  abc\n"` to a file; assert `read_stored_hash` returns `"abc"`.
4. `test_write_stored_hash_creates_parents` — pass a path with non-existent parent dirs; assert after the call the file exists with exact content `"abc\n"` (trailing newline) and parents exist.

**Files touched:** `build_tools/ingest_nextseek_docs/hashing.py`, `tests/unit/test_hashing.py`.

**Observable success criteria:**
- `uv run pytest tests/unit/test_hashing.py -q` exits 0 with exactly 4 tests.
- `hashing.py` has no imports other than `hashlib` and `pathlib`.
- The known-digest assertion uses the specific hex string `2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824`, not `hashlib.sha256(...)` — verified by grep.

**Evaluator:** pytest; `grep -F "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824" tests/unit/test_hashing.py` returns a match.

---

### T7 — TDD `__main__.py` orchestration (DI, atomic hash-last write, logging contract)

**Status:** `pending`
**Agent:** general-purpose
**Prerequisites:** T3, T4, T5, T6

**Description:**
Wire the pipeline in `build_tools/ingest_nextseek_docs/__main__.py`. Signature:

```python
def ingest(
    *,
    docs_dir: Path,
    claude_md_path: Path,
    doc_url: str,
    force: bool,
    fetcher: Callable[[str], bytes] = fetch_source_bytes,
    parser: Callable[[bytes], str] = parse_source_to_markdown,
) -> int: ...
```

No defaults for `docs_dir`, `claude_md_path`, `doc_url`, `force` — required kwargs. argparse in CLI layer supplies production defaults from `constants.py`. Tests always pass `tmp_path` values.

Pipeline body follows spec §4.3–4.8 with **write ordering:** (1) section files → (2) README.md → (3) container/CLAUDE.md → (4) **hash file last**.

Logging: configured via `logging.basicConfig(level=logging.INFO, stream=sys.stderr, format=...)`. Status lines written to `sys.stdout`:
- On exit 0: `no changes\n`.
- On exit 2: `changes written: N section files, README, container/CLAUDE.md\n`.
- On exit 1: nothing to stdout; error to stderr.

**TDD order (all tests pass `tmp_path` + stub fetcher/parser — no monkeypatching at import sites):**
1. `test_ingest_exits_0_when_hash_matches` — seed hash file with the sha256 of a known string; stub `fetcher` to return arbitrary bytes; stub `parser` to return that known string; assert exit 0, stdout starts with `"no changes"`, no new files created in `docs_dir`.
2. `test_ingest_exits_2_on_fresh_run` — no existing hash file; stub parser returns 2-section markdown; assert exit 2, expected section files exist in `tmp_path`, README exists, container/CLAUDE.md's block was rewritten.
3. `test_ingest_force_overrides_hash_match` — hash matches; `force=True`; assert exit 2 and regeneration occurred (mtime of README newer).
4. `test_ingest_fetcher_exception_exits_1_no_writes` — stub `fetcher` to raise `RuntimeError`; assert exit 1, no files written to `tmp_path` (assert `list(tmp_path.iterdir())` contains only the pre-seeded CLAUDE.md file).
5. `test_ingest_parser_returns_no_h1_exits_1` — stub parser returns markdown without any `# ` lines; assert exit 1, no section files written, hash NOT updated.
6. `test_ingest_cleans_stale_section_files` — pre-populate `tmp_path / "docs/nextseek/99-stale.md"`; run with fresh 2-section content; assert `99-stale.md` is gone and the two new files exist.
7. `test_ingest_writes_hash_last` — monkeypatch `write_stored_hash` to raise; run with changed content; assert section files + README + container/CLAUDE.md were all written, but `.content-hash` does NOT exist (proves it was the LAST attempted write).
8. `test_ingest_logging_to_stderr` — capture stderr via pytest's `capsys`; assert at least one INFO-level line from the logger appears; capture stdout; assert ONLY the status line appears (no log noise on stdout).
9. `test_cli_help_mentions_force` — invoke `python -m build_tools.ingest_nextseek_docs --help` via subprocess; assert stdout contains both `--force` and `--help`.

**Files touched:** `build_tools/ingest_nextseek_docs/__main__.py`, `tests/unit/test_main.py`.

**Observable success criteria:**
- `uv run pytest tests/unit/test_main.py -q` exits 0 with exactly 9 tests.
- `ingest()` signature contains `fetcher` and `parser` keyword parameters (verified by `inspect.signature` in a test).
- `grep -c "monkeypatch" tests/unit/test_main.py` returns 1 (only `test_ingest_writes_hash_last` uses monkeypatch, for `write_stored_hash`). All other tests pass stubs via DI.
- The hash-last test (`test_ingest_writes_hash_last`) does not just assert exit code — it asserts absence of the hash file on disk.

**Evaluator:** pytest; `grep -c "monkeypatch" tests/unit/test_main.py` returns exactly 1; read the test file to confirm DI pattern.

---

### T8 — Add `Makefile` target `ingest-nextseek-docs`

**Status:** `pending`
**Agent:** general-purpose
**Prerequisites:** T7

**Description:**
Create a top-level `Makefile` with POSIX-compatible syntax:

```
.PHONY: ingest-nextseek-docs
ingest-nextseek-docs:
	@uv run python -m build_tools.ingest_nextseek_docs $(ARGS); \
	code=$$?; \
	if [ $$code -eq 2 ]; then \
	  echo ""; \
	  echo "NExtSEEK docs changed. Review the diff, commit, and rebuild the Docker image."; \
	fi; \
	exit $$code
```

Tabs (not spaces) for recipe indentation. Single-line continuation so the whole recipe is one shell invocation (preserves `$$code` across lines).

**Files touched:** `Makefile` (new).

**Observable success criteria:**
- `make -n ingest-nextseek-docs ARGS=--help` prints a command that includes both `uv run python -m build_tools.ingest_nextseek_docs` and `--help`.
- `make ingest-nextseek-docs ARGS=--help` runs successfully (exits 0 because `--help` is exit 0) and prints the CLI help containing `--force`.
- `grep -P "^\t" Makefile` returns at least one line (recipe uses tabs).
- `.PHONY` declaration includes `ingest-nextseek-docs`.

**Evaluator:** run the `make -n` and `make` commands; run the grep.

---

### T9 — End-to-end integration test (synthetic HTML through full pipeline)

**Status:** `pending`
**Agent:** general-purpose
**Prerequisites:** T7

**Description:**
Write `tests/integration/test_end_to_end.py`. The test uses `make_synthetic_html` from conftest to build bytes, wraps them in a stubbed `fetcher` callable, and drives the full `ingest(...)` pipeline.

Test cases:
1. **Fresh ingest on a clean `tmp_path`:** 3-section HTML; call `ingest(force=True, docs_dir=tmp_path/"docs/nextseek", claude_md_path=seeded_container_md, doc_url="fake", force=False, fetcher=stub, parser=real_parse_source_to_markdown)`. Assert exit 2. Assert files `01-*.md`, `02-*.md`, `03-*.md`, `README.md`, and `.content-hash` exist. Assert `container/CLAUDE.md` between the markers contains the first section's title. Uses the REAL parser (markitdown) — not a mock — to exercise the whole chain.
2. **Idempotent re-run:** immediately call `ingest(force=False, ...)` again with the same stub; assert exit 0, stdout starts with `"no changes"`, file mtimes unchanged.
3. **Mutation triggers regeneration:** change the stub to produce different HTML with a different first section; call `ingest(force=False, ...)`; assert exit 2, old first section's file gone, new first section's file present, hash updated.

**Files touched:** `tests/integration/test_end_to_end.py`, `tests/integration/conftest.py` (if needed for test-specific fixtures).

**Observable success criteria:**
- `uv run pytest tests/integration/ -q` exits 0 with ≥ 4 tests (the markitdown contract from T1, plus 3 end-to-end cases).
- Full test suite `uv run pytest -q` exits 0.
- No real network call made (enforced by global `--disable-socket`).
- No files committed under `docs/nextseek/` — `git status docs/nextseek/` shows nothing (all test output stayed in `tmp_path`).

**Evaluator:** run the test suite; run `git status`.

---

### T10 — [HUMAN GATE] Review, amend, accept

**Status:** `pending`
**Agent:** Taisha (human)
**Prerequisites:** T1–T9

**Description:**
Human reviews:
- Spec + plan still consistent.
- All test files — are assertions meaningful or do they pass trivially?
- `container/CLAUDE.md` skeleton and (after T7) the populated block structure in a dry-run.
- `make ingest-nextseek-docs ARGS=--help` output.
- Per-task commits look clean with evidence in bodies.

**Explicitly deferred (NOT part of this plan, flagged for follow-up):**
- Running the first live ingestion against the real GitBook (produces a large generated-content diff; gate separately).
- Docker image build that bakes `container/CLAUDE.md` and `docs/nextseek/` at `/app/` — separate POC milestone.
- ruff/mypy config (D13).
- Cron-based refresh and auto-PR (explicit spec non-goal).

**Observable success criteria:**
- Human updates T10's Status to `completed` with a note on acceptance.
- `git log --oneline` shows one commit per task (T0's spec work was folded into this plan revision).
- Status Dashboard below shows all tasks green.

**Evaluator:** human sign-off.

---

## Status Dashboard

| ID | Task | Status | Evidence |
|----|------|--------|----------|
| T1 | Hoisted deps + test infra + contract test + autouse guard | pending | — |
| T2 | `container/CLAUDE.md` skeleton + root pointer | pending | — |
| T3 | TDD fetch.py + stale-imports gate | pending | — |
| T4 | TDD split.py (fence-aware) | pending | — |
| T5 | TDD toc.py + constants.py | pending | — |
| T6 | TDD hashing.py | pending | — |
| T7 | TDD __main__.py (DI + hash-last + logging) | pending | — |
| T8 | Makefile target | pending | — |
| T9 | End-to-end integration | pending | — |
| T10 | Human review & accept | pending | — |

## Open Questions Log

_(Append any questions surfaced during execution here with their resolution.)_

## Task Specs Manifest

Phase 3 EXPLODE complete. Each task in `T1–T9` has a complete 10-section spec in `.claude/tasks/`:

| ID | Spec file | Wave | Dependencies | Coverage target |
|----|-----------|------|--------------|-----------------|
| T1 | `.claude/tasks/task-01-test-infra.md` | 1 | — | N/A (scaffolding) |
| T2 | `.claude/tasks/task-02-container-claude-md.md` | 2 | T1 | N/A |
| T3 | `.claude/tasks/task-03-fetch.md` | 3 (parallel) | T2 | ≥95% (targeting 100%) |
| T4 | `.claude/tasks/task-04-split.md` | 3 (parallel) | T2 | ≥95% |
| T5 | `.claude/tasks/task-05-toc.md` | 3 (parallel) | T2, T4 | ≥95% |
| T6 | `.claude/tasks/task-06-hashing.md` | 3 (parallel) | T2 | ≥95% (targeting 100%) |
| T7 | `.claude/tasks/task-07-orchestrator.md` | 4 | T3, T4, T5, T6 | ≥95% |
| T8 | `.claude/tasks/task-08-makefile.md` | 5 | T7 | N/A (Makefile) |
| T9 | `.claude/tasks/task-09-end-to-end.md` | 5 | T7 | ≥95% whole-package |
| T10 | Human gate (no spec file) | 6 | T1–T9 | N/A |

**Wave structure for Phase 6 execution:**
- Wave 1: T1 (solo)
- Wave 2: T2 (solo)
- Wave 3: T3, T4, T5, T6 (parallel; T5 waits briefly for T4 to publish `Section`)
- Wave 4: T7 (solo)
- Wave 5: T8, T9 (parallel)
- Wave 6: T10 (human gate)

Note: T5 has a secondary dep on T4 because it imports `Section`. In practice T5 can start the same time as T3/T6 (it can create `constants.py` first, then wait on T4's merge before implementing `toc.py`). For simplicity, in Phase 6 we treat T5 as dependent on T4 and let T3/T6 run first within Wave 3.

**Coverage exceptions**: None declared. `Makefile` and `container/CLAUDE.md` skeleton are not Python code, so they carry no coverage target. All Python modules under `build_tools/ingest_nextseek_docs/` must meet the 95% floor.

**Refinements captured in specs beyond the original plan sketch:**
- T1 adds `pytest-cov` to dev deps (originally omitted; 95% floor requires it).
- T2 creates the `build_tools/` + `build_tools/ingest_nextseek_docs/` package scaffolding (empty `__init__.py` files) so T3–T6 don't race on directory creation.
- T8 includes a Python integration test file (`tests/integration/test_makefile.py`) rather than relying on ad-hoc shell checks.
- T9 adds a repo-pollution canary test using `git status --porcelain`.

## Amendment Log

- **2026-04-13** — plan drafted (original T0–T10).
- **2026-04-13** — adversarial review appended; 14 risks identified; hardening decisions captured.
- **2026-04-13** — spike validated GitBook endpoint returns HTML (not PDF); markitdown auto-detects and preserves `<h1>` as `#`. Spec rewritten. Plan revised: dropped T0 (spec rewrite done inline); fixture strategy pivoted from reportlab PDF to synthetic HTML (no binary dep); deps hoisted to T1; DI adopted for fetcher/parser; marker strings centralized in `constants.py`; autouse conftest guard structural instead of conventional; fence-aware splitter explicit; hash written LAST; logging contract codified; commit protocol codified. Spike deps (`reportlab`, `pymupdf4llm`) removed; `markitdown[all]` locked.
- **2026-04-13** — Phase 3 EXPLODE complete. Nine task specs written to `.claude/tasks/` with full behavioral contracts, reference implementations, exact diffs, verification commands, and worktree/branch assignments. Refinements (pytest-cov, package scaffolding in T2, Makefile integration test, repo-pollution canary) captured above.
