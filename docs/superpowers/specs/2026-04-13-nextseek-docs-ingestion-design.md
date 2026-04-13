# NExtSEEK Docs Ingestion — Design Spec

**Date:** 2026-04-13
**Project:** DMAC Assistant POC
**Status:** Draft for review

---

## 1. Problem

The DMAC Assistant runs Claude Code in a container and lets users ask natural-language questions about NExtSEEK workflows. For the agent to answer accurately, it needs access to the NExtSEEK documentation published at `https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/`. Loading the entire GitBook into the agent's context on every session would be wasteful: most conversations touch only a small slice of the docs, and per-session token cost scales with every user.

We need a way to expose the docs such that:

- The agent always knows NExtSEEK docs exist and how to find them.
- The agent only loads detail for the sections it actually needs.
- The solution does not add a runtime network dependency or startup latency.
- The solution does not introduce a new LLM dependency in the build/ingestion pipeline.
- The solution respects DMAC's existing architectural invariants (ADR-002 Docker-as-isolation-boundary, ADR-005 secrets-only-in-env, ADR-008 plugin taxonomy).

## 2. Non-Goals

- A retrieval plugin the agent invokes at query time. The built-in `Read` tool is sufficient; a search/grep/embedding tool is not.
- An MCP server. Same reason — unnecessary for this POC.
- Generalized "ingest any docs site" machinery. NExtSEEK-specific for the POC; generalize later only if a second doc source appears.
- Automatic doc-change detection on a cron. Manual-trigger only for the POC.
- Network-based fetch at `docker build` time or container start time.

## 3. Architecture

A **build-time ingestion tool** — not a plugin (ADR-008 reserves "plugin" for runtime CLI tools the agent invokes). Ingestion is a one-shot script run by a developer via a Makefile target when NExtSEEK docs may have changed. Its output is committed to git. The Docker image build copies the already-generated files.

```
developer runs: make ingest-nextseek-docs
  │
  ├─▶ fetch GitBook PDF (httpx)
  ├─▶ markitdown → raw markdown string
  ├─▶ sha256(raw) ─── compare with docs/nextseek/.content-hash
  │                   │
  │                   ├─ same ──▶ exit 0, print "no changes"
  │                   │
  │                   └─ different:
  │                        ├─▶ split by H1 → per-section .md files
  │                        ├─▶ regenerate docs/nextseek/README.md (TOC)
  │                        ├─▶ regenerate NExtSEEK block in CLAUDE.md
  │                        ├─▶ write new .content-hash
  │                        └─▶ exit 2 (signal: rebuild image)
  ▼
developer reviews git diff, commits, rebuilds image, pushes
```

### Repository Layout After Ingestion

```
dmac_assistant/
├── CLAUDE.md                        # baked into image as /app/CLAUDE.md
├── build-tools/
│   └── ingest_nextseek_docs/
│       ├── __main__.py              # CLI entry point
│       ├── fetch.py                 # httpx + markitdown (lifted from smart-form-tool)
│       ├── split.py                 # H1 splitter, slug generator
│       ├── toc.py                   # README.md + CLAUDE.md block generators
│       └── pyproject.toml           # uv-managed deps
├── docs/
│   └── nextseek/                    # baked into image as /app/docs/nextseek/
│       ├── .content-hash            # sha256 of last ingested raw markdown
│       ├── README.md                # generated: detailed TOC
│       ├── 01-welcome.md            # generated: per-H1 files
│       ├── 02-<slug>.md
│       └── ...
└── Makefile                         # exposes `ingest-nextseek-docs` target
```

### Runtime Behavior Inside the Container

1. `/app/CLAUDE.md` contains a 3–5 line NExtSEEK summary block so the agent knows the docs exist, has a quick top-level mental map, and knows the entry point for detail is `/app/docs/nextseek/README.md`.
2. When a user asks something NExtSEEK-related, the agent uses its built-in `Read` tool on `/app/docs/nextseek/README.md` to see the TOC.
3. The agent picks a section based on TOC descriptions and `Read`s the specific `/app/docs/nextseek/<slug>.md` file.
4. No runtime plugin invocation, no network call, no Bedrock call, no secret — just file reads on a path that's already baked into the image.

