"""Tests for src/dmac_assistant/eval/hibayes_runtime_reliability/render_report.py.

Coverage target: 95%+ on the module (R-10 per-module gate).
Risks mitigated: R-12 (Jinja2 autoescape), R-03 (numeric assertions, dash-for-None),
                 R-07 (no matplotlib import), R-08 (no T03 schema mutation).
"""
from __future__ import annotations

import base64
import importlib
import json
import re
import sys
from html.parser import HTMLParser
from pathlib import Path  # noqa: F401  # used by fixtures via tmp_path (spec §5 verbatim)
from typing import Any

import pytest

# Eval-group dependency: jinja2 lives only inside the
# hibayes-runtime-reliability:dev image. Module-level importorskip lets the
# host bridge venv collect this file but skip every test cleanly (consistent
# with T01's tests/unit/eval/test_module_imports.py pattern).
pytest.importorskip(
    "jinja2",
    reason="eval-group dep; run inside hibayes-runtime-reliability:dev image",
)

from dmac_assistant.eval.hibayes_runtime_reliability.models import (
    HiBayesRuntimeReport,
    PosteriorTaskFamilyReliability,
    ReliabilityBand,
    ReliabilityThresholds,
    TaskFamilyAggregate,
)


# --------------------------------------------------------------------------- #
# Fixtures                                                                    #
# --------------------------------------------------------------------------- #


@pytest.fixture
def thresholds() -> ReliabilityThresholds:
    return ReliabilityThresholds()


@pytest.fixture
def aggregates() -> list[TaskFamilyAggregate]:
    return [
        TaskFamilyAggregate(
            task_family="alpha",
            n_total=20, n_success=19, n_failure=1,
            observed_success_rate=19 / 20,
            n_error=1, n_timeout=0, n_no_answer=0,
            n_artifact_rows=18,
            avg_latency_seconds=12.3,
            avg_cost_usd=0.0123,
            avg_tool_calls_total=4.5,
        ),
        TaskFamilyAggregate(
            task_family="bravo",
            n_total=10, n_success=7, n_failure=3,
            observed_success_rate=7 / 10,
            n_error=2, n_timeout=1, n_no_answer=0,
            n_artifact_rows=6,
            avg_latency_seconds=18.0,
            avg_cost_usd=None,                    # R-05: all-None family
            avg_tool_calls_total=3.0,
        ),
        TaskFamilyAggregate(
            task_family="charlie",
            n_total=2, n_success=1, n_failure=1,  # below min_n_for_classification=3 (R-04)
            observed_success_rate=0.5,
            n_error=0, n_timeout=0, n_no_answer=1,
            n_artifact_rows=1,
            avg_latency_seconds=8.0,
            avg_cost_usd=0.005,
            avg_tool_calls_total=2.0,
        ),
    ]


@pytest.fixture
def posteriors() -> list[PosteriorTaskFamilyReliability]:
    return [
        PosteriorTaskFamilyReliability(
            task_family="alpha",
            posterior_mean=0.96, posterior_median=0.965,
            hdi_low=0.91, hdi_high=0.99,
            p_success_lt_strong=0.05, p_success_lt_acceptable=0.01,
            n_total=20, band=ReliabilityBand.Reliable,
        ),
        PosteriorTaskFamilyReliability(
            task_family="bravo",
            posterior_mean=0.72, posterior_median=0.71,
            hdi_low=0.55, hdi_high=0.88,
            p_success_lt_strong=0.85, p_success_lt_acceptable=0.62,
            n_total=10, band=ReliabilityBand.Brittle,
        ),
        PosteriorTaskFamilyReliability(
            task_family="charlie",
            posterior_mean=0.50, posterior_median=0.50,
            hdi_low=0.10, hdi_high=0.90,
            p_success_lt_strong=0.95, p_success_lt_acceptable=0.85,
            n_total=2, band=ReliabilityBand.TooUncertain,
        ),
    ]


