"""FastAPI app entrypoint for the DMAC bridge bootstrap.

Wave 1 intentionally ships only a module-level `app` object and a `/health`
route. Later waves wire the WebSocket bridge onto the same FastAPI app.
"""
from __future__ import annotations

from fastapi import FastAPI

from dmac_assistant.auth import router as auth_router
from dmac_assistant.ws import router as ws_router


app = FastAPI(title="DMAC Assistant Bridge", version="0.1.0")
app.include_router(auth_router)
app.include_router(ws_router, prefix="/ws", tags=["ws"])


@app.get("/health")
def health() -> dict[str, str]:
    """Basic liveness probe for the bridge skeleton."""
    return {"status": "ok"}


if __name__ == "__main__":  # pragma: no cover
    import os

    import uvicorn

    uvicorn.run(
        "dmac_assistant.app:app",
        host=os.environ.get("DMAC_BRIDGE_HOST", "127.0.0.1"),
        port=int(os.environ.get("DMAC_BRIDGE_PORT", "8000")),
        log_level="info",
    )
