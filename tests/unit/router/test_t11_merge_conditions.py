"""Merge-condition verification for T1.1 — BAML scaffold (atomic).

Spec V.O. #5 mandates that the BAML scaffold land as ONE commit with four
artifacts. Each test below pins one of the four merge conditions; together
they are the canonical post-T1.1 state assertion.
"""

from __future__ import annotations

import re
import tomllib
from importlib import import_module
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT = REPO_ROOT / "pyproject.toml"
ROUTER_BAML = REPO_ROOT / "baml_src/router.baml"


def test_baml_py_pinned_with_tilde_equals() -> None:
    """Merge condition (a): pyproject.toml has 'baml-py~=0.222.0' (NOT '>=').

    The pre-existing line from precursor merge f30c91a was 'baml-py>=0.222.0';
    spec V.O. #5 requires the literal '~=' patch-level pin form. The '>=' form
    is forbidden post-T1.1 because it would silently accept a future 0.223.x
    release whose generated client API may diverge from the committed
    baml_client/ tree.
    """
    text = PYPROJECT.read_text(encoding="utf-8")
    matches = re.findall(r'"baml-py([><=~!]+)([\d.]+)"', text)
    assert matches, "no baml-py entry found in pyproject.toml"
    assert len(matches) == 1, (
        f"expected exactly ONE baml-py entry; found {len(matches)}: {matches}. "
        "uv add may have duplicated rather than replaced — inspect with "
        "`grep -n baml-py pyproject.toml`."
    )
    operator, version = matches[0]
    assert operator == "~=", (
        f"baml-py specifier is '{operator}{version}' but spec V.O. #5 demands "
        f"'~={version}'. Run `uv add 'baml-py~=0.222.0'` to change it."
    )
    assert version == "0.222.0", (
        f"baml-py version is '{version}'; expected '0.222.0' per spec § "
        "Dependency Validation."
    )


def test_router_baml_client_coverage_omit_present() -> None:
    """Merge condition (c): [tool.coverage.run] omit contains the router glob.

    Both the pre-existing 'src/dmac_assistant/eval/*' entry AND the new
    'src/dmac_assistant/router/baml_client/*' entry must be present. T1.1
    MUST append, NOT replace.
    """
    with PYPROJECT.open("rb") as fh:
        config = tomllib.load(fh)
    omit_list = config["tool"]["coverage"]["run"]["omit"]
    assert "src/dmac_assistant/router/baml_client/*" in omit_list, (
        f"router baml_client omit entry missing from pyproject.toml; got: {omit_list}"
    )
    assert "src/dmac_assistant/eval/*" in omit_list, (
        f"pre-existing eval omit entry was clobbered by T1.1; got: {omit_list}. "
        "T1.1 must APPEND to the omit list, not replace it."
    )


def test_router_baml_client_importable() -> None:
    """Merge condition (b) part 1: baml_client/ exists and is importable.

    `baml-cli generate` produced the Python client tree. Importing the package
    is the cheapest proof that codegen succeeded and that the package marker
    files are present.
    """
    mod = import_module("dmac_assistant.router.baml_client")
    assert hasattr(mod, "b"), (
        "dmac_assistant.router.baml_client does not export 'b'. The codegen may "
        "have failed silently or generated for a different default_client_mode. "
        "Verify baml_src/generators.baml router_target says "
        "`default_client_mode async`."
    )


def test_route_query_function_class_present() -> None:
    """Merge condition (b) part 2: codegen produced the RouteQuery types.

    Proves the router.baml schema was consumed correctly: the enums Route /
    ModelClass and the input/output types RouterInput / RouterDecision must
    exist as importable Pydantic models / enums.
    """
    types_mod = import_module("dmac_assistant.router.baml_client.types")
    assert hasattr(types_mod, "Route"), "Route enum not generated"
    assert hasattr(types_mod, "ModelClass"), "ModelClass enum not generated"
    assert hasattr(types_mod, "RouterInput"), "RouterInput model not generated"
    assert hasattr(types_mod, "RouterDecision"), "RouterDecision model not generated"
    assert hasattr(types_mod, "RouteCapability"), "RouteCapability model not generated"
    assert hasattr(types_mod, "TaskFamily"), "TaskFamily model not generated"

    route_enum = types_mod.Route
    route_values = {member.value for member in route_enum}
    assert route_values == {"NextseekQuery", "ContainerCC"}, (
        f"Route enum identifiers drifted; got {route_values}; expected "
        f"{{'NextseekQuery', 'ContainerCC'}} per locked spec lines 185-188."
    )
    model_class_enum = types_mod.ModelClass
    model_class_values = {member.value for member in model_class_enum}
    assert model_class_values == {"Sonnet", "Haiku", "Opus"}, (
        f"ModelClass enum identifiers drifted; got {model_class_values}; expected "
        f"{{'Sonnet', 'Haiku', 'Opus'}} per locked spec lines 190-194."
    )

    router_baml = ROUTER_BAML.read_text(encoding="utf-8")
    assert 'NextseekQuery @alias("nextseek_query")' in router_baml
    assert 'ContainerCC   @alias("container_cc")' in router_baml
    assert 'Sonnet @alias("sonnet")' in router_baml
    assert 'Haiku  @alias("haiku")' in router_baml
    assert 'Opus   @alias("opus")' in router_baml
