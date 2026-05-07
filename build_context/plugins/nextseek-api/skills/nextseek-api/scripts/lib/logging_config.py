"""Quiet-by-default logging for the nextseek-api plugin.

The init bootstrap and per-query scripts must not leak retry/timeout warnings
(e.g. ``server_error_retry``, ``request_timeout``) to stdout, because stdout
is consumed by downstream tools (Read of endpoints_minimal.json, piped JSON
validation, etc.). This module forces the root logger to a single stderr
handler at WARNING+ level with a tidy prefix.

Design decision DD-13 (task-02): all library warnings go to stderr, prefixed
with ``[nextseek]``, so the human reader can distinguish plugin chatter from
the quiet success output on stdout.
"""

from __future__ import annotations

import logging
import sys

_FORMAT = "[nextseek] %(levelname)s %(name)s: %(message)s"


def configure_quiet_logging(level: int = logging.WARNING) -> None:
    """Route the root logger to a single stderr handler.

    Removes any pre-existing handlers (library defaults sometimes attach a
    stdout ``StreamHandler``) and installs one ``StreamHandler(sys.stderr)``
    with a short, prefixed format. Idempotent — safe to call repeatedly.

    Args:
        level: logging level floor; defaults to ``logging.WARNING`` so INFO
            chatter from ``nextseek_client`` / ``schema_rag_client`` never
            reaches the terminal during a successful bootstrap.
    """
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter(_FORMAT))
    root.addHandler(handler)
    root.setLevel(level)
