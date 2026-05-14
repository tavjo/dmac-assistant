# Changelog

All notable changes to this project are documented here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); this project is pre-release so versions are dated rather than semver-numbered.

## [Unreleased]

### Added — 2026-05-13 — HiBayes runtime-reliability analysis pipeline

Offline analysis tool that consumes the HiBayes-ready CSV emitted by `tools/hibayes/exporter.py` and produces per-task-family Bayesian posterior estimates of agent success probability. Output: self-contained HTML report plus CSV/JSON artifacts under `out/hibayes_runtime_reliability/`. Plan: `hibayes-runtime-reliability-2026-05-09` (8 tasks, Wave 1–5, Phase 7 round-4 reviewer PASS).

New files:
- `src/dmac_assistant/eval/hibayes_runtime_reliability/` — pipeline source (models, loader, aggregator, HiBayes runner + CLI, HTML renderer, packaged config + Jinja2 template, in-tree README).
- `Dockerfile.hibayes-eval` — builds the sibling `hibayes-runtime-reliability:dev` image (HiBayes installed via pinned git SHA).
- `scripts/run_hibayes_eval.sh` — wrapper around `docker run hibayes-runtime-reliability:dev` with the canonical mount contract.
- `.coveragerc.in-container` — in-container coverage config (no eval omit; used by §6.2/§6.3 task-07 gates).
- `tests/unit/eval/`, `tests/integration/test_hibayes_pipeline.py`, `tests/fixtures/hibayes_runtime_reliability/` — full test suite (98% in-container package coverage on the eval modules).
- `Makefile`: `hibayes-eval-build` target.

CLI:
```sh
uv run python -m dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes \
    --input <hibayes_eval_rows.csv> --out <output_dir>
```

### Changed — 2026-05-13 — Split-coverage model for the host pytest gate

`pyproject.toml` now carries `[tool.coverage.run] omit = ["src/dmac_assistant/eval/*"]` so the host-side coverage gate measures the bridge subtree only. The eval pipeline modules cannot be exercised on the host venv (their runtime deps live exclusively in the `hibayes-runtime-reliability:dev` image, per DD-13) — their `pytest.importorskip` guards make them skip cleanly host-side. Coverage for those modules is enforced inside the container at ≥95% via the §6.2/§6.3 gates referencing `.coveragerc.in-container`. Together the two gates cover the full `src/dmac_assistant/` tree without overlap. Formalized as plan Amendment 7.

Host-side gate (post-change): **98.84% on 1464 statements**, 624 passed.
In-container gate (post-change): **98% on 520 statements**, 122 passed, 0 failed.

### Notes

Plan A (POC bridge + container + plugin shims, completed 2026-05-01) is documented in the plan files under `.claude/plans/` (gitignored). The original Plan A merge predates this changelog; entries here begin with the 2026-05-13 hibayes pipeline merge.
