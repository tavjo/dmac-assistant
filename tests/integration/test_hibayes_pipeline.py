"""T07 end-to-end integration tests for `main(argv)` in run_hibayes.py.

The whole file is `importorskip`'d on `hibayes` because the eval-group
dependencies (hibayes/numpyro/arviz/jinja2/matplotlib) are image-only per
DD-13. The host bridge venv does not carry them, so a host-side
`uv run pytest` collects-but-skips this file cleanly.
"""
from __future__ import annotations

import contextlib
import io
import json
import re
from dataclasses import dataclass
from pathlib import Path

import pytest

pytest.importorskip(
    "hibayes",
    reason="eval-group dep; run inside hibayes-runtime-reliability:dev image",
)


# --------------------------------------------------------------------------- #
# Module-level fixtures                                                       #
# --------------------------------------------------------------------------- #


@pytest.fixture(scope="session")
def fixture_csv() -> Path:
    """Canonical 3-family fixture from T04 (12 rows, mixed reliable/watch/brittle)."""
    return (
        Path(__file__).parent.parent
        / "fixtures"
        / "hibayes_runtime_reliability"
        / "tiny_three_family.csv"
    )


@dataclass(frozen=True)
class PipelineRun:
    out_dir: Path
    stdout_line: str


@pytest.fixture(scope="session")
def pipeline_run(tmp_path_factory, fixture_csv) -> PipelineRun:
    """Run the pipeline ONCE per test session; return out_dir AND captured stdout."""
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_OK,
        main,
    )

    out_dir = tmp_path_factory.mktemp("hibayes_e2e")
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = main(["--input", str(fixture_csv), "--out", str(out_dir)])
    assert rc == EXIT_OK, f"happy-path session fixture exited with {rc}"
    return PipelineRun(out_dir=out_dir, stdout_line=buf.getvalue().strip())


@pytest.fixture(scope="session")
def pipeline_run_dir(pipeline_run) -> Path:
    return pipeline_run.out_dir


# --------------------------------------------------------------------------- #
# Tests                                                                       #
# --------------------------------------------------------------------------- #


def test_module_imports_main_and_exit_codes():
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_HIBAYES,
        EXIT_INPUT,
        EXIT_OK,
        main,
    )

    assert callable(main)
    assert EXIT_OK == 0
    assert EXIT_INPUT == 1
    assert EXIT_HIBAYES == 2


def test_happy_path_exit_zero(pipeline_run):
    # Re-asserting return type semantics from the session fixture.
    assert isinstance(pipeline_run.out_dir, Path)
    assert pipeline_run.out_dir.is_dir()


def test_all_section5_artifacts_present(pipeline_run_dir):
    expected_files = [
        "report.html",
        "task_family_aggregates.csv",
        "posterior_task_family_reliability.csv",
        "diagnostics.json",
        "config.resolved.yaml",
    ]
    for fname in expected_files:
        p = pipeline_run_dir / fname
        assert p.is_file(), f"missing artifact: {p}"
    # analysis_state may be a file or a directory; just assert it exists.
    state = pipeline_run_dir / "analysis_state"
    assert state.exists(), f"missing analysis_state at {state}"
    plots = pipeline_run_dir / "plots"
    assert plots.is_dir(), f"missing plots dir at {plots}"


def test_artifacts_are_in_out_dir_root_not_subdir(pipeline_run_dir):
    assert (pipeline_run_dir / "report.html").is_file()
    child_dirs = {p.name for p in pipeline_run_dir.iterdir() if p.is_dir()}
    allowed = {"analysis_state", "plots"}
    assert child_dirs.issubset(allowed), (
        f"unexpected subdirectories under out_dir: {child_dirs - allowed}"
    )


def test_stdout_prints_report_path(pipeline_run):
    expected = str((pipeline_run.out_dir / "report.html").resolve())
    assert pipeline_run.stdout_line == expected


def _extract_manifest(text: str) -> str | None:
    """Return the inner JSON content of the hibayes-manifest <script> block."""
    pattern = re.compile(
        r'<script\b[^>]*id="hibayes-manifest"[^>]*>(.*?)</script>',
        re.DOTALL | re.IGNORECASE,
    )
    m = pattern.search(text)
    return m.group(1) if m else None


def test_manifest_parses_and_schema_v1(pipeline_run_dir):
    html = (pipeline_run_dir / "report.html").read_text(encoding="utf-8")
    inner = _extract_manifest(html)
    assert inner is not None, "manifest script block not found"
    # Restore any `<\/` escaping the renderer applied.
    raw_json = inner.replace("<\\/", "</")
    manifest = json.loads(raw_json)
    assert manifest["schema_version"] == "1"
    assert len(manifest["task_family_results"]) == 3


