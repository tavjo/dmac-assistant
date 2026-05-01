"""Tests for build_tools.stage_plugins.

Covers:
  - happy path (allowlist copied exactly; README re-homed; docs/ subtree re-homed)
  - denylist enforcement (atomic refusal; every offender listed; no writes)
  - file-count parity (exact, not >=) - derived from ALLOWLIST, not duplicated
  - canary-file sha256 preserved post-copy
  - symlink resolution + escape detection (broken, escaping, inside-tree)
  - idempotency (second run == first run, byte-identical)
  - stale-file removal (wipe-before-copy guarantee)
  - unexpected top-level warning + --strict refusal
  - .env.example denial
  - denylisted patterns inside allowlisted subtrees
  - CLI argparse surface + refusal exit code == 1
"""
from __future__ import annotations

import hashlib
import os
from pathlib import Path

import pytest

from build_tools import stage_plugins


_ALLOWLIST_SEED_MAP: dict[str, str] = {
    ".claude-plugin": ".claude-plugin/plugin.json",
    "bin": "bin/nextseek-call",
    "commands": "commands/nextseek-api.md",
    "skills": "skills/nextseek-api/SKILL.md",
    "docs": "docs/acceptance/2026-04-14-nextseek-api-bugfix.md",
    "pyproject.toml": "pyproject.toml",
    "uv.lock": "uv.lock",
    "README.md": "README.md",
    "CHANGELOG.md": "CHANGELOG.md",
}


def _allowlist_seed_files() -> set[str]:
    return {_ALLOWLIST_SEED_MAP[entry] for entry in stage_plugins.ALLOWLIST}


def _seed_plugin(root: Path) -> None:
    (root / ".claude-plugin").mkdir(parents=True)
    (root / ".claude-plugin" / "plugin.json").write_text('{"name":"nextseek-api"}\n')
    (root / "bin").mkdir()
    (root / "bin" / "nextseek-call").write_text("#!/bin/sh\necho hi\n")
    (root / "commands").mkdir()
    (root / "commands" / "nextseek-api.md").write_text("# cmd\n")
    (root / "skills" / "nextseek-api").mkdir(parents=True)
    (root / "skills" / "nextseek-api" / "SKILL.md").write_text("# skill\n")
    (root / "docs" / "acceptance").mkdir(parents=True)
    (root / "docs" / "acceptance" / "2026-04-14-nextseek-api-bugfix.md").write_text(
        "# accept\n"
    )
    (root / "pyproject.toml").write_text("[project]\nname='nextseek-api'\n")
    (root / "uv.lock").write_text("# lock\n")
    (root / "README.md").write_text("# nextseek-api readme\n")
    (root / "CHANGELOG.md").write_text("# changelog\n")


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def test_happy_path_stages_allowlist_exactly(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)

    plugin_out = dest / "plugins" / "nextseek-api"
    for rel in _allowlist_seed_files() - {"README.md"}:
        if rel.startswith("docs/"):
            continue
        assert (plugin_out / rel).is_file(), f"missing {rel}"

    assert not (plugin_out / "README.md").exists()
    readme_out = dest / "docs" / "nextseek-api" / "README.md"
    assert readme_out.is_file()
    assert readme_out.read_text() == "# nextseek-api readme\n"

    assert (
        dest
        / "docs"
        / "nextseek-api"
        / "docs"
        / "acceptance"
        / "2026-04-14-nextseek-api-bugfix.md"
    ).is_file()

    assert (src / "README.md").is_file()


def test_docs_subtree_parity_exact(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)

    docs_out_files = {
        p.relative_to(dest / "docs" / "nextseek-api").as_posix()
        for p in (dest / "docs" / "nextseek-api").rglob("*")
        if p.is_file()
    }
    expected_docs = {
        "README.md",
        "docs/acceptance/2026-04-14-nextseek-api-bugfix.md",
    }
    assert docs_out_files == expected_docs, f"docs output drift: {docs_out_files}"


def test_file_count_parity_exact(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)

    plugin_out = dest / "plugins" / "nextseek-api"
    staged = {
        str(p.relative_to(plugin_out)) for p in plugin_out.rglob("*") if p.is_file()
    }
    expected = {
        rel for rel in _allowlist_seed_files() if rel != "README.md" and not rel.startswith("docs/")
    }
    staged_norm = {s.replace(os.sep, "/") for s in staged}
    assert staged_norm == expected, f"extra/missing files: staged={staged_norm} expected={expected}"


