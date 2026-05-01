"""Plan A · T12: ws.dispatch_post_turn_copy invokes copy_files per new file."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import Mock


def test_dispatches_one_call_per_relative_path(monkeypatch):
    """Per-file pattern (M-2): dispatch_post_turn_copy MUST call copy_files
    exactly len(new_files) times, once per relative path with rel_paths={rel}.
    A batched single-call implementation is REJECTED.
    """
    from dmac_assistant import ws
    fake = Mock(return_value=[])
    monkeypatch.setattr("dmac_assistant.ws.copy_files", fake)
    ws.dispatch_post_turn_copy(
        scratch_root=Path("/scratch"), output_root=Path("/output"),
        user_id="alice", new_files={"a.json", "nested/b.txt"},
    )
    assert fake.call_count == 2
    # Each call's rel_paths is a single-element set; collect the inner str.
    seen = sorted(next(iter(call.kwargs["rel_paths"])) for call in fake.call_args_list)
    assert seen == ["a.json", "nested/b.txt"]


def test_sorted_call_order(monkeypatch):
    """Sorted determinism — calls land in lexicographic order."""
    from dmac_assistant import ws
    fake = Mock(return_value=[])
    monkeypatch.setattr("dmac_assistant.ws.copy_files", fake)
    ws.dispatch_post_turn_copy(
        scratch_root=Path("/scratch"), output_root=Path("/output"),
        user_id="alice", new_files={"z.json", "a.json", "m.json"},
    )
    call_paths = [next(iter(call.kwargs["rel_paths"])) for call in fake.call_args_list]
    assert call_paths == ["a.json", "m.json", "z.json"]


def test_per_file_exception_swallowed_other_files_continue(monkeypatch, caplog):
    """One bad file doesn't block the rest (M-2). Mock copy_files at the
    ws-module boundary; raise on the FIRST sorted relpath, return [] otherwise.
    R-03: warning text contains the type name only, never the message body.
    """
    import logging
    from dmac_assistant import ws

    def side_effect(*, rel_paths, **_):
        if next(iter(rel_paths)) == "a.json":
            raise OSError("fake disk full")
        return []
    fake = Mock(side_effect=side_effect)
    monkeypatch.setattr("dmac_assistant.ws.copy_files", fake)

    with caplog.at_level(logging.WARNING, logger="dmac_assistant.ws"):
        ws.dispatch_post_turn_copy(
            scratch_root=Path("/scratch"), output_root=Path("/output"),
            user_id="alice", new_files={"a.json", "b.json"},
        )

    assert fake.call_count == 2  # both files attempted
    warning_records = [r for r in caplog.records if r.levelname == "WARNING"]
    assert any("OSError" in r.getMessage() for r in warning_records)
    # R-03: message body MUST NOT leak.
    assert not any("fake disk full" in r.getMessage() for r in warning_records)


def test_empty_new_files_is_noop(monkeypatch):
    from dmac_assistant import ws
    fake = Mock(return_value=[])
    monkeypatch.setattr("dmac_assistant.ws.copy_files", fake)
    ws.dispatch_post_turn_copy(
        scratch_root=Path("/scratch"), output_root=Path("/output"),
        user_id="alice", new_files=set(),
    )
    assert fake.call_count == 0


def test_pre_turn_files_mutation_excludes_prior_files_on_turn_2():
    """Multi-turn closure mutation (L-2 dict literals).

    fire_post_turn_copy mutates pre_turn_files in-place (clear + update)
    so that turn-2's diff_files only returns NEW/CHANGED files added
    during turn 2. Concrete dict shape across turns:

      Initial:  pre_turn_files = {}
      Turn-1 after-snapshot: {"a.json": (3, 1000)}
        -> diff returns {"a.json"}; mutation makes pre_turn_files = {"a.json": (3, 1000)}
      Turn-2 after-snapshot: {"a.json": (3, 1000), "b.json": (5, 2000)}
        -> diff returns {"b.json"} (a.json unchanged); mutation makes pre_turn_files
           = {"a.json": (3, 1000), "b.json": (5, 2000)}
      Turn-3 after-snapshot: same as turn-2
        -> diff returns set() (no changes)
    """
    from dmac_assistant.run_tracker import diff_files
    pre_turn_files: dict[str, tuple[int, int]] = {}

    after_t1 = {"a.json": (3, 1000)}
    new_t1 = diff_files(pre_turn_files, after_t1)
    assert new_t1 == {"a.json"}
    pre_turn_files.clear()
    pre_turn_files.update(after_t1)

    after_t2 = {"a.json": (3, 1000), "b.json": (5, 2000)}
    new_t2 = diff_files(pre_turn_files, after_t2)
    assert new_t2 == {"b.json"}
    pre_turn_files.clear()
    pre_turn_files.update(after_t2)

    after_t3 = {"a.json": (3, 1000), "b.json": (5, 2000)}
    new_t3 = diff_files(pre_turn_files, after_t3)
    assert new_t3 == set()
