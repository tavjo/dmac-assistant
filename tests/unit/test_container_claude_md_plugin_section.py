"""Plan B · T16 — container/CLAUDE.md hand-edit + auto-gen pipeline regression.

Tests cover:
  - Plan body line 2558-2569 hand-edit: the "Plugins available" section uses
    the new nextseek plugin paths.
  - D12 + D25 (single plugin, new plugin only): zero residual nextseek-api
    references anywhere in the file.
  - Auto-gen sentinel block structural integrity: BEGIN/END markers present.
  - Auto-gen pipeline regression: a hermetic orchestrator.ingest() call using
    fake fetcher/parser writes a non-empty block to a tmp CLAUDE.md (proves
    B16's hand-edit did NOT break the regeneration pipeline).

The test does NOT import chat_nextseek; no importorskip needed.
"""
from __future__ import annotations

import sys
import types
from pathlib import Path

# markitdown is intentionally scoped to the sibling build_tools uv project,
# not the root bridge/container environment. This root-level unit test only
# exercises orchestrator.ingest() with an injected parser, so provide the
# import-time symbol without pulling markitdown into the root project.
markitdown_stub = types.ModuleType("markitdown")
markitdown_stub.MarkItDown = object
sys.modules.setdefault("markitdown", markitdown_stub)

from build_tools.ingest_nextseek_docs import __main__ as orchestrator
from build_tools.ingest_nextseek_docs.constants import BEGIN_MARKER, END_MARKER

REPO_ROOT = Path(__file__).resolve().parents[2]
CLAUDE_MD = (REPO_ROOT / "container" / "CLAUDE.md").resolve()


def _seed_claude_md(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = CLAUDE_MD.read_text()
    begin_idx = text.find(BEGIN_MARKER)
    end_idx = text.find(END_MARKER)
    assert begin_idx >= 0 and end_idx >= 0, "production CLAUDE.md sentinels missing"
    # Preserve the human-authored B16 content while emptying only the generated block.
    seeded = text[:begin_idx] + f"{BEGIN_MARKER}\n{END_MARKER}" + text[end_idx + len(END_MARKER):]
    path.write_text(seeded)


def _fake_fetcher(url: str) -> bytes:
    assert url == "https://fake.example/nextseek-docs"
    return b"fake-bytes"


def _fake_parser(source: bytes) -> str:
    assert source == b"fake-bytes"
    return "# Welcome\n\nIntro paragraph.\n\n# Submit Data\n\nSubmission guidance.\n"


def test_no_nextseek_api_references_in_container_claude_md():
    """D12 + D25: image v3 ships only the new nextseek plugin. The legacy
    nextseek-api name MUST NOT appear anywhere in container/CLAUDE.md.
    Catches any place a stale path reference was missed during the rename."""
    text = CLAUDE_MD.read_text()
    occurrences = text.count("nextseek-api")
    assert occurrences == 0, (
        f"D12 + D25 BREACH: container/CLAUDE.md contains {occurrences} "
        f"reference(s) to the legacy `nextseek-api` plugin name. The image "
        f"ships only the new `nextseek` plugin; container/CLAUDE.md MUST be "
        f"updated to match. Search for and replace every `nextseek-api` "
        f"occurrence with the appropriate `nextseek` form. (Expected zero; "
        f"got {occurrences}.)"
    )


def test_plugins_section_uses_new_paths():
    """The "Plugins available" section names the four canonical new-plugin
    artifacts at the correct paths. Plan body line 2558-2569 verbatim."""
    text = CLAUDE_MD.read_text()
    expected_strings = [
        # The plugin name (in the bullet header):
        "**`nextseek`**",
        # Skill manifest path:
        "/app/plugins/nextseek/skills/nextseek/SKILL.md",
        # Slash command path:
        "/app/plugins/nextseek/commands/nextseek.md",
        # Code path:
        "/app/plugins/nextseek/bin/",
        # Cached catalogs path:
        "/app/plugins/nextseek/context/",
        # The "read SKILL.md first" guidance:
        "read the SKILL.md first",
        # The cred translation note (from §6.1; documents B15's behavior):
        "translated to `API_USER` / `API_PASS` by the container entrypoint",
    ]
    missing = [s for s in expected_strings if s not in text]
    assert not missing, (
        f"container/CLAUDE.md is missing expected strings from the new "
        f"`nextseek` plugin section: {missing}. The hand-edit at lines 5-15 "
        f"must include every plan-body §B16.2 verbatim element."
    )


def test_auto_gen_sentinel_block_intact():
    """The auto-gen sentinel block must remain present + structurally sound.
    BEGIN must precede END. Content between them MAY be empty (pre-regen)
    or non-empty (post-regen) — both are acceptable; the test only enforces
    structural integrity."""
    text = CLAUDE_MD.read_text()
    begin_idx = text.find("<!-- BEGIN NEXTSEEK-DOCS")
    end_idx = text.find("<!-- END NEXTSEEK-DOCS")
    assert begin_idx >= 0, (
        "container/CLAUDE.md is missing the BEGIN NEXTSEEK-DOCS sentinel — "
        "the auto-gen pipeline cannot find an insertion point."
    )
    assert end_idx >= 0, (
        "container/CLAUDE.md is missing the END NEXTSEEK-DOCS sentinel — "
        "the auto-gen pipeline cannot find an insertion endpoint."
    )
    assert begin_idx < end_idx, (
        f"BEGIN sentinel (idx {begin_idx}) must precede END sentinel "
        f"(idx {end_idx})."
    )


def test_ingest_pipeline_produces_non_empty_block_hermetically(tmp_path):
    """Regression: the docs-ingest pipeline writes a non-empty generated block
    to tmp paths with fake fetcher/parser inputs. This never touches production
    docs/nextseek/, never touches production container/CLAUDE.md, and never
    fetches the live GitBook URL."""
    docs_dir = tmp_path / "docs" / "nextseek"
    tmp_claude = tmp_path / "container" / "CLAUDE.md"
    _seed_claude_md(tmp_claude)

    rc = orchestrator.ingest(
        docs_dir=docs_dir,
        claude_md_path=tmp_claude,
        doc_url="https://fake.example/nextseek-docs",
        force=True,
        fetcher=_fake_fetcher,
        parser=_fake_parser,
    )
    assert rc == orchestrator.EXIT_CHANGES_WRITTEN

    new_text = tmp_claude.read_text()
    begin_idx = new_text.find(BEGIN_MARKER)
    end_idx = new_text.find(END_MARKER)
    assert begin_idx >= 0 and end_idx >= 0, (
        "sentinels missing from regenerated tmp file"
    )
    block_content = new_text[begin_idx:end_idx]
    # Strip the BEGIN line itself; assert the remaining body has at least one
    # non-whitespace character (i.e., the auto-gen wrote SOMETHING).
    body_after_begin = block_content.split("\n", 1)[1] if "\n" in block_content \
                                                       else ""
    assert body_after_begin.strip(), (
        f"auto-gen sentinel block is EMPTY after running ingest_nextseek_docs. "
        f"Either docs/nextseek/ is empty (verify with `ls docs/nextseek/`), "
        f"or the pipeline silently failed to write content. Block was: "
        f"{block_content!r}"
    )
