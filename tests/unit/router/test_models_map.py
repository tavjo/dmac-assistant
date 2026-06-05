"""Tests for src/dmac_assistant/router/models.py."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from dmac_assistant.config import ConfigError
from dmac_assistant.router.baml_client.types import ModelClass
from dmac_assistant.router.models import (
    load_model_class_map,
    resolve,
    resolve_cc_model,
)


BEDROCK_ID_RE = re.compile(r"^us\.anthropic\.[a-z0-9.\-:]+$")


def test_default_path_loads_three_class_dict() -> None:
    mapping = load_model_class_map()
    assert isinstance(mapping, dict)
    assert set(mapping.keys()) == {"opus", "sonnet", "haiku"}
    assert all(isinstance(value, str) and value for value in mapping.values())


def test_default_values_match_locked_spec_literals() -> None:
    mapping = load_model_class_map()
    assert mapping["opus"] == "us.anthropic.claude-opus-4-8"
    assert mapping["sonnet"] == "us.anthropic.claude-sonnet-4-6"
    assert mapping["haiku"] == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_default_values_all_match_bedrock_qualified_regex() -> None:
    mapping = load_model_class_map()
    for class_alias, model_id in mapping.items():
        assert BEDROCK_ID_RE.match(model_id), (
            f"{class_alias!r} -> {model_id!r} does not match Bedrock-qualified form"
        )


def test_resolve_returns_string_for_every_model_class_enum_value() -> None:
    for member in ModelClass:
        resolved = resolve(member)
        assert isinstance(resolved, str) and resolved
        assert BEDROCK_ID_RE.match(resolved)


def test_resolve_returns_the_locked_literals() -> None:
    assert resolve(ModelClass.Opus) == "us.anthropic.claude-opus-4-8"
    assert resolve(ModelClass.Sonnet) == "us.anthropic.claude-sonnet-4-6"
    assert resolve(ModelClass.Haiku) == "us.anthropic.claude-haiku-4-5-20251001-v1:0"


def test_resolve_cc_model_returns_the_fixed_opus_id() -> None:
    # OI-5: container_cc always runs the fixed auto-mode-capable Opus tier,
    # read from the map's "opus" key (DD-08), independent of any model class.
    assert resolve_cc_model() == "us.anthropic.claude-opus-4-8"
    assert resolve_cc_model() == load_model_class_map()["opus"]


def test_env_override_takes_precedence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    override = tmp_path / "custom_map.json"
    custom = {
        "opus": "us.anthropic.claude-opus-x-y",
        "sonnet": "us.anthropic.claude-sonnet-x-y",
        "haiku": "us.anthropic.claude-haiku-x-y",
    }
    override.write_text(json.dumps(custom), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(override))
    mapping = load_model_class_map()
    assert mapping == custom


def test_explicit_path_argument_overrides_env_and_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit_map.json"
    custom = {
        "opus": "us.anthropic.from-explicit-opus",
        "sonnet": "us.anthropic.from-explicit-sonnet",
        "haiku": "us.anthropic.from-explicit-haiku",
    }
    explicit.write_text(json.dumps(custom), encoding="utf-8")
    bogus = tmp_path / "bogus.json"
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(bogus))
    mapping = load_model_class_map(path=explicit)
    assert mapping["opus"] == "us.anthropic.from-explicit-opus"


def test_missing_file_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "does_not_exist.json"
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(missing))
    with pytest.raises(ConfigError, match=re.escape(str(missing))):
        load_model_class_map()


def test_invalid_json_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "bad.json"
    bad.write_text("{ not valid json", encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(bad))
    with pytest.raises(ConfigError, match="not valid JSON"):
        load_model_class_map()


def test_top_level_not_a_dict_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "list_top.json"
    bad.write_text(json.dumps([]), encoding="utf-8")
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(bad))
    with pytest.raises(ConfigError, match="object"):
        load_model_class_map()


def test_missing_class_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "missing_haiku.json"
    bad.write_text(
        json.dumps(
            {
                "opus": "us.anthropic.claude-opus-4-7",
                "sonnet": "us.anthropic.claude-sonnet-4-6",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(bad))
    with pytest.raises(ConfigError, match="haiku"):
        load_model_class_map()


def test_empty_string_value_raises_config_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "empty_value.json"
    bad.write_text(
        json.dumps(
            {
                "opus": "us.anthropic.claude-opus-4-7",
                "sonnet": "",
                "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(bad))
    with pytest.raises(ConfigError, match="sonnet"):
        load_model_class_map()


def test_plain_anthropic_form_rejected_at_load_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bad = tmp_path / "plain_form.json"
    bad.write_text(
        json.dumps(
            {
                "opus": "claude-opus-4-7",
                "sonnet": "us.anthropic.claude-sonnet-4-6",
                "haiku": "us.anthropic.claude-haiku-4-5-20251001-v1:0",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DMAC_ROUTER_MODEL_CLASS_MAP_FILE", str(bad))
    with pytest.raises(ConfigError, match="Bedrock"):
        load_model_class_map()
