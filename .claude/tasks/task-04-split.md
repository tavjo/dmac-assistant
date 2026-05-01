# task-04-split

## 1. Overview

Implement a fence-aware H1 splitter that consumes the markdown string produced by `parse_source_to_markdown` and returns a list of `Section` dataclasses, each representing one top-level GitBook page.

**Key invariants:**
- A line matching `^# \S` (H1, at least one non-whitespace char) **outside** a fenced code block opens a new section.
- `#` lines **inside** a fenced code block (between opening and closing ``` ` ``` fences) are ignored.
- Section ordinals are contiguous starting at 1 in source order.
- Section slugs are unique across the returned list. Collisions resolve by appending `-2`, `-3`, ...
- Per-section descriptions are the first non-empty paragraph (up to first blank line) after the H1, truncated at a word boundary to at most 140 chars, with `…` appended if truncated. A section with no body paragraph before the next heading gets the literal `"(section overview)"` description.
- Module is pure-Python, stdlib-only. No `httpx`, `markitdown`, or `pydantic` imports.

## 2. Dependencies

- **Predecessor tasks**: T2 (package exists).
- **Artifacts consumed**: `build_tools/ingest_nextseek_docs/__init__.py` (empty package).
- **External packages**: none.

## 3. Key Design Decisions

- **D4**: Split by H1 — *Constraint*: only `^# \S` opens a section. H2–H6 are section content, not boundaries.
- **D5**: Description = first paragraph, truncated, no LLM — *Constraint*: implement a word-boundary truncator; do not call any model.
- **D8**: Fence-aware — *Constraint*: maintain a `inside_fence` boolean; toggle on lines matching `^\s*```` (three backticks at line start, possibly indented). `#` lines while `inside_fence=True` never open sections.
- **R8/R10 resolution**: fence-aware splitter — *Constraint*: T4's Case F test directly exercises the fence-awareness and is a release-blocker.
- **Coverage floor**: 95%.

## 4. TDD Implementation Order

**Coverage target**: 95% for `split.py`.

**Step 1 — RED (empty input)**: test `split_by_h1("") == []`.
**Step 2 — GREEN**: implement skeleton that handles empty input.

**Step 3 — RED (single H1)**: test single section has correct ordinal, title, slug, body, description.
**Step 4 — GREEN**: line-based splitter.

**Step 5 — RED (three H1s)**: test multi-section ordering and bodies.
**Step 6 — GREEN**: refactor loop.

**Step 7 — RED (slug collision)**: test two colliding-slug titles → `-2` suffix.
**Step 8 — GREEN**: add slug-uniqueness helper.

**Step 9 — RED (empty description)**: test section with only sub-heading before next H1 → `"(section overview)"`.
**Step 10 — GREEN**: add description fallback.

**Step 11 — RED (fence-aware)**: test fenced code block containing `# comment` does NOT open a new section.
**Step 12 — GREEN**: add `inside_fence` state machine.

**Step 13 — RED (description truncation)**: 200-char description with word boundary at 135 → truncated to 135 + `…`.
**Step 14 — GREEN**: add truncator.

**Step 15 — VERIFY**:
  ```bash
  uv run pytest tests/unit/test_split.py -q
  uv run pytest --cov=build_tools.ingest_nextseek_docs.split \
      --cov-report=term-missing tests/unit/test_split.py
  ```

## 5. Behavioral Contract (Tests)

### `tests/unit/test_split.py`

```python
"""Unit tests for build_tools.ingest_nextseek_docs.split."""
from __future__ import annotations

import pytest

from build_tools.ingest_nextseek_docs.split import Section, split_by_h1


def test_split_empty_returns_empty_list() -> None:
    assert split_by_h1("") == []


def test_split_whitespace_only_returns_empty_list() -> None:
    assert split_by_h1("   \n\n  \n") == []


def test_split_single_h1_fields() -> None:
    md = "# Welcome\n\nIntro paragraph for welcome.\n\nMore content.\n"
    result = split_by_h1(md)
    assert len(result) == 1
    s = result[0]
    assert s.ordinal == 1
    assert s.title == "Welcome"
    assert s.slug == "welcome"
    assert "Intro paragraph for welcome." in s.body
    assert s.body.startswith("# Welcome")
    assert s.description == "Intro paragraph for welcome."


def test_split_three_h1s_have_contiguous_ordinals() -> None:
    md = (
        "# A\n\nA body.\n"
        "# B\n\nB body.\n"
        "# C\n\nC body.\n"
    )
    result = split_by_h1(md)
    assert [s.ordinal for s in result] == [1, 2, 3]
    assert [s.title for s in result] == ["A", "B", "C"]
    assert [s.slug for s in result] == ["a", "b", "c"]


def test_split_slug_collision_appends_numeric_suffix() -> None:
    md = (
        "# Hello World!\n\nFirst.\n"
        "# Hello World\n\nSecond.\n"
        "# Hello World?\n\nThird.\n"
    )
    result = split_by_h1(md)
    assert [s.slug for s in result] == [
        "hello-world",
        "hello-world-2",
        "hello-world-3",
    ]


def test_split_section_without_body_uses_fallback_description() -> None:
    md = (
        "# Overview\n"
        "## Subsection\n"
        "Content here.\n"
        "# Next Section\n\nReal intro.\n"
    )
    result = split_by_h1(md)
    assert result[0].description == "(section overview)"
    assert result[1].description == "Real intro."


def test_split_ignores_h1_inside_fenced_code_block() -> None:
    md = (
        "# Real Heading\n\n"
        "Intro.\n\n"
        "```bash\n"
        "# this is a shell comment\n"
        "echo hi\n"
        "```\n\n"
        "More content after fence.\n"
    )
    result = split_by_h1(md)
    assert len(result) == 1, (
        f"fence-aware split should yield 1 section, got {len(result)}: "
        f"{[s.title for s in result]}"
    )
    assert result[0].title == "Real Heading"
    assert "# this is a shell comment" in result[0].body


