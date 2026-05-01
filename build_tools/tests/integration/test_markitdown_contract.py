"""Pin the load-bearing markitdown heading-preservation contract."""
from __future__ import annotations

import os
import tempfile

from markitdown import MarkItDown

from build_tools.tests.conftest import make_synthetic_html


def test_markitdown_preserves_h1_from_html_in_pdf_suffixed_tempfile() -> None:
    """HTML bytes in a .pdf tempfile must still yield markdown H1 headings."""
    source_bytes = make_synthetic_html([("Hello World", "Body paragraph here.")])

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
        handle.write(source_bytes)
        path = handle.name

    try:
        result = MarkItDown().convert(path)
        text = result.text_content
    finally:
        os.unlink(path)

    assert "# Hello World" in text, (
        f"markitdown did not preserve <h1> as '# Hello World'. Got: {text[:500]!r}"
    )
    assert "Body paragraph here." in text