def test_canary_hash_preserved(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    dest = tmp_path / "build_context"

    canary_src = src / ".claude-plugin" / "plugin.json"
    canary_src.write_bytes(b'{"name":"nextseek-api","canary":"FIXED-BYTES-42"}\n')
    expected_hash = _sha256(canary_src)

    stage_plugins.stage(src, dest)

    canary_out = dest / "plugins" / "nextseek-api" / ".claude-plugin" / "plugin.json"
    assert _sha256(canary_out) == expected_hash


@pytest.mark.parametrize(
    "relpath,content",
    [
        (".git/HEAD", b"ref: refs/heads/main\n"),
        (".venv/lib/foo", b"bytecode\n"),
        (".mcp.json", b'{"servers":{}}'),
        ("secrets.pem", b"-----BEGIN PRIVATE KEY-----\n"),
        (".env", b"SECRET=leak\n"),
        (".coverage", b"coverage-data\n"),
        (".pytest_cache/v/cache/lastfailed", b"[]"),
        (".ruff_cache/0.1/foo", b"x"),
        ("bin/host.key", b"-----BEGIN-----\n"),
    ],
)
def test_denylist_each_pattern_refuses(
    tmp_path: Path, relpath: str, content: bytes
) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    denyfile = src / relpath
    denyfile.parent.mkdir(parents=True, exist_ok=True)
    denyfile.write_bytes(content)
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)

    # DD-39 (R-02 batch): when the offender lives inside a denylisted dir,
    # the scan short-circuits and names the dir (not every nested file) so
    # a real `.git/` or `.venv/` tree doesn't produce 145KB of output.
    # Operator-facing signal: the top-level denylisted component is enough.
    top = relpath.split("/", 1)[0]
    assert top in str(excinfo.value), (
        f"expected top-level denylisted component {top!r} in: {excinfo.value}"
    )
    assert not dest.exists(), "build_context should not be created on refusal"


@pytest.mark.parametrize(
    "relpath,content",
    [
        ("bin/__pycache__/foo.cpython-312.pyc", b"\x00\x00"),
        ("bin/foo.pyc", b"\x00\x00"),
        ("bin/foo.pyo", b"\x00\x00"),
        ("skills/nextseek-api/.npmrc", b"//registry.example/:_authToken=LEAK\n"),
        ("commands/.pytest_cache/v/foo", b"x"),
        ("skills/.ruff_cache/0.1/foo", b"x"),
        ("bin/__pycache__/a.pyc", b"\x00"),
        ("docs/__pycache__/b.pyc", b"\x00"),
    ],
)
def test_denylist_inside_allowlisted_subtree_refuses(
    tmp_path: Path, relpath: str, content: bytes
) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    bad = src / relpath
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_bytes(content)
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)
    # DD-39 (R-02 batch): offenders under a denylisted dir are reported by
    # dir path (not per-file). For the file-only patterns in this matrix
    # (``bin/foo.pyc`` etc.) the full relpath IS the offender.
    if "/" in relpath:
        parts = relpath.split("/")
        # Find the first denylisted component (dir or glob-matching file).
        from build_tools.stage_plugins import (
            _is_denylisted_dir_name,
            _is_denylisted_file_name,
        )
        expected: str | None = None
        for i, part in enumerate(parts):
            if _is_denylisted_dir_name(part) or _is_denylisted_file_name(part):
                expected = "/".join(parts[: i + 1])
                break
        assert expected is not None, f"no denylisted component found in {relpath}"
        assert expected in str(excinfo.value), (
            f"expected {expected!r} in: {excinfo.value}"
        )
    else:
        assert relpath in str(excinfo.value)
    assert not dest.exists()


def test_env_example_refused(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / ".env.example").write_text("SEEK_USER=example\n")
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)
    assert ".env.example" in str(excinfo.value)
    assert not dest.exists()


def test_denylist_reports_every_offender_not_fail_fast(tmp_path: Path) -> None:
    """Every distinct denylisted top-level thing is reported (spec intent
    is 'don't fail fast after the first offender', not 'enumerate every
    nested file'). Per DD-39 the scan short-circuits on a denylisted dir
    to avoid the 145KB-of-.git/ explosion — but it still catches all 6
    planted offenders at their top-level-denylisted-component granularity.
    """
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    planted = [".git/HEAD", ".venv/lib/foo", ".mcp.json", "secrets.pem", ".env", ".coverage"]
    for rel in planted:
        f = src / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)

    msg = str(excinfo.value)
    expected_components = [rel.split("/", 1)[0] for rel in planted]
    for component in expected_components:
        assert component in msg, f"offender {component!r} not reported: {msg}"
    assert not dest.exists()


def test_cli_exits_1_on_denylist(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / ".env").write_bytes(b"SECRET=x\n")
    dest = tmp_path / "build_context"

    rc = stage_plugins.main(["--source", str(src), "--dest", str(dest)])
    assert rc == 1
    assert not dest.exists()


def test_symlink_is_resolved(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    real = src / ".claude-plugin" / "_real-readme.md"
    real.write_text("# real readme via symlink\n")
    link = src / "README.md"
    link.unlink()
    link.symlink_to(real)
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)

    readme_out = dest / "docs" / "nextseek-api" / "README.md"
    assert readme_out.is_file()
    assert not readme_out.is_symlink()
    assert readme_out.read_text() == "# real readme via symlink\n"


