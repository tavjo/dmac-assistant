"""tests/unit/eval/test_hibayes_artifact_validity.py — pinning tests for T3.1."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# Tests that import from `run_hibayes.py` use per-test `pytest.importorskip("hibayes")`
# (because DL-028 mandates module-level `import hibayes` in `run_hibayes.py` so
# `--help` exercises the import path; on host where hibayes is NOT installed, a
# `from ...run_hibayes import ...` collection-time evaluation would otherwise error,
# not skip). Tests that import only from `models.py` / `load_csv.py` / `process.py` /
# `render_section.py` run unconditionally on host — those modules are
# hibayes-import-clean per locked DD-42.
#
# The locked DD-42 counter-example at design line 421 grounds the
# "host-runnable without importorskip" license on imports from `models.py`
# (`tests/unit/eval/test_thresholds_yaml.py:14` imports
# `ReliabilityThresholds` from `models.py` without `importorskip` and runs on
# host). That license does NOT extend to `run_hibayes.py`, which carries the
# DL-028 module-level `import hibayes` line by design.
#
# Module-level `importorskip` is INTENTIONALLY NOT used here either — the
# DD-42 import-cleanliness pin (which reads `models.py` as text) and the
# Stage A 29-column header pin (which imports from `load_csv.py`) and the
# `render_section` substring pin (which imports from `render_section.py`)
# all MUST run on host. Putting `importorskip` at module scope would skip
# those too.


def test_models_does_not_import_hibayes_at_module_level() -> None:
    """Locked DD-42: models.py must be hibayes-import-clean."""
    src = Path(__file__).resolve().parents[3] / "src" / "dmac_assistant" / "eval" / "hibayes_artifact_validity" / "models.py"
    content = src.read_text(encoding="utf-8")
    # No top-level `import hibayes` or `from hibayes ...`
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("import hibayes") or stripped.startswith("from hibayes"):
            pytest.fail(f"models.py imports hibayes at module level: {line!r}")


def test_posterior_json_wrapper_schema_top_level_keys(tmp_path: Path) -> None:
    """DL-024: posterior.json has exactly 5 top-level wrapper keys.

    Imports `write_posterior_json` from `run_hibayes.py`, which DL-028 mandates
    carries module-level `import hibayes`; therefore per-test `importorskip`.
    The pinning value of this assertion is exercised in-image where the
    coverage gate runs and `hibayes` IS installed.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import (
        write_posterior_json,
    )
    from dmac_assistant.eval.hibayes_artifact_validity.models import (
        PosteriorTaskFamilyReliability,
    )

    strata = [
        PosteriorTaskFamilyReliability(
            task_family="Report-GEO",
            n_total=3,
            posterior_mean=0.85,
            posterior_median=0.86,
            hdi_low=0.6,
            hdi_high=0.95,
            p_success_lt_strong=0.05,
            p_success_lt_acceptable=0.02,
            band="Reliable",
        ),
    ]
    out = tmp_path / "posterior.json"
    write_posterior_json(
        out_path=out,
        axis="artifact",
        model="two_level_group_binomial",
        prior_sigma_group_scale=2.0,
        strata=strata,
        metadata={
            "run_id": "test",
            "axis_input_csv": "av.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {},
        },
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert set(payload.keys()) == {
        "axis",
        "model",
        "prior_sigma_group_scale",
        "strata",
        "metadata",
    }
    assert payload["axis"] == "artifact"
    assert payload["model"] == "two_level_group_binomial"


def test_posterior_json_per_stratum_9_fields(tmp_path: Path) -> None:
    """DL-024: each strata[i] has exactly the 9 fields per DD-41 lines 400-408.

    Imports `write_posterior_json` from `run_hibayes.py`; see DL-028 note in
    the wrapper-schema test above. Per-test `importorskip` required.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import (
        write_posterior_json,
    )
    from dmac_assistant.eval.hibayes_artifact_validity.models import (
        PosteriorTaskFamilyReliability,
    )

    strata = [
        PosteriorTaskFamilyReliability(
            task_family="Report-NFCORE",
            n_total=3,
            posterior_mean=0.75,
            posterior_median=0.76,
            hdi_low=0.5,
            hdi_high=0.9,
            p_success_lt_strong=0.15,
            p_success_lt_acceptable=0.07,
            band="Watch",
        ),
    ]
    out = tmp_path / "posterior.json"
    write_posterior_json(
        out_path=out,
        axis="artifact",
        model="two_level_group_binomial",
        prior_sigma_group_scale=2.0,
        strata=strata,
        metadata={
            "run_id": "t",
            "axis_input_csv": "av.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {},
        },
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    stratum = payload["strata"][0]
    expected_keys = {
        "task_family",
        "n_total",
        "posterior_mean",
        "posterior_median",
        "hdi_low",
        "hdi_high",
        "p_success_lt_strong",
        "p_success_lt_acceptable",
        "band",
    }
    assert set(stratum.keys()) == expected_keys


def test_posterior_json_metadata_subkeys(tmp_path: Path) -> None:
    """DL-024: metadata has run_id, axis_input_csv, thresholds, fit_diagnostics.

    Imports `write_posterior_json` from `run_hibayes.py`; see DL-028 note in
    the wrapper-schema test above. Per-test `importorskip` required.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import (
        write_posterior_json,
    )

    out = tmp_path / "posterior.json"
    write_posterior_json(
        out_path=out,
        axis="artifact",
        model="two_level_group_binomial",
        prior_sigma_group_scale=2.0,
        strata=[],
        metadata={
            "run_id": "abc",
            "axis_input_csv": "x.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {"rhat_max": 1.01},
        },
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    md = payload["metadata"]
    assert set(md.keys()) >= {"run_id", "axis_input_csv", "thresholds", "fit_diagnostics"}


def test_stage_a_csv_header_29_columns_pin() -> None:
    """Step 1 RED-step pin: `load_artifact_validity_csv` consumes a CSV whose
    header has exactly the locked-design §5.1 29 columns in the documented order.

    This is a host-runnable schema-pin (no hibayes import) — `load_csv.py` is
    hibayes-import-clean. Pinning the header here makes "an executor accidentally
    drops or renames a column" fail at unit-test time, not at integration time.
    """
    from dmac_assistant.eval.hibayes_artifact_validity.load_csv import (
        ARTIFACT_VALIDITY_CSV_COLUMNS,
    )

    expected = [
        "run_id",
        "query_id",
        "task_family",
        "artifact_eval_id",
        "artifact_expected",
        "expected_artifact_kind",
        "artifact_declared",
        "artifact_path",
        "artifact_basename",
        "artifact_ext",
        "runtime_success",
        "failure_mode",
        "artifact_exists",
        "artifact_accessible",
        "file_size_bytes",
        "parser_used",
        "parse_success",
        "sheet_count",
        "row_count",
        "column_count",
        "nonempty_cell_count",
        "null_cell_fraction",
        "required_fields_present",
        "required_fields_complete",
        "missing_required_fields",
        "all_required_rows_complete",
        "artifact_validity_status",
        "artifact_success",
        "validation_notes",
    ]
    assert ARTIFACT_VALIDITY_CSV_COLUMNS == expected
    assert len(ARTIFACT_VALIDITY_CSV_COLUMNS) == 29


def test_run_hibayes_consumes_stage_a_csv(tmp_path: Path) -> None:
    """End-to-end smoke: run_hibayes against a minimal synthetic Stage A CSV produces a posterior.json.

    Per-test `pytest.importorskip` here (not module-level — see header note) so this
    runtime test skips cleanly on host where `hibayes` is not installed, while the
    pure-schema / DD-42 / DL-024 tests above still run.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import (
        run_artifact_axis,
    )

    av_csv = tmp_path / "av.csv"
    # Minimal Stage A header + a handful of rows enabling group-binomial fit.
    av_csv.write_text(
        "run_id,query_id,task_family,artifact_eval_id,artifact_expected,expected_artifact_kind,"
        "artifact_declared,artifact_path,artifact_basename,artifact_ext,runtime_success,"
        "failure_mode,artifact_exists,artifact_accessible,file_size_bytes,parser_used,"
        "parse_success,sheet_count,row_count,column_count,nonempty_cell_count,null_cell_fraction,"
        "required_fields_present,required_fields_complete,missing_required_fields,"
        "all_required_rows_complete,artifact_validity_status,artifact_success,validation_notes\n"
    )
    for i in range(1, 4):
        for fam in ("Report-GEO", "Report-NFCORE"):
            success = "True" if i != 3 else "False"
            status = "Valid" if success == "True" else "Missing"
            av_csv.write_text(
                av_csv.read_text() +
                f"run,Q-{fam}-{i},{fam},Q-{fam}-{i}::0,True,GEO_XLSX,True,/a,b,.xlsx,True,none,"
                f"True,True,100,openpyxl,True,1,1,1,1,0.0,True,True,,True,{status},{success},\n"
            )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    posterior_path = run_artifact_axis(
        input_csv=av_csv,
        out_dir=out_dir,
        thresholds={"strong": 0.9, "acceptable": 0.8},
        prior_sigma_group_scale=2.0,
        seed=42,
    )
    payload = json.loads(posterior_path.read_text(encoding="utf-8"))
    assert payload["axis"] == "artifact"
    assert payload["model"] == "two_level_group_binomial"
    assert len(payload["strata"]) >= 1


def test_render_section_emits_expected_substrings() -> None:
    """In-image coverage pin (DL-038 hardener pass 2 D1 MED): exercise
    `render_section.render_section()` so the in-image `--cov` gate reaches
    its 95% floor on `render_section.py`.

    Loads the packaged `section.html.j2` from the per-axis `report_template/`
    directory (locked DD-28) via `importlib.resources` — the same discovery
    pattern `run_hibayes._discover_default_config_path` uses for the YAML.
    Asserts substrings the Jinja2 template MUST emit per Section 6 File 8
    (`<h2>Artifact Validity</h2>`, the model name, task_family + band cells).
    No `pytest.importorskip("hibayes")` — render_section.py is
    hibayes-import-clean by design (it only imports jinja2 + stdlib).

    `posterior` is intentionally a plain dict here (not a Pydantic model
    instance) because Jinja2 attribute lookup falls back to item access on
    dicts; the combined renderer (task-13) feeds the same dict shape.
    """
    import importlib.resources

    from dmac_assistant.eval.hibayes_artifact_validity.render_section import (
        render_section,
    )

    template_dir = Path(
        importlib.resources.files("dmac_assistant.eval.hibayes_artifact_validity")
        / "report_template"
    )
    posterior = {
        "axis": "artifact",
        "model": "two_level_group_binomial",
        "prior_sigma_group_scale": 2.0,
        "strata": [
            {
                "task_family": "Report-GEO",
                "n_total": 3,
                "posterior_mean": 0.85,
                "posterior_median": 0.86,
                "hdi_low": 0.6,
                "hdi_high": 0.95,
                "p_success_lt_strong": 0.05,
                "p_success_lt_acceptable": 0.02,
                "band": "Reliable",
            },
        ],
        "metadata": {},
    }
    html = render_section(posterior=posterior, template_dir=template_dir)
    assert "<h2>Artifact Validity</h2>" in html
    assert "two_level_group_binomial" in html
    assert "Report-GEO" in html
    assert "Reliable" in html


def test_discover_default_config_path_returns_packaged_yaml() -> None:
    """In-image coverage pin (DL-038 hardener pass 2 D1 MED): exercise
    `_discover_default_config_path` directly so it shows as covered in the
    in-image `--cov` report (not merely covered as an import-time side
    effect through `_DEFAULT_CONFIG_PATH`).

    Asserts the returned path points at the per-axis packaged YAML named
    `hibayes_artifact_validity.yaml` under `config/`. The function body itself
    is hibayes-import-clean (it only touches `importlib.resources` + `pathlib`),
    BUT it lives inside `run_hibayes.py`, which DL-028 mandates carries
    module-level `import hibayes`. Importing `_discover_default_config_path`
    therefore triggers the module-level hibayes import on host. Per-test
    `pytest.importorskip("hibayes")` keeps this test as a clean host-skip;
    the assertion runs in-image where hibayes is installed.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import (
        _discover_default_config_path,
    )

    p = _discover_default_config_path()
    assert p.name == "hibayes_artifact_validity.yaml"
    assert p.parent.name == "config"


def test_main_help_exits_zero() -> None:
    """In-image coverage pin (DL-038 hardener pass 2 D1 MED): invoke `main()`
    with `--help` so argparse setup + `_DEFAULT_CONFIG_PATH` default-binding
    are covered. argparse raises SystemExit(0) on `--help`.

    This is also the in-process equivalent of the DL-028 wrapper-smoke (which
    invokes the same code via `python -m ...run_hibayes --help`); both must
    succeed. Hibayes-import-clean *at the `--help` code path* — the module-level
    `import hibayes` line is what loads the package, but `--help` runs through
    the same module-import side effect under in-image pytest where hibayes IS
    present. On HOST this test still loads the module (which triggers a real
    `import hibayes` per DL-028's load-bearing module-level imports), so it
    needs `pytest.importorskip` even though argparse itself is hibayes-free.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_main_end_to_end_with_minimal_csv(tmp_path: Path) -> None:
    """In-image coverage pin (DL-038 hardener pass 2 D1 MED): drive `main()`
    end-to-end through the argparse → YAML-config-load → `run_artifact_axis`
    path so the body of `main()` (currently unexercised by
    `test_run_hibayes_consumes_stage_a_csv`, which calls `run_artifact_axis`
    directly) reaches the in-image 95% coverage floor.

    Skipped on host (per-test `pytest.importorskip`) because `main` triggers
    a real hibayes fit; runs in-image where hibayes is installed.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import main

    av_csv = tmp_path / "av.csv"
    av_csv.write_text(
        "run_id,query_id,task_family,artifact_eval_id,artifact_expected,expected_artifact_kind,"
        "artifact_declared,artifact_path,artifact_basename,artifact_ext,runtime_success,"
        "failure_mode,artifact_exists,artifact_accessible,file_size_bytes,parser_used,"
        "parse_success,sheet_count,row_count,column_count,nonempty_cell_count,null_cell_fraction,"
        "required_fields_present,required_fields_complete,missing_required_fields,"
        "all_required_rows_complete,artifact_validity_status,artifact_success,validation_notes\n"
    )
    for i in range(1, 4):
        for fam in ("Report-GEO", "Report-NFCORE"):
            success = "True" if i != 3 else "False"
            status = "Valid" if success == "True" else "Missing"
            av_csv.write_text(
                av_csv.read_text()
                + f"run,Q-{fam}-{i},{fam},Q-{fam}-{i}::0,True,GEO_XLSX,True,/a,b,.xlsx,True,none,"
                f"True,True,100,openpyxl,True,1,1,1,1,0.0,True,True,,True,{status},{success},\n"
            )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # `main` returns 0 on success; default `--config` resolves to the packaged
    # YAML via `_DEFAULT_CONFIG_PATH` (DL-028 sub-condition (c) discovery path).
    rc = main(["--input", str(av_csv), "--out-dir", str(out_dir), "--seed", "42"])
    assert rc == 0
    posterior_path = out_dir / "posterior.json"
    assert posterior_path.is_file()
    payload = json.loads(posterior_path.read_text(encoding="utf-8"))
    assert payload["axis"] == "artifact"
    assert payload["model"] == "two_level_group_binomial"


# --------------------------------------------------------------------------- #
# Coverage-completing unit tests for deterministic helper branches.            #
# These exercise pure code paths the 10 contract tests above do not reach, so  #
# the in-image `--cov` gate clears its 95% floor on every module. They do not  #
# change the behavioral contract — they pin additional branches of the same   #
# locked Section 6 reference implementation.                                  #
# --------------------------------------------------------------------------- #


def test_load_csv_skips_malformed_short_row(tmp_path: Path) -> None:
    """`load_artifact_validity_csv` swallows a row that fails Pydantic
    construction (a short row whose missing column becomes `None`, which
    fails the `str`-typed `query_id` field) and continues with valid rows.

    Host-runnable: `load_csv.py` is hibayes-import-clean.
    """
    from dmac_assistant.eval.hibayes_artifact_validity.load_csv import (
        load_artifact_validity_csv,
    )

    csv_path = tmp_path / "av.csv"
    # First data row is short (one trailing field) — DictReader fills the
    # missing columns with `None`, so `query_id` becomes `None` and Pydantic
    # rejects it. Second data row is well-formed.
    csv_path.write_text(
        "query_id,task_family,artifact_expected,artifact_success,artifact_validity_status\n"
        "short\n"
        "Q-1,Report-GEO,True,True,Valid\n",
        encoding="utf-8",
    )
    rows = load_artifact_validity_csv(csv_path)
    assert len(rows) == 1
    assert rows[0].query_id == "Q-1"
    assert rows[0].task_family == "Report-GEO"


def test_models_rejects_inverted_hdi() -> None:
    """`PosteriorTaskFamilyReliability._check_hdi_ordering` raises when
    `hdi_low > hdi_high`. Host-runnable: `models.py` is hibayes-import-clean.
    """
    import pydantic

    from dmac_assistant.eval.hibayes_artifact_validity.models import (
        PosteriorTaskFamilyReliability,
    )

    with pytest.raises(pydantic.ValidationError):
        PosteriorTaskFamilyReliability(
            task_family="Report-GEO",
            n_total=3,
            posterior_mean=0.8,
            posterior_median=0.8,
            hdi_low=0.9,
            hdi_high=0.5,
            p_success_lt_strong=0.1,
            p_success_lt_acceptable=0.05,
            band="Watch",
        )


def test_aggregate_filters_not_expected_rows() -> None:
    """`aggregate_by_task_family` drops rows where `artifact_expected` is
    False (DD-15/DD-37 NotExpected filter). Host-runnable: `process.py` and
    `models.py` are hibayes-import-clean.
    """
    from dmac_assistant.eval.hibayes_artifact_validity.models import (
        ArtifactValidityRow,
    )
    from dmac_assistant.eval.hibayes_artifact_validity.process import (
        aggregate_by_task_family,
    )

    rows = [
        ArtifactValidityRow(
            query_id="Q-1",
            task_family="Report-GEO",
            artifact_expected=True,
            artifact_success=True,
            artifact_validity_status="Valid",
        ),
        ArtifactValidityRow(
            query_id="Q-2",
            task_family="Report-GEO",
            artifact_expected=False,  # NotExpected — must be dropped.
            artifact_success=False,
            artifact_validity_status="NotExpected",
        ),
    ]
    aggregates = aggregate_by_task_family(rows)
    assert len(aggregates) == 1
    assert aggregates[0].task_family == "Report-GEO"
    assert aggregates[0].n_total == 1
    assert aggregates[0].n_success == 1


def test_band_covers_all_branches() -> None:
    """`_band` returns each documented band category for representative
    inputs (Section 6 File 5 lines 114-122).

    `_band` is hibayes-import-clean in its body, but it lives in
    `run_hibayes.py`, which DL-028 mandates carries module-level
    `import hibayes`. Per-test `pytest.importorskip("hibayes")` keeps this a
    clean host-skip; it runs in-image where the `--cov` gate applies.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import _band

    # n_total < 3 -> TooUncertain (line 114-115)
    assert _band(0.99, 0.0, 0.0, n_total=2) == "TooUncertain"
    # mean >= 0.95 and p_lt_strong < 0.20 -> Reliable (line 116-117)
    assert _band(0.97, 0.05, 0.02, n_total=5) == "Reliable"
    # p_lt_acceptable >= 0.50 -> Brittle (line 118-119)
    assert _band(0.40, 0.90, 0.70, n_total=5) == "Brittle"
    # mean >= 0.80 and p_lt_acceptable < 0.30 -> Watch (line 120-121)
    assert _band(0.85, 0.40, 0.10, n_total=5) == "Watch"
    # falls through everything -> TooUncertain (line 122)
    assert _band(0.60, 0.50, 0.40, n_total=5) == "TooUncertain"


def test_fit_two_level_group_binomial_empty_returns_empty() -> None:
    """`_fit_two_level_group_binomial([])` short-circuits to `[]` without a
    HiBayes fit (Section 6 File 5 lines 140-141).

    Per-test `pytest.importorskip("hibayes")` — symbol lives in
    `run_hibayes.py`.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_artifact_validity.run_hibayes import (
        _fit_two_level_group_binomial,
    )

    result = _fit_two_level_group_binomial(
        [],
        prior_sigma_group_scale=2.0,
        thresholds={"strong": 0.9, "acceptable": 0.8},
        seed=42,
    )
    assert result == []
