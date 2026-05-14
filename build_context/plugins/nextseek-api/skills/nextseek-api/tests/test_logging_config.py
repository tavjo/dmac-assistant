"""Tests for scripts/lib/logging_config.py — DD-13 (task-02 / issue #14)."""

from __future__ import annotations

import logging
import sys

from lib.logging_config import configure_quiet_logging


def test_configure_quiet_logging_installs_single_stderr_handler() -> None:
    # Seed root with a bogus stdout handler to prove configure_quiet_logging
    # wipes existing handlers.
    root = logging.getLogger()
    bogus = logging.StreamHandler(sys.stdout)
    root.addHandler(bogus)
    try:
        configure_quiet_logging()
        handlers = root.handlers
        assert len(handlers) == 1
        handler = handlers[0]
        assert isinstance(handler, logging.StreamHandler)
        assert handler.stream is sys.stderr
        # Level floor is WARNING by default.
        assert root.level == logging.WARNING
    finally:
        # Best-effort restore
        for h in list(root.handlers):
            root.removeHandler(h)


def test_configure_quiet_logging_is_idempotent() -> None:
    configure_quiet_logging()
    configure_quiet_logging()
    root = logging.getLogger()
    try:
        assert len(root.handlers) == 1
    finally:
        for h in list(root.handlers):
            root.removeHandler(h)


def test_configure_quiet_logging_honors_level_arg() -> None:
    configure_quiet_logging(level=logging.ERROR)
    try:
        assert logging.getLogger().level == logging.ERROR
    finally:
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)


def test_warnings_land_on_stderr_not_stdout(
    capsys,
) -> None:
    configure_quiet_logging()
    try:
        logging.getLogger("nextseek_client").warning(
            "server_error_retry attempt=1"
        )
        captured = capsys.readouterr()
        assert "server_error_retry" in captured.err
        assert "server_error_retry" not in captured.out
        assert "[nextseek]" in captured.err
    finally:
        root = logging.getLogger()
        for h in list(root.handlers):
            root.removeHandler(h)
