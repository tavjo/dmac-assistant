#!/usr/bin/env bash
# run_hibayes_eval_functional.sh — thin wrapper around `docker run hibayes-runtime-reliability:dev`
# for the functional-usefulness in-image axis (Stage D for T3.2).
#
# Per plan-DD-01 / locked DD-21 Option (b): per-axis sibling wrapper.
# Per locked DD-28: source dirs are config/ and report_template/ under hibayes_functional_usefulness/.
# Container-side mount targets remain /work/config and /work/templates (canonical).
#
# Usage:
#   scripts/run_hibayes_eval_functional.sh python -m dmac_assistant.eval.hibayes_functional_usefulness.run_hibayes --help
#   scripts/run_hibayes_eval_functional.sh pytest tests/unit/eval/test_hibayes_functional_usefulness.py -q
#
# Environment overrides:
#   IMAGE  — image tag (default: hibayes-runtime-reliability:dev)
#   REPO   — repo root (default: git rev-parse --show-toplevel)

set -euo pipefail

IMAGE="${IMAGE:-hibayes-runtime-reliability:dev}"
REPO="${REPO:-$(git rev-parse --show-toplevel)}"

mkdir -p "${REPO}/out"
mkdir -p "${REPO}/data"

# PYTHONPATH=/work/src is REQUIRED. See scripts/run_hibayes_eval.sh:25-34 for the
# canonical explanation.
# build_tools/ is mounted at /work/build_tools and /work is added to PYTHONPATH
# because tests/conftest.py imports build_tools.verify_env at collection time
# (task-3R2).
docker run --rm \
    --platform linux/amd64 \
    -e PYTHONPATH=/work:/work/src \
    -v "${REPO}/src:/work/src:ro" \
    -v "${REPO}/tests:/work/tests:ro" \
    -v "${REPO}/tools:/work/tools:ro" \
    -v "${REPO}/build_tools:/work/build_tools:ro" \
    -v "${REPO}/data:/work/data:ro" \
    -v "${REPO}/out:/work/out:rw" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_functional_usefulness/config:/work/config:ro" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_functional_usefulness/report_template:/work/templates:ro" \
    "${IMAGE}" \
    uv run "$@"
