"""T03 session-discovery tests: encode_cwd, list_sessions, most_recent_session."""
from __future__ import annotations

import time
import uuid
from pathlib import Path

import pytest


@pytest.fixture
def claude_root(tmp_path: Path) -> Path:
    """A fresh ~/.claude-style root for each test."""
    root = tmp_path / ".claude"
    (root / "projects").mkdir(parents=True)
    return root


def _write_session_file(
    projects_root: Path,
    cwd: str,
    session_id: str,
    mtime: float | None = None,
) -> Path:
    from dmac_assistant.sessions import encode_cwd

    directory = projects_root / "projects" / encode_cwd(cwd)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{session_id}.jsonl"
    path.write_text(
        '{"type":"system","subtype":"init","session_id":"'
        + session_id
        + '","cwd":"'
        + cwd
        + '"}\n',
        encoding="utf-8",
    )
    if mtime is not None:
        path.touch()
        import os

        os.utime(path, (mtime, mtime))
    return path


@pytest.mark.parametrize(
    ("cwd", "expected"),
    [
        ("/home/user", "-home-user"),
        ("/Users/taishajoseph/.claude", "-Users-taishajoseph--claude"),
        ("/tmp", "-tmp"),
        ("", ""),
        ("abc123", "abc123"),
        ("/home/uber", "-home-uber"),
        ("a/b/c", "a-b-c"),
    ],
)
def test_encode_cwd_matches_claude_code_algorithm(cwd: str, expected: str) -> None:
    from dmac_assistant.sessions import encode_cwd

    assert encode_cwd(cwd) == expected


def test_encode_cwd_keeps_non_ascii_alnum_characters() -> None:
    from dmac_assistant.sessions import encode_cwd

    assert encode_cwd("/home/uber-ä") == "-home-uber-ä"


def test_session_dir_composes_claude_root_with_encoded_cwd(claude_root: Path) -> None:
    from dmac_assistant.sessions import session_dir

    result = session_dir(claude_root, "/home/user")
    assert result == claude_root / "projects" / "-home-user"


def test_list_sessions_empty_when_directory_missing(claude_root: Path) -> None:
    from dmac_assistant.sessions import list_sessions

    assert list_sessions(claude_root, "/home/user") == []


def test_list_sessions_empty_when_no_jsonl_files(claude_root: Path) -> None:
    from dmac_assistant.sessions import encode_cwd, list_sessions

    target = claude_root / "projects" / encode_cwd("/home/user")
    target.mkdir(parents=True)
    (target / "README.md").write_text("not a session", encoding="utf-8")

    assert list_sessions(claude_root, "/home/user") == []


def test_list_sessions_single_entry(claude_root: Path) -> None:
    from dmac_assistant.sessions import list_sessions

    sid = str(uuid.uuid4())
    path = _write_session_file(claude_root, "/home/user", sid)

    sessions = list_sessions(claude_root, "/home/user")
    assert len(sessions) == 1
    record = sessions[0]
    assert record.session_id == sid
    assert record.cwd == "/home/user"
    assert record.encoded_cwd == "-home-user"
    assert record.path.resolve() == path.resolve()
    assert record.mtime > 0


def test_list_sessions_sorts_newest_first(claude_root: Path) -> None:
    from dmac_assistant.sessions import list_sessions

    sid_old = str(uuid.uuid4())
    sid_mid = str(uuid.uuid4())
    sid_new = str(uuid.uuid4())
    now = time.time()
    _write_session_file(claude_root, "/home/user", sid_old, mtime=now - 1000)
    _write_session_file(claude_root, "/home/user", sid_mid, mtime=now - 500)
    _write_session_file(claude_root, "/home/user", sid_new, mtime=now)

    sessions = list_sessions(claude_root, "/home/user")
    assert [session.session_id for session in sessions] == [sid_new, sid_mid, sid_old]


def test_list_sessions_tie_breaks_by_session_id(claude_root: Path) -> None:
    from dmac_assistant.sessions import list_sessions

    sid_a = "00000000-0000-0000-0000-000000000001"
    sid_b = "00000000-0000-0000-0000-00000000000f"
    now = 1_700_000_000.0
    _write_session_file(claude_root, "/home/user", sid_b, mtime=now)
    _write_session_file(claude_root, "/home/user", sid_a, mtime=now)

    sessions = list_sessions(claude_root, "/home/user")
    assert [session.session_id for session in sessions] == [sid_a, sid_b]


def test_list_sessions_ignores_non_jsonl_files(claude_root: Path) -> None:
    from dmac_assistant.sessions import encode_cwd, list_sessions

    sid = str(uuid.uuid4())
    _write_session_file(claude_root, "/home/user", sid)

    target = claude_root / "projects" / encode_cwd("/home/user")
    (target / "notes.txt").write_text("stray", encoding="utf-8")
    (target / "backup.jsonl.bak").write_text("also stray", encoding="utf-8")

    sessions = list_sessions(claude_root, "/home/user")
    assert [session.session_id for session in sessions] == [sid]


def test_list_sessions_ignores_malformed_uuid_filenames(claude_root: Path) -> None:
    from dmac_assistant.sessions import encode_cwd, list_sessions

    sid = str(uuid.uuid4())
    _write_session_file(claude_root, "/home/user", sid)

    target = claude_root / "projects" / encode_cwd("/home/user")
    (target / "not-a-uuid.jsonl").write_text("skip me", encoding="utf-8")
    (target / "12345.jsonl").write_text("also skip", encoding="utf-8")

    sessions = list_sessions(claude_root, "/home/user")
    assert [session.session_id for session in sessions] == [sid]


def test_list_sessions_returns_absolute_paths(claude_root: Path) -> None:
    from dmac_assistant.sessions import list_sessions

    sid = str(uuid.uuid4())
    _write_session_file(claude_root, "/home/user", sid)

    sessions = list_sessions(claude_root, "/home/user")
    assert sessions[0].path.is_absolute()


def test_list_sessions_skips_unstatable_file(monkeypatch: pytest.MonkeyPatch, claude_root: Path) -> None:
    from dmac_assistant.sessions import list_sessions

    sid = str(uuid.uuid4())
    path = _write_session_file(claude_root, "/home/user", sid)

    original_stat = Path.stat

    def fake_stat(self: Path, *args, **kwargs):
        if self == path:
            raise OSError("boom")
        return original_stat(self, *args, **kwargs)

    monkeypatch.setattr(Path, "stat", fake_stat)

    assert list_sessions(claude_root, "/home/user") == []


def test_most_recent_session_none_when_empty(claude_root: Path) -> None:
    from dmac_assistant.sessions import most_recent_session

    assert most_recent_session(claude_root, "/home/user") is None


def test_most_recent_session_returns_newest(claude_root: Path) -> None:
    from dmac_assistant.sessions import most_recent_session

    sid_old = str(uuid.uuid4())
    sid_new = str(uuid.uuid4())
    now = time.time()
    _write_session_file(claude_root, "/home/user", sid_old, mtime=now - 100)
    _write_session_file(claude_root, "/home/user", sid_new, mtime=now)

    record = most_recent_session(claude_root, "/home/user")
    assert record is not None
    assert record.session_id == sid_new


def test_session_record_is_frozen(claude_root: Path) -> None:
    from dataclasses import FrozenInstanceError

    from dmac_assistant.sessions import list_sessions

    sid = str(uuid.uuid4())
    _write_session_file(claude_root, "/home/user", sid)

    record = list_sessions(claude_root, "/home/user")[0]
    with pytest.raises(FrozenInstanceError):
        record.session_id = "other"  # type: ignore[misc]
