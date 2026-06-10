"""The rewritten runner: 9-op routing, no chat_nextseek import, exit-code parity."""
import importlib.util, json, pathlib, subprocess, sys
import pytest

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin/_nextseek_runner.py"


def test_runner_imports_no_chat_nextseek():
    text = RUNNER.read_text(encoding="utf-8")
    assert "import chat_nextseek" not in text and "from chat_nextseek" not in text


def _run(args, env_extra=None):
    env = {"NEXTSEEK_DRY_RUN": "1", "API_USER": "u", "API_PASS": "p",
           "NEXTSEEK_URL": "https://ns.example", "PATH": __import__("os").environ["PATH"]}
    if env_extra:
        env.update(env_extra)
    return subprocess.run([sys.executable, str(RUNNER), *args], capture_output=True, text=True, env=env)


def test_entity_dry_run_emits_json_exit0():
    r = _run(["--agent", "entity", "--query", "x"])
    assert r.returncode == 0
    assert json.loads(r.stdout)  # one JSON line on stdout


def test_api_write_advisory_blocks_without_confirm_exit5():
    # advisory check still surfaces exit 5 in dry-run for missing --confirmed-write
    r = _run(["--agent", "api-write", "--parser-plan", "{}"])
    assert r.returncode == 5
    assert json.loads(r.stderr)["error"]["code"] == "WRITE_BLOCKED"


def test_api_read_with_confirmed_write_exit3():
    # vet finding 14: --confirmed-write is invalid on api-read → local VALIDATION/exit 3
    r = _run(["--agent", "api-read", "--parser-plan", "{}", "--confirmed-write"])
    assert r.returncode == 3
    assert json.loads(r.stderr)["error"]["code"] == "VALIDATION"


def test_report_bad_mode_exit3():
    # vet finding 21: bad --mode stays a LOCAL exit-3, not a sidecar round-trip
    r = _run(["--agent", "report", "--mode", "bogus", "--project", "p"])
    assert r.returncode == 3


def test_unknown_agent_exit2_or_3():
    r = _run(["--agent", "nope", "--query", "x"])
    assert r.returncode != 0  # argparse choices rejects → exit 2


# ---------------------------------------------------------------------------
# Carry-forward: viewset 401 → AUTH_FAILED / exit-8 (W2 post-wave review)
# ---------------------------------------------------------------------------

def _load_runner():
    """Load _nextseek_runner as a module so we can monkeypatch its internals."""
    import importlib.util, pathlib, sys
    _BIN = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin"
    if str(_BIN) not in sys.path:
        sys.path.insert(0, str(_BIN))
    _P = _BIN / "_nextseek_runner.py"
    _s = importlib.util.spec_from_file_location("_nextseek_runner_401_test", _P)
    mod = importlib.util.module_from_spec(_s)
    _s.loader.exec_module(mod)
    return mod


def test_viewset_401_maps_to_auth_failed_exit8(monkeypatch, capsys):
    """A 401 from the assistant viewset must exit 8 (AUTH_FAILED), not 4."""
    import httpx

    runner = _load_runner()
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.setenv("API_PASS", "p")
    monkeypatch.setenv("NEXTSEEK_URL", "https://ns.example")

    class FakeResponse:
        status_code = 401

    def fake_run_query(self, query, *, mode, **kw):
        raise httpx.HTTPStatusError("401", request=None, response=FakeResponse())

    import _assistant_client as ac
    monkeypatch.setattr(ac.AssistantClient, "run_query", fake_run_query)

    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", "--agent", "query", "--query", "x"])
    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 8, (
        f"Expected exit 8 (AUTH_FAILED) on 401, got {exc_info.value.code}"
    )
    err_out = capsys.readouterr().err
    err_payload = json.loads(err_out.strip())
    assert err_payload["error"]["code"] == "AUTH_FAILED"