def test_manifest_has_n_failure_per_family(pipeline_run_dir):
    html = (pipeline_run_dir / "report.html").read_text(encoding="utf-8")
    inner = _extract_manifest(html)
    assert inner is not None
    raw_json = inner.replace("<\\/", "</")
    manifest = json.loads(raw_json)
    for entry in manifest["task_family_results"]:
        assert "n_failure" in entry
        assert isinstance(entry["n_failure"], int)
        assert entry["n_failure"] >= 0
        assert entry["n_failure"] == entry["n_total"] - entry["n_success"]


def test_matplotlib_backend_is_agg_after_run(pipeline_run_dir):  # noqa: ARG001
    import matplotlib

    assert matplotlib.get_backend().lower() == "agg"


def test_xss_in_task_family_is_escaped_end_to_end(tmp_path, fixture_csv):
    """R-12 end-to-end smoke. Build a derived CSV with an XSS payload, run, assert."""
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_OK,
        main,
    )

    xss = "<script>alert(1)</script>"
    # Build a 12-row derived CSV with one family containing the XSS string.
    src_text = fixture_csv.read_text()
    lines = src_text.splitlines()
    header = lines[0]
    body = lines[1:]
    # Replace task_family on rows 9-12 (spreadsheet-tricky) with the XSS payload.
    new_body = []
    for line in body:
        cells = line.split(",")
        if cells[1] == "spreadsheet-tricky":
            cells[1] = xss
        new_body.append(",".join(cells))
    xss_csv = tmp_path / "xss.csv"
    xss_csv.write_text("\n".join([header, *new_body]) + "\n")

    out_dir = tmp_path / "out"
    rc = main(["--input", str(xss_csv), "--out", str(out_dir)])
    assert rc == EXIT_OK

    text = (out_dir / "report.html").read_text(encoding="utf-8")

    # Two-capture-group iterator pattern: opening tag in group 1, inner in group 2.
    script_re = re.compile(
        r'(<script\b[^>]*>)(.*?)</script>', re.DOTALL | re.IGNORECASE
    )
    manifest_inner = None
    other_inners: list[str] = []
    body_text = text
    for match in script_re.finditer(text):
        opening = match.group(1)
        inner = match.group(2)
        body_text = body_text.replace(match.group(0), "")
        if 'id="hibayes-manifest"' in opening:
            manifest_inner = inner
        else:
            other_inners.append(inner)

    # (b) Body assertion: HTML autoescape worked.
    assert xss not in body_text
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body_text

    # (c) Inline-JS assertion: no literal closing </script> in non-manifest blocks.
    for inner in other_inners:
        assert "</script>" not in inner

    # (d) Manifest carve-out: data path was lossless.
    assert manifest_inner is not None
    raw_json = manifest_inner.replace("<\\/", "</")
    manifest = json.loads(raw_json)
    task_families = {e["task_family"] for e in manifest["task_family_results"]}
    assert xss in task_families


def test_missing_input_returns_exit_input(tmp_path, capsys):
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    missing = tmp_path / "no_such.csv"
    out_dir = tmp_path / "out"
    rc = main(["--input", str(missing), "--out", str(out_dir)])
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "error: input csv not found:" in captured.err
    assert str(missing.resolve()) in captured.err
    assert captured.out == ""


def test_corrupt_csv_returns_exit_input(tmp_path, capsys, fixture_csv):
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    # Same header as the canonical fixture; one row with runtime_success=maybe.
    header = fixture_csv.read_text().splitlines()[0]
    bad_row = (
        "bad-row-001,search-basic,,dmac:test,true,false,false,maybe,"
        "none,10.0,0.05,3,2,1"
    )
    bad_csv = tmp_path / "bad.csv"
    bad_csv.write_text(f"{header}\n{bad_row}\n")
    out_dir = tmp_path / "out"
    rc = main(["--input", str(bad_csv), "--out", str(out_dir)])
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    # §2.5 mandates single-line stderr; normalize-on-emit must guarantee no
    # embedded newlines in the truncated first-rejection error.
    assert "\n" not in captured.err.rstrip("\n")
    err = captured.err.strip()
    assert err.startswith("error: input csv has 1 invalid rows;")
    assert captured.out == ""

    # Truncation: error msg after "first rejection: <query_id>: " ≤ 200 chars.
    m = re.search(r"first rejection: ([^:]+): (.*)\Z", err)
    assert m is not None, f"could not parse first-rejection from: {err!r}"
    error_msg = m.group(2)
    assert len(error_msg) <= 200


