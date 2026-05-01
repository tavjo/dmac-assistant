"""Unit tests for build_tools.stage_plugins."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from build_tools import stage_plugins as sp


def _make_minimal_plugin(root: Path) -> Path:
    """Build a small but valid plugin source tree under root/plugin."""
    plugin = root / "nextseek-api"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "manifest.json").write_text("{}")
    (plugin / "bin").mkdir()
    (plugin / "bin" / "tool.sh").write_text("#!/bin/sh\necho hi\n")
    (plugin / "commands").mkdir()
    (plugin / "commands" / "cmd.md").write_text("# cmd\n")
    (plugin / "skills").mkdir()
    (plugin / "skills" / "skill.md").write_text("# skill\n")
    (plugin / "docs").mkdir()
    (plugin / "docs" / "guide.md").write_text("# guide\n")
    (plugin / "pyproject.toml").write_text("[project]\nname='x'\n")
    (plugin / "uv.lock").write_text("# lock\n")
    (plugin / "README.md").write_text("# Readme\n")
    (plugin / "CHANGELOG.md").write_text("# Changelog\n")
    return plugin


# ---- scan_source ---------------------------------------------------------


def test_scan_source_clean_tree(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    report = sp.scan_source(plugin)
    assert report.denylist_offenders == ()
    assert report.unexpected_top_level_entries == ()


def test_scan_source_flags_denylisted_directory(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / ".git").mkdir()
    (plugin / ".git" / "HEAD").write_text("ref: refs/heads/main\n")
    report = sp.scan_source(plugin)
    assert ".git" in report.denylist_offenders


def test_scan_source_flags_denylisted_file_pattern(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / "bin" / "compiled.pyc").write_text("bytecode")
    (plugin / ".env").write_text("SECRET=1")
    report = sp.scan_source(plugin)
    assert any(".env" in p for p in report.denylist_offenders)
    assert any("compiled.pyc" in p for p in report.denylist_offenders)


def test_scan_source_flags_unexpected_top_level(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / "extras").mkdir()
    (plugin / "extras" / "x.txt").write_text("x")
    (plugin / "weird_top.md").write_text("oops")
    report = sp.scan_source(plugin)
    assert "extras" in report.unexpected_top_level_entries
    assert "weird_top.md" in report.unexpected_top_level_entries


def test_scan_source_does_not_recurse_into_unexpected_top_level_dir(
    tmp_path: Path,
) -> None:
    """An unexpected top-level dir is reported once; deeper denylist is not scanned."""
    plugin = _make_minimal_plugin(tmp_path)
    bogus = plugin / "unexpected"
    (bogus / "subdir").mkdir(parents=True)
    (bogus / "subdir" / "x.pyc").write_text("y")  # would be denylisted if recursed
    report = sp.scan_source(plugin)
    assert "unexpected" in report.unexpected_top_level_entries
    assert report.denylist_offenders == ()


def test_scan_source_flags_broken_symlink(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    link = plugin / "bin" / "broken"
    link.symlink_to(plugin / "bin" / "does_not_exist")
    report = sp.scan_source(plugin)
    assert any("broken symlink" in p for p in report.denylist_offenders)


def test_scan_source_flags_symlink_escaping_root(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("oops")
    link = plugin / "bin" / "escape"
    link.symlink_to(outside)
    report = sp.scan_source(plugin)
    assert any("escape ->" in p for p in report.denylist_offenders)


def test_scan_source_flags_dir_symlink_inside_root(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    link = plugin / "bin" / "alias"
    link.symlink_to(plugin / "docs", target_is_directory=True)
    report = sp.scan_source(plugin)
    assert any("dir-symlink" in p for p in report.denylist_offenders)


def test_scan_source_file_symlink_inside_root_is_ok(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    link = plugin / "bin" / "ln"
    link.symlink_to(plugin / "bin" / "tool.sh")
    report = sp.scan_source(plugin)
    assert report.denylist_offenders == ()


def test_scan_source_denylisted_filename_via_symlink(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    target = plugin / "bin" / "tool.sh"
    link = plugin / "bin" / "compiled.pyc"  # denylisted name
    link.symlink_to(target)
    report = sp.scan_source(plugin)
    assert any("compiled.pyc" in p for p in report.denylist_offenders)


# ---- stage ---------------------------------------------------------------


def test_stage_raises_when_source_missing(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        sp.stage(tmp_path / "missing", tmp_path / "out")


def test_stage_raises_when_source_is_file(tmp_path: Path) -> None:
    f = tmp_path / "f.txt"
    f.write_text("x")
    with pytest.raises(NotADirectoryError):
        sp.stage(f, tmp_path / "out")


def test_stage_raises_on_denylist(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / ".git").mkdir()
    with pytest.raises(sp.DenylistViolation, match="denylisted"):
        sp.stage(plugin, tmp_path / "out")


def test_stage_warns_unexpected_top_level_in_non_strict(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / "weird.md").write_text("hi")
    sp.stage(plugin, tmp_path / "out")
    captured = capsys.readouterr()
    assert "weird.md" in captured.err
    assert (tmp_path / "out").exists()


def test_stage_strict_raises_on_unexpected_top_level(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / "weird.md").write_text("hi")
    with pytest.raises(sp.DenylistViolation, match="unexpected"):
        sp.stage(plugin, tmp_path / "out", strict=True)


def test_stage_copies_expected_layout(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    dest = tmp_path / "out"
    # pre-existing dest should be wiped
    dest.mkdir()
    (dest / "stale.txt").write_text("stale")

    sp.stage(plugin, dest)

    plugin_out = dest / "plugins" / "nextseek-api"
    docs_out = dest / "docs" / "nextseek-api"
    assert not (dest / "stale.txt").exists()
    assert (plugin_out / ".claude-plugin" / "manifest.json").exists()
    assert (plugin_out / "bin" / "tool.sh").exists()
    assert (plugin_out / "commands" / "cmd.md").exists()
    assert (plugin_out / "skills" / "skill.md").exists()
    assert (plugin_out / "pyproject.toml").exists()
    assert (plugin_out / "uv.lock").exists()
    assert (plugin_out / "CHANGELOG.md").exists()
    # README + docs go to the docs side
    assert (docs_out / "README.md").exists()
    assert (docs_out / "docs" / "guide.md").exists()


# ---- main CLI ------------------------------------------------------------


def test_main_success_returns_0(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    dest = tmp_path / "out"
    rc = sp.main(["--source", str(plugin), "--dest", str(dest)])
    assert rc == 0
    assert (dest / "plugins" / "nextseek-api").exists()


def test_main_denylist_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / ".git").mkdir()
    rc = sp.main(["--source", str(plugin), "--dest", str(tmp_path / "out")])
    assert rc == 1
    captured = capsys.readouterr()
    assert "denylisted" in captured.err


def test_main_missing_source_returns_1(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    rc = sp.main(["--source", str(tmp_path / "nope"), "--dest", str(tmp_path / "out")])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.err  # error printed


def test_main_strict_unexpected_returns_1(tmp_path: Path) -> None:
    plugin = _make_minimal_plugin(tmp_path)
    (plugin / "weird.md").write_text("hi")
    rc = sp.main(["--source", str(plugin), "--dest", str(tmp_path / "out"), "--strict"])
    assert rc == 1


def test_main_module_dunder_executes_via_runpy(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Cover the ``if __name__ == '__main__'`` guard via runpy."""
    import runpy

    plugin = _make_minimal_plugin(tmp_path)
    dest = tmp_path / "out"
    monkeypatch.setattr(
        "sys.argv",
        ["stage_plugins", "--source", str(plugin), "--dest", str(dest)],
    )
    with pytest.raises(SystemExit) as exc_info:
        runpy.run_module("build_tools.stage_plugins", run_name="__main__")
    assert exc_info.value.code == 0