def test_split_description_truncates_at_word_boundary() -> None:
    long_para = (
        "Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu "
        "nu xi omicron pi rho sigma tau upsilon phi chi psi omega one two "
        "three four five six seven eight nine ten."
    )
    md = f"# Long Title\n\n{long_para}\n"
    result = split_by_h1(md)
    desc = result[0].description
    assert len(desc) <= 141  # 140 + potential ellipsis
    assert desc.endswith("…"), f"expected ellipsis, got: {desc!r}"
    # Truncation lands at a word boundary — no broken words
    assert " " in desc or desc == "…"
    stripped = desc.rstrip("…").rstrip()
    assert long_para.startswith(stripped), (
        "truncated description must be a prefix of the original paragraph"
    )


def test_split_description_under_140_chars_not_truncated() -> None:
    md = "# Short\n\nShort paragraph.\n"
    result = split_by_h1(md)
    assert result[0].description == "Short paragraph."
    assert not result[0].description.endswith("…")


def test_split_slug_strips_nonalnum_runs() -> None:
    md = "# Foo -- Bar\n\nBody.\n"
    result = split_by_h1(md)
    assert result[0].slug == "foo-bar"


def test_split_ignores_h2_h3_as_section_boundaries() -> None:
    md = (
        "# Root\n\nRoot intro.\n\n"
        "## Sub\n\nSub body.\n\n"
        "### Subsub\n\nMore.\n"
    )
    result = split_by_h1(md)
    assert len(result) == 1
    assert "## Sub" in result[0].body
    assert "### Subsub" in result[0].body


def test_split_returns_section_dataclass_instances() -> None:
    result = split_by_h1("# A\n\nBody.\n")
    assert isinstance(result[0], Section)
```

## 6. Reference Implementation

### `build_tools/ingest_nextseek_docs/split.py` (new)

```python
"""Fence-aware H1 splitter for GitBook-derived markdown."""
from __future__ import annotations

import re
from dataclasses import dataclass

_H1_RE = re.compile(r"^#\s+(\S.*)$")
_FENCE_RE = re.compile(r"^\s*```")
_SLUG_NONALNUM_RE = re.compile(r"[^a-z0-9]+")

MAX_DESCRIPTION_LEN = 140
EMPTY_DESCRIPTION_FALLBACK = "(section overview)"


@dataclass
class Section:
    """One top-level GitBook page."""

    ordinal: int
    title: str
    slug: str
    body: str
    description: str


def split_by_h1(markdown: str) -> list[Section]:
    """Split `markdown` into sections at H1 boundaries, ignoring fenced code.

    Args:
        markdown: Source markdown (typically produced by `parse_source_to_markdown`).

    Returns:
        List of `Section` dataclasses in source order. Ordinals start at 1 and
        are contiguous. Slugs are unique across the list.
    """
    if not markdown.strip():
        return []

    lines = markdown.splitlines(keepends=True)
    inside_fence = False
    pending_title: str | None = None
    pending_body_lines: list[str] = []
    raw_sections: list[tuple[str, str]] = []  # (title, body_text_with_leading_h1)

    def flush() -> None:
        if pending_title is not None:
            body_text = "".join(pending_body_lines)
            raw_sections.append((pending_title, body_text))

    for line in lines:
        if _FENCE_RE.match(line):
            inside_fence = not inside_fence
            if pending_title is not None:
                pending_body_lines.append(line)
            continue
        if not inside_fence:
            m = _H1_RE.match(line.rstrip("\n"))
            if m:
                flush()
                pending_title = m.group(1).strip()
                pending_body_lines = [line]
                continue
        if pending_title is not None:
            pending_body_lines.append(line)
    flush()

    sections: list[Section] = []
    used_slugs: dict[str, int] = {}
    for i, (title, body) in enumerate(raw_sections, start=1):
        slug = _slugify(title, used_slugs)
        description = _extract_description(body)
        sections.append(
            Section(
                ordinal=i,
                title=title,
                slug=slug,
                body=body,
                description=description,
            )
        )
    return sections


