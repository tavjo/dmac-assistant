"""Tests for src/dmac_assistant/router/capabilities.py."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dmac_assistant.config import ConfigError
from dmac_assistant.router.baml_client.types import RouteCapability, TaskFamily
from dmac_assistant.router.capabilities import load_capabilities


REPO_ROOT = Path(__file__).resolve().parent.parent.parent.parent
DEFAULT_JSON_PATH = REPO_ROOT / "build_context" / "route_capabilities.json"


def test_default_path_loads_two_routes():
    """The committed build_context/route_capabilities.json loads cleanly."""
    routes = load_capabilities()
    assert isinstance(routes, list)
    assert len(routes) == 2
    assert all(isinstance(r, RouteCapability) for r in routes)


def test_default_route_names_match_baml_enum_aliases():
    """The route_name values must match the BAML Route enum @alias strings."""
    routes = load_capabilities()
    names = {r.route_name for r in routes}
    assert names == {"nextseek_query", "container_cc"}


def test_default_routes_have_non_empty_tools():
    routes = load_capabilities()
    for r in routes:
        assert isinstance(r.tools, list)
        assert len(r.tools) >= 1
        assert all(isinstance(t, str) and t for t in r.tools)


def test_default_routes_have_task_families_with_examples():
    routes = load_capabilities()
    for r in routes:
        assert isinstance(r.task_families, list)
        assert len(r.task_families) >= 1
        for tf in r.task_families:
            assert isinstance(tf, TaskFamily)
            assert tf.name
            assert tf.description
            assert isinstance(tf.example_queries, list)
            assert len(tf.example_queries) >= 1


def test_default_json_is_byte_equal_to_committed_file(tmp_path: Path):
    """Sanity-check encoding and parseability of the committed JSON file."""
    raw = DEFAULT_JSON_PATH.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf"), "JSON must not have a UTF-8 BOM"
    parsed = json.loads(raw.decode("utf-8"))
    assert "routes" in parsed
    assert len(parsed["routes"]) == 2


def test_env_override_takes_precedence(tmp_path: Path, monkeypatch):
    override = tmp_path / "custom_capabilities.json"
    minimal = {
        "routes": [
            {
                "route_name": "custom_route",
                "description": "Custom route for the override test.",
                "tools": ["alpha"],
                "task_families": [
                    {
                        "name": "fam_a",
                        "description": "Family A.",
                        "example_queries": ["example query"],
                    }
                ],
            }
        ]
    }
    override.write_text(json.dumps(minimal), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(override))
    routes = load_capabilities()
    assert len(routes) == 1
    assert routes[0].route_name == "custom_route"


def test_explicit_path_argument_overrides_env_and_default(
    tmp_path: Path, monkeypatch
):
    """Passing path= takes precedence over the env var and default path."""
    explicit = tmp_path / "explicit_capabilities.json"
    minimal = {
        "routes": [
            {
                "route_name": "explicit_route",
                "description": "From explicit path argument.",
                "tools": ["t"],
                "task_families": [
                    {"name": "f", "description": "d", "example_queries": ["q"]}
                ],
            }
        ]
    }
    explicit.write_text(json.dumps(minimal), encoding="utf-8")
    bogus = tmp_path / "bogus.json"
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bogus))
    routes = load_capabilities(path=explicit)
    assert len(routes) == 1
    assert routes[0].route_name == "explicit_route"


def test_missing_file_raises_config_error(tmp_path: Path, monkeypatch):
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(missing))
    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        load_capabilities()


def test_unreadable_file_raises_config_error(tmp_path: Path, monkeypatch):
    """Exercise the OSError wrapper without relying on chmod semantics."""
    bad = tmp_path / "exists_but_unreadable.json"
    bad.write_text("{}", encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))

    def _raise_oserror(*args, **kwargs):
        raise OSError("permission denied (simulated)")

    monkeypatch.setattr(Path, "read_text", _raise_oserror)
    with pytest.raises(ConfigError, match="not readable"):
        load_capabilities()


def test_invalid_json_raises_config_error(tmp_path: Path, monkeypatch):
    bad = tmp_path / "bad.json"
    bad.write_text("{ this is not valid json", encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_capabilities()


def test_top_level_not_a_dict_raises_config_error(tmp_path: Path, monkeypatch):
    bad = tmp_path / "list_at_top.json"
    bad.write_text(json.dumps(["not", "a", "dict"]), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))
    with pytest.raises(ConfigError, match="object"):
        load_capabilities()


def test_missing_routes_key_raises_config_error(tmp_path: Path, monkeypatch):
    bad = tmp_path / "no_routes_key.json"
    bad.write_text(json.dumps({"unrelated": []}), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))
    with pytest.raises(ConfigError, match="routes"):
        load_capabilities()


def test_routes_not_a_list_raises_config_error(tmp_path: Path, monkeypatch):
    bad = tmp_path / "routes_not_list.json"
    bad.write_text(json.dumps({"routes": "string-not-list"}), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))
    with pytest.raises(ConfigError, match="routes"):
        load_capabilities()


def test_empty_routes_list_raises_config_error(tmp_path: Path, monkeypatch):
    bad = tmp_path / "empty_routes.json"
    bad.write_text(json.dumps({"routes": []}), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))
    with pytest.raises(ConfigError, match="empty"):
        load_capabilities()


def test_invalid_route_item_raises_config_error(tmp_path: Path, monkeypatch):
    """Pydantic validation failures surface as ConfigError."""
    bad = tmp_path / "bad_item.json"
    bad.write_text(
        json.dumps(
            {
                "routes": [
                    {
                        "description": "no route_name field",
                        "tools": ["x"],
                        "task_families": [
                            {"name": "n", "description": "d", "example_queries": ["q"]}
                        ],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DMAC_ROUTE_CAPABILITIES_FILE", str(bad))
    with pytest.raises(ConfigError):
        load_capabilities()
