"""
Structural tests for skills/nextseek-api/SKILL.md.

These assert the skill file has:
1. Valid YAML frontmatter with name and description.
2. Trigger keywords in the description so Claude Code auto-loads the skill.
3. Every bin/ shim name mentioned in the body.
4. AskUserQuestion referenced in the write-safety section.
5. At least 3 example transcripts headed '## Example 1/2/3'.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml


# skills/nextseek-api/tests/test_skill_md.py — 4 parents up = plugin root
PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
SKILL_FILE = PLUGIN_ROOT / "skills" / "nextseek-api" / "SKILL.md"

REQUIRED_SHIM_NAMES = [
    "nextseek-init",
    "nextseek-spec",
    "nextseek-validate",
    "nextseek-exec",
    "nextseek-call",
    "nextseek-vocab",
    "nextseek-session",
]

REQUIRED_TRIGGER_SUBSTRINGS = [
    "/nextseek-api",
    "NExtSEEK",
]


def _split_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---\n"):
        raise ValueError("File does not start with YAML frontmatter delimiter '---'")
    match = re.search(r"\n---\n", content[4:])
    if not match:
        raise ValueError("Closing '---' frontmatter delimiter not found")
    fm_raw = content[4 : 4 + match.start()]
    body = content[4 + match.end() :]
    fm = yaml.safe_load(fm_raw) or {}
    return fm, body


@pytest.fixture
def skill_frontmatter_and_body() -> tuple[dict, str]:
    assert SKILL_FILE.is_file(), f"{SKILL_FILE} does not exist"
    content = SKILL_FILE.read_text()
    return _split_frontmatter(content)


# ----- Test 1 -----
def test_frontmatter_valid(skill_frontmatter_and_body) -> None:
    """Frontmatter must have name='nextseek-api' and a non-empty description."""
    fm, _body = skill_frontmatter_and_body
    assert fm.get("name") == "nextseek-api", (
        f"name must be 'nextseek-api', got {fm.get('name')!r}"
    )
    assert isinstance(fm.get("description"), str), "description must be a string"
    assert len(fm["description"].strip()) >= 100, (
        f"description too short ({len(fm['description'].strip())} chars); "
        "needs rich trigger keywords for auto-invocation"
    )


# ----- Test 2 -----
def test_description_has_trigger_keywords(skill_frontmatter_and_body) -> None:
    """Description must include keywords that trigger skill auto-load."""
    fm, _body = skill_frontmatter_and_body
    desc = fm["description"]
    for trigger in REQUIRED_TRIGGER_SUBSTRINGS:
        assert trigger in desc, f"description missing trigger substring: {trigger!r}"
    # Also must mention at least 2 of: query, sample, project, study, lookup, retrieve
    query_words = ["query", "sample", "project", "study", "look up", "retrieve"]
    hits = sum(1 for w in query_words if w.lower() in desc.lower())
    assert hits >= 2, (
        f"description should mention at least 2 query-related words "
        f"from {query_words}; got {hits}"
    )


# ----- Test 3 -----
def test_all_scripts_referenced(skill_frontmatter_and_body) -> None:
    """Every bin/ shim name must appear at least once in the body."""
    _fm, body = skill_frontmatter_and_body
    for shim in REQUIRED_SHIM_NAMES:
        assert shim in body, f"Shim name not referenced in body: {shim!r}"


# ----- Test 4 -----
def test_askuserquestion_referenced_for_writes(skill_frontmatter_and_body) -> None:
    """The body must mention AskUserQuestion in the write-safety context."""
    _fm, body = skill_frontmatter_and_body
    assert "AskUserQuestion" in body, (
        "Body must reference AskUserQuestion (write-safety instruction)"
    )
    # Scope: the AskUserQuestion reference must live near a write-safety keyword
    askq_positions = [m.start() for m in re.finditer(r"AskUserQuestion", body)]
    write_context_regex = re.compile(
        r"write|mutat|confirm|POST|PATCH|DELETE|non-GET|safety",
        re.IGNORECASE,
    )
    found_context = False
    for pos in askq_positions:
        window = body[max(0, pos - 500) : pos + 500]
        if write_context_regex.search(window):
            found_context = True
            break
    assert found_context, (
        "AskUserQuestion mention must be near write-safety keywords "
        "(write/mutate/POST/PATCH/DELETE/non-GET/safety)"
    )


# ----- Test 5 -----
def test_at_least_three_example_transcripts(skill_frontmatter_and_body) -> None:
    """Body must contain 3 example transcript headers."""
    _fm, body = skill_frontmatter_and_body
    # Accept '## Example 1', '## Example 1 —', '## Example 1:', '### Example 1'
    example_headers = re.findall(
        r"^#{2,3}\s+Example\s+([123])\b",
        body,
        re.MULTILINE,
    )
    assert set(example_headers) >= {"1", "2", "3"}, (
        f"Body must contain '## Example 1', '## Example 2', '## Example 3' "
        f"headers; found: {example_headers}"
    )


# ----- Test 6 (DD-4) -----
def test_skill_md_has_no_nextseek_get_reference() -> None:
    """DD-4 (task-06a): SKILL.md must not mention the old nextseek-get shim name."""
    content = SKILL_FILE.read_text()
    assert "nextseek-get" not in content, (
        "DD-4: SKILL.md must not reference nextseek-get after the rename to nextseek-spec"
    )


# ----- Task-09 structural additions -----


def _read_body() -> str:
    content = SKILL_FILE.read_text()
    _fm, body = _split_frontmatter(content)
    return body


def test_skill_md_has_quick_start_section() -> None:
    """DD-17: opening section is a scannable Quick Start (one-page bootstrap recipe)."""
    body = _read_body()
    assert re.search(
        r"^## (Quick Start|How to answer a question)\b", body, re.MULTILINE
    ), "Body must contain a '## Quick Start' (or 'How to answer a question') section"


def test_skill_md_has_two_worked_example_sections() -> None:
    """Task-09: at least two H2 'Example N' sections (DD-17 inlined transcripts)."""
    body = _read_body()
    examples = re.findall(r"^## Example\s+\d", body, re.MULTILINE)
    assert len(examples) >= 2, (
        f"Body must contain at least two '## Example N' sections; found {len(examples)}"
    )


def test_skill_md_documents_env_var_precedence() -> None:
    """Env URL precedence chain must be documented in NEXTSEEK > API_BASE_URL > BASE_URL order."""
    body = _read_body()
    assert "NEXTSEEK_BASE_URL" in body
    assert "API_BASE_URL" in body
    assert "BASE_URL" in body
    assert re.search(
        r"NEXTSEEK_BASE_URL.*API_BASE_URL.*BASE_URL", body, re.S
    ), "Body must list URL env vars in precedence order"
    assert "USE_DEV_API" in body, "USE_DEV_API hard-override must be documented"


def test_skill_md_has_advanced_search_entity_tree_section() -> None:
    """advanced_search section must point to entity_tree.json AND nextseek-vocab resolve."""
    body = _read_body()
    assert re.search(
        r"^## .*advanced_search", body, re.MULTILINE | re.IGNORECASE
    ), "Body must contain a section header about advanced_search"
    assert "entity_tree.json" in body
    assert "nextseek-vocab resolve" in body


def test_skill_md_has_pagination_section() -> None:
    """Pagination section must mention page[size] / page[number] semantics."""
    body = _read_body()
    assert re.search(r"^## .*[Pp]agination", body, re.MULTILINE)
    assert "page[size]" in body or "page[number]" in body
    assert "--auto-paginate" in body


def test_skill_md_documents_cache_paths() -> None:
    """Cache-paths table must list the 4 v2 cache files under the resolved base."""
    body = _read_body()
    for fragment in (
        "session.json",
        "endpoints_minimal.json",
        "endpoints_full/",
        "entity_tree.json",
    ):
        assert fragment in body, f"Cache file fragment missing from body: {fragment!r}"
    assert re.search(
        r"~/\.cache/nextseek-api/v2/\{?env\}?/?", body
    ), "Cache base path must include the v2 generation segment"


def test_skill_md_json_examples_use_snake_case() -> None:
    """All RequestSpec JSON examples in the body must use snake_case keys (no camelCase)."""
    body = _read_body()
    # Inside fenced JSON blocks: require no operationId / pathParams / queryParams / requestBody
    json_blocks = re.findall(r"```json\n(.*?)\n```", body, re.DOTALL)
    forbidden = ("operationId", "pathParams", "queryParams", "requestBody")
    for block in json_blocks:
        for token in forbidden:
            assert token not in block, (
                f"JSON example contains camelCase key {token!r}; should be snake_case"
            )


def test_skill_md_documents_env_file_flag() -> None:
    """All shims accept --env-file PATH; document it once."""
    body = _read_body()
    assert "--env-file" in body, "Body must mention --env-file flag"


def test_skill_md_documents_clear_cache_flag() -> None:
    """--clear-cache flag on nextseek-init must be documented."""
    body = _read_body()
    assert "--clear-cache" in body
