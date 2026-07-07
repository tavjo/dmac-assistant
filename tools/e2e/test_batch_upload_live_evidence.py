"""Hermetic ($0, socket-disabled) tests for the T10 live-paid evidence logic + verifier.

Run:
    env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tools/e2e/test_batch_upload_live_evidence.py \
      --override-ini "addopts=--disable-socket -q" \
      --cov=tools/e2e/batch_upload_live_evidence --cov=tools/e2e/verify_batch_upload_live \
      --cov-report=term-missing --cov-fail-under=95
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from tools.e2e import batch_upload_live_evidence as ev  # noqa: E402
from tools.e2e import verify_batch_upload_live as vr  # noqa: E402


# ---------------------------------------------------------------------------
# Frame builders


def _bash(command: str, fid: str = "t1") -> dict:
    return {"type": "tool_use", "tool": "Bash", "input": {"command": command}, "id": fid}


def _route(route: str = "container_cc", model_class: str = "opus") -> dict:
    return {"type": "route_decided", "route": route, "model_class": model_class}


def _reply(text: str) -> dict:
    return {"type": "assistant_message", "content": text}


def _ended(*, session_id: str = "sess-1", cost: object = 0.3, usage=None) -> dict:
    frame: dict[str, object] = {"type": "session_ended", "session_id": session_id}
    if cost is not None:
        frame["total_cost_usd"] = cost
    if usage is not None:
        frame["usage"] = usage
    return frame


def _all_shims_bash() -> list[dict]:
    return [_bash(f"{shim} --project-id 1", fid=f"t-{shim}") for shim in ev.BATCH_UPLOAD_SHIMS]


def _good_frames(cost=0.3) -> list[dict]:
    return [
        _route(),
        *_all_shims_bash(),
        _reply("Built workbook /data/scratch/upload.xlsx; validation valid=true."),
        _ended(cost=cost),
    ]


# ---------------------------------------------------------------------------
# Cost


def test_extract_cost_authoritative():
    c = ev.extract_cost([_ended(cost=0.4242)])
    assert c.cost_usd == pytest.approx(0.4242)
    assert c.cost_source == ev.COST_SOURCE_AUTHORITATIVE
    assert c.has_result_frame is True


def test_extract_cost_authoritative_zero_is_still_authoritative():
    c = ev.extract_cost([_ended(cost=0.0)])
    assert c.cost_usd == 0.0
    assert c.cost_source == ev.COST_SOURCE_AUTHORITATIVE


def test_extract_cost_bool_total_is_not_numeric():
    # A stray boolean must NOT be read as a cost figure.
    c = ev.extract_cost([_ended(cost=True, usage={"input_tokens": 10, "output_tokens": 2})])
    assert c.cost_source == ev.COST_SOURCE_ESTIMATE


def test_extract_cost_estimate_fallback_exact():
    usage = {
        "input_tokens": 1_000_000,
        "output_tokens": 1_000_000,
        "cache_creation_input_tokens": 1_000_000,
        "cache_read_input_tokens": 1_000_000,
    }
    c = ev.extract_cost([_ended(cost=None, usage=usage)])
    # 5 + 25 + 6.25 + 0.50 per million-each.
    assert c.cost_usd == pytest.approx(36.75)
    assert c.cost_source == ev.COST_SOURCE_ESTIMATE
    assert c.has_result_frame is False


def test_estimate_never_overrides_real_cost():
    usage = {"input_tokens": 9_000_000, "output_tokens": 9_000_000}
    c = ev.extract_cost([_ended(cost=0.12, usage=usage)])
    assert c.cost_usd == pytest.approx(0.12)  # real figure wins over the large estimate
    assert c.cost_source == ev.COST_SOURCE_AUTHORITATIVE


def test_extract_cost_unavailable_when_no_session_ended():
    c = ev.extract_cost([_route(), _reply("x")])
    assert c.cost_usd == 0.0
    assert c.cost_source == ev.COST_SOURCE_NONE


def test_estimate_cost_from_usage_defaults_missing_keys():
    assert ev.estimate_cost_from_usage({}) == 0.0
    assert ev.estimate_cost_from_usage({"input_tokens": 2_000_000}) == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Route / reply / session / error


def test_classify_route():
    assert ev.classify_route([_route("container_cc")]) == "container_cc"
    assert ev.classify_route([_route(route=None)]) is None  # type: ignore[arg-type]
    assert ev.classify_route([_reply("x")]) is None


def test_extract_reply_joins_messages():
    frames = [_reply("line one"), _bash("nextseek-validate-upload"), _reply("line two")]
    assert ev.extract_reply(frames) == "line one\nline two"


def test_extract_reply_empty():
    assert ev.extract_reply([_route(), _ended()]) == ""


def test_detect_error_explicit_error_frame():
    assert ev.detect_error([_route(), {"type": "error", "reason": "exec_timeout"}]) is True


def test_detect_error_no_session_ended():
    assert ev.detect_error([_route(), _reply("partial")]) is True


def test_detect_error_clean():
    assert ev.detect_error(_good_frames()) is False


def test_session_id_of():
    assert ev.session_id_of([_ended(session_id="abc")]) == "abc"
    assert ev.session_id_of([_ended(session_id="")]) is None
    assert ev.session_id_of([_route()]) is None


# ---------------------------------------------------------------------------
# Invocation proof


def test_invocation_basic():
    invs = ev.extract_tool_invocations([_bash("nextseek-validate-upload --project-id 1")])
    assert [i.shim for i in invs] == ["nextseek-validate-upload"]


def test_invocation_basename_from_absolute_path():
    invs = ev.extract_tool_invocations(
        [_bash("/app/plugins/nextseek/bin/nextseek-build-payload --out /tmp/x")]
    )
    assert [i.shim for i in invs] == ["nextseek-build-payload"]


def test_invocation_command_v_arg_only_not_counted():
    # `command -v <shim>` mentions but does not invoke the shim.
    assert ev.extract_tool_invocations([_bash("command -v nextseek-validate-upload")]) == []


def test_invocation_echo_arg_only_not_counted():
    assert ev.extract_tool_invocations([_bash("echo nextseek-build-payload")]) == []


def test_invocation_multi_segment_finds_both():
    invs = ev.extract_tool_invocations(
        [_bash("nextseek-build-payload --out /tmp/x && nextseek-validate-upload --project-id 1")]
    )
    assert sorted(i.shim for i in invs) == ["nextseek-build-payload", "nextseek-validate-upload"]


def test_invocation_longer_name_not_matched():
    # basename-exact: a longer/other binary must NOT match a shim prefix.
    assert ev.extract_tool_invocations([_bash("nextseek-validate-upload-xtra --x")]) == []


def test_invocation_non_bash_tool_ignored():
    frame = {"type": "tool_use", "tool": "Read", "input": {"command": "nextseek-validate-upload"}}
    assert ev.extract_tool_invocations([frame]) == []


def test_invocation_non_string_command_ignored():
    frame = {"type": "tool_use", "tool": "Bash", "input": {"command": None}}
    assert ev.extract_tool_invocations([frame]) == []


def test_invocation_unbalanced_quotes_skipped():
    # shlex raises on the bad segment; the good one still counts.
    invs = ev.extract_tool_invocations(
        [_bash('nextseek-validate-upload --x "unterminated ; nextseek-build-payload --out /tmp/x')]
    )
    assert [i.shim for i in invs] == ["nextseek-build-payload"]


def test_invocation_env_prefix_head():
    invs = ev.extract_tool_invocations([_bash("FOO=bar nextseek-validate-upload --project-id 1")])
    assert [i.shim for i in invs] == ["nextseek-validate-upload"]


# ---------------------------------------------------------------------------
# Verdict


def test_evaluate_turn_all_good():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    assert row.passed is True
    assert row.problems == []
    assert row.validate_invoked is True
    assert row.needs_review is False
    assert row.cost_usd == pytest.approx(0.3)
    assert set(row.invoked_shims) == set(ev.BATCH_UPLOAD_SHIMS)


def test_evaluate_turn_red_no_validate():
    frames = [
        _route(),
        _bash("nextseek-build-payload --out /tmp/x"),
        _reply("built but did not validate"),
        _ended(cost=0.2),
    ]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    assert row.passed is False
    assert any("never invoked" in p for p in row.problems)


def test_evaluate_turn_red_cost_zero():
    row = ev.evaluate_turn(query="q", frames=_good_frames(cost=0.0), is_error=False)
    assert row.passed is False
    assert any("<= 0" in p for p in row.problems)


def test_evaluate_turn_red_is_error():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=True)
    assert row.passed is False
    assert any("errored" in p for p in row.problems)


def test_evaluate_turn_red_wrong_route():
    frames = [_route("nextseek"), *_all_shims_bash(), _reply("x"), _ended(cost=0.2)]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    assert row.passed is False
    assert any("route" in p for p in row.problems)


def test_evaluate_turn_red_empty_reply():
    frames = [_route(), *_all_shims_bash(), _ended(cost=0.2)]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    assert row.passed is False
    assert any("empty agent reply" in p for p in row.problems)


def test_evaluate_turn_review_note_when_shim_skipped_but_validate_ran():
    frames = [
        _route(),
        _bash("nextseek-validate-upload --project-id 1"),
        _reply("validated"),
        _ended(cost=0.2),
    ]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    assert row.passed is True  # green
    assert row.needs_review is True
    assert row.review_notes and "not observed" in row.review_notes[0]


def test_turn_row_to_dict_roundtrip():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    d = row.to_dict()
    assert d["passed"] is True and d["validate_invoked"] is True and d["query"] == "q"


# ---------------------------------------------------------------------------
# Fresh sessions + summary


def test_assert_fresh_sessions_ok():
    assert ev.assert_fresh_sessions(["a", "b", "c"]) == []


def test_assert_fresh_sessions_missing():
    assert any("missing" in v for v in ev.assert_fresh_sessions([None]))


def test_assert_fresh_sessions_duplicate():
    assert any("duplicate" in v for v in ev.assert_fresh_sessions(["a", "a"]))


def test_build_summary_all_pass():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    s = ev.build_summary(row, ledger_total_usd=0.3, cap_usd=5.0, aborted_on_budget=False)
    assert s["all_pass"] is True and s["within_cap"] is True
    assert s["rate_table_version"] == ev.PUBLISHED_RATE_TABLE_VERSION


def test_build_summary_aborted():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    s = ev.build_summary(row, ledger_total_usd=0.3, cap_usd=5.0, aborted_on_budget=True)
    assert s["all_pass"] is False and s["aborted_on_budget"] is True


def test_build_summary_over_cap():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    s = ev.build_summary(row, ledger_total_usd=6.0, cap_usd=5.0, aborted_on_budget=False)
    assert s["within_cap"] is False


def test_build_summary_fresh_violation_fails():
    frames = [_route(), *_all_shims_bash(), _reply("x"), _ended(session_id="")]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    s = ev.build_summary(row, ledger_total_usd=0.3, cap_usd=5.0, aborted_on_budget=False)
    assert s["all_pass"] is False and s["fresh_session_violations"]


# ---------------------------------------------------------------------------
# Verifier (bundle-level)


def _write_bundle(tmp_path, frames, *, cap=5.0, ledger_cost=0.3, summary_overrides=None):
    bundle = tmp_path / "20260707T000000Z"
    bundle.mkdir()
    transcript = bundle / "live_e2e_transcript.json"
    transcript.write_text(
        json.dumps({"meta": {"query": "prepare a batch upload", "cap_usd": cap}, "frames": frames}),
        encoding="utf-8",
    )
    (bundle / "ledger.jsonl").write_text(
        json.dumps(
            {"op": "cc_turn", "model": "opus", "projected_usd": 0.5,
             "actual_usd": ledger_cost, "status": "settled"}
        )
        + "\n",
        encoding="utf-8",
    )
    row = ev.evaluate_turn(query="prepare a batch upload", frames=frames,
                           is_error=ev.detect_error(frames))
    summary = ev.build_summary(row, ledger_total_usd=ledger_cost, cap_usd=cap,
                               aborted_on_budget=False)
    if summary_overrides:
        summary = {**summary, **summary_overrides}
    (bundle / "per_turn_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    return transcript


def test_verify_ok(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames())
    result = vr.verify(transcript)
    assert result["ok"] is True, result["problems"]
    assert result["cost_source"] == ev.COST_SOURCE_AUTHORITATIVE


def test_verify_missing_transcript(tmp_path):
    result = vr.verify(tmp_path / "nope.json")
    assert result["ok"] is False and "not found" in result["problems"][0]


def test_verify_no_frames(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    t = bundle / "live_e2e_transcript.json"
    t.write_text(json.dumps({"meta": {}}), encoding="utf-8")
    result = vr.verify(t)
    assert result["ok"] is False and "frames" in result["problems"][0]


def test_verify_missing_ledger_is_markdown_not_proof(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames())
    (transcript.parent / "ledger.jsonl").unlink()
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("markdown is never proof" in p for p in result["problems"])


def test_verify_missing_summary(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames())
    (transcript.parent / "per_turn_summary.json").unlink()
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("per_turn_summary" in p for p in result["problems"])


def test_verify_recompute_catches_bad_turn(tmp_path):
    # Transcript lacks the validate shim; a tampered summary claims all_pass True.
    frames = [_route(), _bash("nextseek-build-payload --out /tmp/x"),
              _reply("built"), _ended(cost=0.2)]
    transcript = _write_bundle(tmp_path, frames, summary_overrides={"all_pass": True})
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("never invoked" in p for p in result["problems"])
    assert any("all_pass" in p for p in result["problems"])


def test_verify_tampered_cost(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames())
    summary = json.loads((transcript.parent / "per_turn_summary.json").read_text())
    summary["turn"]["cost_usd"] = 99.0
    (transcript.parent / "per_turn_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("cost_usd" in p for p in result["problems"])


def test_verify_over_cap(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames(), cap=0.1, ledger_cost=0.3)
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("exceeds cap" in p for p in result["problems"])


def test_verify_main_exit_codes(tmp_path, capsys):
    transcript = _write_bundle(tmp_path, _good_frames())
    assert vr.main([str(transcript)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert vr.main([str(tmp_path / "missing.json")]) == 1


def test_verify_ledger_blank_line_skipped(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames(), ledger_cost=0.3)
    ledger = transcript.parent / "ledger.jsonl"
    ledger.write_text(ledger.read_text() + "\n", encoding="utf-8")  # trailing blank line
    result = vr.verify(transcript)
    assert result["ok"] is True
    assert result["ledger_total_usd"] == pytest.approx(0.3)


def test_verify_tampered_validate_invoked_flag(tmp_path):
    transcript = _write_bundle(tmp_path, _good_frames())
    summary = json.loads((transcript.parent / "per_turn_summary.json").read_text())
    summary["turn"]["validate_invoked"] = False  # lie: recompute says True
    (transcript.parent / "per_turn_summary.json").write_text(json.dumps(summary), encoding="utf-8")
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("validate_invoked" in p for p in result["problems"])


def test_invocation_non_string_frame_id():
    frame = {"type": "tool_use", "tool": "Bash",
             "input": {"command": "nextseek-validate-upload --x"}, "id": 123}
    invs = ev.extract_tool_invocations([frame])
    assert invs[0].frame_id is None


def test_invocation_bare_assignment_segment():
    # A segment that is only a VAR=val assignment (no command word) yields no invocation.
    assert ev.extract_tool_invocations([_bash("FOO=bar")]) == []
