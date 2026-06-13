"""Tests for sidecar/app/ns_client.py (T15, A-5).

TDD step 1 (client): failing tests written before implementation.
Uses httpx.MockTransport so no real network is needed.
"""
import httpx
import pytest
from sidecar.app import ns_client, ops


def _client(handler):
    """Return an httpx.Client with a MockTransport injected — used by monkeypatches."""
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_call_op_posts_to_endpoint_with_basic_auth(monkeypatch):
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers.get("authorization")
        return httpx.Response(200, json={"op": "entity", "result": {"matched": "MUS"}})

    monkeypatch.setattr(
        ns_client.httpx, "post",
        lambda url, **k: _client(handler).post(
            url, **{x: k[x] for x in ("json", "auth", "timeout") if x in k}
        ),
    )
    out = ns_client.call_op("entity", {"query": "q"}, base_url="http://ns", auth=("u", "p"))
    assert out["result"]["matched"] == "MUS"
    assert seen["url"] == "http://ns/nextseek_api/assistant/entity/"
    assert seen["auth"].startswith("Basic ")


@pytest.mark.parametrize("status,code,exc", [
    (401, None, ops.AuthFailedError),
    (422, "VALIDATION", ops.OpValidationError),
    (403, "WRITE_BLOCKED", ops.WriteBlockedError),
    (403, "FORBIDDEN", ops.AuthFailedError),          # non-participant
    (502, "AGENT_FAILED", ops.AgentFailedError),
    (500, "CONFIG_ERROR", ops.AgentFailedError),
])
def test_error_envelope_maps_to_exception(monkeypatch, status, code, exc):
    body = {"code": code, "errors": [{"title": code or "", "detail": "x"}]} if code else {}

    def handler(req):
        return httpx.Response(status, json=body)

    monkeypatch.setattr(
        ns_client.httpx, "post",
        lambda url, **k: _client(handler).post(
            url, **{x: k[x] for x in ("json", "auth", "timeout") if x in k}
        ),
    )
    with pytest.raises(exc):
        ns_client.call_op("entity", {"query": "q"}, base_url="http://ns", auth=("u", "p"))


def test_transport_error_maps(monkeypatch):
    def boom(url, **k):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(ns_client.httpx, "post", boom)
    with pytest.raises(ops.TransportError):
        ns_client.call_op("entity", {"query": "q"}, base_url="http://ns", auth=("u", "p"))


def test_fetch_artifact_returns_bytes(monkeypatch):
    def handler(req):
        return httpx.Response(200, content=b"WB")

    monkeypatch.setattr(
        ns_client.httpx, "get",
        lambda url, **k: _client(handler).get(
            url, **{x: k[x] for x in ("auth", "timeout") if x in k}
        ),
    )
    assert ns_client.fetch_artifact("/a/url/", base_url="http://ns", auth=("u", "p")) == b"WB"
