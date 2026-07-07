"""Validate required pytest node ids against a JUnit XML report."""
from __future__ import annotations

import argparse
import hashlib
import pathlib
import sys
import xml.etree.ElementTree as ET

SENTINEL = "# === END REQUIRED (T0-sealed; do NOT edit above this line) ==="


def required_block(registry: pathlib.Path) -> str:
    lines: list[str] = []
    for line in registry.read_text().splitlines(keepends=True):
        lines.append(line)
        if line.rstrip("\n") == SENTINEL:
            return "".join(lines)
    raise ValueError("missing required-block sentinel")


def verify_required_sha(registry: pathlib.Path, sha_path: pathlib.Path) -> None:
    actual = hashlib.sha256(required_block(registry).encode()).hexdigest()
    expected = sha_path.read_text().strip()
    if actual != expected:
        raise ValueError("pinned_nodes required block sha256 mismatch")


def required_pins(registry: pathlib.Path, file_token: str) -> list[str]:
    pins: list[str] = []
    for raw in required_block(registry).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if file_token in line:
            pins.append(line)
    return pins


def _bare_name(node_id: str) -> str:
    return node_id.rsplit("::", 1)[-1]


def _pin_file(node_id: str) -> str:
    return node_id.split("::", 1)[0]


def _case_file(case: ET.Element) -> str:
    file_attr = case.attrib.get("file")
    if file_attr:
        return file_attr
    classname = case.attrib.get("classname", "").replace(".", "/")
    return classname + ".py"


def _case_matches(case: ET.Element, pin: str) -> bool:
    expected_name = _bare_name(pin)
    actual_name = case.attrib.get("name", "")
    if actual_name != expected_name:
        return False
    expected_file = _pin_file(pin)
    return expected_file.endswith(_case_file(case)) or _case_file(case).endswith(expected_file)


def check_pins(
    file_token: str,
    junit_xml: pathlib.Path,
    *,
    registry: pathlib.Path,
    sha_path: pathlib.Path,
) -> list[str]:
    verify_required_sha(registry, sha_path)
    pins = required_pins(registry, file_token)
    tree = ET.parse(junit_xml)
    cases = list(tree.iter("testcase"))
    errors: list[str] = []
    for pin in pins:
        matches = [case for case in cases if _case_matches(case, pin)]
        if not matches:
            errors.append(f"missing required pin: {pin}")
            continue
        bad_children = [
            child.tag
            for case in matches
            for child in list(case)
            if child.tag in {"skipped", "error", "failure"}
        ]
        if bad_children:
            errors.append(f"required pin did not pass cleanly: {pin} ({','.join(bad_children)})")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("file_token")
    parser.add_argument("junit_xml")
    parser.add_argument("--registry", default="tests/unit/pinned_nodes.txt")
    parser.add_argument("--sha", default="tests/unit/pinned_nodes.required.sha256")
    args = parser.parse_args(argv)
    try:
        errors = check_pins(
            args.file_token,
            pathlib.Path(args.junit_xml),
            registry=pathlib.Path(args.registry),
            sha_path=pathlib.Path(args.sha),
        )
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
