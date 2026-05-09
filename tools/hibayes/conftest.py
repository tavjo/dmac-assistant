"""Make `tools.hibayes.exporter` importable when running pytest from the repo root.

Bridge `pyproject.toml` sets `pythonpath = ["src"]`, which excludes the repo root,
so `import tools.hibayes.exporter` would fail without this conftest.

This file is at `tools/hibayes/conftest.py`, so:
    parents[0] = tools/hibayes/
    parents[1] = tools/
    parents[2] = <repo root>   ← what we insert
so we use `parents[2]`. Phase 4 BLOCKER-1: do NOT copy `parents[1]` from the
sibling `tools/e2e/run_judge_batch.py:16` — that file inserts `tools/` (parents[1])
because it imports SIBLING modules under `tools.e2e.*`. We need the repo root
because we resolve `tools.hibayes.exporter` from the absolute package root. Same
technique, different index, different reason. Don't blindly mirror.

Run with: see DD-13 in plan hibayes-csv-exporter-2026-05-08.
"""
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
