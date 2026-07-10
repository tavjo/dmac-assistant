"""Defect 1: default NEXTSEEK_ASSISTANT_PREFIX must be cc-assistant."""
from __future__ import annotations

import ast
import os
import pathlib
import sys

import pytest

os.environ.setdefault("DMAC_RUNNER_NS_NO_REMAP", "1")

sys.path.insert(0, str(pathlib.Path("build_context/plugins/nextseek/bin")))


def _default_prefix_literal(path: pathlib.Path, *, func_name: str) -> str | None:
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            for child in ast.walk(node):
                if (
                    isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "get"
                    and len(child.args) >= 2
                    and isinstance(child.args[0], ast.Constant)
                    and child.args[0].value == "NEXTSEEK_ASSISTANT_PREFIX"
                    and isinstance(child.args[1], ast.Constant)
                ):
                    return child.args[1].value
    return None


def test_nextseek_runner_default_prefix_is_cc_assistant():
    path = pathlib.Path("build_context/plugins/nextseek/bin/_nextseek_runner.py")
    assert _default_prefix_literal(path, func_name="_run_viewset") == (
        "nextseek_api/cc-assistant"
    )


def test_runner_ns_default_prefix_is_cc_assistant():
    path = pathlib.Path("container/runner_ns.py")
    assert _default_prefix_literal(path, func_name="_build_assistant_client") == (
        "nextseek_api/cc-assistant"
    )


def test_runner_ns_runtime_default_without_env(monkeypatch):
    from container import runner_ns

    monkeypatch.setenv("NEXTSEEK_URL", "https://example.test")
    monkeypatch.delenv("NEXTSEEK_ASSISTANT_PREFIX", raising=False)
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.setenv("API_PASS", "p")

    class FakeClient:
        def __init__(self, *, base_url, assistant_prefix, auth):
            self.assistant_prefix = assistant_prefix

    monkeypatch.setitem(sys.modules, "_assistant_client", type(sys)("ac"))
    import types

    fake_mod = types.ModuleType("_assistant_client")
    fake_mod.AssistantClient = FakeClient
    monkeypatch.setitem(sys.modules, "_assistant_client", fake_mod)

    client = runner_ns._build_assistant_client()
    assert client.assistant_prefix == "nextseek_api/cc-assistant"
