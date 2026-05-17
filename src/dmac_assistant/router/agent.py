"""Bridge-side BAML wrapper for the LLM router."""
from __future__ import annotations

import asyncio
import logging

from dmac_assistant.router.baml_client import b
from dmac_assistant.router.baml_client.types import (
    ModelClass,
    Route,
    RouteCapability,
    RouterDecision,
    RouterInput,
)
from dmac_assistant.router.capabilities import load_capabilities


log = logging.getLogger(__name__)

_FALLBACK_REASONING = "<router_unavailable>"


def _fallback_decision() -> RouterDecision:
    return RouterDecision(
        route=Route.ContainerCC,
        model_class=ModelClass.Sonnet,
        reasoning=_FALLBACK_REASONING,
    )


class RouterAgent:
    """Async router wrapper around BAML's RouteQuery function."""

    def __init__(self, capabilities: list[RouteCapability] | None = None) -> None:
        if capabilities is None:
            capabilities = load_capabilities()
        self._capabilities = capabilities

    async def route(self, user_query: str) -> RouterDecision:
        """Return a router decision, falling back if the BAML call fails."""
        request = RouterInput(
            user_query=user_query,
            routes=self._capabilities,
        )
        try:
            return await b.RouteQuery(input=request)
        except asyncio.CancelledError:
            raise
        except BaseException as exc:  # noqa: BLE001 - broad catch required by router spec
            log.warning(
                "router_fallback",
                extra={
                    "router_fallback": True,
                    "exc_type": type(exc).__name__,
                },
            )
            return _fallback_decision()