def test_default_config_resolves_when_omitted(pipeline_run_dir):
    """When --config is omitted, T05's config.resolved.yaml matches packaged defaults."""
    import yaml

    from dmac_assistant.eval.hibayes_runtime_reliability.models import (
        ReliabilityThresholds,
    )

    resolved_path = pipeline_run_dir / "config.resolved.yaml"
    resolved = yaml.safe_load(resolved_path.read_text())
    expected = ReliabilityThresholds().model_dump()
    assert resolved["thresholds"] == expected


def test_pandas_module_prefix_exception_returns_exit_input(
    monkeypatch, tmp_path, capsys, fixture_csv
):
    """Force the pandas-module-prefix except branch in main()."""
    import pandas

    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    # Use a valid input file path (so the existence check passes) but force
    # load_runtime_eval_csv to raise pandas.errors.ParserError.
    input_csv = tmp_path / "input.csv"
    input_csv.write_text(fixture_csv.read_text())

    def _raise(*a, **k):
        raise pandas.errors.ParserError("simulated parse failure")

    monkeypatch.setattr(rh, "load_runtime_eval_csv", _raise)

    out_dir = tmp_path / "out"
    rc = main(["--input", str(input_csv), "--out", str(out_dir)])
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "error: failed to read input csv" in captured.err
    assert captured.out == ""


def test_numpyro_module_prefix_exception_returns_exit_hibayes(
    monkeypatch, fixture_csv, tmp_path, capsys
):
    """Force the JAX/numpyro-module-prefix except branch in main()."""
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_HIBAYES,
        main,
    )

    class _FakeNumpyroErr(Exception):
        pass

    _FakeNumpyroErr.__module__ = "numpyro.distributions.constraints"

    def _raise(*a, **k):
        raise _FakeNumpyroErr("simulated numpyro failure")

    monkeypatch.setattr(rh, "run_hibayes", _raise)

    out_dir = tmp_path / "out"
    rc = main(["--input", str(fixture_csv), "--out", str(out_dir)])
    assert rc == EXIT_HIBAYES
    captured = capsys.readouterr()
    assert re.match(r"^error: hibayes pipeline failed:", captured.err)
    assert captured.out == ""


def test_missing_diagnostics_json_yields_empty_plot_paths(tmp_path):
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        _read_plot_paths,
    )

    assert _read_plot_paths(tmp_path) == {}


# --------------------------------------------------------------------------- #
# Additional branch-coverage tests (R-10 — required to keep run_hibayes.py    #
# overall ≥ 95% per task-07 §6.2).                                            #
# --------------------------------------------------------------------------- #


def test_missing_config_returns_exit_input(tmp_path, capsys, fixture_csv):
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    missing_cfg = tmp_path / "no_such.yaml"
    rc = main(
        [
            "--input",
            str(fixture_csv),
            "--out",
            str(tmp_path / "out"),
            "--config",
            str(missing_cfg),
        ]
    )
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "error: config yaml not found:" in captured.err
    assert captured.out == ""


def test_yaml_parse_error_returns_exit_input(tmp_path, capsys, fixture_csv):
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    bad_yaml = tmp_path / "bad.yaml"
    bad_yaml.write_text("this: : not valid : yaml: :\n  - [\n")
    rc = main(
        [
            "--input",
            str(fixture_csv),
            "--out",
            str(tmp_path / "out"),
            "--config",
            str(bad_yaml),
        ]
    )
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "error: failed to parse config yaml" in captured.err
    assert captured.out == ""


def test_invalid_thresholds_config_returns_exit_input(tmp_path, capsys, fixture_csv):
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    # Valid YAML but invalid threshold (acceptable_floor must be ≤ 1.0).
    bad_cfg = tmp_path / "bad_thresholds.yaml"
    bad_cfg.write_text("acceptable_floor: 99.0\nstrong_floor: 0.5\n")
    rc = main(
        [
            "--input",
            str(fixture_csv),
            "--out",
            str(tmp_path / "out"),
            "--config",
            str(bad_cfg),
        ]
    )
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "error: invalid thresholds config" in captured.err
    assert captured.out == ""


