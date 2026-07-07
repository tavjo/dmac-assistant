"""Hermetic ($0, socket-disabled) tests for the T10 live-paid evidence logic + verifier.

Run (dotted --cov module form — the slash/path form reports 0% under the repo tools/ layout):
    env UV_CACHE_DIR=/tmp/uv-cache uv run pytest tools/e2e/test_batch_upload_live_evidence.py \
      --override-ini "addopts=--disable-socket -q" \
      --cov=tools.e2e.batch_upload_live_evidence --cov=tools.e2e.verify_batch_upload_live \
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


def test_invocation_unparseable_command_yields_nothing():
    # An unbalanced quote is a shell syntax error — nothing executes, so we conservatively
    # detect no invocation (a false-negative is safe; a false-positive is not).
    invs = ev.extract_tool_invocations(
        [_bash('nextseek-validate-upload --x "unterminated ; nextseek-build-payload --out /tmp/x')]
    )
    assert invs == []


def test_invocation_env_prefix_head():
    invs = ev.extract_tool_invocations([_bash("FOO=bar nextseek-validate-upload --project-id 1")])
    assert [i.shim for i in invs] == ["nextseek-validate-upload"]


# --- C1: operator inside a quoted literal must NOT forge an invocation ---


@pytest.mark.parametrize(
    "command",
    [
        'echo "step1 && nextseek-validate-upload && step3"',
        "printf '%s' 'hello|nextseek-validate-upload|world'",
        'echo "note; nextseek-validate-upload; done"',
        'python -c "print(\'nextseek-validate-upload\')"',
    ],
)
def test_invocation_quoted_operator_not_counted(command):
    assert ev.extract_tool_invocations([_bash(command)]) == []


def test_invocation_full_turn_forgery_rejected():
    # A turn whose only Bash frame narrates the shim inside a quoted echo must NOT pass.
    frames = [
        _route(),
        _bash('echo "step1 && nextseek-validate-upload && step3"'),
        _reply("I would run the validate step."),
        _ended(cost=0.2),
    ]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    assert row.validate_invoked is False
    assert row.passed is False


# --- M3: legitimate real-invocation forms must be detected ---


def test_invocation_bash_c_inner():
    invs = ev.extract_tool_invocations([_bash('bash -c "nextseek-validate-upload --project-id 1"')])
    assert "nextseek-validate-upload" in [i.shim for i in invs]


def test_invocation_command_substitution():
    invs = ev.extract_tool_invocations([_bash("RESULT=$(nextseek-validate-upload --project-id 1)")])
    assert "nextseek-validate-upload" in [i.shim for i in invs]


def test_invocation_backtick_substitution():
    invs = ev.extract_tool_invocations([_bash("X=`nextseek-build-payload --out /tmp/x`")])
    assert "nextseek-build-payload" in [i.shim for i in invs]


def test_invocation_xargs():
    invs = ev.extract_tool_invocations([_bash("echo 1 | xargs nextseek-validate-upload")])
    assert "nextseek-validate-upload" in [i.shim for i in invs]


def test_extract_cost_terminal_frame_wins():
    # A decoy cheap result frame before the real one must not mask the true cost (M2).
    frames = [
        {"type": "session_ended", "session_id": "decoy", "total_cost_usd": 0.001},
        {"type": "session_ended", "session_id": "real", "total_cost_usd": 7.0},
    ]
    c = ev.extract_cost(frames)
    assert c.cost_usd == pytest.approx(7.0)
    assert ev.session_id_of(frames) == "real"


def test_extract_cost_negative_authoritative_is_flagged():
    # A negative total_cost_usd is recorded as authoritative (not routed to the estimate), then the
    # verdict layer flags cost <= 0 (L2).
    c = ev.extract_cost([_ended(cost=-1.0)])
    assert c.cost_usd == -1.0 and c.cost_source == ev.COST_SOURCE_AUTHORITATIVE
    row = ev.evaluate_turn(query="q", frames=_good_frames(cost=-1.0), is_error=False)
    assert row.passed is False and any("<= 0" in p for p in row.problems)


def test_build_summary_over_cap_fails_all_pass():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    s = ev.build_summary(row, ledger_total_usd=6.0, cap_usd=5.0, aborted_on_budget=False)
    assert s["within_cap"] is False and s["all_pass"] is False  # H3: within_cap folds into all_pass


# ---------------------------------------------------------------------------
# Verifier (bundle-level)


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
# Evidence bundle writer


def test_render_summary_txt_has_cost_and_reproduce():
    row = ev.evaluate_turn(query="q", frames=_good_frames(), is_error=False)
    summary = ev.build_summary(row, ledger_total_usd=0.3, cap_usd=5.0, aborted_on_budget=False)
    txt = ev.render_summary_txt(summary, reproduce_cmd="uv run python x.py --paid", evidence_dir_name="20260707T000000Z")
    assert "total_cost_usd:" in txt and "--- reproduce ---" in txt
    assert "uv run python x.py --paid" in txt
    assert "claude_code_result" in txt


def test_render_summary_txt_lists_problems():
    row = ev.evaluate_turn(query="q", frames=_good_frames(cost=0.0), is_error=False)
    summary = ev.build_summary(row, ledger_total_usd=0.0, cap_usd=5.0, aborted_on_budget=False)
    txt = ev.render_summary_txt(summary, reproduce_cmd="cmd", evidence_dir_name="d")
    assert "PROBLEMS (hard failures):" in txt and "<= 0" in txt


def test_render_summary_txt_lists_review_notes():
    frames = [_route(), _bash("nextseek-validate-upload --project-id 1"), _reply("ok"), _ended(cost=0.2)]
    row = ev.evaluate_turn(query="q", frames=frames, is_error=False)
    summary = ev.build_summary(row, ledger_total_usd=0.2, cap_usd=5.0, aborted_on_budget=False)
    txt = ev.render_summary_txt(summary, reproduce_cmd="cmd", evidence_dir_name="d")
    assert "REVIEW NOTES (green-but-flagged):" in txt


def test_write_evidence_bundle_ok(tmp_path):
    out = tmp_path / "20260707T010203Z"
    summary = ev.write_evidence_bundle(
        out,
        query="prepare a batch upload",
        frames=_good_frames(),
        cap_usd=5.0,
        ledger_total_usd=0.3,
        transport_error=None,
        aborted_on_budget=False,
        reproduce_cmd="uv run python run.py --paid",
    )
    assert summary["all_pass"] is True
    assert (out / "live_e2e_transcript.json").exists()
    assert (out / "per_turn_summary.json").exists()
    assert (out / "SUMMARY.txt").exists()
    # The written transcript is re-verifiable once a ledger is present.
    (out / "ledger.jsonl").write_text(
        json.dumps({"op": "cc_turn", "model": "opus", "projected_usd": 0.5,
                    "actual_usd": 0.3, "status": "settled"}) + "\n",
        encoding="utf-8",
    )
    result = vr.verify(out / "live_e2e_transcript.json")
    assert result["ok"] is True, result["problems"]


def test_write_evidence_bundle_transport_error_fails(tmp_path):
    out = tmp_path / "err"
    summary = ev.write_evidence_bundle(
        out,
        query="q",
        frames=[_route(), *_all_shims_bash(), _reply("x"), _ended(cost=0.2)],
        cap_usd=5.0,
        ledger_total_usd=0.2,
        transport_error="timeout",
        aborted_on_budget=False,
        reproduce_cmd="cmd",
    )
    assert summary["all_pass"] is False
    assert summary["turn"]["is_error"] is True


def test_write_evidence_bundle_aborted(tmp_path):
    out = tmp_path / "ab"
    summary = ev.write_evidence_bundle(
        out, query="q", frames=_good_frames(), cap_usd=5.0, ledger_total_usd=0.0,
        transport_error=None, aborted_on_budget=True, reproduce_cmd="cmd",
        extra_meta={"reserved_only": True},
    )
    assert summary["all_pass"] is False and summary["aborted_on_budget"] is True
    meta = json.loads((out / "live_e2e_transcript.json").read_text())["meta"]
    assert meta["reserved_only"] is True


# ---------------------------------------------------------------------------
# Verifier (bundle-level)


def _write_bundle(tmp_path, frames, *, cap=5.0, ledger_cost=0.3, ledger_status="settled",
                  summary_overrides=None, meta_extra=None):
    bundle = tmp_path / "20260707T000000Z"
    bundle.mkdir(exist_ok=True)
    transcript = bundle / "live_e2e_transcript.json"
    meta = {"query": "prepare a batch upload", "cap_usd": cap}
    if meta_extra:
        meta.update(meta_extra)
    transcript.write_text(json.dumps({"meta": meta, "frames": frames}), encoding="utf-8")
    entry = {"op": "cc_turn", "model": "opus", "projected_usd": 0.5, "status": ledger_status}
    entry["actual_usd"] = ledger_cost if ledger_status == "settled" else None
    (bundle / "ledger.jsonl").write_text(json.dumps(entry) + "\n", encoding="utf-8")
    row = ev.evaluate_turn(query="prepare a batch upload", frames=frames,
                           is_error=ev.detect_error(frames))
    settled_total = ledger_cost if ledger_status == "settled" else 0.0
    summary = ev.build_summary(row, ledger_total_usd=settled_total, cap_usd=cap,
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
    # A real spend above the POLICY cap fails, regardless of what the bundle declares.
    transcript = _write_bundle(tmp_path, _good_frames(cost=9.0), cap=5.0, ledger_cost=9.0)
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("exceeds policy cap" in p for p in result["problems"])


def test_verify_ignores_self_declared_meta_cap(tmp_path):
    # H1: a bundle that declares a looser cap than policy is a red flag; the verifier does not
    # adopt meta.cap_usd as its ceiling.
    transcript = _write_bundle(tmp_path, _good_frames(cost=0.3), cap=1000.0, ledger_cost=0.3)
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("declares cap" in p and "policy" in p for p in result["problems"])
    assert result["policy_cap_usd"] == vr.POLICY_CAP_USD


def test_verify_ledger_understates_authoritative_cost(tmp_path):
    # H2/M1: the driver-written ledger says $0.01 but the turn's own result frame says $7 — the
    # verifier reconciles the two and cap-checks the REAL spend.
    transcript = _write_bundle(tmp_path, _good_frames(cost=7.0), cap=5.0, ledger_cost=0.01)
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("authoritative transcript cost" in p for p in result["problems"])
    assert any("exceeds policy cap" in p for p in result["problems"])


def test_verify_reserved_only_ledger_flagged(tmp_path):
    # M1: a crash between reserve and record leaves a reserved-only ledger recording $0 for a paid
    # turn — the transcript's authoritative $0.3 no longer reconciles.
    transcript = _write_bundle(tmp_path, _good_frames(cost=0.3), ledger_status="reserved")
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("authoritative transcript cost" in p for p in result["problems"])


def test_verify_multiple_session_ended_flagged(tmp_path):
    # M2: a decoy result frame before the real one.
    frames = [_route(), *_all_shims_bash(), _reply("done"),
              _ended(session_id="decoy", cost=0.001), _ended(session_id="real", cost=0.3)]
    transcript = _write_bundle(tmp_path, frames, ledger_cost=0.3)
    result = vr.verify(transcript)
    assert result["ok"] is False
    assert any("session_ended frames" in p for p in result["problems"])


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
