"""T3.1 — Jinja2 section partial renderer consumed by T4.1's combined report."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape


def render_section(*, posterior: dict[str, Any], template_dir: Path) -> str:
    env = Environment(
        loader=FileSystemLoader(str(template_dir)),
        autoescape=select_autoescape(["html", "htm", "j2", "xml"]),
    )
    template = env.get_template("section.html.j2")
    return template.render(posterior=posterior)
