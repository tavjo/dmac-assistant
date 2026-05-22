"""tests/unit/eval/test_hibayes_combined_report.py — pinning tests for T4.1.

Tests cover: hibayes-import-cleanliness, all-three-present happy path, missing-axis
placeholder + non-zero exit, --allow-partial override, KeyError on wrapper-schema
violation (DL-024), axis-mismatch ValueError (silent-miscategorization guard).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Eval-group dependency: jinja2 lives only inside the hibayes-eval image
# (see pyproject.toml:58 + 66-68). Module-level importorskip lets the host
# bridge venv collect this file but skip every test cleanly. Mirrors the
# precedent at tests/unit/eval/test_render_report.py:23-26.
pytest.importorskip(
    "jinja2",
    reason="eval-group dep; run inside hibayes-eval image",
)

from dmac_assistant.eval.hibayes_combined_report.render import (
    render_combined_report,
    validate_posterior_wrapper_schema,
)


def _write_valid_posterior(path: Path, axis: str) -> None:
    payload = {
        "axis": axis,
        "model": "two_level_group_binomial",
        "prior_sigma_group_scale": 2.0,
        "strata": [
            {
                "task_family": "Search-Basic",
                "n_total": 5,
                "posterior_mean": 0.9,
                "posterior_median": 0.9,
                "hdi_low": 0.7,
                "hdi_high": 0.98,
                "p_success_lt_strong": 0.05,
                "p_success_lt_acceptable": 0.01,
                "band": "Reliable",
            }
        ],
        "metadata": {
            "run_id": "t",
            "axis_input_csv": "x.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_render_module_does_not_import_hibayes() -> None:
    """DL-013: render.py is hibayes-import-clean."""
    src = (
        Path(__file__).resolve().parents[3]
        / "src" / "dmac_assistant" / "eval"
        / "hibayes_combined_report" / "render.py"
    )
    for line in src.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith(("import hibayes", "from hibayes")):
            pytest.fail(f"render.py imports hibayes at module level: {line!r}")


def test_validate_wrapper_schema_accepts_5_top_level_keys(tmp_path: Path) -> None:
    """DL-024: 5 wrapper keys are required; extras allowed."""
    payload = {
        "axis": "artifact",
        "model": "two_level_group_binomial",
        "prior_sigma_group_scale": 2.0,
        "strata": [],
        "metadata": {},
    }
    # Should NOT raise.
    validate_posterior_wrapper_schema(payload, source_label="test")


def test_validate_wrapper_schema_keyerrors_on_missing_top_level_key() -> None:
    """DL-024: KeyError on any missing wrapper key."""
    payload = {
        "axis": "artifact",
        # missing "model"
        "prior_sigma_group_scale": 2.0,
        "strata": [],
        "metadata": {},
    }
    with pytest.raises(KeyError, match="model"):
        validate_posterior_wrapper_schema(payload, source_label="test")


def test_validate_wrapper_schema_keyerrors_on_flat_strata_list() -> None:
    """DL-024 explicit guard: feeding a flat 9-key-list JSON (not wrapped) must fail loud."""
    payload = [
        {"task_family": "X", "n_total": 5, "posterior_mean": 0.9}  # flat list, no wrapper
    ]
    with pytest.raises((KeyError, TypeError)):
        validate_posterior_wrapper_schema(payload, source_label="test")


def test_render_combined_report_axis_mismatch_raises(tmp_path: Path) -> None:
    """D3 guard: passing a runtime posterior.json via --artifact (or any axis
    swap) is a silent-miscategorization risk; render.py MUST validate that
    each argument's posterior['axis'] matches the slot it was passed to.
    """
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"
    # Intentionally write the wrong axis label into the artifact slot.
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "runtime")  # WRONG — should be "artifact"
    _write_valid_posterior(fu, "functional")
    out_html = tmp_path / "combined.html"

    with pytest.raises(ValueError, match="axis"):
        render_combined_report(
            runtime_path=rt,
            artifact_path=av,
            functional_path=fu,
            out_html=out_html,
            allow_partial=False,
        )


def test_render_combined_report_happy_path(tmp_path: Path) -> None:
    """All 3 posterior.json present → exit 0; HTML emitted."""
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    out_html = tmp_path / "combined.html"

    exit_code = render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    assert exit_code == 0
    html = out_html.read_text(encoding="utf-8")
    assert "<html" in html.lower()
    assert "Runtime Reliability" in html or "runtime" in html.lower()
    assert "Artifact Validity" in html or "artifact" in html.lower()
    assert "Functional Usefulness" in html or "functional" in html.lower()


def test_render_combined_report_missing_axis_returns_nonzero(tmp_path: Path) -> None:
    """DD-41: missing axis → placeholder + non-zero exit (unless --allow-partial)."""
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"  # missing intentionally
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    out_html = tmp_path / "combined.html"

    exit_code = render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,  # nonexistent
        out_html=out_html,
        allow_partial=False,
    )
    assert exit_code != 0
    html = out_html.read_text(encoding="utf-8")
    assert "NOT AVAILABLE" in html or "not available" in html.lower()


def test_render_combined_report_allow_partial_override(tmp_path: Path) -> None:
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"  # missing
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    out_html = tmp_path / "combined.html"

    exit_code = render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=True,
    )
    assert exit_code == 0


def test_combined_template_uses_include_directives_for_new_axes() -> None:
    """ESC-5 / locked DD-41 line 388: `combined.html.j2` MUST `{% include %}`
    the artifact + functional axes' section partials (NOT inline them). Runtime
    is intentionally inlined because no runtime section.html.j2 exists in the
    codebase (task-12 adapter is JSON-only; existing runtime module has no
    `report_template/` directory).
    """
    src = (
        Path(__file__).resolve().parents[3]
        / "src" / "dmac_assistant" / "eval"
        / "hibayes_combined_report" / "report_template"
        / "combined.html.j2"
    )
    content = src.read_text(encoding="utf-8")
    # Must contain `{% include %}` directives (at minimum two — one per new axis).
    include_count = content.count("{% include")
    assert include_count >= 2, (
        f"combined.html.j2 must use `{{% include %}}` for the artifact + "
        f"functional axes per locked DD-41 line 388; found {include_count} "
        f"include directives."
    )
    # Must reference the per-axis section partials by their loader keys.
    # (Loader-key naming is documented in Section 6 File 2; the keys are
    # axis-namespaced to avoid `section.html.j2` basename collision.)
    assert "artifact_section.html.j2" in content, (
        "combined.html.j2 must include the artifact axis's section partial by "
        "its loader key `artifact_section.html.j2`."
    )
    assert "functional_section.html.j2" in content, (
        "combined.html.j2 must include the functional axis's section partial "
        "by its loader key `functional_section.html.j2`."
    )


def test_render_combined_report_includes_per_axis_section_content(tmp_path: Path) -> None:
    """ESC-5 / locked DD-41 line 388: end-to-end render pulls in the per-axis
    section partials owned by task-10 / task-11. Verifies the loader is wired
    correctly by asserting rendered HTML contains structural markers that the
    per-axis `section.html.j2` partials actually emit but `combined.html.j2`
    does NOT emit directly: the artifact partial's `hibayes-section--artifact`
    class attribute (task-10 File 8, line 979) and the functional partial's
    `<h2>Functional Usefulness</h2>` heading (task-11 §6 line 311 — task-11's
    only diff from task-10 File 8 is the `<h2>` text substitution, so the
    functional partial's class attribute remains `hibayes-section--artifact`
    and cannot be used as a functional-specific marker).
    """
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    out_html = tmp_path / "combined.html"

    exit_code = render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    assert exit_code == 0
    html = out_html.read_text(encoding="utf-8")
    # Artifact partial emits `class="hibayes-section hibayes-section--artifact"`
    # (task-10 File 8 line 979). Functional partial's only diff from File 8 is
    # `<h2>Artifact Validity</h2>` → `<h2>Functional Usefulness</h2>` (task-11
    # §6 line 311), so its class attribute stays `--artifact`; the heading text
    # is the functional partial's unique structural marker.
    assert "hibayes-section--artifact" in html, (
        "Rendered HTML missing `hibayes-section--artifact` class — the artifact "
        "axis's section partial was not included. Check FileSystemLoader path "
        "discovery in render.py."
    )
    assert "<h2>Functional Usefulness</h2>" in html, (
        "Rendered HTML missing `<h2>Functional Usefulness</h2>` heading — the "
        "functional axis's section partial was not included. Check "
        "FileSystemLoader path discovery in render.py."
    )
