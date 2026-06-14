"""The rewritten runner: 9-op routing, no chat_nextseek import, exit-code parity."""
import importlib.util, json, pathlib, subprocess, sys
import pytest

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin/_nextseek_runner.py"
_BIN = RUNNER.parent


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


# ---------------------------------------------------------------------------
# Important-2: CONFIG_MISSING / exit-2 guard
# ---------------------------------------------------------------------------

def test_missing_api_user_exits_config_missing(monkeypatch, capsys):
    """Important-2: absent API_USER must exit 2 with code CONFIG_MISSING."""
    runner = _load_runner()
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    monkeypatch.delenv("API_USER", raising=False)
    monkeypatch.setenv("API_PASS", "p")
    monkeypatch.setenv("NEXTSEEK_URL", "https://ns.example")
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", "--agent", "entity", "--query", "x"])
    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 2
    err_payload = json.loads(capsys.readouterr().err.strip())
    assert err_payload["error"]["code"] == "CONFIG_MISSING"


def test_missing_api_pass_exits_config_missing(monkeypatch, capsys):
    """Important-2: absent API_PASS must exit 2 with code CONFIG_MISSING."""
    runner = _load_runner()
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.delenv("API_PASS", raising=False)
    monkeypatch.setenv("NEXTSEEK_URL", "https://ns.example")
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", "--agent", "entity", "--query", "x"])
    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 2
    err_payload = json.loads(capsys.readouterr().err.strip())
    assert err_payload["error"]["code"] == "CONFIG_MISSING"


# ---------------------------------------------------------------------------
# Important-3: sidecar dispatch paths pinned (live branch, no network)
# ---------------------------------------------------------------------------

# Expected args dict that call_op should receive for each op.
# Keys: (op, argv_extra, expected_args)
_SIDECAR_CASES = [
    ("entity",              ["--query", "myq"],                                           {"query": "myq"}),
    ("parse",               ["--query", "myq"],                                           {"query": "myq"}),
    ("graph",               ["--query", "myq"],                                           {"query": "myq"}),
    ("api-read",            ["--parser-plan", '{"x":1}'],                                 {"parser_plan": '{"x":1}'}),
    ("api-write",           ["--parser-plan", '{"x":1}', "--confirmed-write"],            {"parser_plan": '{"x":1}', "confirmed_write": True}),
    ("report",              ["--mode", "samples", "--project", "MyProj"],                 {"mode": "samples", "project": "MyProj"}),
    ("generate-submission", ["--type", "GEO", "--uids", "uid1,uid2", "--query", "geoq"],  {"type": "GEO", "uids": "uid1,uid2", "query": "geoq"}),
]


@pytest.mark.parametrize("op,argv_extra,expected_args", _SIDECAR_CASES,
                         ids=[c[0] for c in _SIDECAR_CASES])
def test_sidecar_dispatch_pins(op, argv_extra, expected_args, monkeypatch, capsys):
    """Important-3a: each of the 7 sidecar ops must call call_op with the spec-mapped args."""
    if str(_BIN) not in sys.path:
        sys.path.insert(0, str(_BIN))
    import importlib
    sc = importlib.import_module("_sidecar_client")

    captured = {}

    def fake_call_op(captured_op, captured_args, **kwargs):
        captured["op"] = captured_op
        captured["args"] = captured_args
        return {"ok": True}

    # Patch call_op on the already-imported _sidecar_client module AND on any
    # reference the runner has picked up via its lazy 'import _sidecar_client as sc'.
    # We patch the module itself; since the runner does 'import _sidecar_client as sc'
    # inside each dispatcher (not at module load), patching the module attribute is
    # sufficient.
    monkeypatch.setattr(sc, "call_op", fake_call_op)
    # Also inject the patched module so the runner's lazy import picks it up.
    monkeypatch.setitem(sys.modules, "_sidecar_client", sc)

    runner = _load_runner()
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.setenv("API_PASS", "p")
    monkeypatch.setenv("NEXTSEEK_URL", "https://ns.example")
    monkeypatch.setenv("NEXTSEEK_SIDECAR_HOST", "testhost")
    monkeypatch.setenv("NEXTSEEK_SIDECAR_PORT", "8765")
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", "--agent", op, *argv_extra])

    runner.main()  # must not raise
    assert captured.get("op") == op, f"call_op op mismatch: {captured.get('op')!r} != {op!r}"
    assert captured.get("args") == expected_args, (
        f"args mismatch for {op!r}:\n  got:      {captured.get('args')!r}\n  expected: {expected_args!r}"
    )

    # Bonus: validate args against the strict contract
    from _ws_contract import validate_op_args
    validate_op_args(op, captured["args"])  # must not raise


def test_sidecar_write_blocked_propagates(monkeypatch, capsys):
    """Important-3b: SidecarCallError(WRITE_BLOCKED) from call_op → exit 5."""
    if str(_BIN) not in sys.path:
        sys.path.insert(0, str(_BIN))
    import importlib
    sc = importlib.import_module("_sidecar_client")

    def fake_call_op_blocked(op, args, **kwargs):
        raise sc.SidecarCallError("WRITE_BLOCKED", "no")

    monkeypatch.setattr(sc, "call_op", fake_call_op_blocked)
    monkeypatch.setitem(sys.modules, "_sidecar_client", sc)

    runner = _load_runner()
    monkeypatch.delenv("NEXTSEEK_DRY_RUN", raising=False)
    monkeypatch.setenv("API_USER", "u")
    monkeypatch.setenv("API_PASS", "p")
    monkeypatch.setenv("NEXTSEEK_URL", "https://ns.example")
    monkeypatch.setattr(sys, "argv", ["_nextseek_runner", "--agent", "entity", "--query", "x"])

    with pytest.raises(SystemExit) as exc_info:
        runner.main()
    assert exc_info.value.code == 5
    err_payload = json.loads(capsys.readouterr().err.strip())
    assert err_payload["error"]["code"] == "WRITE_BLOCKED"
