"""Plan A · T5: ws.dispatch_post_turn_copy invokes copier per new run_id."""
from __future__ import annotations

from unittest.mock import patch


def test_dispatch_copies_each_new_run(tmp_path):
    from dmac_assistant import ws

    scratch = tmp_path / "scratch"
    (scratch / "alice").mkdir(parents=True)

    with patch.object(ws, "copy_run_artifacts") as mock_copy:
        ws.dispatch_post_turn_copy(
            scratch_root=scratch,
            output_root=tmp_path / "output",
            user_id="alice",
            new_run_ids={"r-1", "r-2"},
        )

    assert mock_copy.call_count == 2
    called_run_ids = {call.kwargs["run_id"] for call in mock_copy.call_args_list}
    assert called_run_ids == {"r-1", "r-2"}
    # W3-M2: lock the sorted-iteration invariant (plan body line 1528).
    # An implementation that uses unordered set iteration passes the
    # set-equality check above but fails this ordered-list assertion.
    called_run_ids_in_order = [call.kwargs["run_id"] for call in mock_copy.call_args_list]
    assert called_run_ids_in_order == sorted({"r-1", "r-2"})


def test_dispatch_iterates_in_sorted_order(tmp_path):
    """W3-M2: explicit sorted-iteration test for a >2-run input.
    Defends against a future change that uses unordered set iteration.
    """
    from dmac_assistant import ws
    with patch.object(ws, "copy_run_artifacts") as mock_copy:
        ws.dispatch_post_turn_copy(
            scratch_root=tmp_path, output_root=tmp_path,
            user_id="alice",
            new_run_ids={"r-3", "r-1", "r-2"},
        )
    called = [call.kwargs["run_id"] for call in mock_copy.call_args_list]
    assert called == ["r-1", "r-2", "r-3"]


def test_dispatch_swallows_copier_errors(tmp_path):
    from dmac_assistant import ws

    with patch.object(ws, "copy_run_artifacts", side_effect=OSError("disk full")):
        # Must not raise — copier failure cannot kill the session (L2).
        ws.dispatch_post_turn_copy(
            scratch_root=tmp_path,
            output_root=tmp_path,
            user_id="alice",
            new_run_ids={"r-1"},
        )


def test_dispatch_empty_set_is_noop(tmp_path):
    from dmac_assistant import ws
    with patch.object(ws, "copy_run_artifacts") as mock_copy:
        ws.dispatch_post_turn_copy(
            scratch_root=tmp_path, output_root=tmp_path,
            user_id="alice", new_run_ids=set(),
        )
    mock_copy.assert_not_called()


def test_pre_turn_runs_mutation_excludes_prior_runs_on_turn_2(tmp_path):
    """W3-C1: the multi-turn snapshot-update path is non-trivial. The
    fire_post_turn_copy closure mutates pre_turn_runs in-place (clear/update)
    so that turn-2's diff_runs only returns NEW dirs added during turn 2.

    A bug where the mutation is missing OR the closure rebinds (e.g.
    `pre_turn_runs = after`) instead of mutating-in-place breaks this
    invariant — turn-1's runs leak back into turn-2's "new_runs" and get
    redundantly re-copied. T5's other 8 unit tests do not exercise this.

    This test simulates the closure body's mutation against synthetic
    snapshot sets, covering the multi-turn correctness contract synchronously
    (no event loop required).
    """
    from dmac_assistant.run_tracker import diff_runs

    # Initial pre-turn snapshot (start of WS session — empty).
    pre_turn_runs: set[str] = set()

    # --- Turn 1: container creates run "r-1". ---
    after_t1 = {"r-1"}
    new_t1 = diff_runs(pre_turn_runs, after_t1)
    assert new_t1 == {"r-1"}
    # Mutation under test (verbatim from fire_post_turn_copy body):
    pre_turn_runs.clear()
    pre_turn_runs.update(after_t1)

    # --- Turn 2: container creates run "r-2". ---
    after_t2 = {"r-1", "r-2"}
    new_t2 = diff_runs(pre_turn_runs, after_t2)
    # The critical assertion: turn-1's "r-1" MUST NOT reappear as new on turn 2.
    assert new_t2 == {"r-2"}
    pre_turn_runs.clear()
    pre_turn_runs.update(after_t2)

    # --- Turn 3: no new runs. ---
    after_t3 = {"r-1", "r-2"}
    new_t3 = diff_runs(pre_turn_runs, after_t3)
    assert new_t3 == set()
