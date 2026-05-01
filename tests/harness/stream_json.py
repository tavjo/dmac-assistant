"""Parser helpers for Claude Code ``--output-format stream-json`` output."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Generator, Iterable


class StreamJSONParseError(ValueError):
    """Raised when a line cannot be decoded in strict mode."""


def _iter_lines(raw: bytes | str) -> Iterable[tuple[int, str]]:
    if isinstance(raw, bytes):
        text = raw.decode("utf-8-sig", errors="strict")
    else:
        text = raw

    for idx, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        yield idx, line


def parse_stream(
    raw: bytes | str,
    *,
    strict: bool = True,
) -> Generator[dict[str, Any], None, None]:
    """Yield decoded stream-json events from captured Claude stdout."""
    for lineno, line in _iter_lines(raw):
        try:
            yield json.loads(line)
        except json.JSONDecodeError as exc:
            if strict:
                raise StreamJSONParseError(
                    f"stream-json decode failed on line {lineno}: {exc.msg}"
                ) from exc
            continue


@dataclass
class ToolUseEvent:
    """One ``tool_use`` content block observed in an ``assistant`` event."""

    id: str | None
    name: str | None
    input: dict[str, Any] | None


@dataclass
class StreamJSONParser:
    """Stateful accumulator over Claude stream-json events."""

    assistant_texts: list[str] = field(default_factory=list)
    tool_uses: list[ToolUseEvent] = field(default_factory=list)
    final_usage: dict[str, Any] | None = None
    final_result: dict[str, Any] | None = None

    def feed(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "assistant":
            message = event.get("message") or {}
            content = message.get("content") or []
            for block in content:
                if not isinstance(block, dict):
                    continue
                btype = block.get("type")
                if btype == "text":
                    text = block.get("text")
                    if isinstance(text, str):
                        self.assistant_texts.append(text)
                elif btype == "tool_use":
                    raw_input = block.get("input")
                    self.tool_uses.append(
                        ToolUseEvent(
                            id=block.get("id"),
                            name=block.get("name"),
                            input=raw_input if isinstance(raw_input, dict) else None,
                        )
                    )
        elif etype == "result":
            self.final_result = event
            usage = event.get("usage")
            if isinstance(usage, dict):
                self.final_usage = usage

    def contains_text(self, needle: str) -> bool:
        """Return True when any assistant text block contains ``needle``."""
        return any(needle in text for text in self.assistant_texts)

    def tool_use_events(self) -> list[ToolUseEvent]:
        """Return every observed ``tool_use`` block in order."""
        return list(self.tool_uses)