## 4. Pipeline Detail

### 4.1 Fetch

Lift `fetch_pdf_content` from `smart-form-tool/packages/core/src/smart_form_core/utils/nextseek_docs.py`. GitBook exposes a full-space PDF export:

```python
DEFAULT_DOC_URL = (
    "https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/"
    "~gitbook/pdf?limit=100"
)

with httpx.Client(timeout=120.0, follow_redirects=True) as client:
    response = client.get(DEFAULT_DOC_URL)
    response.raise_for_status()
pdf_bytes = response.content
```

The URL is overridable via `NEXTSEEK_DOC_URL` env var to ease testing with a fixture.

### 4.2 Parse

Lift `parse_pdf_with_markitdown`:

```python
from markitdown import MarkItDown
md = MarkItDown()
result = md.convert(temp_pdf_path)
raw_markdown = result.text_content
```

### 4.3 Change Detection

```python
content_hash = hashlib.sha256(raw_markdown.encode("utf-8")).hexdigest()
hash_path = Path("docs/nextseek/.content-hash")
if hash_path.exists() and hash_path.read_text().strip() == content_hash:
    print("no changes")
    sys.exit(0)
```

`--force` flag bypasses the early exit and always regenerates.

### 4.4 Split by H1

Parse the markdown line-by-line. A line matching `^# ` (single hash, space) opens a new section. All content between that H1 and the next H1 (or EOF) belongs to that section.

Filename slug rules:
- Lowercase the heading text.
- Replace any run of non-alphanumeric characters with a single `-`.
- Strip leading/trailing `-`.
- Prefix with a zero-padded 2-digit ordinal matching the section's order in the source: `01-welcome.md`, `02-getting-started.md`, etc. The ordinal preserves source order in `ls` output and makes the TOC easier to scan.
- If two H1s slug-collide after normalization, append `-2`, `-3`, etc.

Write each section's body (including the H1 line) to `docs/nextseek/<ordinal>-<slug>.md`. Before writing, delete any existing `docs/nextseek/*.md` files *except* `README.md` and `.content-hash` — stale section files from removed GitBook pages must not linger.

### 4.5 Per-Section One-Line Descriptions

For each section, the description is the first non-empty paragraph after the H1, truncated to ~140 characters at a word boundary if longer. A "paragraph" here is content up to the first blank line. If the section has no body text before the next heading (e.g., the page is only a list of sub-pages), the description falls back to the literal string `(section overview)`.

### 4.6 Generate `docs/nextseek/README.md`

```markdown
# NExtSEEK Documentation — Table of Contents

_Generated by build-tools/ingest_nextseek_docs. Do not edit by hand._

Source: https://koch-institute-mit.gitbook.io/mit-data-management-analysis-core/
Content hash: <first 12 chars of sha256>

## Sections

- **[Welcome](01-welcome.md)** — <one-line description>
- **[Getting Started](02-getting-started.md)** — <one-line description>
- ...
```

### 4.7 Update the NExtSEEK Block in `CLAUDE.md`

The baked CLAUDE.md contains a delimited block that the ingestion tool rewrites in place:

```markdown
<!-- BEGIN NEXTSEEK-DOCS (auto-generated) -->
## NExtSEEK Documentation

<first paragraph of the first H1 section from the GitBook — verbatim>

Top-level sections: Welcome, Getting Started, Sample Registration, ...

For detail, read `/app/docs/nextseek/README.md` first.
<!-- END NEXTSEEK-DOCS (auto-generated) -->
```

The tool reads CLAUDE.md, replaces the content between the markers, and writes it back. If the markers don't exist, the tool fails with a clear error instructing the developer to add the marker block manually (one-time setup).

The prose line is verbatim from the first H1 section's first paragraph — typically a GitBook "Welcome" or "Introduction" page written specifically to summarize the space. No LLM involvement.

