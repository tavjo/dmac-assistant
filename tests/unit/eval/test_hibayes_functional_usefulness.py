"""tests/unit/eval/test_hibayes_functional_usefulness.py — pinning tests for T3.2."""
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
# 12-column Stage C functional-usefulness header pin (which imports from
# `load_csv.py`) and the `render_section` substring pin (which imports from
# `render_section.py`) all MUST run on host. Putting `importorskip` at module
# scope would skip those too.


def test_models_does_not_import_hibayes() -> None:
    """Locked DD-42: models.py is hibayes-import-clean."""
    src = (
        Path(__file__).resolve().parents[3]
        / "src" / "dmac_assistant" / "eval"
        / "hibayes_functional_usefulness" / "models.py"
    )
    content = src.read_text(encoding="utf-8")
    for line in content.splitlines():
        if line.strip().startswith(("import hibayes", "from hibayes")):
            pytest.fail(f"models.py imports hibayes at module level: {line!r}")


def test_posterior_json_axis_is_functional(tmp_path: Path) -> None:
    """DL-024: posterior.json has exactly 5 top-level wrapper keys + axis='functional'.

    Imports `write_posterior_json` from `run_hibayes.py`, which DL-028 mandates
    carries module-level `import hibayes`; therefore per-test `importorskip`.
    The pinning value of this assertion is exercised in-image where the
    coverage gate runs and `hibayes` IS installed.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import (
        write_posterior_json,
    )

    out = tmp_path / "posterior.json"
    write_posterior_json(
        out_path=out,
        axis="functional",
        model="two_level_group_binomial",
        prior_sigma_group_scale=2.0,
        strata=[],
        metadata={
            "run_id": "t",
            "axis_input_csv": "fu.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {},
        },
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["axis"] == "functional"
    assert payload["model"] == "two_level_group_binomial"
    assert set(payload.keys()) == {"axis", "model", "prior_sigma_group_scale", "strata", "metadata"}


def test_posterior_json_per_stratum_9_fields(tmp_path: Path) -> None:
    """DL-024: each strata[i] has exactly the 9 fields per DD-41 lines 400-408.

    Imports `write_posterior_json` from `run_hibayes.py`; see DL-028 note in
    the wrapper-schema test above. Per-test `importorskip` required.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.models import (
        PosteriorTaskFamilyReliability,
    )
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import (
        write_posterior_json,
    )

    strata = [
        PosteriorTaskFamilyReliability(
            task_family="Search-Basic",
            n_total=5,
            posterior_mean=0.9,
            posterior_median=0.9,
            hdi_low=0.7,
            hdi_high=0.98,
            p_success_lt_strong=0.05,
            p_success_lt_acceptable=0.01,
            band="Reliable",
        )
    ]
    out = tmp_path / "posterior.json"
    write_posterior_json(
        out_path=out,
        axis="functional",
        model="two_level_group_binomial",
        prior_sigma_group_scale=2.0,
        strata=strata,
        metadata={
            "run_id": "t",
            "axis_input_csv": "fu.csv",
            "thresholds": {"strong": 0.9, "acceptable": 0.8},
            "fit_diagnostics": {},
        },
    )
    payload = json.loads(out.read_text(encoding="utf-8"))
    expected_keys = {
        "task_family", "n_total", "posterior_mean", "posterior_median",
        "hdi_low", "hdi_high", "p_success_lt_strong", "p_success_lt_acceptable", "band",
    }
    assert set(payload["strata"][0].keys()) == expected_keys


