"""T1.2 - BridgeAttachSocket dual-transport extension contract.

Pins the locked spec section "Extend BridgeAttachSocket" by exercising the
demux unit through two transport shapes:

1. SocketIO-shaped, today's attach path: has `._sock` and `.recv(size)`.
2. Raw-socket-shaped, T3.1's new exec path: no `._sock`; has both `.read(size)`
   and `.recv(size)` per F-03 of the round-4 design review.

The `read_event_line()` method is the line-oriented surface that T3.2's
`_dispatch_ns_turn` consumes; the edge-case tests pin its contract.
"""

from __future__ import annotations

import logging
import struct

import pytest

from dmac_assistant.containers import BridgeAttachSocket


def _make_frame(stream_id: int, payload: bytes) -> bytes:
    """Build a Docker stdcopy 8-byte-header frame."""
    header = bytes([stream_id, 0, 0, 0]) + struct.pack(">I", len(payload))
    return header + payload


class _RawSocketFake:
    """Raw-socket-shaped fake with both read and recv interfaces."""

    def __init__(self, data: bytes) -> None:
        self._buf = bytearray(data)
        self.sent = bytearray()
        self.shutdown_called: int | None = None
        self.closed = False
        self.read_calls = 0
        self.recv_calls = 0

    def read(self, n: int) -> bytes:
        self.read_calls += 1
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def recv(self, n: int) -> bytes:
        self.recv_calls += 1
        chunk = bytes(self._buf[:n])
        del self._buf[:n]
        return chunk

    def sendall(self, data: bytes) -> None:
        self.sent.extend(data)

    def shutdown(self, how: int) -> None:
        self.shutdown_called = how

    def close(self) -> None:
        self.closed = True


class _SocketIOFake:
    """SocketIO-shaped fake with `._sock` and its own `.recv()`."""

    def __init__(self, sock: _RawSocketFake) -> None:
        self._sock = sock
        self.closed = False
        self.wrapper_recv_calls = 0

    def recv(self, n: int) -> bytes:
        self.wrapper_recv_calls += 1
        return self._sock.recv(n)

    def close(self) -> None:
        self.closed = True


def test_dual_transport_read_frame_socketio() -> None:
    """SocketIO-shaped fake: read_frame demuxes stdout correctly."""
    raw = _RawSocketFake(_make_frame(1, b"hello"))
    wrapper = _SocketIOFake(raw)
    sock = BridgeAttachSocket(wrapper)

    assert sock.read_frame() == ("stdout", b"hello")
    assert raw.recv_calls > 0
    assert raw.read_calls == 0


def test_dual_transport_read_frame_raw_socket_uses_read() -> None:
    """Raw-socket-shaped fake: read_frame demuxes stdout via .read()."""
    raw = _RawSocketFake(_make_frame(1, b"hello"))
    sock = BridgeAttachSocket(raw)

    assert sock.read_frame() == ("stdout", b"hello")
    assert raw.read_calls > 0
    assert raw.recv_calls == 0


def test_dual_transport_send_stdin_socketio() -> None:
    """SocketIO-shaped fake: send_stdin routes through _transport()."""
    raw = _RawSocketFake(b"")
    wrapper = _SocketIOFake(raw)
    sock = BridgeAttachSocket(wrapper)

    sock.send_stdin(b"hi")

    assert bytes(raw.sent) == b"hi"


def test_dual_transport_send_stdin_raw_socket() -> None:
    """Raw-socket-shaped fake: send_stdin routes directly."""
    raw = _RawSocketFake(b"")
    sock = BridgeAttachSocket(raw)

    sock.send_stdin(b"hi")

    assert bytes(raw.sent) == b"hi"


def test_dual_transport_close_stdin_socketio() -> None:
    """SocketIO-shaped fake: close_stdin probes ._sock and shuts down."""
    raw = _RawSocketFake(b"")
    wrapper = _SocketIOFake(raw)
    sock = BridgeAttachSocket(wrapper)

    sock.close_stdin()

    assert raw.shutdown_called == 1


def test_dual_transport_close_stdin_raw_socket() -> None:
    """Raw-socket-shaped fake: close_stdin falls through to _raw.shutdown."""
    raw = _RawSocketFake(b"")
    sock = BridgeAttachSocket(raw)

    sock.close_stdin()

    assert raw.shutdown_called == 1


def test_read_event_line_multi_line_one_frame() -> None:
    """Edge case (a): one stdout frame carries multiple newline-separated lines."""
    frame = _make_frame(1, b"line1\nline2\nline3\n")
    raw = _RawSocketFake(frame)
    sock = BridgeAttachSocket(raw)

    assert sock.read_event_line() == "line1"
    assert sock.read_event_line() == "line2"
    assert sock.read_event_line() == "line3"
    assert sock.read_event_line() is None


def test_read_event_line_line_spans_multiple_frames() -> None:
    """Edge case (b): a line spans two stdout frames."""
    f1 = _make_frame(1, b"partia")
    f2 = _make_frame(1, b"l\nrest\n")
    raw = _RawSocketFake(f1 + f2)
    sock = BridgeAttachSocket(raw)

    assert sock.read_event_line() == "partial"
    assert sock.read_event_line() == "rest"
    assert sock.read_event_line() is None


def test_read_event_line_skips_stderr(caplog: pytest.LogCaptureFixture) -> None:
    """Edge case (c): stderr frames are skipped and logged at DEBUG."""
    f1 = _make_frame(1, b"alpha\n")
    f2 = _make_frame(2, b"diagnostic stderr noise\n")
    f3 = _make_frame(1, b"beta\n")
    raw = _RawSocketFake(f1 + f2 + f3)
    sock = BridgeAttachSocket(raw)

    with caplog.at_level(logging.DEBUG, logger="dmac_assistant.containers"):
        assert sock.read_event_line() == "alpha"
        assert sock.read_event_line() == "beta"
        assert sock.read_event_line() is None

    assert any(
        "diagnostic" in record.message.lower()
        or "stderr" in record.message.lower()
        for record in caplog.records
    ), f"expected DEBUG log on stderr frame; got records: {[r.message for r in caplog.records]}"


def test_read_event_line_eof_with_residual_returns_line_then_none() -> None:
    """Edge case (d): EOF arrives with a partial line in the buffer."""
    frame = _make_frame(1, b"final-line-no-newline")
    raw = _RawSocketFake(frame)
    sock = BridgeAttachSocket(raw)

    assert sock.read_event_line() == "final-line-no-newline"
    assert sock.read_event_line() is None


def test_read_event_line_zero_length_stdout_frame_is_noop() -> None:
    """Edge case (e): zero-length stdout frame mid-stream is a no-op."""
    f1 = _make_frame(1, b"alpha\n")
    f2 = _make_frame(1, b"")
    f3 = _make_frame(1, b"beta\n")
    raw = _RawSocketFake(f1 + f2 + f3)
    sock = BridgeAttachSocket(raw)

    assert sock.read_event_line() == "alpha"
    assert sock.read_event_line() == "beta"
    assert sock.read_event_line() is None
