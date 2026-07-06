"""Independent static verifier for the batch-upload pin registry contract."""
from __future__ import annotations

import argparse
import hashlib
import pathlib

SENTINEL = "# === END REQUIRED (T0-sealed; do NOT edit above this line) ==="
MIN_REQUIRED_NODE_IDS = 1


def _required_block(path: pathlib.Path) -> str:
    lines: list[str] = []
    for line in path.read_text().splitlines(keepends=True):
        lines.append(line)
        if line.rstrip("\n") == SENTINEL:
            return "".join(lines)
    raise ValueError("missing required sentinel")


def _node_count(block: str) -> int:
    return sum(
        1
        for raw in block.splitlines()
        if raw.strip() and not raw.lstrip().startswith("#")
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("registry")
    parser.add_argument("sha")
    args = parser.parse_args()
    block = _required_block(pathlib.Path(args.registry))
    actual = hashlib.sha256(block.encode()).hexdigest()
    expected = pathlib.Path(args.sha).read_text().strip()
    if actual != expected:
        raise SystemExit("required block sha mismatch")
    count = _node_count(block)
    if count < MIN_REQUIRED_NODE_IDS:
        raise SystemExit("required block has too few node ids")
    print(f"ok {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