def test_posterior_json_metadata_subkeys(tmp_path: Path) -> None:
    """DL-024 (per plan T3.2 row): metadata has run_id, axis_input_csv, thresholds, fit_diagnostics.

    Imports `write_posterior_json` from `run_hibayes.py`; see DL-028 note in
    the wrapper-schema test above. Per-test `importorskip` required.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import (
        write_posterior_json,
    )

    out = tmp_path / "posterior.json"
    write_posterior_json(
        out_path=out,
        axis="functional",
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


def test_run_hibayes_consumes_functional_csv(tmp_path: Path) -> None:
    """End-to-end smoke: run_hibayes against a minimal synthetic Stage C CSV produces a posterior.json.

    Per-test `pytest.importorskip` here (not module-level — see header note) so this
    runtime test skips cleanly on host where `hibayes` is not installed, while the
    pure-schema / DD-42 / DL-024 tests above still run.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import (
        run_functional_axis,
    )

    fu_csv = tmp_path / "fu.csv"
    # Minimal Stage C 12-column header per locked-spec §5.3 verbatim (lines 603-619)
    # + a handful of rows enabling group-binomial fit. `functional_success` is
    # the DD-08-derived column (col 9). Column order MUST equal the
    # `FUNCTIONAL_USEFULNESS_HEADER_12` emitted by T2.1's
    # `tools/e2e/functional_evaluator.py` (see task-08 §6 lines 137-150).
    fu_csv.write_text(
        "query_id,task_family,expected_behavior,runtime_success,artifact_status,"
        "outcome,usefulness_score,primary_issue,functional_success,"
        "needs_human_review,review_priority,rationale\n"
    )
    for i in range(1, 4):
        for fam in ("Search-Basic", "Report-GEO"):
            success = "True" if i != 3 else "False"
            # Per locked §5.3: outcome ∈ FunctionalOutcome enum; functional_success
            # is DD-08-derived. For the success rows we use FullySatisfied / NoIssue;
            # for the failure rows we use NotSatisfied / RuntimeFailure.
            outcome = "FullySatisfied" if success == "True" else "NotSatisfied"
            primary_issue = "NoIssue" if success == "True" else "RuntimeFailure"
            review_priority = "Low" if success == "True" else "High"
            needs_review = "False" if success == "True" else "True"
            fu_csv.write_text(
                fu_csv.read_text() +
                f"Q-{fam}-{i},{fam},AnswerExpected,{success},Valid,"
                f"{outcome},3,{primary_issue},{success},"
                f"{needs_review},{review_priority},r\n"
            )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    posterior_path = run_functional_axis(
        input_csv=fu_csv,
        out_dir=out_dir,
        thresholds={"strong": 0.9, "acceptable": 0.8},
        prior_sigma_group_scale=2.0,
        seed=42,
    )
    payload = json.loads(posterior_path.read_text(encoding="utf-8"))
    assert payload["axis"] == "functional"
    assert payload["model"] == "two_level_group_binomial"
    assert len(payload["strata"]) >= 1


def test_functional_usefulness_csv_header_12_columns_pin() -> None:
    """Step 1 RED-step pin: `load_functional_usefulness_csv` consumes a CSV
    whose header has exactly the locked-design §5.3 12 columns in the
    documented order.

    Mirrors task-10's `test_stage_a_csv_header_29_columns_pin` (29-column
    artifact-axis pin). Host-runnable schema-pin (no hibayes import) —
    `load_csv.py` is hibayes-import-clean. Pinning the header here makes
    "an executor accidentally drops, renames, or reorders a column" fail
    at unit-test time, not at integration time. The expected list MUST
    equal `tools.e2e.functional_evaluator.FUNCTIONAL_USEFULNESS_HEADER_12`
    (T2.1 producer); a mismatch is a producer/consumer drift bug.
    """
    from dmac_assistant.eval.hibayes_functional_usefulness.load_csv import (
        FUNCTIONAL_USEFULNESS_CSV_COLUMNS,
    )

    expected = [
        "query_id",
        "task_family",
        "expected_behavior",
        "runtime_success",
        "artifact_status",
        "outcome",
        "usefulness_score",
        "primary_issue",
        "functional_success",
        "needs_human_review",
        "review_priority",
        "rationale",
    ]
    assert FUNCTIONAL_USEFULNESS_CSV_COLUMNS == expected
    assert len(FUNCTIONAL_USEFULNESS_CSV_COLUMNS) == 12