def test_symlink_inside_tree_resolves_ok(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    target = src / "bin" / "nextseek-call"
    link = src / "bin" / "nextseek-call-alias"
    link.symlink_to(target)
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)
    assert (dest / "plugins" / "nextseek-api" / "bin" / "nextseek-call-alias").is_file()


def test_symlink_to_directory_inside_tree_refused(tmp_path: Path) -> None:
    """DD-38 (R-02): dir-symlinks are refused even when the target stays
    inside the tree. ``shutil.copytree(symlinks=False)`` follows the link
    and would copy denylisted content reachable only via the alias
    (e.g. ``bin/alias -> ../docs/__pycache__``). File-symlinks remain
    allowed (see ``test_symlink_inside_tree_resolves_ok``).
    """
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / "bin" / "skills-alias").symlink_to(
        src / "skills" / "nextseek-api", target_is_directory=True
    )
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)
    assert "bin/skills-alias" in str(excinfo.value)
    assert "dir-symlink" in str(excinfo.value)
    # Atomic refusal: dest must not be populated.
    assert not (dest / "plugins" / "nextseek-api" / "bin" / "skills-alias").exists()


def test_symlink_to_directory_smuggling_denylisted_content_refused(
    tmp_path: Path,
) -> None:
    """Regression guard for the original reviewer finding: ``bin/alias``
    points at a sibling path containing denylisted artifacts. Without the
    R-02 fix the scanner would accept the link (target is inside root) and
    ``shutil.copytree`` would pull the ``.pyc`` into the image.
    """
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    hidden = src / "docs" / "__pycache__"
    hidden.mkdir()
    (hidden / "leak.pyc").write_bytes(b"\x00\x01")
    (src / "bin" / "alias").symlink_to(hidden, target_is_directory=True)
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation):
        stage_plugins.stage(src, dest)


def test_symlink_escaping_tree_refused(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    outside = tmp_path / "outside_secret"
    outside.write_text("stolen-credentials\n")
    escaping_link = src / "bin" / "escape-link"
    escaping_link.symlink_to(outside)
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)
    assert "escape-link" in str(excinfo.value) or "escapes" in str(excinfo.value).lower()
    assert not dest.exists()


def test_symlink_to_absolute_system_path_refused(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / "bin" / "passwd-link").symlink_to("/etc/passwd")
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation):
        stage_plugins.stage(src, dest)
    assert not dest.exists()


def test_broken_symlink_refused(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / "bin" / "broken").symlink_to(tmp_path / "does-not-exist")
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest)
    assert "broken" in str(excinfo.value) or "broken symlink" in str(excinfo.value).lower()
    assert not dest.exists()


def test_stage_warns_on_unexpected_top_level_entry(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / "random_note.txt").write_text("fyi\n")
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)

    captured = capsys.readouterr()
    assert "random_note.txt" in captured.err
    assert "not in ALLOWLIST" in captured.err or "unexpected" in captured.err.lower()
    assert not (dest / "plugins" / "nextseek-api" / "random_note.txt").exists()


def test_stage_strict_mode_refuses_unexpected(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    (src / "random_note.txt").write_text("fyi\n")
    dest = tmp_path / "build_context"

    with pytest.raises(stage_plugins.DenylistViolation) as excinfo:
        stage_plugins.stage(src, dest, strict=True)
    assert "random_note.txt" in str(excinfo.value)
    assert not dest.exists()


def test_idempotent_second_run_identical(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)
    first = {p.relative_to(dest).as_posix(): _sha256(p) for p in dest.rglob("*") if p.is_file()}
    stage_plugins.stage(src, dest)
    second = {p.relative_to(dest).as_posix(): _sha256(p) for p in dest.rglob("*") if p.is_file()}
    assert first == second


def test_stale_file_removed_on_restage(tmp_path: Path) -> None:
    src = tmp_path / "src" / "nextseek-api"
    _seed_plugin(src)
    extra = src / "docs" / "acceptance" / "extra.md"
    extra.write_text("# temporary\n")
    dest = tmp_path / "build_context"

    stage_plugins.stage(src, dest)
    staged_extra = dest / "docs" / "nextseek-api" / "docs" / "acceptance" / "extra.md"
    assert staged_extra.is_file()

    extra.unlink()
    stage_plugins.stage(src, dest)
    assert not staged_extra.exists(), "stale file survived re-stage - wipe-before-copy broken"


def test_missing_source_raises(tmp_path: Path) -> None:
    src = tmp_path / "does-not-exist"
    dest = tmp_path / "build_context"
    with pytest.raises(FileNotFoundError):
        stage_plugins.stage(src, dest)
