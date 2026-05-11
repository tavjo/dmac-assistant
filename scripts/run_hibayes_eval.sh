#!/usr/bin/env bash
# run_hibayes_eval.sh — thin wrapper around `docker run hibayes-runtime-reliability:dev`.
# Mounts src/, tests/, data/, out/ at the canonical container paths and forwards
# all remaining args to `uv run` inside the container.
#
# Usage:
#   scripts/run_hibayes_eval.sh pytest tests/unit/eval -q
#   scripts/run_hibayes_eval.sh python -m dmac_assistant.eval.hibayes_runtime_reliability.run_hibayes --help
#
# Environment overrides:
#   IMAGE  — image tag (default: hibayes-runtime-reliability:dev)
#   REPO   — repo root (default: git rev-parse --show-toplevel)

set -euo pipefail

IMAGE="${IMAGE:-hibayes-runtime-reliability:dev}"
REPO="${REPO:-$(git rev-parse --show-toplevel)}"

mkdir -p "${REPO}/out"
mkdir -p "${REPO}/data"

docker run --rm \
    --platform linux/amd64 \
    -v "${REPO}/src:/work/src:ro" \
    -v "${REPO}/tests:/work/tests:ro" \
    -v "${REPO}/data:/work/data:ro" \
    -v "${REPO}/out:/work/out:rw" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_runtime_reliability/config:/work/config:ro" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_runtime_reliability/templates:/work/templates:ro" \
    "${IMAGE}" \
    uv run "$@"
