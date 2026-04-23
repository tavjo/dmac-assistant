"""Capture a pinned Claude stream-json fixture from the local Docker image."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = REPO_ROOT / "Dockerfile"
FIXTURE_DIR = REPO_ROOT / "tests" / "unit" / "fixtures"


def _pinned_version() -> str:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")
    match = re.search(r"claude-code@([0-9.]+)", dockerfile)
    if match is None:
        raise RuntimeError("Could not find pinned claude-code version in Dockerfile")
    return match.group(1)


def main() -> int:
    version = _pinned_version()
    target = FIXTURE_DIR / f"streamjson_init_{version}.jsonl"
    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)

    cmd = [
        "docker",
        "run",
        "--rm",
        "--entrypoint",
        "claude",
        "dmac-assistant:poc",
        "--print",
        "--output-format",
        "stream-json",
        "--dangerously-skip-permissions",
        "reply with exactly OK",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or "docker capture failed")

    lines = [line for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        raise RuntimeError("docker capture produced no stream-json lines")

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {target.relative_to(REPO_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
