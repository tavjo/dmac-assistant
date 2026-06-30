"""Thin wrapper around markitdown for extracting text from user-supplied files
(protocols, PDFs, docx, pptx, xlsx, html, ...). markitdown is image-only; this
module lazy-imports it so host unit tests can mock it."""
from __future__ import annotations

import sys


def extract_text(path: str) -> str:
    try:
        from markitdown import MarkItDown
    except ImportError:
        sys.stderr.write("nextseek-error: CONFIG_MISSING — markitdown not installed (image-only)\n")
        raise SystemExit(2)
    result = MarkItDown().convert(path)
    return getattr(result, "text_content", "") or ""
