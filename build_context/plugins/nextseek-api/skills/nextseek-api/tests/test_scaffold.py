"""Structural scaffold tests for the nextseek-api plugin.

Validates that task-01 created the canonical directory tree, a valid
plugin.json, and a pyproject.toml that declares all required runtime
and dev dependencies. No executable plugin logic is tested here —
downstream tasks (02/03/04) cover their own modules.
"""

from __future__ import annotations

import json
import tomllib
from pathlib import Path


# Plugin root is two levels up from this test file:
# <plugin_root>/skills/nextseek-api/tests/test_scaffold.py
PLUGIN_ROOT = Path(__file__).resolve().parents[3]


def test_plugin_json_exists_and_has_required_keys() -> None:
    """`.claude-plugin/plugin.json` must exist with name, version, description."""
    plugin_json_path = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
    assert plugin_json_path.is_file(), f"missing: {plugin_json_path}"

    data = json.loads(plugin_json_path.read_text())
    assert data["name"] == "nextseek-api"
    assert data["version"] == "0.1.0"
    assert isinstance(data["description"], str) and len(data["description"]) > 0
    assert "author" in data
    assert isinstance(data.get("keywords", []), list)
    assert "nextseek" in data["keywords"]


def test_canonical_directory_structure_exists() -> None:
    """All required subdirectories must exist."""
    required_dirs = [
        ".claude-plugin",
        "commands",
        "skills/nextseek-api",
        "skills/nextseek-api/scripts",
        "skills/nextseek-api/scripts/lib",
        "skills/nextseek-api/tests",
    ]
    for rel in required_dirs:
        path = PLUGIN_ROOT / rel
        assert path.is_dir(), f"missing directory: {path}"


def test_lib_init_and_tests_init_present() -> None:
    """Package marker files must exist so `from lib.X import ...` works."""
    lib_init = PLUGIN_ROOT / "skills" / "nextseek-api" / "scripts" / "lib" / "__init__.py"
    tests_init = PLUGIN_ROOT / "skills" / "nextseek-api" / "tests" / "__init__.py"
    assert lib_init.is_file(), f"missing: {lib_init}"
    assert tests_init.is_file(), f"missing: {tests_init}"


def test_scripts_init_present() -> None:
    """scripts/__init__.py must exist per CL-1 so `scripts/` is a package root."""
    scripts_init = PLUGIN_ROOT / "skills" / "nextseek-api" / "scripts" / "__init__.py"
    assert scripts_init.is_file(), f"missing: {scripts_init}"


def test_conftest_has_sys_path_hack() -> None:
    """tests/conftest.py must inject scripts/ onto sys.path per CL-1."""
    conftest = PLUGIN_ROOT / "skills" / "nextseek-api" / "tests" / "conftest.py"
    assert conftest.is_file(), f"missing: {conftest}"

    text = conftest.read_text()
    # The exact CL-1 sys.path hack must be present
    assert "import sys" in text
    assert "from pathlib import Path" in text
    assert "_SCRIPTS_DIR" in text
    assert 'parent.parent / "scripts"' in text
    assert "sys.path.insert(0, str(_SCRIPTS_DIR))" in text


def test_cache_paths_stub_present_and_importable() -> None:
    """scripts/lib/cache_paths.py must exist per CL-7 and expose the 5 helpers."""
    cache_paths = PLUGIN_ROOT / "skills" / "nextseek-api" / "scripts" / "lib" / "cache_paths.py"
    assert cache_paths.is_file(), f"missing: {cache_paths}"

    text = cache_paths.read_text()
    # All 5 helper functions from CL-7 must be defined
    for fn_name in [
        "def resolve_plugin_cache_base",
        "def resolve_env_cache_dir",
        "def resolve_session_json_path",
        "def resolve_endpoints_minimal_path",
        "def resolve_endpoints_full_dir",
    ]:
        assert fn_name in text, f"cache_paths.py missing: {fn_name}"


def test_pyproject_declares_runtime_and_dev_deps() -> None:
    """`pyproject.toml` must pin httpx, pydantic, python-dotenv, pytest, pytest-cov."""
    pyproject_path = PLUGIN_ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), f"missing: {pyproject_path}"

    data = tomllib.loads(pyproject_path.read_text())
    project = data.get("project", {})
    assert project.get("name") == "nextseek-api"
    assert project.get("requires-python", "").startswith(">=3.11")

    runtime_deps = project.get("dependencies", [])
    runtime_joined = " ".join(runtime_deps)
    assert "httpx>=0.28" in runtime_joined
    assert "pydantic>=2.10" in runtime_joined
    assert "python-dotenv>=1.0" in runtime_joined

    optional = project.get("optional-dependencies", {})
    dev_deps = optional.get("dev", [])
    dev_joined = " ".join(dev_deps)
    assert "pytest>=8.0" in dev_joined
    assert "pytest-cov>=5.0" in dev_joined


def test_stub_command_and_skill_markdown_exist_with_frontmatter() -> None:
    """commands/nextseek-api.md and skills/nextseek-api/SKILL.md must exist with YAML frontmatter."""
    command_md = PLUGIN_ROOT / "commands" / "nextseek-api.md"
    skill_md = PLUGIN_ROOT / "skills" / "nextseek-api" / "SKILL.md"

    assert command_md.is_file(), f"missing: {command_md}"
    assert skill_md.is_file(), f"missing: {skill_md}"

    command_text = command_md.read_text()
    skill_text = skill_md.read_text()

    # Both start with YAML frontmatter delimited by --- lines
    assert command_text.lstrip().startswith("---"), "command.md missing frontmatter"
    assert skill_text.lstrip().startswith("---"), "SKILL.md missing frontmatter"

    # Stub still mentions the plugin name
    assert "nextseek-api" in command_text
    assert "nextseek-api" in skill_text


def test_gitignore_ignores_worktrees_and_cache_dirs() -> None:
    """`.gitignore` must exist and list .worktrees, __pycache__, .pytest_cache, .coverage."""
    gitignore = PLUGIN_ROOT / ".gitignore"
    assert gitignore.is_file(), f"missing: {gitignore}"

    text = gitignore.read_text()
    for pattern in [".worktrees/", "__pycache__/", ".pytest_cache/", ".coverage"]:
        assert pattern in text, f".gitignore missing pattern: {pattern}"
