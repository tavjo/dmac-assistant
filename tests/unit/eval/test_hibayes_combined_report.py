"""tests/unit/eval/test_hibayes_combined_report.py — pinning tests for task-17.

Task-17 rewrites the combined HiBayes evaluator HTML report into a single tabbed
report whose three tab panels (runtime / artifact / functional) each match the
visual quality of the existing runtime report. These tests pin:

  1. `render.py` stays hibayes-import-clean (DL-013).
  2. `validate_posterior_wrapper_schema` retained — raises KeyError on a missing
     top-level wrapper key.
  3. `_check_axis` retained — ValueError on a `--runtime/--artifact/--functional`
     argument swap.
  4. The rendered HTML has exactly one tab control with three tab triggers and
     three tab panels keyed `runtime` / `artifact` / `functional`.
  5. Each panel contains its axis heading and a `.table-card` table whose
     header row carries the 9 strata field names.
  6. Each panel contains `.metric` cards and at least two Chart.js `<canvas>`
     elements (posterior-mean + risk, per D8).
  7. The runtime panel embeds exactly two `data:image/png;base64,` images and
     contains no forest-plot element (D5).
  8. The artifact + functional panels each embed three base64 plot images
     including a forest plot (D5).
  9. When an axis's plot inputs omit the forest plot, that panel renders cleanly
     without an empty/broken forest slot.
 10. Happy-path render: all 3 axes present → exit 0; one HTML file written;
     output contains `<canvas` and at least one base64 PNG.
 11. Missing-axis placeholder: a missing axis → that tab shows a placeholder +
     non-zero exit unless `--allow-partial` (DD-41).
 12. `combined.html.j2` contains no `{% include %}` of the deleted per-axis
     `section.html.j2` partials.

Module-level `pytest.importorskip("jinja2")` lets the host bridge venv collect
the file and skip every test cleanly (jinja2 is image-only).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Eval-group dependency: jinja2 lives only inside the hibayes-eval image
# (see pyproject.toml + Dockerfile.hibayes-eval). Module-level importorskip
# lets the host bridge venv collect this file but skip every test cleanly.
# Mirrors tests/unit/eval/test_render_report.py.
pytest.importorskip(
    "jinja2",
    reason="eval-group dep; run inside hibayes-eval image",
)

from dmac_assistant.eval.hibayes_combined_report.render import (
    render_combined_report,
    validate_posterior_wrapper_schema,
)


# --------------------------------------------------------------------------- #
# Fixture helpers                                                             #
# --------------------------------------------------------------------------- #

_NINE_STRATA_FIELDS = (
    "task_family",
    "n_total",
    "posterior_mean",
    "posterior_median",
    "hdi_low",
    "hdi_high",
    "p_success_lt_strong",
    "p_success_lt_acceptable",
    "band",
)


def _write_valid_posterior(path: Path, axis: str) -> None:
    """Write a valid posterior.json with two strata (so band-counts vary)."""
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
            },
            {
                "task_family": "Report-GEO",
                "n_total": 3,
                "posterior_mean": 0.75,
                "posterior_median": 0.76,
                "hdi_low": 0.4,
                "hdi_high": 0.95,
                "p_success_lt_strong": 0.4,
                "p_success_lt_acceptable": 0.2,
                "band": "Watch",
            },
        ],
        "metadata": {
            "run_id": "t",
            "axis_input_csv": "x.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {},
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


# A tiny well-formed PNG (1×1 transparent pixel) — sufficient for "non-empty PNG
# file exists" assertions; the renderer base64-encodes file bytes regardless of
# image content.
_TINY_PNG_BYTES = bytes.fromhex(
    "89504e470d0a1a0a"
    "0000000d49484452"
    "00000001000000010806000000"
    "1f15c4890000000a4944415478da6300010000"
    "0500010d0a2db40000000049454e44ae426082"
)


def _write_plot(plots_dir: Path, name: str) -> Path:
    plots_dir.mkdir(parents=True, exist_ok=True)
    p = plots_dir / name
    p.write_bytes(_TINY_PNG_BYTES)
    return p


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


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


def test_report_has_one_tab_control_with_three_tabs(tmp_path: Path) -> None:
    """Rendered HTML has exactly one tab control with three tab triggers and
    three tab panels keyed `runtime` / `artifact` / `functional`.
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
    # Exactly three tab triggers (the `data-tab` attribute identifies each).
    assert html.count('data-tab="runtime"') == 1
    assert html.count('data-tab="artifact"') == 1
    assert html.count('data-tab="functional"') == 1
    # Exactly three tab panels (the `data-tab-panel` attribute identifies each).
    assert html.count('data-tab-panel="runtime"') == 1
    assert html.count('data-tab-panel="artifact"') == 1
    assert html.count('data-tab-panel="functional"') == 1
    # Exactly one tab control container.
    assert html.count('class="tab-control"') == 1