def _slugify(title: str, used_slugs: dict[str, int]) -> str:
    base = _SLUG_NONALNUM_RE.sub("-", title.lower()).strip("-")
    if not base:
        base = "section"
    candidate = base
    suffix = 2
    while candidate in used_slugs:
        candidate = f"{base}-{suffix}"
        suffix += 1
    used_slugs[candidate] = 1
    return candidate


def _extract_description(body_with_h1: str) -> str:
    """Return the first non-empty paragraph after the H1, truncated."""
    # Drop the H1 line itself; look for the first paragraph thereafter.
    lines = body_with_h1.splitlines()
    # Skip the H1 line and any immediately-following blank lines.
    i = 1
    while i < len(lines) and not lines[i].strip():
        i += 1
    # Collect lines until the next blank line OR the next heading line.
    para_lines: list[str] = []
    while i < len(lines):
        line = lines[i]
        if not line.strip():
            break
        if line.lstrip().startswith("#"):
            # Heading before any paragraph — this section has no body text.
            break
        para_lines.append(line.strip())
        i += 1
    paragraph = " ".join(para_lines).strip()
    if not paragraph:
        return EMPTY_DESCRIPTION_FALLBACK
    return _truncate_at_word_boundary(paragraph, MAX_DESCRIPTION_LEN)


def _truncate_at_word_boundary(text: str, max_len: int) -> str:
    if len(text) <= max_len:
        return text
    head = text[:max_len]
    last_space = head.rfind(" ")
    if last_space <= 0:
        return head.rstrip() + "…"
    return head[:last_space].rstrip() + "…"
```

## 7. Modified Files (exact diffs)

None — new file.

## 8. Verification

```bash
# New tests pass
uv run pytest tests/unit/test_split.py -q

# Coverage
uv run pytest --cov=build_tools.ingest_nextseek_docs.split \
    --cov-report=term-missing --cov-fail-under=95 tests/unit/test_split.py

# No forbidden deps
uv run python -c "
import ast, sys
tree = ast.parse(open('build_tools/ingest_nextseek_docs/split.py').read())
for node in ast.walk(tree):
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        names = [n.name for n in getattr(node, 'names', [])]
        if isinstance(node, ast.ImportFrom):
            mod = (node.module or '')
            assert not mod.startswith(('httpx', 'markitdown', 'pydantic')), mod
        for n in names:
            assert not n.startswith(('httpx', 'markitdown', 'pydantic')), n
print('split.py import hygiene ok')
"

# Full suite
uv run pytest -q
```

**Expected test count**: 11 new tests in `test_split.py`.

**Expected coverage**: ≥ 95% for `split.py` (targeting ~100%).

## 9. Implementation Notes

- `_H1_RE` uses `\S.*` so `# ` (hash-space-end) does NOT open a section — the title must start with a non-whitespace char.
- `_FENCE_RE` matches fences with leading whitespace (e.g., indented code blocks inside blockquotes). This is deliberate — markitdown may emit such.
- Body text includes the H1 line itself so downstream `render_readme` can render it faithfully. Do not strip the H1 from `Section.body`.
- Description extraction stops at the first blank line OR the first `#`-prefixed line, whichever comes first. This avoids accidentally pulling an H2/H3 heading into the description.
- Slug generation lowercases first, then replaces non-alphanumeric runs with `-`, then strips leading/trailing `-`. Edge case: a title of all punctuation (`"!!!"`) slugifies to empty; we fall back to `"section"`.

## 10. Worktree & Branch

- **Branch**: `task/04-split`
- **Worktree**: `.claude/worktrees/task-04-split/`
- **Merge target**: `ultraplan/nextseek-docs-ingestion`
- **Merge condition**: all Section 8 checks pass; `split.py` coverage ≥ 95%.

## Spec Risk Notes (Phase 4)

**Status**: vetted.

- **Untested edge in `_truncate_at_word_boundary`**: the `if last_space <= 0: return head.rstrip() + "…"` branch handles descriptions with no word boundary in the first 140 chars (e.g., a single enormous URL). Not covered by the 11 tests. The line is a single `return` so missing it costs ~1 of ~40 statements → ~2.5% coverage loss. Still well above 95% floor. If the actual report shows <95%, add `test_split_description_no_word_boundary_truncates_hard` with input `"a" * 200` as a single body line.
- **Empty-title pathology**: a heading like `# ` with no title text would slugify to empty → the impl falls back to `"section"` (see `_slugify` logic). Not directly tested. Since the H1 regex requires `^#\s+\S` (non-whitespace after `#`), this case can only be reached if a future caller passes hand-crafted markdown that bypasses the regex — e.g., if `split_by_h1` is called with pre-split section text. For now, the regex gates this out of the pipeline. Safe.
- **Ordinal gap risk**: the impl assigns ordinals contiguously 1..N based on source order. If a future caller filters sections post-split, ordinals remain contiguous but may not reflect the filter. This is the caller's responsibility. Documented implicitly by the `i, (title, body) in enumerate(...)` pattern.
