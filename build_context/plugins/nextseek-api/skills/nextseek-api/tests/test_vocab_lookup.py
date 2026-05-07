"""Tests for scripts/vocab_lookup.py — list/search/resolve against cached entity tree."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

import vocab_lookup
from vocab_lookup import main
from lib.entity_tree_schemas import EntityTree, NodeAttribute


def _write_tree(base: Path, env: str, nodes: list[dict]) -> Path:
    env_dir = base / env
    env_dir.mkdir(parents=True, exist_ok=True)
    tree = EntityTree(
        session_id="sess-1",
        fetched_at=datetime.now(timezone.utc),
        nodes=[NodeAttribute.model_validate(n) for n in nodes],
        edges=[],
    )
    p = env_dir / "entity_tree.json"
    p.write_text(tree.model_dump_json())
    return p


@pytest.fixture
def cache_base(tmp_path: Path) -> Path:
    return tmp_path / "cache"


@pytest.fixture
def populated_tree(cache_base: Path) -> Path:
    _write_tree(
        cache_base,
        "prod",
        [
            {
                "node": "D.SEQ",
                "id": 1,
                "description": "DNA sequencing sample",
                "clade": "seq",
                "metadata_fields": "platform;depth",
            },
            {
                "node": "TUM",
                "id": 2,
                "description": "Tumor sample",
                "clade": "bio",
                "metadata_fields": "site",
            },
            {
                "node": "RNA",
                "id": 3,
                "description": "RNA sample",
                "clade": "seq",
                "metadata_fields": "",
            },
        ],
    )
    return cache_base


def test_list_all_nodes(populated_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["list", "--env", "prod"], cache_base=populated_tree)
    assert rc == 0
    out = capsys.readouterr().out
    assert "D.SEQ" in out
    assert "TUM" in out
    assert "RNA" in out


def test_list_filters_by_clade(
    populated_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["list", "--env", "prod", "--clade", "seq"], cache_base=populated_tree)
    assert rc == 0
    out = capsys.readouterr().out
    assert "D.SEQ" in out
    assert "RNA" in out
    assert "TUM" not in out


def test_search_substring(populated_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["search", "tumor", "--env", "prod"], cache_base=populated_tree)
    assert rc == 0
    out = capsys.readouterr().out
    assert "TUM" in out
    assert "D.SEQ" not in out


def test_resolve_exact(populated_tree: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = main(["resolve", "D.SEQ", "--env", "prod"], cache_base=populated_tree)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert parsed["node"] == "D.SEQ"
    assert parsed["id"] == 1


def test_resolve_ambiguous_returns_top_n(
    populated_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["resolve", "sample", "--env", "prod"], cache_base=populated_tree)
    assert rc == 0
    parsed = json.loads(capsys.readouterr().out)
    assert isinstance(parsed, list)
    assert len(parsed) >= 1


def test_resolve_no_match(
    populated_tree: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["resolve", "zzzz_nomatch", "--env", "prod"], cache_base=populated_tree)
    assert rc == 1
    err = capsys.readouterr().err
    assert "no vocab match" in err


def test_resolve_fails_cleanly_if_cache_missing(
    cache_base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["resolve", "X", "--env", "prod"], cache_base=cache_base)
    assert rc != 0
    err = capsys.readouterr().err
    assert "entity tree cache missing" in err
    assert "nextseek-init" in err


def test_list_fails_cleanly_if_cache_missing(
    cache_base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["list", "--env", "prod"], cache_base=cache_base)
    assert rc != 0
    err = capsys.readouterr().err
    assert "entity tree cache missing" in err


def test_search_fails_cleanly_if_cache_missing(
    cache_base: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    rc = main(["search", "foo", "--env", "prod"], cache_base=cache_base)
    assert rc != 0


def test_main_defaults_to_resolve_plugin_cache_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """When cache_base is None, _load_tree falls back to resolve_plugin_cache_base()."""
    fake_base = tmp_path / "fallback"
    _write_tree(fake_base, "prod", [{"node": "Z", "id": 9, "description": "z"}])
    monkeypatch.setattr(vocab_lookup, "resolve_plugin_cache_base", lambda: fake_base)
    rc = main(["list", "--env", "prod"])
    assert rc == 0
    assert "Z" in capsys.readouterr().out


def test_main_no_subcommand_errors(capsys: pytest.CaptureFixture[str]) -> None:
    """Missing subcommand triggers argparse error (non-zero rc)."""
    rc = main([])
    assert rc != 0
