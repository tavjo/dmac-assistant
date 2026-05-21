#!/usr/bin/env bash
# run_hibayes_eval_artifact.sh — thin wrapper around `docker run hibayes-runtime-reliability:dev`
# for the artifact-validity in-image axis (Stage D for T3.1).
#
# Per plan-DD-01 / locked DD-21 Option (b): per-axis sibling wrapper.
# Per locked DD-28: source dirs are config/ and report_template/ under hibayes_artifact_validity/.
# Container-side mount targets remain /work/config and /work/templates (canonical).
#
# Usage:
#   scripts/run_hibayes_eval_artifact.sh python -m dmac_assistant.eval.hibayes_artifact_validity.run_hibayes --help
#   scripts/run_hibayes_eval_artifact.sh pytest tests/unit/eval/test_hibayes_artifact_validity.py -q
#
# Environment overrides:
#   IMAGE  — image tag (default: hibayes-runtime-reliability:dev)
#   REPO   — repo root (default: git rev-parse --show-toplevel)

set -euo pipefail

IMAGE="${IMAGE:-hibayes-runtime-reliability:dev}"
REPO="${REPO:-$(git rev-parse --show-toplevel)}"

mkdir -p "${REPO}/out"
mkdir -p "${REPO}/data"

# PYTHONPATH=/work/src is REQUIRED. The image is built with
# `uv sync --no-install-project` so `dmac_assistant` is NOT installed in
# /work/.venv; the package is reached exclusively through the live bind-mount
# at /work/src. The pyproject `pythonpath = ["src", "."]` is pytest-only and
# does NOT cover `python -m dmac_assistant.eval...run_hibayes`. See
# scripts/run_hibayes_eval.sh:25-34 for the canonical comment block.
docker run --rm \
    --platform linux/amd64 \
    -e PYTHONPATH=/work/src \
    -v "${REPO}/src:/work/src:ro" \
    -v "${REPO}/tests:/work/tests:ro" \
    -v "${REPO}/tools:/work/tools:ro" \
    -v "${REPO}/data:/work/data:ro" \
    -v "${REPO}/out:/work/out:rw" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_artifact_validity/config:/work/config:ro" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_artifact_validity/report_template:/work/templates:ro" \
    "${IMAGE}" \
    uv run "$@"