def test_supplied_config_resolves(tmp_path, fixture_csv, capsys):
    """Exercise _resolve_config_path's `supplied is not None` branch end-to-end."""
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_OK,
        main,
        _resolve_config_path,
    )

    # Copy packaged config into tmp_path; pass it explicitly via --config.
    cfg_target = tmp_path / "thresholds.yaml"
    cfg_target.write_text(
        "reliable_mean_floor: 0.95\nreliable_p_lt_strong_max: 0.20\n"
        "watch_mean_floor: 0.80\nwatch_p_lt_acceptable_max: 0.30\n"
        "brittle_p_lt_acceptable_min: 0.50\n"
        "strong_floor: 0.90\nacceptable_floor: 0.80\n"
        "min_n_for_classification: 3\n"
    )
    # Sanity: _resolve_config_path returns the supplied path resolved.
    resolved = _resolve_config_path(cfg_target)
    assert resolved == cfg_target.resolve()

    rc = main(
        [
            "--input",
            str(fixture_csv),
            "--out",
            str(tmp_path / "out"),
            "--config",
            str(cfg_target),
        ]
    )
    assert rc == EXIT_OK
    capsys.readouterr()  # drain


def test_load_runtime_eval_csv_oserror_branch(
    monkeypatch, tmp_path, capsys, fixture_csv
):
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    input_csv = tmp_path / "input.csv"
    input_csv.write_text(fixture_csv.read_text())

    def _raise(*a, **k):
        raise PermissionError("simulated permission failure")

    monkeypatch.setattr(rh, "load_runtime_eval_csv", _raise)

    rc = main(["--input", str(input_csv), "--out", str(tmp_path / "out")])
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "error: failed to read input csv" in captured.err
    assert captured.out == ""


def test_empty_rows_returns_exit_input(monkeypatch, tmp_path, capsys, fixture_csv):
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.load_csv import LoadReport
    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_INPUT,
        main,
    )

    input_csv = tmp_path / "input.csv"
    input_csv.write_text(fixture_csv.read_text())

    def _empty(*a, **k):
        return [], LoadReport(
            accepted=0, rejected=[], normalized_task_family_count=0, warnings=[]
        )

    monkeypatch.setattr(rh, "load_runtime_eval_csv", _empty)

    rc = main(["--input", str(input_csv), "--out", str(tmp_path / "out")])
    assert rc == EXIT_INPUT
    captured = capsys.readouterr()
    assert "contains no valid rows" in captured.err
    assert captured.out == ""


def test_hibayes_value_error_returns_exit_hibayes(
    monkeypatch, fixture_csv, tmp_path, capsys
):
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_HIBAYES,
        main,
    )

    def _raise(*a, **k):
        raise ValueError("simulated hibayes value error")

    monkeypatch.setattr(rh, "run_hibayes", _raise)

    rc = main(["--input", str(fixture_csv), "--out", str(tmp_path / "out")])
    assert rc == EXIT_HIBAYES
    captured = capsys.readouterr()
    assert "error: hibayes pipeline failed: ValueError:" in captured.err
    assert captured.out == ""


def test_unknown_module_exception_propagates(
    monkeypatch, fixture_csv, tmp_path
):
    """Exceptions whose module is neither jax/numpyro nor pandas re-raise."""
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import main

    class _Unknown(Exception):
        pass

    _Unknown.__module__ = "totally.unrelated"

    def _raise(*a, **k):
        raise _Unknown("simulated unrelated failure")

    monkeypatch.setattr(rh, "run_hibayes", _raise)
    with pytest.raises(_Unknown):
        main(["--input", str(fixture_csv), "--out", str(tmp_path / "out")])


def test_unknown_module_loader_exception_propagates(
    monkeypatch, fixture_csv, tmp_path
):
    """Loader exceptions whose module is neither pandas nor OSError re-raise."""
    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import main

    class _UnknownLoaderErr(Exception):
        pass

    _UnknownLoaderErr.__module__ = "totally.unrelated"

    def _raise(*a, **k):
        raise _UnknownLoaderErr("simulated unrelated loader failure")

    monkeypatch.setattr(rh, "load_runtime_eval_csv", _raise)
    input_csv = tmp_path / "input.csv"
    input_csv.write_text(fixture_csv.read_text())
    with pytest.raises(_UnknownLoaderErr):
        main(["--input", str(input_csv), "--out", str(tmp_path / "out")])


def test_render_report_template_error_returns_exit_hibayes(
    monkeypatch, fixture_csv, tmp_path, capsys
):
    import jinja2

    from dmac_assistant.eval.hibayes_runtime_reliability import run_hibayes as rh

    from dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes import (
        EXIT_HIBAYES,
        main,
    )

    # Run the pipeline up to render, but force render_report to fail.
    def _raise(*a, **k):
        raise jinja2.TemplateError("simulated template error")

    monkeypatch.setattr(rh, "render_report", _raise)
    rc = main(["--input", str(fixture_csv), "--out", str(tmp_path / "out")])
    assert rc == EXIT_HIBAYES
    captured = capsys.readouterr()
    assert "error: report rendering failed:" in captured.err
    assert captured.out == ""
