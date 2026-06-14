"""Rewritten runner_ns.py emits the SAME JSONL contract the bridge ns_adapter expects
(recon:nsRoute §3). chat_nextseek is NOT imported; the viewset client is injected."""
import importlib, json, os, sys, types, pathlib
import pytest

RUNNER = pathlib.Path(__file__).resolve().parents[2] / "container/runner_ns.py"


def test_no_chat_nextseek_import():
    text = RUNNER.read_text(encoding="utf-8")
    assert "from chat_nextseek" not in text and "import chat_nextseek" not in text
    # SQLiteSessionState path also gone (session lives in the sidecar now)
    assert "SQLiteSessionState" not in text


def _emit_lines(query, fake_terminal, fake_events, monkeypatch, tmp_path):
    """Run main() in-process with DMAC_RUNNER_NS_NO_REMAP=1 capturing _emit_jsonl output."""
    os.environ["DMAC_RUNNER_NS_NO_REMAP"] = "1"
    os.environ.update({"API_USER": "u", "API_PASS": "p", "NEXTSEEK_URL": "https://ns.example"})
    mod = importlib.import_module("runner_ns") if "runner_ns" in sys.modules else _load()
    captured = []
    monkeypatch.setattr(mod, "_emit_jsonl", lambda name, payload: captured.append({"event": name, "payload": payload}))
    class FakeClient:
        def run_query(self, q, *, mode, **k): return fake_terminal, fake_events
    monkeypatch.setattr(mod, "_build_assistant_client", lambda: FakeClient())
    monkeypatch.setattr("sys.stdin", types.SimpleNamespace(readline=lambda: query + "\n"))
    mod.main()
    return captured


def _load():
    spec = importlib.util.spec_from_file_location("runner_ns", RUNNER)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m); return m


def test_success_emits_query_complete_with_reply(monkeypatch, tmp_path):
    out = _emit_lines("find samples",
                      {"reply": "here are 3 samples", "session_id": "s1"},
                      [("agent_started", {"agent": "entity", "mode": ""})],
                      monkeypatch, tmp_path)
    names = [e["event"] for e in out]
    assert "query_complete" in names
    qc = [e for e in out if e["event"] == "query_complete"][0]
    assert qc["payload"]["reply"] == "here are 3 samples"
    # no failure signals on success
    assert qc["payload"].get("status") not in ("error", "partial", "failure")


def test_error_emits_query_error_with_agent(monkeypatch, tmp_path):
    out = _emit_lines("x", {"__error__": "boom", "agent": "entity"}, [], monkeypatch, tmp_path)
    qe = [e for e in out if e["event"] == "query_error"]
    assert qe and qe[0]["payload"]["agent"] == "entity"


def test_debug_error_terminal_renders_as_failure(monkeypatch, tmp_path):
    # vet finding 11/13/19: a query_complete carrying debug.error must NOT show the reply
    out = _emit_lines("x", {"reply": "secret partial result", "debug": {"error": "soft fail"}},
                      [], monkeypatch, tmp_path)
    qc = [e for e in out if e["event"] == "query_complete"][0]
    assert qc["payload"]["status"] == "error"
    assert "secret partial result" not in json.dumps(qc["payload"])  # reply redacted
    assert qc["payload"].get("debug", {}).get("error") == "soft fail"  # debug propagated
