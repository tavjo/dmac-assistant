import pathlib
import sys

import httpx
import pytest

_BIN = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin"
sys.path.insert(0, str(_BIN))
import _assistant_client as c

SSE = (
    b"event: agent_started\ndata: {\"agent\": \"entity\", \"mode\": \"\"}\n\n"
    b"event: query_complete\ndata: {\"reply\": \"hello\", \"session_id\": \"s1\"}\n\n"
)


def test_run_query_parses_sse_terminal():
    def handler(request):
        assert request.url.path.endswith("/assistant/query/")
        return httpx.Response(200, content=SSE, headers={"content-type": "text/event-stream"})

    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(handler))
    terminal, events = client.run_query("find samples", mode="standard")
    assert terminal["reply"] == "hello"
    assert any(e[0] == "agent_started" for e in events)


def test_run_query_error_event_terminal():
    sse = b"event: query_error\ndata: {\"error\": \"boom\", \"agent\": \"entity\"}\n\n"
    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(lambda r: httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})))
    terminal, _ = client.run_query("x", mode="standard")
    assert terminal["__error__"] == "boom" and terminal["agent"] == "entity"


def test_inbound_validation_rejects_drifted_event():
    sse = b"event: query_complete\ndata: {\"reply\": \"r\", \"unexpected_field\": 1}\n\n"
    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(lambda r: httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})))
    with pytest.raises(Exception):
        client.run_query("x", mode="standard")


def test_run_query_preserves_debug_in_terminal():
    sse = b"event: query_complete\ndata: {\"reply\": \"r\", \"debug\": {\"error\": \"soft fail\"}}\n\n"
    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(lambda r: httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})))
    terminal, _ = client.run_query("x", mode="standard")
    assert terminal["debug"]["error"] == "soft fail"


def test_run_query_stream_without_terminal():
    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(lambda r: httpx.Response(200, content=b"", headers={"content-type": "text/event-stream"})))
    terminal, _ = client.run_query("x", mode="standard")
    assert "stream ended without terminal event" in terminal["__error__"]


def test_session_detail_downloads():
    def handler(request):
        if request.url.path.endswith("/sessions/s1/"):
            return httpx.Response(200, json={
                "session_id": "11111111-1111-4111-8111-111111111111",
                "created_at": "2026-06-09T00:00:00Z",
                "query_count": 1,
                "has_results": True,
            })
        if "/bundles/2/" in request.url.path and "/artifacts/" not in request.url.path:
            return httpx.Response(200, json={"bundle_id": 2})
        if request.url.path.endswith("/artifacts/key/"):
            return httpx.Response(200, content=b"payload")
        raise AssertionError(f"unexpected path {request.url.path}")

    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(handler))
    detail = client.session_detail("s1", include_turns=False)
    assert detail["query_count"] == 1
    assert client.download_bundle("s1", 2)["bundle_id"] == 2
    assert client.download_artifact("s1", 2, "key") == b"payload"


def test_iter_sse_skips_invalid_json():
    sse = b"event: ping\ndata: not-json\n\n"
    client = c.AssistantClient(base_url="https://ns.example", assistant_prefix="nextseek_api/assistant",
                               auth=("u", "p"), transport=httpx.MockTransport(lambda r: httpx.Response(200, content=sse, headers={"content-type": "text/event-stream"})))
    terminal, events = client.run_query("x", mode="standard")
    assert events == []
    assert "stream ended without terminal event" in terminal["__error__"]
