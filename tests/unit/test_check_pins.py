from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from tests.unit import check_pins

SENTINEL = check_pins.SENTINEL


def _write_registry(tmp_path: Path, pins: list[str]) -> tuple[Path, Path]:
    registry = tmp_path / "pinned_nodes.txt"
    block = "".join(f"{pin}\n" for pin in pins) + SENTINEL + "\n"
    registry.write_text(block)
    sha = tmp_path / "pinned_nodes.required.sha256"
    import hashlib

    sha.write_text(hashlib.sha256(block.encode()).hexdigest() + "\n")
    return registry, sha


def _write_junit(tmp_path: Path, body: str) -> Path:
    junit = tmp_path / "junit.xml"
    junit.write_text(
        "<?xml version='1.0' encoding='utf-8'?><testsuite>"
        + body
        + "</testsuite>"
    )
    return junit


def _run(tmp_path: Path, pins: list[str], junit_body: str) -> int:
    registry, sha = _write_registry(tmp_path, pins)
    junit = _write_junit(tmp_path, junit_body)
    return check_pins.main([
        "test_example.py",
        str(junit),
        "--registry",
        str(registry),
        "--sha",
        str(sha),
    ])


def test_check_pins_rejects_missing_pin(tmp_path):
    rc = _run(tmp_path, ["tests/unit/test_example.py::test_required"], "")
    assert rc == 1


def test_check_pins_rejects_skipped_pin(tmp_path):
    rc = _run(
        tmp_path,
        ["tests/unit/test_example.py::test_required"],
        "<testcase classname='tests.unit.test_example' name='test_required'><skipped /></testcase>",
    )
    assert rc == 1


def test_check_pins_rejects_errored_pin(tmp_path):
    rc = _run(
        tmp_path,
        ["tests/unit/test_example.py::test_required"],
        "<testcase classname='tests.unit.test_example' name='test_required'><error /></testcase>",
    )
    assert rc == 1


def test_check_pins_rejects_failed_pin(tmp_path):
    rc = _run(
        tmp_path,
        ["tests/unit/test_example.py::test_required"],
        "<testcase classname='tests.unit.test_example' name='test_required'><failure /></testcase>",
    )
    assert rc == 1


def test_check_pins_param_pin_matches_present(tmp_path):
    rc = _run(
        tmp_path,
        ["tests/unit/test_example.py::test_param[case]"],
        "<testcase classname='tests.unit.test_example' name='test_param[case]' />",
    )
    assert rc == 0


def test_check_pins_param_pin_rejects_absent(tmp_path):
    rc = _run(
        tmp_path,
        ["tests/unit/test_example.py::test_param[case]"],
        "<testcase classname='tests.unit.test_example' name='test_param[other]' />",
    )
    assert rc == 1


def test_check_pins_rejects_right_name_wrong_file(tmp_path):
    rc = _run(
        tmp_path,
        ["tests/unit/test_example.py::test_required"],
        "<testcase classname='tests.unit.other_file' name='test_required' />",
    )
    assert rc == 1


def test_check_pins_rejects_tampered_required_block(tmp_path):
    registry, sha = _write_registry(tmp_path, ["tests/unit/test_example.py::test_required"])
    registry.write_text(registry.read_text().replace("test_required", "test_other"))
    junit = _write_junit(
        tmp_path,
        "<testcase classname='tests.unit.test_example' name='test_other' />",
    )
    assert check_pins.main([
        "test_example.py",
        str(junit),
        "--registry",
        str(registry),
        "--sha",
        str(sha),
    ]) == 1


def test_check_pins_real_junit_oracle(tmp_path):
    test_file = tmp_path / "test_real_oracle.py"
    test_file.write_text(
        textwrap.dedent(
            """
            import pytest

            def test_pass[case]():
                pass
            """
        ).replace("test_pass[case]", "test_pass")
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(test_file),
            "--override-ini",
            "addopts=-q",
            "--junitxml",
            str(tmp_path / "real.xml"),
        ],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    assert result.returncode == 0
    registry, sha = _write_registry(tmp_path, [f"{test_file}::test_pass"])
    errors = check_pins.check_pins(
        test_file.name,
        tmp_path / "real.xml",
        registry=registry,
        sha_path=sha,
    )
    assert errors == []