def test_each_panel_has_axis_heading_and_strata_table(tmp_path: Path) -> None:
    """Each panel contains its axis heading and a `.table-card` table whose
    header row carries the 9 strata field names.
    """
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    out_html = tmp_path / "combined.html"

    render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    html = out_html.read_text(encoding="utf-8")
    assert "Runtime Reliability" in html
    assert "Artifact Validity" in html
    assert "Functional Usefulness" in html
    # At least three `.table-card` instances (one per panel).
    assert html.count('class="table-card"') >= 3
    # All 9 strata field names appear in the HTML (rendered table headers).
    for field in _NINE_STRATA_FIELDS:
        assert field in html, (
            f"strata field {field!r} missing from rendered table headers"
        )


def test_each_panel_has_metric_cards_and_two_charts(tmp_path: Path) -> None:
    """Each panel contains `.metric` cards and at least two Chart.js `<canvas>`
    elements (posterior-mean + risk per D8).
    """
    rt = tmp_path / "runtime.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    out_html = tmp_path / "combined.html"

    render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    html = out_html.read_text(encoding="utf-8")
    # `.metric` is the runtime-template card class; reused per panel — at least
    # 3 metric cards per panel × 3 panels = 9 (family count, total n, bands; we
    # require at least 6 to leave some slack for layout variations).
    assert html.count('class="metric"') >= 6, (
        f"expected at least 6 .metric cards across 3 panels; got "
        f"{html.count('class=\"metric\"')}"
    )
    # At least 6 `<canvas>` elements (2 charts per panel × 3 panels).
    assert html.count("<canvas") >= 6, (
        f"expected at least 6 <canvas> chart elements (2 per panel × 3 "
        f"panels); got {html.count('<canvas')}"
    )


def test_runtime_panel_embeds_two_plots_no_forest(tmp_path: Path) -> None:
    """The runtime panel embeds exactly two `data:image/png;base64,` images and
    contains no forest-plot element (D5).

    Fixture setup: creates the runtime axis's `plots/` dir next to its
    posterior.json (per the §6.1 derivation rule) and writes two PNGs —
    posterior_predictive_plot.png and prior_predictive_plot.png (no
    forest_plot.png).
    """
    rt_dir = tmp_path / "runtime"
    rt_dir.mkdir()
    rt = rt_dir / "posterior.json"
    av = tmp_path / "artifact.json"
    fu = tmp_path / "functional.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    # Runtime axis: two plots, no forest.
    rt_plots = rt_dir / "plots"
    _write_plot(rt_plots, "posterior_predictive_plot.png")
    _write_plot(rt_plots, "prior_predictive_plot.png")
    # No plots for artifact/functional in this test — keeps focus on runtime.
    out_html = tmp_path / "combined.html"

    render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    html = out_html.read_text(encoding="utf-8")
    # Isolate the runtime panel (the substring between its opening
    # `data-tab-panel="runtime"` and the next `data-tab-panel=` delimiter).
    panel_open = html.index('data-tab-panel="runtime"')
    after_runtime = html[panel_open:]
    next_panel = after_runtime.find('data-tab-panel="artifact"')
    runtime_panel = (
        after_runtime if next_panel == -1 else after_runtime[:next_panel]
    )
    # Exactly two embedded base64 PNGs in the runtime panel.
    assert runtime_panel.count("data:image/png;base64,") == 2, (
        f"runtime panel must embed exactly 2 base64 PNGs; got "
        f"{runtime_panel.count('data:image/png;base64,')}"
    )
    # No forest-plot marker in the runtime panel.
    assert "forest_plot" not in runtime_panel, (
        "runtime panel must NOT include a forest-plot element (D5)"
    )
    assert 'alt="forest_plot' not in runtime_panel


def test_new_axis_panels_embed_three_plots_incl_forest(tmp_path: Path) -> None:
    """The artifact and functional panels each embed three base64 plot images
    including a forest plot (D5).
    """
    rt = tmp_path / "runtime.json"
    av_dir = tmp_path / "artifact"
    av_dir.mkdir()
    av = av_dir / "posterior.json"
    fu_dir = tmp_path / "functional"
    fu_dir.mkdir()
    fu = fu_dir / "posterior.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    # Artifact axis: all three plots.
    av_plots = av_dir / "plots"
    _write_plot(av_plots, "posterior_predictive_plot.png")
    _write_plot(av_plots, "prior_predictive_plot.png")
    _write_plot(av_plots, "forest_plot.png")
    # Functional axis: all three plots.
    fu_plots = fu_dir / "plots"
    _write_plot(fu_plots, "posterior_predictive_plot.png")
    _write_plot(fu_plots, "prior_predictive_plot.png")
    _write_plot(fu_plots, "forest_plot.png")
    out_html = tmp_path / "combined.html"

    render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    html = out_html.read_text(encoding="utf-8")
    # Isolate each panel by its `data-tab-panel="..."` delimiter.
    def _panel(name: str, next_name: str | None) -> str:
        start = html.index(f'data-tab-panel="{name}"')
        rest = html[start:]
        if next_name is None:
            return rest
        end_marker = f'data-tab-panel="{next_name}"'
        end = rest.find(end_marker)
        return rest if end == -1 else rest[:end]

    artifact_panel = _panel("artifact", "functional")
    functional_panel = _panel("functional", None)
    assert artifact_panel.count("data:image/png;base64,") == 3, (
        f"artifact panel must embed exactly 3 base64 PNGs; got "
        f"{artifact_panel.count('data:image/png;base64,')}"
    )
    assert functional_panel.count("data:image/png;base64,") == 3, (
        f"functional panel must embed exactly 3 base64 PNGs; got "
        f"{functional_panel.count('data:image/png;base64,')}"
    )
    # Both new-axis panels must contain a forest-plot marker.
    assert "forest_plot" in artifact_panel
    assert "forest_plot" in functional_panel