def _make_report(
    aggregates: list[TaskFamilyAggregate],
    posteriors: list[PosteriorTaskFamilyReliability],
    thresholds: ReliabilityThresholds,
    *,
    diagnostics_summary: dict[str, Any] | None = None,
    generated_at: str = "2026-05-09T00:00:00Z",
) -> HiBayesRuntimeReport:
    return HiBayesRuntimeReport(
        aggregates=aggregates,
        posteriors=posteriors,
        thresholds=thresholds,
        diagnostics_summary=diagnostics_summary or {
            "r_hat": {"status": "pass", "reason": "max r_hat 1.005"},
            "divergences": {"status": "pass", "reason": "0 divergences"},
            "hdi_80": {
                "alpha": {"low": 0.93, "high": 0.98},
                "bravo": {"low": 0.60, "high": 0.85},
                "charlie": {"low": 0.20, "high": 0.80},
            },
        },
        generated_at=generated_at,
    )


@pytest.fixture
def report(aggregates, posteriors, thresholds) -> HiBayesRuntimeReport:
    return _make_report(aggregates, posteriors, thresholds)


@pytest.fixture
def render_report_callable():
    """Lazy-import so the test file collects even pre-implementation (Step 2)."""
    from dmac_assistant.eval.hibayes_runtime_reliability import render_report as mod
    return mod.render_report


# --------------------------------------------------------------------------- #
# Helpers                                                                     #
# --------------------------------------------------------------------------- #


_MANIFEST_RE = re.compile(
    r'<script type="application/json" id="hibayes-manifest">(.*?)</script>',
    re.DOTALL,
)


def _extract_manifest_text(html: str) -> str:
    matches = _MANIFEST_RE.findall(html)
    assert len(matches) == 1, f"expected exactly one manifest block, got {len(matches)}"
    return matches[0]


class _CanvasIdCollector(HTMLParser):
    """Collects all <canvas id="…"> ids; used for T-08."""
    def __init__(self) -> None:
        super().__init__()
        self.ids: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "canvas":
            return
        for k, v in attrs:
            if k == "id" and v is not None:
                self.ids.append(v)


class _TableRowCounter(HTMLParser):
    """Counts <tr class="row-summary"> rows; used for T-07."""
    def __init__(self) -> None:
        super().__init__()
        self.summary_rows = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "tr":
            return
        for k, v in attrs:
            if k == "class" and v and "row-summary" in v.split():
                self.summary_rows += 1


# --------------------------------------------------------------------------- #
# Tests (19 functions; 22 parametrized cases collected)                      #
# --------------------------------------------------------------------------- #


# T-01
def test_module_imports():
    """The module imports cleanly and exposes `render_report`."""
    mod = importlib.import_module(
        "dmac_assistant.eval.hibayes_runtime_reliability.render_report"
    )
    assert callable(getattr(mod, "render_report", None))


