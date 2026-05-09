# HiBayes CSV Exporter

Converts a DMAC Assistant headless-run HTML report into a HiBayes-ready 14-column CSV.

## Install

```bash
uv sync --group tools   # installs pandas (used by .to_dataframe())
```

## Run

```bash
uv run python -m tools.hibayes.exporter \
    evidence/headless/<RUN_ID>/report.html
# Default output: <report-dir>/hibayes_eval_rows.csv

# Mark a run as Opus (default is Sonnet → is_opus=0):
uv run python -m tools.hibayes.exporter <report.html> --model-family opus

# Custom output path:
uv run python -m tools.hibayes.exporter <report.html> --output /tmp/my.csv
```

## Tests

```bash
uv run pytest tools/hibayes/tests \
    --override-ini="addopts=" \
    --override-ini="testpaths=tools/hibayes/tests" \
    --disable-socket \
    --cov=tools/hibayes --cov-report=term-missing --cov-fail-under=95
```

The bridge `pyproject.toml` injects coverage flags scoped to `src/dmac_assistant`.
The `--override-ini` flags above strip those so the coverage gate runs against
`tools/hibayes/` only. See plan `.claude/plans/hibayes-csv-exporter-2026-05-08.md`
DD-13 for the rationale.

## Notes

- The `--use-llm-classifier` flag is reserved but not yet implemented; it raises
  `NotImplementedError`. BAML scaffolding is deferred — see plan DD-11.
- Output CSV columns are locked in this order: `query_id, task_family, task_subtype,
  image, answer_provided, is_error, timed_out, runtime_success, failure_mode,
  latency_seconds, cost_usd, tool_calls_total, artifact_count, is_opus`.
