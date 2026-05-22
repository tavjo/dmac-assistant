"""T4.1 — Combined HTML report renderer.

Reads three posterior.json files (runtime + artifact + functional) and emits
hibayes_combined_report.html. Hibayes-import-clean (locked DD-41 + plan DL-013).

Per locked DD-41 partial-failure behavior:
- Render placeholder section for each missing axis.
- Exit non-zero by default if any expected axis is missing; --allow-partial overrides.

ESC-5 resolution (Hardener Pass 2, 2026-05-18): per locked DD-41 line 388,
combined.html.j2 uses `{% include %}` for the artifact + functional axes'
section partials (owned by task-10 / task-11). The runtime axis is rendered
INLINE in combined.html.j2 because task-12 (the runtime CSV→JSON adapter)
does NOT emit a section.html.j2 and the existing runtime module has no
`report_template/` directory. The Jinja2 FileSystemLoader is configured with
three search paths and the per-axis partials are exposed under unique loader
keys (`artifact_section.html.j2`, `functional_section.html.j2`) via a small
DictLoader → ChoiceLoader chain to avoid `section.html.j2` basename collision
across the three FileSystemLoader search paths.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape


REQUIRED_WRAPPER_KEYS: frozenset[str] = frozenset(
    {"axis", "model", "prior_sigma_group_scale", "strata", "metadata"}
)


def validate_posterior_wrapper_schema(
    payload: Any,
    *,
    source_label: str,
) -> None:
    """Raise KeyError if `payload` is missing any of the 5 top-level wrapper keys.

    Also raises TypeError if `payload` is not a dict (e.g., someone fed a flat
    strata list instead of the wrapped object).
    """
    if not isinstance(payload, dict):
        raise TypeError(
            f"posterior.json from {source_label}: expected dict with wrapper keys "
            f"{sorted(REQUIRED_WRAPPER_KEYS)}; got {type(payload).__name__}"
        )
    missing = REQUIRED_WRAPPER_KEYS - set(payload.keys())
    if missing:
        raise KeyError(
            f"posterior.json from {source_label}: missing top-level wrapper keys "
            f"{sorted(missing)}; required: {sorted(REQUIRED_WRAPPER_KEYS)}"
        )


def _load_posterior(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    payload = json.loads(path.read_text(encoding="utf-8"))
    validate_posterior_wrapper_schema(payload, source_label=str(path))
    return payload


def _check_axis(
    payload: dict[str, Any] | None, expected_axis: str, *, source_label: str
) -> None:
    """Raise ValueError if the loaded posterior's axis label disagrees with
    the slot it was passed to. Guards against operators swapping the
    --runtime / --artifact / --functional CLI arguments and producing a
    silently miscategorized combined report.
    """
    if payload is None:
        return
    actual = payload.get("axis")
    if actual != expected_axis:
        raise ValueError(
            f"posterior.json from {source_label}: axis mismatch — "
            f"expected axis={expected_axis!r}, got axis={actual!r}. "
            f"This usually means the --runtime / --artifact / --functional "
            f"CLI arguments were passed in the wrong order."
        )


def _discover_axis_section_partial(axis_module_dotted: str) -> str | None:
    """Locate a per-axis `report_template/section.html.j2` partial via Python
    module-relative path discovery.

    Returns the file's text content (so it can be registered under an
    axis-namespaced loader key) or None if the module / partial is absent
    (e.g., when running host-side tests before the per-axis module's files
    have been materialized by task-10 / task-11).

    Args:
        axis_module_dotted: e.g.
            `dmac_assistant.eval.hibayes_artifact_validity` or
            `dmac_assistant.eval.hibayes_functional_usefulness`.
    """
    import importlib.util

    spec = importlib.util.find_spec(axis_module_dotted)
    if spec is None or spec.origin is None:
        return None
    module_dir = Path(spec.origin).parent
    partial = module_dir / "report_template" / "section.html.j2"
    if not partial.is_file():
        return None
    return partial.read_text(encoding="utf-8")


def _build_jinja_environment() -> Environment:
    """Configure the Jinja2 environment so `combined.html.j2` can `{% include %}`
    the artifact + functional axes' section partials per locked DD-41 line 388.

    Loader layout (resolution order via ChoiceLoader):
      1. DictLoader exposing the artifact axis's `section.html.j2` content
         under the loader key `artifact_section.html.j2`.
      2. DictLoader exposing the functional axis's `section.html.j2` content
         under the loader key `functional_section.html.j2`.
      3. FileSystemLoader pointed at the combined-report's own
         `report_template/` directory (which contains `combined.html.j2`).

    The DictLoader indirection sidesteps `section.html.j2` basename collision
    across the three per-axis FileSystemLoaders. If a per-axis partial is
    missing (e.g., host-side tests before task-10 / task-11 have landed), the
    corresponding key is omitted from the DictLoader; the `{% include %}` will
    then raise `jinja2.TemplateNotFound` at render time — fail-loud, matching
    DD-41's render-policy posture.
    """
    combined_template_dir = Path(__file__).parent / "report_template"

    per_axis_templates: dict[str, str] = {}
    artifact_partial = _discover_axis_section_partial(
        "dmac_assistant.eval.hibayes_artifact_validity"
    )
    if artifact_partial is not None:
        per_axis_templates["artifact_section.html.j2"] = artifact_partial
    functional_partial = _discover_axis_section_partial(
        "dmac_assistant.eval.hibayes_functional_usefulness"
    )
    if functional_partial is not None:
        per_axis_templates["functional_section.html.j2"] = functional_partial

    loader = ChoiceLoader(
        [
            DictLoader(per_axis_templates),
            FileSystemLoader(str(combined_template_dir)),
        ]
    )
    return Environment(
        loader=loader,
        autoescape=select_autoescape(["html", "htm", "j2", "xml"]),
    )


def render_combined_report(
    *,
    runtime_path: Path,
    artifact_path: Path,
    functional_path: Path,
    out_html: Path,
    allow_partial: bool,
) -> int:
    runtime = _load_posterior(runtime_path)
    artifact = _load_posterior(artifact_path)
    functional = _load_posterior(functional_path)

    _check_axis(runtime, "runtime", source_label=str(runtime_path))
    _check_axis(artifact, "artifact", source_label=str(artifact_path))
    _check_axis(functional, "functional", source_label=str(functional_path))

    env = _build_jinja_environment()
    template = env.get_template("combined.html.j2")

    html = template.render(
        runtime=runtime,
        artifact=artifact,
        functional=functional,
        missing_axes=[
            label
            for label, payload in [
                ("runtime", runtime),
                ("artifact", artifact),
                ("functional", functional),
            ]
            if payload is None
        ],
    )
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(html, encoding="utf-8")

    any_missing = any(p is None for p in (runtime, artifact, functional))
    if any_missing and not allow_partial:
        return 1
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dmac_assistant.eval.hibayes_combined_report.render",
    )
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--functional", type=Path, required=True)
    parser.add_argument("--out-html", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true")
    args = parser.parse_args(argv)
    return render_combined_report(
        runtime_path=args.runtime,
        artifact_path=args.artifact,
        functional_path=args.functional,
        out_html=args.out_html,
        allow_partial=args.allow_partial,
    )


if __name__ == "__main__":
    import sys
    sys.exit(main())
