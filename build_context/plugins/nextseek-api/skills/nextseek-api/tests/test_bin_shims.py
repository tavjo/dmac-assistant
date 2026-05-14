"""
Subprocess tests for bin/ shims.

Each shim must:
1. Exist at bin/<name>
2. Be executable (chmod +x)
3. Start with a bash shebang
4. Reference the correct target Python script name
5. Exec uv run --with httpx --with pydantic --with python-dotenv
6. Pass-through --help (or any args) to the underlying Python script and exit 0

The tests invoke each shim with --help via subprocess, with CLAUDE_PLUGIN_ROOT
set to the stub root, and assert the underlying script sees --help and exits 0.

This file also hosts Issue #6 parametrized tests verifying that EVERY Python
shim accepts `--env-file PATH` via the shared `add_env_file_arg` helper.
"""
from __future__ import annotations

import importlib
import json
import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


# skills/nextseek-api/tests/test_bin_shims.py — 4 parents up = plugin root
PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent.parent
BIN_DIR = PLUGIN_ROOT / "bin"
SCRIPTS_DIR = PLUGIN_ROOT / "skills" / "nextseek-api" / "scripts"

SHIM_TO_SCRIPT = {
    "nextseek-init": "init_session.py",
    # DD-4 (task-06a): renamed from nextseek-get / get_endpoint_spec.py.
    "nextseek-spec": "fetch_spec.py",
    "nextseek-validate": "validate_request.py",
    "nextseek-exec": "execute_request.py",
    # task-02 / issue #17: session-status shim for TTL visibility.
    "nextseek-session": "session_status.py",
    # task-08: unified resolve + validate + execute shim.
    "nextseek-call": "call_request.py",
}


@pytest.fixture
def stub_plugin_root(tmp_path: Path) -> Path:
    """
    Build an isolated plugin-root layout with stub Python scripts that print
    a recognizable marker and exit 0, so shim subprocess tests can assert
    the shim correctly resolves + exec's the target script.
    """
    root = tmp_path / "plugin"
    (root / "bin").mkdir(parents=True)
    (root / "skills" / "nextseek-api" / "scripts").mkdir(parents=True)

    # Copy real shims into the stub tree
    for shim_name in SHIM_TO_SCRIPT:
        src = BIN_DIR / shim_name
        dst = root / "bin" / shim_name
        shutil.copy2(src, dst)
        dst.chmod(dst.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)

    # Write stub Python scripts — each just prints its own name + args and exits 0
    for shim_name, script_name in SHIM_TO_SCRIPT.items():
        stub_path = root / "skills" / "nextseek-api" / "scripts" / script_name
        stub_path.write_text(
            "import sys\n"
            f"print('STUB:{script_name}:' + ' '.join(sys.argv[1:]))\n"
            "sys.exit(0)\n"
        )

    return root


def _invoke_shim(
    stub_plugin_root: Path,
    shim_name: str,
    args: list[str],
) -> subprocess.CompletedProcess[str]:
    """Run a shim with CLAUDE_PLUGIN_ROOT set to the stub root."""
    shim_path = stub_plugin_root / "bin" / shim_name
    env = os.environ.copy()
    env["CLAUDE_PLUGIN_ROOT"] = str(stub_plugin_root)
    return subprocess.run(
        [str(shim_path), *args],
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )


# ----- Per-shim structural assertions (no subprocess call required) -----

@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_file_exists_and_is_executable(shim_name: str, script_name: str) -> None:
    shim_path = BIN_DIR / shim_name
    assert shim_path.is_file(), f"{shim_path} does not exist"
    mode = shim_path.stat().st_mode
    assert mode & stat.S_IXUSR, f"{shim_path} is not executable for owner"
    assert mode & stat.S_IXGRP, f"{shim_path} is not executable for group"
    assert mode & stat.S_IXOTH, f"{shim_path} is not executable for other"


@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_has_bash_shebang(shim_name: str, script_name: str) -> None:
    content = (BIN_DIR / shim_name).read_text()
    first_line = content.splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", (
        f"{shim_name} must start with '#!/usr/bin/env bash', got {first_line!r}"
    )


@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_references_correct_target_script(shim_name: str, script_name: str) -> None:
    content = (BIN_DIR / shim_name).read_text()
    assert script_name in content, (
        f"{shim_name} should reference {script_name}, got:\n{content}"
    )


@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_uses_uv_run_with_required_deps(shim_name: str, script_name: str) -> None:
    content = (BIN_DIR / shim_name).read_text()
    assert "uv run" in content
    assert "--with httpx" in content
    assert "--with pydantic" in content
    assert "--with python-dotenv" in content
    assert "exec " in content, f"{shim_name} should use exec, not a subshell"