### 4.8 Exit Codes

- `0` — no changes (hash matched).
- `1` — error (network failure, parse failure, etc.).
- `2` — changes written; image rebuild needed.

The `make ingest-nextseek-docs` target prints a clear message on exit 2 reminding the developer to review the diff, commit, and rebuild the image.

## 5. Components

| Module | Responsibility |
|---|---|
| `build-tools/ingest_nextseek_docs/fetch.py` | `fetch_pdf_content(url) -> bytes`; `parse_pdf_with_markitdown(bytes) -> str`. Lifted from smart-form-tool; no BAML, embeddings, clustering, or DB code. |
| `build-tools/ingest_nextseek_docs/split.py` | `split_by_h1(markdown) -> list[Section]` where `Section` has `ordinal`, `title`, `slug`, `body`, `description`. |
| `build-tools/ingest_nextseek_docs/toc.py` | `render_readme(sections, source_url, hash) -> str`; `render_claude_md_block(sections, overview_paragraph) -> str`; `update_claude_md(path, block)`. |
| `build-tools/ingest_nextseek_docs/__main__.py` | CLI: argparse (`--force`), orchestrate fetch → parse → hash → (early exit or regen), write files, choose exit code. |
| `Makefile` target `ingest-nextseek-docs` | `uv run python -m ingest_nextseek_docs ingest "$@"` with a clear post-run message on exit 2. |

Each module is independently testable. `fetch.py` is the only module with a network dep; the rest are pure functions over strings and paths.

## 6. Testing

- **Unit:** `split.py` tested against small synthetic markdown inputs covering: single H1, multiple H1s, H1 with only sub-headings (no body paragraph), duplicate-slug collision. `toc.py` tested against a fixed list of sections, asserting stable output (golden file).
- **Integration:** One end-to-end test with a fixture PDF committed to `tests/fixtures/` (a small ~5-page GitBook export). Test runs the full pipeline against the fixture, asserts the generated file tree, README.md content, and CLAUDE.md block match golden outputs. No live network.
- **Idempotency:** Run ingestion twice against the same fixture; second run must exit 0 with no file changes.

Do not write a test that hits the live GitBook URL — it would couple CI to an external service DMAC doesn't control.

## 7. Error Handling

- Network failure on fetch: log, exit 1. The existing generated files remain untouched.
- markitdown failure: log with the input file path preserved for debugging, exit 1.
- Zero H1 sections found in parsed markdown: log error indicating probable markitdown output change, exit 1. Do not silently write an empty TOC.
- Missing `<!-- BEGIN NEXTSEEK-DOCS -->` markers in CLAUDE.md: log error with one-line fix instructions, exit 1. Do not append a new block — that would double-inject on a second run.

## 8. Invariants Preserved

- **ADR-002 (Docker-as-isolation-boundary):** Docs are baked into the image. The container has no new mount, no new network route.
- **ADR-005 (secrets-only-in-env):** No secrets involved anywhere — the GitBook is public.
- **ADR-008 (plugin taxonomy):** This is a build-time tool, explicitly not a plugin. The runtime plugin directory stays untouched.
- **ADR-012 (`--dangerously-skip-permissions` safety):** The agent's new capability is reading baked-in files under `/app/docs/` — read-only data inside the container's already-bounded blast radius.

## 9. Open Items (POC Scope)

- **Who triggers ingestion and rebuild?** Manual for POC. A CI job or cron that diffs the GitBook weekly and opens a PR is a reasonable post-POC addition but out of scope here.
- **What if a section is very large (>50KB)?** Accept as-is for POC. The agent's `Read` handles large files fine. If in practice a single page dominates context, revisit with an H2 sub-split for that section only.
- **What about the IGB and internal BMC documentation that smart-form-tool also ingests?** Deferred. NExtSEEK only for POC. Adding more sources later is additive — new ingestion target, parallel output tree under `docs/`, additional CLAUDE.md block.