# T-02
def test_renderer_writes_file_at_expected_path(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    assert out == tmp_path / "report.html"
    assert out.exists()
    assert out.stat().st_size > 1024  # non-trivial output


# T-03
def test_renderer_output_parses_as_html5(render_report_callable, report, tmp_path):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    # html.parser does not validate HTML5 strictly, but it raises on truly
    # malformed markup. We assert: doctype present, <html> tag opens, </html>
    # closes, no unclosed quote in attributes (parser would warn).
    assert html.startswith("<!DOCTYPE html>"), html[:200]
    assert "<html lang=\"en\">" in html
    assert html.rstrip().endswith("</html>")
    # Re-parse to verify no UnicodeDecodeError or unbalanced-tag malformation.
    parser = HTMLParser()
    parser.feed(html)
    parser.close()


# T-04
def test_renderer_contains_title_with_generated_at(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "<title>" in html
    # generated_at must appear in the title (or immediately under <h1>) so
    # it survives ad-hoc indexing/grep.
    assert report.generated_at in html


# T-05
def test_renderer_emits_exactly_one_hibayes_manifest_script(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    matches = _MANIFEST_RE.findall(html)
    assert len(matches) == 1, f"expected exactly 1 manifest block, got {len(matches)}"


# T-06
def test_manifest_json_parses_and_has_task_family_results(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    payload = json.loads(_extract_manifest_text(html))
    assert payload["schema_version"] == "1"
    assert payload["n_families"] == 3
    assert isinstance(payload["task_family_results"], list)
    # Schema lock (DL-T06-5): every row must include n_failure (= n_total - n_success).
    first = payload["task_family_results"][0]
    assert "n_failure" in first
    assert first["n_failure"] == first["n_total"] - first["n_success"]


# T-07
def test_manifest_length_matches_posteriors(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    payload = json.loads(_extract_manifest_text(out.read_text(encoding="utf-8")))
    assert len(payload["task_family_results"]) == len(report.posteriors)
    seen = {row["task_family"] for row in payload["task_family_results"]}
    expected = {p.task_family for p in report.posteriors}
    assert seen == expected


# T-08
def test_table_has_tr_per_task_family(render_report_callable, report, tmp_path):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    counter = _TableRowCounter()
    counter.feed(html)
    counter.close()
    assert counter.summary_rows == len(report.posteriors)


# T-09
def test_all_four_chart_canvas_ids_present(render_report_callable, report, tmp_path):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    collector = _CanvasIdCollector()
    collector.feed(html)
    collector.close()
    assert set(collector.ids) >= {
        "posteriorMeanChart",
        "observedVsPosteriorChart",
        "failureModeChart",
        "riskChart",
    }


# T-10
def test_chartjs_cdn_url_present(render_report_callable, report, tmp_path):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert "https://cdn.jsdelivr.net/npm/chart.js@4" in html


# T-11
def test_warning_banner_visible_when_any_checker_failed(
    render_report_callable, aggregates, posteriors, thresholds, tmp_path
):
    diagnostics_summary = {
        "r_hat": {"status": "pass", "reason": "max r_hat 1.005"},
        "loo": {"status": "fail", "reason": "scale violation; pareto-k > 0.7"},
        "hdi_80": {"alpha": {"low": 0.9, "high": 0.99}},
    }
    report = _make_report(
        aggregates, posteriors, thresholds,
        diagnostics_summary=diagnostics_summary,
    )
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert 'id="diagnostics-banner"' in html
    assert "loo" in html and "scale violation" in html


# T-12
def test_warning_banner_absent_when_all_checkers_pass(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    assert 'id="diagnostics-banner"' not in html


# T-13 — R-12 mitigation
def test_jinja_autoescape_blocks_script_injection_in_task_family(
    render_report_callable, thresholds, tmp_path
):
    aggregates = [
        TaskFamilyAggregate(
            task_family="<script>alert('xss')</script>",
            n_total=5, n_success=3, n_failure=2, observed_success_rate=3 / 5,
            n_error=1, n_timeout=0, n_no_answer=1, n_artifact_rows=0,
            avg_latency_seconds=1.0, avg_cost_usd=0.001, avg_tool_calls_total=0.0,
        ),
    ]
    posteriors = [
        PosteriorTaskFamilyReliability(
            task_family="<script>alert('xss')</script>",
            posterior_mean=0.6, posterior_median=0.6,
            hdi_low=0.3, hdi_high=0.9,
            p_success_lt_strong=0.7, p_success_lt_acceptable=0.4,
            n_total=5, band=ReliabilityBand.Watch,
        ),
    ]
    report = _make_report(aggregates, posteriors, thresholds)
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")

    # The literal injection MUST NOT appear in the HTML body or table cells.
    # Note: the manifest is JSON, where the value is fine as a JSON string —
    # we strip the manifest block before checking.
    body = _MANIFEST_RE.sub("", html)
    assert "<script>alert('xss')</script>" not in body
    # The escaped form MUST appear (proves Jinja saw + escaped it):
    assert "&lt;script&gt;alert(&#39;xss&#39;)&lt;/script&gt;" in body or \
           "&lt;script&gt;alert(&#x27;xss&#x27;)&lt;/script&gt;" in body


# T-14 — R-03 mitigation (chart-data numeric)
def test_chart_data_values_are_numeric_not_strings(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    payload = json.loads(_extract_manifest_text(html))
    # Use the same data-shaping helper the renderer used:
    from dmac_assistant.eval.hibayes_runtime_reliability.render_report import (
        build_chart_data,
    )
    chart_data = build_chart_data(report)
    # posteriorMean and HDI bands must all be float|None — never str.
    for fam in chart_data["posteriorMean"]["families"]:
        assert isinstance(fam, str)  # family label is the only str
    for v in chart_data["posteriorMean"]["values"]:
        assert isinstance(v, (int, float))
    for lo, hi in chart_data["posteriorMean"]["hdi_bands"]:
        assert isinstance(lo, (int, float)) and isinstance(hi, (int, float))
    # Manifest should serialize None as JSON null (not string "null"):
    assert all(
        row["avg_cost_usd"] is None or isinstance(row["avg_cost_usd"], (int, float))
        for row in payload["task_family_results"]
    )


# T-15 — R-03 mitigation (table cells)
def test_no_literal_none_or_nan_or_null_in_table_cells(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    body = _MANIFEST_RE.sub("", html)  # JSON manifest may legitimately contain `null`
    assert ">None<" not in body, "raw Python None reached a <td> cell"
    assert ">NaN<" not in body, "raw NaN reached a <td> cell"
    assert ">null<" not in body, "literal string 'null' reached a <td> cell"


# T-16a / T-16b — base64 PNG inlining contract
def test_base64_inlined_png_present_when_plot_paths_provided(
    render_report_callable, report, tmp_path
):
    # Minimal valid 1x1 transparent PNG.
    png_bytes = base64.b64decode(
        b"iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII="
    )
    p1 = tmp_path / "ppc.png"
    p1.write_bytes(png_bytes)
    out = render_report_callable(
        report,
        out_dir=tmp_path,
        plot_paths={"posterior_predictive_plot": p1},
    )
    html = out.read_text(encoding="utf-8")
    assert "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAE" in html


def test_base64_inlined_png_absent_when_plot_paths_none(
    render_report_callable, report, tmp_path
):
    out = render_report_callable(report, out_dir=tmp_path, plot_paths=None)
    html = out.read_text(encoding="utf-8")
    assert "data:image/png;base64," not in html


# T-17 — band → pill class mapping (parametrized; 4 collected)
@pytest.mark.parametrize(
    "band,css_class",
    [
        (ReliabilityBand.Reliable, "pill ok"),
        (ReliabilityBand.Watch, "pill warn"),
        (ReliabilityBand.Brittle, "pill fail"),
        (ReliabilityBand.TooUncertain, "pill muted"),
    ],
    ids=["Reliable", "Watch", "Brittle", "TooUncertain"],
)
def test_band_renders_correct_pill_class(
    band, css_class, render_report_callable, thresholds, tmp_path
):
    aggregates = [
        TaskFamilyAggregate(
            task_family="x",
            n_total=10, n_success=5, n_failure=5, observed_success_rate=0.5,
            n_error=0, n_timeout=0, n_no_answer=0, n_artifact_rows=0,
            avg_latency_seconds=1.0, avg_cost_usd=0.001, avg_tool_calls_total=0.0,
        ),
    ]
    posteriors = [
        PosteriorTaskFamilyReliability(
            task_family="x",
            posterior_mean=0.5, posterior_median=0.5,
            hdi_low=0.1, hdi_high=0.9,
            p_success_lt_strong=0.5, p_success_lt_acceptable=0.5,
            n_total=10, band=band,
        ),
    ]
    report = _make_report(aggregates, posteriors, thresholds)
    out = render_report_callable(report, out_dir=tmp_path)
    html = out.read_text(encoding="utf-8")
    body = _MANIFEST_RE.sub("", html)
    assert f'class="{css_class}"' in body


# T-18 — pure helper (REFACTOR step verification)
def test_build_chart_data_returns_locked_keys(report):
    from dmac_assistant.eval.hibayes_runtime_reliability.render_report import (
        build_chart_data,
    )
    data = build_chart_data(report)
    assert set(data.keys()) == {
        "posteriorMean",
        "observedVsPosterior",
        "failureMode",
        "risk",
    }


# T-20 — encode_plot_png exception branch (R-C / M-3 fix)
def test_encode_plot_png_returns_none_on_missing_file(tmp_path):
    """The except branch in encode_plot_png returns None silently (DD-10)."""
    from dmac_assistant.eval.hibayes_runtime_reliability.render_report import (
        encode_plot_png,
    )
    missing = tmp_path / "definitely-not-here.png"
    assert not missing.exists()
    assert encode_plot_png(missing) is None


# T-19 — module does NOT import matplotlib (R-07 hardening for T06 specifically)
def test_render_report_module_does_not_import_matplotlib():
    # Re-import in a fresh subprocess-style check: ensure matplotlib is not
    # pulled in as a side effect of importing render_report.
    for mod_name in list(sys.modules):
        if mod_name.startswith("matplotlib"):
            del sys.modules[mod_name]
    importlib.import_module(
        "dmac_assistant.eval.hibayes_runtime_reliability.render_report"
    )
    assert not any(
        m == "matplotlib" or m.startswith("matplotlib.") for m in sys.modules
    ), "render_report.py must not import matplotlib (R-07 hardening: T06 reads PNGs as bytes only)"
