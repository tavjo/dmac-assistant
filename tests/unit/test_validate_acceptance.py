"""Hermetic coverage for the OI-3 T6 acceptance validator.

These tests exercise ``tools/oi3-acceptance/validate_acceptance.py`` against the
committed synthetic PASS fixture and against programmatically-mutated FAILING
variants. They make NO network call, NO Docker call, and NO Bedrock call — the
validator is a pure file-reading function, so its gate logic is fully provable
with zero spend (the entire point of the T6 verification path).

Import strategy mirrors ``tests/unit/test_bedrock_proxy.py``: the validator lives
under the hyphen-free ``tools/oi3-acceptance/`` dir (not a Python package on the
default path), so we put that dir on ``sys.path`` and import the module by name.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_DIR = REPO_ROOT / "tools" / "oi3-acceptance"
if str(TOOL_DIR) not in sys.path:
    sys.path.insert(0, str(TOOL_DIR))

import validate_acceptance as va  # noqa: E402

PASS_FIXTURE = TOOL_DIR / "runs" / "_fixture_selftest"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _copy_fixture(dst: Path) -> Path:
    """Copy the committed PASS fixture into a writable temp dir."""
    shutil.copytree(PASS_FIXTURE, dst)
    return dst


def _conditions_by_name(run_dir: Path) -> dict[str, va.Condition]:
    return {c.name: c for c in va.validate(run_dir)}


# ---------------------------------------------------------------------------
# PASS fixture
# ---------------------------------------------------------------------------

def test_pass_fixture_exists_and_all_conditions_pass():
    assert PASS_FIXTURE.is_dir(), f"committed PASS fixture missing: {PASS_FIXTURE}"
    conditions = va.validate(PASS_FIXTURE)
    assert len(conditions) == 7
    failing = [c.name for c in conditions if not c.passed]
    assert not failing, f"PASS fixture should satisfy all conditions; failed: {failing}"


def test_pass_fixture_main_exits_zero(capsys):
    rc = va.main([str(PASS_FIXTURE)])
    assert rc == 0
    out = capsys.readouterr().out
    assert "RESULT: PASS" in out
    # Every condition prints a PASS line.
    assert out.count("PASS") >= 7


# ---------------------------------------------------------------------------
# Structural / usage failures
# ---------------------------------------------------------------------------

def test_nonexistent_run_dir_exits_2(tmp_path, capsys):
    missing = tmp_path / "does-not-exist"
    rc = va.main([str(missing)])
    assert rc == 2


def test_wrong_arg_count_exits_2():
    assert va.main([]) == 2
    assert va.main(["a", "b"]) == 2


# ---------------------------------------------------------------------------
# Per-condition FAILING variants (each must drop the run to a non-zero exit)
# ---------------------------------------------------------------------------

def test_fail_mode_transcript_is_error_true(tmp_path, capsys):
    """Condition 2: flip the result frame to is_error=true → non-zero exit."""
    run_dir = _copy_fixture(tmp_path / "run")
    transcript = run_dir / "turn_transcript.jsonl"
    lines = transcript.read_text(encoding="utf-8").splitlines()
    mutated = []
    for ln in lines:
        frame = json.loads(ln)
        if frame.get("type") == "result":
            frame["is_error"] = True
            frame["subtype"] = "error_during_execution"
        mutated.append(json.dumps(frame))
    transcript.write_text("\n".join(mutated) + "\n", encoding="utf-8")

    conditions = _conditions_by_name(run_dir)
    assert conditions["turn-no-error-and-reply"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_proxylog_did_not_grow(tmp_path):
    """Condition 5: proxylog-bytes-after <= before → traversal provenance fails."""
    run_dir = _copy_fixture(tmp_path / "run")
    proxy = run_dir / "proxy_log.txt"
    text = proxy.read_text(encoding="utf-8")
    # Make after < before (a local stub never grows the live log).
    text = text.replace("proxylog-bytes-after: 2048", "proxylog-bytes-after: 512")
    proxy.write_text(text, encoding="utf-8")

    conditions = _conditions_by_name(run_dir)
    assert conditions["proxy-traversal-provenance"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_token_hit_in_agent_env(tmp_path):
    """Condition 4: a non-zero aws-token-hits count fails the env-clean gate."""
    run_dir = _copy_fixture(tmp_path / "run")
    scan = run_dir / "agent_env_scan.txt"
    text = scan.read_text(encoding="utf-8").replace("aws-token-hits: 0", "aws-token-hits: 1")
    scan.write_text(text, encoding="utf-8")

    conditions = _conditions_by_name(run_dir)
    assert conditions["agent-env-token-clean"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_bearer_key_present(tmp_path):
    """Condition 4: bearer-key-name-present: true fails even with 0 token hits."""
    run_dir = _copy_fixture(tmp_path / "run")
    scan = run_dir / "agent_env_scan.txt"
    text = scan.read_text(encoding="utf-8").replace(
        "bearer-key-name-present: false", "bearer-key-name-present: true"
    )
    scan.write_text(text, encoding="utf-8")
    assert _conditions_by_name(run_dir)["agent-env-token-clean"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_token_hit_in_proxy_log(tmp_path):
    """Condition 6: a non-zero token-hits in the proxy log fails (G3)."""
    run_dir = _copy_fixture(tmp_path / "run")
    proxy = run_dir / "proxy_log.txt"
    text = proxy.read_text(encoding="utf-8").replace("token-hits: 0", "token-hits: 2")
    proxy.write_text(text, encoding="utf-8")
    assert _conditions_by_name(run_dir)["proxy-log-token-clean"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_ledger_over_cap(tmp_path):
    """Condition 1: ledger total over $5.00 fails."""
    run_dir = _copy_fixture(tmp_path / "run")
    ledger = run_dir / "ledger.json"
    data = json.loads(ledger.read_text(encoding="utf-8"))
    data["total_usd"] = 7.50
    ledger.write_text(json.dumps(data), encoding="utf-8")
    assert _conditions_by_name(run_dir)["ledger-total-within-cap"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_sentinel_not_echoed_in_reply(tmp_path):
    """Condition 5: model reply lacks the sentinel → cross-witness fails."""
    run_dir = _copy_fixture(tmp_path / "run")
    transcript = run_dir / "turn_transcript.jsonl"
    text = transcript.read_text(encoding="utf-8").replace(
        "00000000-fake-fake-fake-000000000000",
        "DIFFERENT-token-not-the-sentinel",
        1,  # only replace in the assistant reply (first occurrence)
    )
    transcript.write_text(text, encoding="utf-8")
    assert _conditions_by_name(run_dir)["proxy-traversal-provenance"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_missing_raw_config_env_block(tmp_path):
    """Condition 3: drop the RAW Config.Env markers → container provenance fails
    (defeats the summary-only / wrong-container fake)."""
    run_dir = _copy_fixture(tmp_path / "run")
    scan = run_dir / "agent_env_scan.txt"
    text = scan.read_text(encoding="utf-8")
    text = text.replace(va._RAW_ENV_BEGIN, "").replace(va._RAW_ENV_END, "")
    scan.write_text(text, encoding="utf-8")
    assert _conditions_by_name(run_dir)["container-identity-provenance"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_empty_raw_config_env_block(tmp_path):
    """Condition 3: markers present but empty body → still fails (non-empty check)."""
    run_dir = _copy_fixture(tmp_path / "run")
    scan = run_dir / "agent_env_scan.txt"
    lines = scan.read_text(encoding="utf-8").splitlines()
    out, skipping = [], False
    for ln in lines:
        if ln.strip() == va._RAW_ENV_BEGIN:
            out.append(ln)
            skipping = True
            continue
        if ln.strip() == va._RAW_ENV_END:
            skipping = False
            out.append(ln)
            continue
        if not skipping:
            out.append(ln)
    scan.write_text("\n".join(out) + "\n", encoding="utf-8")
    assert _conditions_by_name(run_dir)["container-identity-provenance"].passed is False
    assert va.main([str(run_dir)]) == 1


def test_fail_mode_classifier_verdict_invalid_json(tmp_path):
    """Condition 7: unparseable classifier_verdict.json fails."""
    run_dir = _copy_fixture(tmp_path / "run")
    (run_dir / "classifier_verdict.json").write_text("{not json", encoding="utf-8")
    assert _conditions_by_name(run_dir)["classifier-verdict-parses"].passed is False
    assert va.main([str(run_dir)]) == 1


@pytest.mark.parametrize("artifact", [
    "ledger.json",
    "turn_transcript.jsonl",
    "agent_env_scan.txt",
    "proxy_log.txt",
    "classifier_verdict.json",
])
def test_fail_mode_missing_artifact(tmp_path, artifact):
    """Any missing artifact drops the run to a non-zero exit."""
    run_dir = _copy_fixture(tmp_path / "run")
    (run_dir / artifact).unlink()
    assert va.main([str(run_dir)]) == 1


def test_empty_transcript_is_error(tmp_path):
    """A transcript with no result frame is treated as an error (fail-closed)."""
    run_dir = _copy_fixture(tmp_path / "run")
    (run_dir / "turn_transcript.jsonl").write_text("", encoding="utf-8")
    is_error, reply = va._extract_reply_text("")
    assert is_error is True
    assert reply == ""
    assert va.main([str(run_dir)]) == 1