def test_render_section_emits_expected_substrings() -> None:
    """In-image coverage pin (mirror of task-10's DL-038 hardener pass 2 D1
    MED): exercise `render_section.render_section()` so the in-image `--cov`
    gate reaches its 95% floor on `render_section.py`.

    Loads the packaged `section.html.j2` from the per-axis `report_template/`
    directory (locked DD-28) via `importlib.resources` — the same discovery
    pattern `run_hibayes._discover_default_config_path` uses for the YAML.
    Asserts substrings the Jinja2 template MUST emit per Section 6 substitution
    rules (`<h2>Functional Usefulness</h2>`, the model name, task_family + band
    cells). No `pytest.importorskip("hibayes")` — render_section.py is
    hibayes-import-clean by design (it only imports jinja2 + stdlib).

    `posterior` is intentionally a plain dict here (not a Pydantic model
    instance) because Jinja2 attribute lookup falls back to item access on
    dicts; the combined renderer (task-13) feeds the same dict shape.

    NOTE: `render_section.py` is hibayes-import-clean (no `import hibayes`),
    but it DOES import `jinja2`, which is an eval-group dependency installed
    only inside the `hibayes-runtime-reliability:dev` image (see
    `pyproject.toml [tool.coverage.run]` comment and the existing
    `tests/unit/eval/test_render_report.py:23` module-level
    `pytest.importorskip("jinja2")`). A per-test `pytest.importorskip("jinja2")`
    keeps this test a clean host-skip; the pinning assertions run in-image
    where jinja2 IS installed and the `--cov` gate runs — exactly the context
    this test is documented as an in-image coverage pin for.
    """
    import importlib.resources

    pytest.importorskip("jinja2")
    from dmac_assistant.eval.hibayes_functional_usefulness.render_section import (
        render_section,
    )

    template_dir = Path(
        importlib.resources.files("dmac_assistant.eval.hibayes_functional_usefulness")
        / "report_template"
    )
    posterior = {
        "axis": "functional",
        "model": "two_level_group_binomial",
        "prior_sigma_group_scale": 2.0,
        "strata": [
            {
                "task_family": "Search-Basic",
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
    assert "<h2>Functional Usefulness</h2>" in html
    assert "two_level_group_binomial" in html
    assert "Search-Basic" in html
    assert "Reliable" in html


def test_discover_default_config_path_returns_packaged_yaml() -> None:
    """In-image coverage pin (mirror of task-10's DL-038 hardener pass 2 D1
    MED): exercise `_discover_default_config_path` directly so it shows as
    covered in the in-image `--cov` report (not merely covered as an
    import-time side effect through `_DEFAULT_CONFIG_PATH`).

    Asserts the returned path points at the per-axis packaged YAML named
    `hibayes_functional_usefulness.yaml` under `config/`. The function body
    itself is hibayes-import-clean (it only touches `importlib.resources` +
    `pathlib`), BUT it lives inside `run_hibayes.py`, which DL-028 mandates
    carries module-level `import hibayes`. Importing
    `_discover_default_config_path` therefore triggers the module-level
    hibayes import on host. Per-test `pytest.importorskip("hibayes")` keeps
    this test as a clean host-skip; the assertion runs in-image where hibayes
    is installed.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import (
        _discover_default_config_path,
    )

    p = _discover_default_config_path()
    assert p.name == "hibayes_functional_usefulness.yaml"
    assert p.parent.name == "config"


def test_main_help_exits_zero() -> None:
    """In-image coverage pin (mirror of task-10's DL-038 hardener pass 2 D1
    MED): invoke `main()` with `--help` so argparse setup +
    `_DEFAULT_CONFIG_PATH` default-binding are covered. argparse raises
    SystemExit(0) on `--help`.

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
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import main

    with pytest.raises(SystemExit) as excinfo:
        main(["--help"])
    assert excinfo.value.code == 0


def test_main_end_to_end_with_minimal_csv(tmp_path: Path) -> None:
    """In-image coverage pin (mirror of task-10's DL-038 hardener pass 2 D1
    MED): drive `main()` end-to-end through the argparse → YAML-config-load
    → `run_functional_axis` path so the body of `main()` (currently
    unexercised by `test_run_hibayes_consumes_functional_csv`, which calls
    `run_functional_axis` directly) reaches the in-image 95% coverage floor.

    Skipped on host (per-test `pytest.importorskip`) because `main` triggers
    a real hibayes fit; runs in-image where hibayes is installed.
    """
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import main

    fu_csv = tmp_path / "fu.csv"
    # 12-column header per locked §5.3 (identical to the
    # test_run_hibayes_consumes_functional_csv fixture above).
    fu_csv.write_text(
        "query_id,task_family,expected_behavior,runtime_success,artifact_status,"
        "outcome,usefulness_score,primary_issue,functional_success,"
        "needs_human_review,review_priority,rationale\n"
    )
    for i in range(1, 4):
        for fam in ("Search-Basic", "Report-GEO"):
            success = "True" if i != 3 else "False"
            outcome = "FullySatisfied" if success == "True" else "NotSatisfied"
            primary_issue = "NoIssue" if success == "True" else "RuntimeFailure"
            review_priority = "Low" if success == "True" else "High"
            needs_review = "False" if success == "True" else "True"
            fu_csv.write_text(
                fu_csv.read_text()
                + f"Q-{fam}-{i},{fam},AnswerExpected,{success},Valid,"
                f"{outcome},3,{primary_issue},{success},"
                f"{needs_review},{review_priority},r\n"
            )
    out_dir = tmp_path / "out"
    out_dir.mkdir()
    # `main` returns 0 on success; default `--config` resolves to the packaged
    # YAML via `_DEFAULT_CONFIG_PATH` (DL-028 sub-condition (c) discovery path).
    rc = main(["--input", str(fu_csv), "--out-dir", str(out_dir), "--seed", "42"])
    assert rc == 0
    posterior_path = out_dir / "posterior.json"
    assert posterior_path.is_file()
    payload = json.loads(posterior_path.read_text(encoding="utf-8"))
    assert payload["axis"] == "functional"
    assert payload["model"] == "two_level_group_binomial"


# --- Deterministic in-image coverage pins -----------------------------------
# The MCMC-driven end-to-end tests above only exercise whichever `_band`
# branches the (non-deterministic across strata) posterior happens to land in.
# The four tests below pin the pure deterministic helpers — `_band`'s four
# banding branches, `_fit_two_level_group_binomial`'s empty-aggregate early
# return, `load_csv`'s malformed-row skip, and `models.py`'s HDI-ordering
# validator — so the in-image `--cov` gate reaches its 95% floor regardless of
# the sampler RNG. `_band` + `_fit...` live in `run_hibayes.py` (module-level
# `import hibayes` per DL-028) so they gate with per-test `importorskip`.


def test_band_covers_all_four_branches() -> None:
    """Pin every `_band` return branch — deterministic, RNG-independent."""
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import _band

    # n_total < 3 → TooUncertain (regardless of the rate args).
    assert _band(0.99, 0.0, 0.0, n_total=2) == "TooUncertain"
    # high mean + low p_lt_strong → Reliable.
    assert _band(0.97, 0.05, 0.01, n_total=10) == "Reliable"
    # high p_lt_acceptable → Brittle.
    assert _band(0.50, 0.90, 0.70, n_total=10) == "Brittle"
    # moderate mean + low p_lt_acceptable → Watch.
    assert _band(0.85, 0.40, 0.10, n_total=10) == "Watch"
    # everything else → TooUncertain (final fallthrough).
    assert _band(0.60, 0.40, 0.40, n_total=10) == "TooUncertain"


def test_fit_returns_empty_for_no_aggregates() -> None:
    """Pin `_fit_two_level_group_binomial`'s empty-aggregate early return."""
    pytest.importorskip("hibayes")
    from dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes import (
        _fit_two_level_group_binomial,
    )

    result = _fit_two_level_group_binomial(
        [], prior_sigma_group_scale=2.0, thresholds={"strong": 0.9}, seed=1
    )
    assert result == []


def test_load_csv_skips_malformed_rows(tmp_path: Path) -> None:
    """Pin `load_functional_usefulness_csv`'s per-row exception skip.

    Host-runnable — `load_csv.py` is hibayes-import-clean. A row missing the
    required `query_id` / `task_family` cells (here: a short row) is skipped
    rather than aborting the load.
    """
    from dmac_assistant.eval.hibayes_functional_usefulness.load_csv import (
        load_functional_usefulness_csv,
    )

    csv_path = tmp_path / "fu.csv"
    csv_path.write_text(
        "query_id,task_family,functional_success\n"
        "Q-1,Fam-A,True\n"
        # Malformed: DictReader yields None for the missing columns, which
        # `.lower()` cannot handle for `functional_success` — row is skipped.
        "Q-2\n"
        "Q-3,Fam-A,False\n",
        encoding="utf-8",
    )
    rows = load_functional_usefulness_csv(csv_path)
    assert [r.query_id for r in rows] == ["Q-1", "Q-3"]


def test_posterior_model_rejects_inverted_hdi() -> None:
    """Pin `models.py`'s HDI-ordering validator (hdi_low > hdi_high → error).

    Host-runnable — `models.py` is hibayes-import-clean per locked DD-42.
    """
    import pydantic

    from dmac_assistant.eval.hibayes_functional_usefulness.models import (
        PosteriorTaskFamilyReliability,
    )

    with pytest.raises(pydantic.ValidationError):
        PosteriorTaskFamilyReliability(
            task_family="Fam-A",
            n_total=3,
            posterior_mean=0.5,
            posterior_median=0.5,
            hdi_low=0.9,
            hdi_high=0.1,
            p_success_lt_strong=0.1,
            p_success_lt_acceptable=0.1,
            band="Watch",
        )