def test_forest_slot_omitted_when_axis_lacks_forest_plot(tmp_path: Path) -> None:
    """When an axis's plot inputs omit the forest plot, that panel renders
    cleanly without an empty/broken forest slot.
    """
    rt = tmp_path / "runtime.json"
    av_dir = tmp_path / "artifact"
    av_dir.mkdir()
    av = av_dir / "posterior.json"
    fu = tmp_path / "functional.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    # Artifact axis: posterior + prior, NO forest.
    av_plots = av_dir / "plots"
    _write_plot(av_plots, "posterior_predictive_plot.png")
    _write_plot(av_plots, "prior_predictive_plot.png")
    out_html = tmp_path / "combined.html"

    render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    html = out_html.read_text(encoding="utf-8")
    # Isolate the artifact panel.
    art_start = html.index('data-tab-panel="artifact"')
    rest = html[art_start:]
    next_marker = rest.find('data-tab-panel="functional"')
    artifact_panel = rest if next_marker == -1 else rest[:next_marker]
    # Exactly two PNGs (no forest).
    assert artifact_panel.count("data:image/png;base64,") == 2, (
        f"artifact panel without forest plot must embed exactly 2 PNGs; got "
        f"{artifact_panel.count('data:image/png;base64,')}"
    )
    # Crucially: no forest_plot marker (no empty/broken slot).
    assert "forest_plot" not in artifact_panel, (
        "artifact panel must NOT include a forest-plot slot when forest_plot.png "
        "is absent"
    )
    # And no orphan `<img ... src="data:image/png;base64," ...>` (no empty src).
    assert 'src="data:image/png;base64,"' not in artifact_panel


def test_render_combined_report_happy_path(tmp_path: Path) -> None:
    """All 3 axes present → exit 0; one HTML file written; output contains
    `<canvas` and at least one base64 PNG.
    """
    rt_dir = tmp_path / "runtime"
    rt_dir.mkdir()
    rt = rt_dir / "posterior.json"
    av_dir = tmp_path / "artifact"
    av_dir.mkdir()
    av = av_dir / "posterior.json"
    fu_dir = tmp_path / "functional"
    fu_dir.mkdir()
    fu = fu_dir / "posterior.json"
    _write_valid_posterior(rt, "runtime")
    _write_valid_posterior(av, "artifact")
    _write_valid_posterior(fu, "functional")
    # One plot per axis is enough for the base64-PNG assertion.
    _write_plot(rt_dir / "plots", "posterior_predictive_plot.png")
    _write_plot(av_dir / "plots", "posterior_predictive_plot.png")
    _write_plot(fu_dir / "plots", "posterior_predictive_plot.png")
    out_html = tmp_path / "combined.html"

    exit_code = render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=False,
    )
    assert exit_code == 0
    assert out_html.is_file()
    html = out_html.read_text(encoding="utf-8")
    assert "<canvas" in html
    assert "data:image/png;base64," in html


def test_render_combined_report_missing_axis_placeholder(tmp_path: Path) -> None:
    """A missing axis → that tab shows a placeholder + non-zero exit unless
    `--allow-partial` (DD-41).
    """
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

    # With --allow-partial the same missing-axis configuration must exit 0.
    exit_code_partial = render_combined_report(
        runtime_path=rt,
        artifact_path=av,
        functional_path=fu,
        out_html=out_html,
        allow_partial=True,
    )
    assert exit_code_partial == 0


def test_no_obsolete_section_partials_referenced() -> None:
    """`combined.html.j2` contains no `{% include %}` of the deleted per-axis
    `section.html.j2` partials. Task-17 D1 removes the partial mechanism.
    """
    src = (
        Path(__file__).resolve().parents[3]
        / "src" / "dmac_assistant" / "eval"
        / "hibayes_combined_report" / "report_template"
        / "combined.html.j2"
    )
    content = src.read_text(encoding="utf-8")
    assert "{% include" not in content, (
        "combined.html.j2 must not include any external partials — task-17 D1 "
        "removed the per-axis section.html.j2 mechanism."
    )
    assert "artifact_section.html.j2" not in content
    assert "functional_section.html.j2" not in content
    assert "section.html.j2" not in content
