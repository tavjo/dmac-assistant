#!/usr/bin/env bash
# T4.2 / DL-025 — in-image wrapper for the combined-report renderer.
# Per locked DD-21 line 226 + DD-41 line 381: combined report runs in-image.
#
# ESC-5 resolution (Pass 3 / AM-001 / DL-032 — Option α):
# Per-axis section partials are discovered by task-13's render.py via
# Python-module-relative paths (`importlib.util.find_spec(<axis_module>)`),
# NOT via bind-mount target literals. The wider `-v "${REPO}/src:/work/src:ro"`
# mount below is sufficient: it exposes every per-axis module (including its
# `report_template/section.html.j2`, when present) at `/work/src/dmac_assistant/eval/…`,
# and `PYTHONPATH=/work/src` makes those modules importable so
# `importlib.util.find_spec` resolves them. The combined-report's own
# `report_template/` (containing `combined.html.j2`) is mounted at
# `/work/templates` for the renderer's primary FileSystemLoader search path.

set -euo pipefail

IMAGE="${IMAGE:-hibayes-runtime-reliability:dev}"
REPO="${REPO:-$(git rev-parse --show-toplevel)}"

mkdir -p "${REPO}/out"

docker run --rm \
    --platform linux/amd64 \
    -e PYTHONPATH=/work/src \
    -v "${REPO}/src:/work/src:ro" \
    -v "${REPO}/tools:/work/tools:ro" \
    -v "${REPO}/out:/work/out:rw" \
    -v "${REPO}/src/dmac_assistant/eval/hibayes_combined_report/report_template:/work/templates:ro" \
    "${IMAGE}" \
    uv run "$@"
