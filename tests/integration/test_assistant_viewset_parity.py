"""T13 Step 2 — live assistant-viewset parity (gates 4/5).

Drives the NExtSEEK assistant viewset DIRECTLY (host-side, no agent container)
through the SAME typed `AssistantClient` + mirrored Pydantic models the in-image
thin runner_ns uses, and asserts:

  * gate 4 — strict Pydantic validation succeeds on REAL viewset responses for
    both `query` (mode="standard") and `plan` (mode="plan"); the run reaches a
    clean terminal (a `reply`, no `__error__`); A-4 optional fields
    (`bundle_id`/`files`) validate when the local stack emits them.
  * gate 5 — query/plan artifacts are discoverable via `QueryCompleteEvent`
    (`artifacts`/`files`) and `session_detail(include_turns=True)`; when the
    stack actually emits a downloadable bundle/file, one is fetched. The local
    E2E stack is DATA-SPARSE (1 project "Published Data", no samples) so an empty
    `artifacts`/`files` list is a VALID structural outcome — this test asserts
    shape + types, never that any specific artifact exists (would be brittle on
    a data-light stack).

Host-side URL seam (T13). The E2E target is the LOCAL NExtSEEK stack, NOT the
dev server. The host-side validation guard requires NEXTSEEK_URL to be an https
`dev` URL (so `live_env` keeps validating it), so the local target is carried by
a SEPARATE override `DMAC_E2E_NS_URL` (host terms, default http://localhost:8000).
This test runs HOST-side and calls the viewset directly at that override; if the
override is given in container-gateway terms (`host.docker.internal`, which does
NOT resolve on the macOS host), it is translated back to `localhost`. `live_env`
is used ONLY for credentials. NEVER edit .env — this is a per-invocation seam.
"""
from __future__ import annotations

import pathlib
import sys
import urllib.parse

import pytest

_BIN = pathlib.Path(__file__).resolve().parents[2] / "build_context/plugins/nextseek/bin"
if str(_BIN) not in sys.path:
    sys.path.insert(0, str(_BIN))

import _assistant_client as ac  # noqa: E402
from _assistant_models import (  # noqa: E402
    QueryCompleteEvent,
    SessionDetailResponse,
)


# `live` (not just `live_docker`) so the conftest session guard counts this test
# toward the "selected-but-none-ran" red-fail check; it hits the live viewset +
# its LLM backend, so it is paid and deselected by `-m "not live"`.
pytestmark = [
    pytest.mark.integration,
    pytest.mark.live,
    pytest.mark.slow,
]

_LOCALHOST_GATEWAY = "host.docker.internal"
_DEFAULT_E2E_NS_URL = "http://localhost:8000"


def _host_side_base_url() -> str:
    """Resolve the LOCAL-stack base URL in host terms.

    Reads `DMAC_E2E_NS_URL` (default http://localhost:8000). If it was given in
    container-gateway terms (`host.docker.internal`, which does not resolve on the
    macOS host), translate it back to `localhost`."""
    import os

    raw = os.environ.get("DMAC_E2E_NS_URL") or _DEFAULT_E2E_NS_URL
    parsed = urllib.parse.urlsplit(raw)
    if parsed.hostname == _LOCALHOST_GATEWAY:
        netloc = "localhost"
        if parsed.port:
            netloc = f"{netloc}:{parsed.port}"
        return urllib.parse.urlunsplit(parsed._replace(netloc=netloc))
    return raw


@pytest.fixture
def _live_sockets(live_env: dict[str, str]):
    """Enable real sockets to the concrete viewset host for this live test only.

    `live_env` is requested for credential validation; the repo runs under
    pytest-socket `--disable-socket`, so allow exactly the host this test calls
    (the local stack host) plus unix sockets."""
    import pytest_socket

    base = _host_side_base_url()
    host = urllib.parse.urlsplit(base).hostname
    allowed = [h for h in {host, "localhost", "127.0.0.1"} if h]
    pytest_socket.enable_socket()
    pytest_socket.socket_allow_hosts(allowed, allow_unix_socket=True)
    try:
        yield
    finally:
        pytest_socket.disable_socket()


@pytest.fixture
def _client(live_env: dict[str, str], _live_sockets: None) -> ac.AssistantClient:
    base = _host_side_base_url()
    return ac.AssistantClient(
        base_url=base,
        assistant_prefix="nextseek_api/assistant",
        auth=(live_env["NEXTSEEK_USERNAME"], live_env["NEXTSEEK_PASSWORD"]),
        timeout=300.0,
    )


def _assert_clean_terminal(terminal: dict, mode: str) -> None:
    """Gate 4: a clean terminal validates against QueryCompleteEvent + has a reply."""
    assert "__error__" not in terminal, (
        f"{mode!r} viewset call returned an error terminal: "
        f"{ {k: v for k, v in terminal.items() if k != 'reply'} !r}"
    )
    # Strict Pydantic re-validation on the REAL response (run_query already
    # validated inside the poll loop; assert here so the gate is explicit and the
    # failure message is interpretable). extra="forbid" on the model means any
    # unmirrored key would raise here.
    event = QueryCompleteEvent(**terminal)
    assert isinstance(event.reply, str) and event.reply.strip(), (
        f"{mode!r} viewset reply was empty: {event.reply!r}"
    )
    assert isinstance(event.artifacts, list)
    # A-4 optional fields: present-or-absent both valid; when present they must
    # be the modeled types (None | int, None | list[dict]).
    assert event.bundle_id is None or isinstance(event.bundle_id, int)
    assert event.files is None or isinstance(event.files, list)


@pytest.mark.timeout(900)
@pytest.mark.parametrize("mode", ["standard", "plan"])
def test_viewset_parity_query_and_plan(
    _client: ac.AssistantClient, mode: str
) -> None:
    """Gate 4/5: query + plan modes validate strictly against the live viewset and
    are discoverable via session_detail; download a bundle/artifact when emitted."""
    terminal, _events = _client.run_query(
        "how many samples are in the database", mode=mode
    )
    _assert_clean_terminal(terminal, mode)

    session_id = terminal.get("session_id")
    assert session_id, f"{mode!r} terminal carried no session_id: {terminal.keys()!r}"

    # Gate 5: the turn is discoverable via session_detail(include_turns=True),
    # which strict-validates SessionDetailResponse.
    detail = _client.session_detail(str(session_id), include_turns=True)
    parsed = SessionDetailResponse(**detail)
    assert parsed.query_count >= 1, f"session_detail query_count={parsed.query_count}"
    assert parsed.turns is not None and len(parsed.turns) >= 1, (
        f"{mode!r} session has no turns: {detail!r}"
    )

    # Gate 5: when the data-sparse stack actually emits a downloadable bundle +
    # file, fetch one end-to-end. Empty artifacts/files is a valid structural
    # outcome on this stack — assert shape, don't require content.
    bundle_id = terminal.get("bundle_id")
    files = terminal.get("files") or []
    event = QueryCompleteEvent(**terminal)
    if bundle_id is not None and files:
        bundle = _client.download_bundle(str(session_id), int(bundle_id))
        assert isinstance(bundle, dict)
        # Download the first artifact whose key the bundle exposes (file artifacts
        # only). Structural: a successful 200 + non-None bytes is the gate.
        file_artifacts = [a for a in event.artifacts if a.artifact_type == "file"]
        if file_artifacts:
            content = _client.download_artifact(
                str(session_id), int(bundle_id), file_artifacts[0].key
            )
            assert content is not None
