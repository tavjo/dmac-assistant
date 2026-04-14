"""Fetch GitBook source bytes and convert them to markdown via markitdown."""
from __future__ import annotations

import logging
import os
import tempfile

import httpx
from markitdown import MarkItDown

logger = logging.getLogger(__name__)


def fetch_source_bytes(url: str) -> bytes:
    """Fetch raw bytes from a URL, following redirects."""
    logger.info("Fetching source bytes from: %s", url)
    with httpx.Client(timeout=120.0, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
    logger.info("Fetched %d bytes", len(response.content))
    return response.content


def parse_source_to_markdown(source_bytes: bytes) -> str:
    """Convert fetched bytes to markdown using markitdown auto-detection."""
    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(source_bytes)
        temp_path = handle.name
    try:
        md = MarkItDown()
        result = md.convert(temp_path)
        text = result.text_content
        logger.info("Extracted %d characters of markdown", len(text))
        return text
    finally:
        os.unlink(temp_path)