@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_honors_claude_plugin_root_env(shim_name: str, script_name: str) -> None:
    content = (BIN_DIR / shim_name).read_text()
    assert "CLAUDE_PLUGIN_ROOT" in content, (
        f"{shim_name} must reference CLAUDE_PLUGIN_ROOT for script path resolution"
    )


@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_passes_args_through(shim_name: str, script_name: str) -> None:
    content = (BIN_DIR / shim_name).read_text()
    assert '"$@"' in content, f"{shim_name} must pass through $@"


@pytest.mark.parametrize("shim_name,script_name", sorted(SHIM_TO_SCRIPT.items()))
def test_shim_has_safety_preamble(shim_name: str, script_name: str) -> None:
    content = (BIN_DIR / shim_name).read_text()
    assert "set -euo pipefail" in content, (
        f"{shim_name} must include 'set -euo pipefail' safety preamble"
    )


# ----- End-to-end subprocess tests against stub Python scripts -----

def test_nextseek_init_invokes_stub_script(stub_plugin_root: Path) -> None:
    result = _invoke_shim(stub_plugin_root, "nextseek-init", ["--help"])
    assert result.returncode == 0, (
        f"nextseek-init exit {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "STUB:init_session.py:--help" in result.stdout


def test_nextseek_spec_invokes_stub_script(stub_plugin_root: Path) -> None:
    result = _invoke_shim(stub_plugin_root, "nextseek-spec", ["--operation-id", "getSamples"])
    assert result.returncode == 0, (
        f"nextseek-spec exit {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "STUB:fetch_spec.py:--operation-id getSamples" in result.stdout


def test_nextseek_get_removed() -> None:
    """DD-4: bin/nextseek-get must not exist after the rename."""
    assert not (BIN_DIR / "nextseek-get").exists(), (
        "bin/nextseek-get must be deleted per DD-4 (no backward-compat alias)."
    )


def test_nextseek_spec_exists_and_executable() -> None:
    """DD-4: bin/nextseek-spec replaces bin/nextseek-get."""
    spec = BIN_DIR / "nextseek-spec"
    assert spec.exists(), "bin/nextseek-spec missing"
    mode = spec.stat().st_mode
    assert mode & stat.S_IXUSR, "bin/nextseek-spec not executable for owner"


def test_nextseek_validate_invokes_stub_script(stub_plugin_root: Path) -> None:
    result = _invoke_shim(stub_plugin_root, "nextseek-validate", ["--help"])
    assert result.returncode == 0, (
        f"nextseek-validate exit {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "STUB:validate_request.py:--help" in result.stdout


def test_nextseek_session_invokes_stub_script(stub_plugin_root: Path) -> None:
    result = _invoke_shim(stub_plugin_root, "nextseek-session", ["--env", "prod"])
    assert result.returncode == 0, (
        f"nextseek-session exit {result.returncode}\n"
        f"stdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "STUB:session_status.py:--env prod" in result.stdout


def test_nextseek_exec_invokes_stub_script(stub_plugin_root: Path) -> None:
    result = _invoke_shim(
        stub_plugin_root,
        "nextseek-exec",
        ["--method", "GET", "--endpoint", "schema_rag/retrieve/"],
    )
    assert result.returncode == 0, (
        f"nextseek-exec exit {result.returncode}\nstdout={result.stdout}\nstderr={result.stderr}"
    )
    assert "STUB:execute_request.py:--method GET --endpoint schema_rag/retrieve/" in result.stdout


# =============================================================================
# Issue #6 — --env-file harmonization tests
# =============================================================================
# Every shim must accept `--env-file PATH` via the shared cli_common helper.
# Shims that actually call `load_environment` must pass the path through.

# Scripts that consume --env-file AND call load_environment. The per-module
# `load_environment` re-export is patched (monkeypatching `lib.env_loader`
# directly would not rebind the already-imported module reference).
_LOADER_SHIMS = ("init_session", "fetch_spec", "execute_request")


def _make_fake_config():
    """Build a NextseekConfig-compatible stub for fake_load_environment."""
    # Imported lazily so test collection doesn't require importing lib.
    from lib.nextseek_client import NextseekConfig

    return NextseekConfig(
        base_url="https://nextseek.mit.edu/nextseek_api",
        username="u",
        password="p",
    )


@pytest.mark.parametrize("script", _LOADER_SHIMS)
def test_shim_passes_env_file_to_load_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    script: str,
) -> None:
    """Each loader shim must forward --env-file PATH to load_environment()."""
    env_path = tmp_path / ".env"
    env_path.write_text(
        "SEEK_USER=u\nSEEK_PASSWORD=p\n"
        "NEXTSEEK_BASE_URL=https://nextseek.mit.edu/nextseek_api\n"
    )

    mod = importlib.import_module(script)

    captured: dict[str, object] = {}
    fake_cfg = _make_fake_config()

    def fake_load_environment(*args, **kwargs):
        # load_environment is called as load_environment(env_path=..., use_dev=...)
        captured["env_path"] = kwargs.get("env_path") if "env_path" in kwargs else (
            args[0] if args else None
        )
        return fake_cfg

    # Patch the per-module re-export, not lib.env_loader.
    monkeypatch.setattr(f"{script}.load_environment", fake_load_environment)

    # Short-circuit the network path by raising inside the NextseekClient
    # context manager entry — we only care that args parsed and load_environment
    # was called with the right --env-file value.
    def _boom(*a, **kw):  # noqa: ARG001
        raise RuntimeError("short-circuit: network not exercised in this test")

    monkeypatch.setattr(f"{script}.NextseekClient", _boom)

    # Build the per-script argv. All three shims accept --env and --env-file.
    argv = ["--env", "dev", "--env-file", str(env_path)]
    if script == "fetch_spec":
        argv += ["--operation-id", "someOp"]
    elif script == "execute_request":
        # execute_request needs a RequestSpec JSON via --file; seed one that
        # triggers CACHE_MISS BEFORE load_environment is called ... except
        # load_environment runs AFTER the cache check. Seed a spec file AND
        # a fake cached endpoint via monkeypatched _load_cached_endpoint.
        spec_file = tmp_path / "spec.json"
        spec_file.write_text(
            json.dumps(
                {
                    "operation_id": "schema_rag_retrieve",
                    "method": "POST",
                    "endpoint": "/nextseek_api/schema_rag/retrieve/",
                    "path_params": {},
                    "query_params": {},
                    "headers": {},
                    "request_body": {"query": "x"},
                }
            )
        )
        argv += ["--file", str(spec_file)]
        # Fake endpoint so the cache-miss branch is not taken.
        from lib.models import FullEndpoint

        fake_endpoint = FullEndpoint.model_validate(
            {
                "operationId": "schema_rag_retrieve",
                "method": "POST",
                "path": "/nextseek_api/schema_rag/retrieve/",
                "description": "",
                "tags": [],
                "parameters": [],
                "request_schema": {},
                "response_schema": {},
                "relevance_score": 1.0,
            }
        )
        monkeypatch.setattr(
            f"{script}._load_cached_endpoint",
            lambda op_id, env_tag: fake_endpoint,
        )

    # Run: main(argv) should parse the flag and call fake_load_environment,
    # then hit the NextseekClient short-circuit. Scripts wrap broad exceptions
    # and convert them to non-zero exit codes, so rc is an int (typically 2).
    try:
        rc = mod.main(argv)
    except SystemExit as exc:  # argparse errors raise SystemExit
        rc = int(exc.code) if exc.code is not None else 0
    except RuntimeError:
        # execute_request does not blanket-catch RuntimeError from
        # NextseekClient, so _boom propagates. That's fine: load_environment
        # was still called first.
        rc = None

    assert "env_path" in captured, (
        f"{script}.main() never called load_environment(); captured={captured}; rc={rc}"
    )
    assert captured["env_path"] == env_path, (
        f"{script} forwarded {captured['env_path']!r}, expected {env_path!r}"
    )


def test_validate_request_accepts_env_file_flag(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """validate_request.py must accept --env-file without error.

    validate_request does NOT call load_environment (it only reads JSON + cache);
    the flag is surface-only for CLI consistency. Verify argparse accepts it
    and the shim still runs through its normal code path.
    """
    import validate_request

    env_path = tmp_path / "ignored.env"
    env_path.write_text("SEEK_USER=u\nSEEK_PASSWORD=p\n")

    # Feed a minimally-valid RequestSpec via --file; the cache-miss branch is
    # acceptable (EXIT_CACHE_MISS=2) because we only care the flag is accepted.
    spec_file = tmp_path / "spec.json"
    spec_file.write_text(
        json.dumps(
            {
                "operation_id": "does_not_exist",
                "method": "GET",
                "endpoint": "/nextseek_api/samples/",
                "path_params": {},
                "query_params": {},
                "headers": {},
                "request_body": None,
            }
        )
    )

    rc = validate_request.main(
        ["--env", "dev", "--env-file", str(env_path), "--file", str(spec_file)]
    )
    # Cache miss is expected (rc=2) — the point is argparse accepted --env-file.
    assert rc in (0, 1, 2), f"unexpected exit code {rc}"


@pytest.mark.parametrize(
    "script",
    ("init_session", "fetch_spec", "execute_request", "validate_request"),
)
def test_shim_main_accepts_argv_list(script: str) -> None:
    """Every shim's main() must accept an optional argv list (Section 9)."""
    mod = importlib.import_module(script)
    assert callable(mod.main)
    import inspect

    sig = inspect.signature(mod.main)
    params = list(sig.parameters.values())
    assert len(params) == 1, (
        f"{script}.main() must accept exactly one parameter (argv), got {params}"
    )
    p = params[0]
    assert p.default is None, (
        f"{script}.main() argv param must default to None, got {p.default!r}"
    )
